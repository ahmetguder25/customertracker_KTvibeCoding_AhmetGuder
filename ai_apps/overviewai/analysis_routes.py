from flask import Blueprint, request, jsonify
import os

ai_analysis_bp = Blueprint('ai_analysis', __name__)

@ai_analysis_bp.route("/api/chunk", methods=["POST"])
def api_chunk_document():
    from . import tasks
    from . import rag_db
    from app import get_db, CUSTOMER_DOCS_FOLDER
    data = request.get_json() or {}
    doc_id = str(data.get("document_id", ""))
    
    if not doc_id:
        return jsonify({"error": "Missing document_id"}), 400
        
    # Look up filename
    conn = get_db()
    row = conn.execute("SELECT FileName FROM BOA.COR.CustomerDocument WHERE DocID=?", (doc_id,)).fetchone()
    conn.close()
    
    if not row:
        return jsonify({"error": "Document not found"}), 404
        
    filepath = os.path.join(CUSTOMER_DOCS_FOLDER, row["FileName"])
    
    # Initialize state
    rag_db.upsert_task(doc_id, "Chunking", "Pending", "Added to queue...")
    
    # Dispatch
    tasks.process_chunking_task(doc_id, filepath)
    
    return jsonify({"message": "Chunking task dispatched", "document_id": doc_id}), 202

@ai_analysis_bp.route("/api/map", methods=["POST"])
def api_map_document():
    from . import tasks
    from . import rag_db
    data = request.get_json() or {}
    doc_id = str(data.get("document_id", ""))
    
    if not doc_id:
        return jsonify({"error": "Missing document_id"}), 400
        
    # Initialize state
    rag_db.upsert_task(doc_id, "Mapping", "Pending", "Added to queue...")
    
    # Dispatch
    tasks.process_mapping_task(doc_id)
    
    return jsonify({"message": "Mapping task dispatched", "document_id": doc_id}), 202

@ai_analysis_bp.route("/api/status", methods=["GET", "POST"])
def api_status():
    from . import rag_db
    if request.method == "POST":
        data = request.get_json() or {}
        doc_id = str(data.get("document_id", ""))
    else:
        doc_id = request.args.get("document_id", "")
        
    if not doc_id:
        return jsonify({"error": "Missing document_id"}), 400
        
    task_list = rag_db.get_task_status(doc_id)
    
    status_map = {
        "chunking": {"status": "Not Started", "message": "", "percent": 0},
        "mapping": {"status": "Not Started", "message": "", "percent": 0}
    }
    
    for t in task_list:
        task_type = t["task_type"].lower()
        if task_type in status_map:
            status_map[task_type] = {
                "status": t["status"],
                "message": t["progress_message"],
                "percent": t["percent_complete"]
            }
            
    return jsonify(status_map)

@ai_analysis_bp.route("/api/analyze", methods=["POST"])
def api_analyze():
    from . import tasks
    from . import rag_db
    data = request.get_json() or {}
    doc_id = str(data.get("document_id", ""))
    query = data.get("query", "").strip()
    
    if not doc_id or not query:
        return jsonify({"error": "Missing document_id or query"}), 400
        
    # Simple synchronous analysis endpoint for the prototype
    try:
        # Check if Ollama is alive
        ok, msg = tasks.check_ollama_status()
        if not ok:
            return jsonify({"error": msg}), 500
            
        # Get summaries to act as global context
        summaries = rag_db.get_summaries(doc_id)
        if not summaries:
            return jsonify({"error": "No graph summaries found for this document. Have you run Mapping?"}), 400
            
        context = "\n\n".join([s["summary_text"] for s in summaries])
        
        prompt = f"Given the following financial graph community summaries:\n\n{context}\n\nAnswer the query: {query}"
        system = "You are a financial analyst. Synthesize the context to answer the question accurately."
        
        response = tasks.query_ollama(prompt, system=system)
        
        return jsonify({
            "answer": response,
            "document_id": doc_id,
            "query": query
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500
