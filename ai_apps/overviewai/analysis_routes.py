from flask import Blueprint, request, jsonify
import os
import requests

ai_analysis_bp = Blueprint('ai_analysis', __name__)

SPARX_API_URL = os.getenv("SPARX_API_URL", "http://10.19.57.150:8000")

@ai_analysis_bp.route("/api/chunk", methods=["POST"])
def api_chunk_document():
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
    
    if not os.path.exists(filepath):
        return jsonify({"error": "Document file not found on disk"}), 404
        
    # Send file to Sparx API
    try:
        with open(filepath, 'rb') as f:
            files = {'file': (row["FileName"], f, 'application/pdf')}
            data_payload = {'document_id': doc_id}
            resp = requests.post(f"{SPARX_API_URL}/api/chunk", files=files, data=data_payload, timeout=10)
            resp.raise_for_status()
            return jsonify(resp.json()), resp.status_code
    except requests.exceptions.RequestException as e:
        return jsonify({"error": f"Failed to reach Sparx AI service: {e}"}), 502

@ai_analysis_bp.route("/api/map", methods=["POST"])
def api_map_document():
    data = request.get_json() or {}
    doc_id = str(data.get("document_id", ""))
    
    if not doc_id:
        return jsonify({"error": "Missing document_id"}), 400
        
    try:
        resp = requests.post(f"{SPARX_API_URL}/api/map", data={'document_id': doc_id}, timeout=5)
        resp.raise_for_status()
        return jsonify(resp.json()), resp.status_code
    except requests.exceptions.RequestException as e:
        return jsonify({"error": f"Failed to reach Sparx AI service: {e}"}), 502

@ai_analysis_bp.route("/api/status", methods=["GET", "POST"])
def api_status():
    if request.method == "POST":
        data = request.get_json() or {}
        doc_id = str(data.get("document_id", ""))
    else:
        doc_id = request.args.get("document_id", "")
        
    if not doc_id:
        return jsonify({"error": "Missing document_id"}), 400
        
    try:
        resp = requests.get(f"{SPARX_API_URL}/api/status", params={'document_id': doc_id}, timeout=5)
        if resp.status_code == 200:
            return jsonify(resp.json())
        else:
            return jsonify({
                "chunking": {"status": "Failed", "message": f"Sparx HTTP {resp.status_code}: {resp.text}", "percent": 0},
                "mapping": {"status": "Failed", "message": f"Sparx HTTP {resp.status_code}: {resp.text}", "percent": 0}
            }), 502
    except requests.exceptions.RequestException as e:
        # Provide a fallback status if Sparx is unreachable so the UI doesn't crash
        return jsonify({
            "chunking": {"status": "Failed", "message": "Sparx Offline", "percent": 0},
            "mapping": {"status": "Failed", "message": "Sparx Offline", "percent": 0}
        }), 502

@ai_analysis_bp.route("/api/analyze", methods=["POST"])
def api_analyze():
    data = request.get_json() or {}
    doc_id = str(data.get("document_id", ""))
    query = data.get("query", "").strip()
    
    if not doc_id or not query:
        return jsonify({"error": "Missing document_id or query"}), 400
        
    try:
        payload = {'document_id': doc_id, 'query': query}
        resp = requests.post(f"{SPARX_API_URL}/api/analyze", data=payload, timeout=600)
        resp.raise_for_status()
        return jsonify(resp.json())
    except requests.exceptions.RequestException as e:
        return jsonify({"error": f"Failed to reach Sparx AI service: {e}"}), 502
