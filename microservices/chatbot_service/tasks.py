import os
from huey import SqliteHuey
import logging
from microservices.chatbot_service.db import get_db

QUEUE_DB = os.path.join(os.path.dirname(__file__), 'chatbot_queue.db')
huey = SqliteHuey(filename=QUEUE_DB, immediate=True)

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
    import time
    t_pipeline_start = time.time()

    try:
        import ollama as _ollama
        from microservices.chatbot_service.rag import search_document_hybrid as _rag_search
        from microservices.chatbot_service.rag import GEN_MODEL, EMBED_MODEL
        from microservices.chatbot_service.perf_log import log_chat_perf
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

    # ── RAG Search ──────────────────────────────────────────────────────────────
    rag_perf = {}
    try:
        result = _rag_search(prompt, n_results=20, selected_docs=selected_docs)
        chunks = result.get("chunks", [])
        queries = result.get("queries_used", [])
        rag_perf = result.get("perf", {})
    except Exception as exc:
        logger.error(f"RAG search error: {exc}")
        conn.execute("UPDATE messages SET content = ?, status = 'error' WHERE id = ?", (f"Retrieval error: {exc}", message_id))
        conn.commit()
        conn.close()
        log_chat_perf(
            message_id=message_id, prompt=prompt, prompt_words=len(prompt.split()),
            selected_docs=str(selected_docs), language=language,
            model_gen=GEN_MODEL, model_embed=EMBED_MODEL, method="hybrid",
            status="error", error_message=str(exc)
        )
        return

    context = "\n\n---\n\n".join(chunks) if chunks else "(No relevant context found.)"
    context_chars = len(context)
    
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

    # ── LLM Generation ──────────────────────────────────────────────────────────
    t_gen_start = time.time()
    token_count = 0
    status = "success"
    error_msg = None

    try:
        stream = _ollama.chat(
            model=GEN_MODEL,
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
                token_count += 1
                
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
        status = "error"
        error_msg = str(exc)
        
    finally:
        conn.close()

    t_gen_ms = int((time.time() - t_gen_start) * 1000)
    t_total_ms = int((time.time() - t_pipeline_start) * 1000)

    # ── Write performance log ───────────────────────────────────────────────────
    print(
        f"[chatbot] message_id={message_id} | total={t_total_ms}ms | "
        f"RAG={rag_perf.get('t_rag_total_ms', '?')}ms "
        f"(expand={rag_perf.get('t_expand_ms', '?')}ms, "
        f"embed={rag_perf.get('t_embed_ms', '?')}ms [{rag_perf.get('embed_calls', '?')} calls], "
        f"search={rag_perf.get('t_search_ms', '?')}ms) | "
        f"gen={t_gen_ms}ms ({token_count} tokens) | "
        f"model={GEN_MODEL} | status={status}",
        flush=True
    )

    try:
        log_chat_perf(
            message_id=message_id,
            prompt=prompt,
            prompt_words=len(prompt.split()),
            selected_docs=str(selected_docs),
            language=language,
            model_gen=GEN_MODEL,
            model_embed=EMBED_MODEL,
            method="hybrid",
            t_total_ms=t_total_ms,
            t_expand_ms=rag_perf.get("t_expand_ms"),
            t_embed_ms=rag_perf.get("t_embed_ms"),
            t_search_ms=rag_perf.get("t_search_ms"),
            t_generate_ms=t_gen_ms,
            queries_expanded=rag_perf.get("queries_expanded"),
            embed_calls=rag_perf.get("embed_calls"),
            chunks_retrieved=rag_perf.get("chunks_retrieved"),
            context_chars=context_chars,
            tokens_generated=token_count,
            status=status,
            error_message=error_msg,
        )
    except Exception as e:
        print(f"[chatbot] perf_log write failed (non-fatal): {e}", flush=True)

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
