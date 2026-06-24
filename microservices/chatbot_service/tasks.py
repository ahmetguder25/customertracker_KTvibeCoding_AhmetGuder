import os
from huey import SqliteHuey
import logging
from microservices.chatbot_service.db import get_db

QUEUE_DB = os.path.join(os.path.dirname(__file__), 'chatbot_queue.db')
huey = SqliteHuey(filename=QUEUE_DB)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ChatbotTasks")

def build_system_prompt(language="English"):
    lang_instruction = (
        "You must respond strictly in TURKISH ONLY, regardless of the language the user types in."
        if language == "Turkish" else
        "You must respond strictly in ENGLISH ONLY, regardless of the language the user types in."
    )
    
    return (
        f"You are an expert structured finance analyst and Islamic finance compliance "
        f"specialist. {lang_instruction}\n\n"
        "Read the provided document excerpts carefully. Your task is to synthesize "
        "the rules, conditions, and exceptions found across the excerpts to form a "
        "single, comprehensive compliance opinion.\n\n"
        "Walk through your reasoning step-by-step using this structure:\n"
        "1. GENERAL PRINCIPLE — State the governing rule or principle.\n"
        "2. CONDITIONS FOR PERMISSIBILITY — List the specific requirements that must "
        "be satisfied.\n"
        "3. PROHIBITIONS & DISQUALIFYING FACTORS — Note anything that would render "
        "the transaction impermissible.\n"
        "4. EXCEPTIONS & SPECIAL CIRCUMSTANCES — Identify any exceptions or edge "
        "cases that apply.\n"
        "5. CONCLUSION — Apply the above to the question and give a clear, direct "
        "compliance opinion.\n\n"
        "If you cannot determine the answer from the provided text, explain precisely "
        "which specific rule, parameter, or contract detail is missing from the "
        "context. Do not speculate or guess beyond what the excerpts state."
    )

@huey.task()
def generate_chat_reply(message_id, prompt, selected_docs=None, language="English"):
    try:
        import ollama as _ollama
        from microservices.chatbot_service.rag import search_document_hybrid as _rag_search
        _RAG_AVAILABLE = True
    except ImportError as e:
        logger.error(f"RAG/Ollama import failed: {e}")
        _RAG_AVAILABLE = False

    conn = get_db()
    
    if not _RAG_AVAILABLE:
        conn.execute("UPDATE messages SET content = ?, status = 'error' WHERE id = ?", ("RAG module or Ollama not available.", message_id))
        conn.commit()
        conn.close()
        return

    try:
        result = _rag_search(prompt, n_results=20, selected_docs=selected_docs)
        chunks = result.get("chunks", [])
        queries = result.get("queries_used", [])
    except Exception as exc:
        logger.error(f"RAG search error: {exc}")
        conn.execute("UPDATE messages SET content = ?, status = 'error' WHERE id = ?", (f"Retrieval error: {exc}", message_id))
        conn.commit()
        conn.close()
        return

    context = "\n\n---\n\n".join(chunks) if chunks else "(No relevant context found.)"
    
    # We prefix queries used so the frontend can display them later
    queries_str = "\\n".join(f"- {q}" for q in queries)
    
    user_message = (
        f"Document excerpts ({len(chunks)} sections retrieved):\n\n"
        f"{context}\n\n---\n\nQuestion: {prompt}"
    )

    full_text = ""
    # Add a hidden metadata block at the start for queries (if any)
    if queries:
        full_text += f"<!-- QUERIES_USED: {queries_str} -->\n"

    try:
        stream = _ollama.chat(
            model="gemma2",
            messages=[
                {"role": "system", "content": build_system_prompt(language)},
                {"role": "user",   "content": user_message},
            ],
            stream=True,
        )
        
        chunk_counter = 0
        for chunk in stream:
            token = chunk["message"]["content"]
            if token:
                full_text += token
                chunk_counter += 1
                
                # Update DB every 5 tokens to reduce sqlite locking, but keep UI responsive
                if chunk_counter % 5 == 0:
                    conn.execute("UPDATE messages SET content = ? WHERE id = ?", (full_text, message_id))
                    conn.commit()
                    
        # Final update
        conn.execute("UPDATE messages SET content = ?, status = 'done' WHERE id = ?", (full_text, message_id))
        conn.commit()
        
    except Exception as exc:
        logger.error(f"Ollama stream error: {exc}")
        conn.execute("UPDATE messages SET content = ?, status = 'error' WHERE id = ?", (full_text + f"\n\n[Error: {exc}]", message_id))
        conn.commit()
        
    finally:
        conn.close()

@huey.task()
def sync_rag_task():
    import subprocess
    import sys
    import os
    
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    script_path = os.path.join(BASE_DIR, "process_pdf.py")
    
    try:
        print("Starting RAG Sync process...")
        result = subprocess.run([sys.executable, script_path], capture_output=True, text=True)
        print(result.stdout)
        if result.stderr:
            print("STDERR:", result.stderr)
        print("RAG Sync process completed.")
    except Exception as e:
        print(f"Error in sync_rag_task: {e}")
