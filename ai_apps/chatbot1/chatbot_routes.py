from flask import Blueprint, request, jsonify, Response, stream_with_context
from flask import current_app as app
import json

chatbot_bp = Blueprint("chatbot", __name__)

try:
    from ai_apps.chatbot1.rag import search_document_hybrid as _rag_search
    _RAG_AVAILABLE = True
except ImportError:
    _RAG_AVAILABLE = False

_RAG_SYSTEM_PROMPT = (
    "You are an expert structured finance analyst and Islamic finance compliance "
    "specialist. You must respond strictly in ENGLISH ONLY, regardless of the "
    "language the user types in.\n\n"
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

@chatbot_bp.route("/api/ask-document", methods=["POST"])
def ask_document():
    try:
        import ollama as _ollama
    except ImportError:
        return jsonify({"error": "ollama not installed"}), 500

    data   = request.get_json(silent=True) or {}
    prompt = (data.get("prompt") or "").strip()

    if not prompt:
        return jsonify({"error": "No prompt provided."}), 400

    if not _RAG_AVAILABLE:
        return jsonify({"error": "RAG module unavailable."}), 500

    try:
        result  = _rag_search(prompt, n_results=20)
        chunks  = result["chunks"]
        queries = result["queries_used"]
    except FileNotFoundError as exc:
        return jsonify({"error": str(exc)}), 503
    except Exception as exc:
        app.logger.error(f"[ask_document] retrieval error: {exc}")
        return jsonify({"error": f"Retrieval failed: {exc}"}), 500

    context      = "\n\n---\n\n".join(chunks) if chunks else "(No relevant context found.)"
    user_message = (
        f"Document excerpts ({len(chunks)} sections retrieved):\n\n"
        f"{context}\n\n---\n\nQuestion: {prompt}"
    )

    def generate():
        try:
            stream = _ollama.chat(
                model="qwen3.5:9b",
                messages=[
                    {"role": "system", "content": _RAG_SYSTEM_PROMPT},
                    {"role": "user",   "content": user_message},
                ],
                stream=True,
            )
            for chunk in stream:
                token = chunk["message"]["content"]
                if token:
                    yield f"data: {json.dumps({'token': token})}\n\n"
            yield f"data: {json.dumps({'done': True, 'queries_used': queries})}\n\n"
        except Exception as exc:
            app.logger.error(f"[ask_document] stream error: {exc}")
            yield f"data: {json.dumps({'error': str(exc)})}\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
