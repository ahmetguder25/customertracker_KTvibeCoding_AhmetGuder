import os
import json
import sqlite3
from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
from microservices.chatbot_service.db import get_db, init_db
from microservices.chatbot_service.tasks import generate_chat_reply
import uuid
from microservices.chatbot_service.rag import DB_PATH
import logging

app = Flask(__name__)
# Allow CORS for the frontend running on 5000
CORS(app, resources={r"/api/*": {"origins": "*"}})

@app.route("/api/conversations", methods=["GET"])
def get_conversations():
    user_id = request.args.get("user_id")
    if not user_id:
        return jsonify({"error": "Missing user_id"}), 400
    
    conn = get_db()
    rows = conn.execute("SELECT id, title, created_at FROM conversations WHERE user_id = ? ORDER BY created_at DESC", (user_id,)).fetchall()
    conn.close()
    
    return jsonify([dict(r) for r in rows])

@app.route("/api/documents", methods=["GET"])
def get_documents():
    try:
        con = sqlite3.connect(DB_PATH)
        rows = con.execute("SELECT DISTINCT document_id FROM chunks ORDER BY document_id").fetchall()
        con.close()
        return jsonify([r[0] for r in rows])
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/conversations", methods=["POST"])
def create_conversation():
    data = request.json
    user_id = data.get("user_id")
    title = data.get("title", "New Chat")
    
    if not user_id:
        return jsonify({"error": "Missing user_id"}), 400
        
    conn = get_db()
    cur = conn.execute("INSERT INTO conversations (user_id, title) VALUES (?, ?)", (user_id, title))
    conv_id = cur.lastrowid
    conn.commit()
    conn.close()
    
    return jsonify({"id": conv_id, "title": title})

@app.route("/api/messages", methods=["GET"])
def get_messages():
    conversation_id = request.args.get("conversation_id")
    if not conversation_id:
        return jsonify({"error": "Missing conversation_id"}), 400
        
    conn = get_db()
    rows = conn.execute("SELECT id, role, content, status, created_at FROM messages WHERE conversation_id = ? ORDER BY id ASC", (conversation_id,)).fetchall()
    conn.close()
    
    return jsonify([dict(r) for r in rows])

@app.route("/api/chat", methods=["POST"])
def post_chat():
    data = request.json
    user_id = data.get("user_id")
    conversation_id = data.get("conversation_id")
    prompt = data.get("prompt", "").strip()
    selected_docs = data.get("selected_docs", [])
    language = data.get("language", "English")
    
    if not user_id or not prompt:
        return jsonify({"error": "Missing user_id or prompt"}), 400
        
    if not selected_docs:
        return jsonify({"error": "Please select at least one document."}), 400
        
    conn = get_db()
    
    # If no conversation_id, create one
    if not conversation_id:
        # Title is the first 30 chars of the prompt
        title = prompt[:30] + "..." if len(prompt) > 30 else prompt
        cursor = conn.execute("INSERT INTO conversations (user_id, title) VALUES (?, ?)", (user_id, title))
        conversation_id = cursor.lastrowid
        
    # Create the message entry with status 'processing'
    cursor = conn.execute("INSERT INTO messages (conversation_id, role, content, status) VALUES (?, ?, ?, ?)", 
                          (conversation_id, "user", prompt, "done"))
                          
    bot_cursor = conn.execute("INSERT INTO messages (conversation_id, role, content, status) VALUES (?, ?, ?, ?)", 
                          (conversation_id, "bot", "", "processing"))
    message_id = bot_cursor.lastrowid
    
    conn.commit()
    conn.close()

    # Enqueue task
    from microservices.chatbot_service.tasks import generate_chat_reply
    generate_chat_reply(message_id, prompt, selected_docs, language)
    
    return jsonify({"conversation_id": conversation_id, "message_id": message_id, "status": "processing"})

@app.route("/api/health", methods=["GET"])
def api_health():
    # Check if there's any active process
    try:
        # Check if RAG is running
        import os, json
        status_file = os.path.join(os.path.dirname(__file__), "rag_status.json")
        rag_msg = None
        rag_active = False
        if os.path.exists(status_file):
            try:
                with open(status_file, "r") as f:
                    data = json.load(f)
                    rag_active = data.get("active_process", False)
                    rag_msg = data.get("message")
            except: pass

        if rag_active:
            return jsonify({
                "status": "Online",
                "active_process": True,
                "message": rag_msg or "RAG Sync running..."
            })

        # Otherwise check chat processing
        conn = get_db()
        row = conn.execute("SELECT COUNT(*) as count FROM messages WHERE status='processing'").fetchone()
        conn.close()
        is_processing = (row["count"] > 0) if row else False
        return jsonify({
            "status": "Online",
            "active_process": is_processing,
            "message": "Processing message..." if is_processing else "Idle"
        })
    except Exception as e:
        return jsonify({"status": "Error", "message": str(e), "active_process": False}), 500

@app.route("/api/reset", methods=["POST"])
def api_reset():
    # Clear pending tasks by marking 'processing' messages as 'error'
    try:
        conn = get_db()
        conn.execute("UPDATE messages SET status='error', content='Message aborted by administrator.' WHERE status='processing'")
        conn.commit()
        conn.close()
        return jsonify({"success": True, "message": "Pending tasks cleared."})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/documents/check", methods=["GET"])
def api_documents_check():
    name = request.args.get("name")
    if not name:
        return jsonify({"error": "Missing name"}), 400
    
    # Check if file exists recursively in sources/
    import os
    sources_dir = os.path.join(os.path.dirname(__file__), "sources")
    for root, _, files in os.walk(sources_dir):
        if name in files:
            return jsonify({"exists": True})
    return jsonify({"exists": False})

@app.route("/api/documents/upload", methods=["POST"])
def api_documents_upload():
    import os
    if 'file' not in request.files:
        return jsonify({"error": "No file part"}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400
    
    # Save to sources/
    sources_dir = os.path.join(os.path.dirname(__file__), "sources")
    os.makedirs(sources_dir, exist_ok=True)
    file_path = os.path.join(sources_dir, file.filename)
    file.save(file_path)
    return jsonify({"success": True})

@app.route("/api/rag_sync", methods=["POST"])
def api_rag_sync():
    # Enqueue background task
    try:
        from microservices.chatbot_service.tasks import sync_rag_task
        sync_rag_task()
        return jsonify({"success": True, "message": "RAG Sync started in background."})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    init_db()
    app.run(port=5001, debug=True)
