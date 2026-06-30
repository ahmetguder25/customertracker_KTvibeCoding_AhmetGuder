import os
import sys
import logging
from flask import Flask, request, jsonify
from flask_cors import CORS

# Add root folder to sys.path so we can import core
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.shared.db import get_db
from app.shared.config import CUSTOMER_DOCS_FOLDER

from microservices.sparx_ai_service import tasks, rag_db

app = Flask(__name__)
# Allow CORS for the frontend running on 5000
CORS(app, resources={r"/api/*": {"origins": "*"}})

@app.route("/api/chunk", methods=["POST"])
def api_chunk_document():
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
        
    try:
        rag_db.upsert_task(doc_id, "Chunking", "Pending", "Added to Sparx queue...")
        tasks.process_chunking_task(doc_id, filepath)
        return jsonify({"message": "Chunking task dispatched", "document_id": doc_id}), 200
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": f"Failed to start task: {e}"}), 502

@app.route("/api/map", methods=["POST"])
def api_map_document():
    data = request.get_json() or {}
    doc_id = str(data.get("document_id", ""))
    
    if not doc_id:
        return jsonify({"error": "Missing document_id"}), 400
        
    try:
        rag_db.upsert_task(doc_id, "Mapping", "Pending", "Added to Sparx queue...")
        tasks.process_mapping_task(doc_id)
        return jsonify({"message": "Mapping task dispatched", "document_id": doc_id}), 200
    except Exception as e:
        return jsonify({"error": f"Failed to start mapping task: {e}"}), 502

@app.route("/api/status", methods=["GET", "POST"])
def api_status():
    if request.method == "POST":
        data = request.get_json() or {}
        doc_id = str(data.get("document_id", ""))
    else:
        doc_id = request.args.get("document_id", "")
        
    if not doc_id:
        return jsonify({"error": "Missing document_id"}), 400
        
    try:
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
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({
            "chunking": {"status": "Failed", "message": "Sparx DB Error", "percent": 0},
            "mapping": {"status": "Failed", "message": "Sparx DB Error", "percent": 0}
        }), 502

@app.route("/api/analyze", methods=["POST"])
def api_analyze():
    data = request.get_json() or {}
    doc_id = str(data.get("document_id", ""))
    query = data.get("query", "").strip()
    
    if not doc_id or not query:
        return jsonify({"error": "Missing document_id or query"}), 400
        
    try:
        ok, msg = tasks.check_vllm_status()
        if not ok:
            return jsonify({"error": msg}), 500
            
        summaries = rag_db.get_summaries(doc_id)
        if not summaries:
            return jsonify({"error": "No graph summaries found for this document. Have you run Mapping?"}), 400
            
        import json
        import numpy as np
        query_emb = tasks.embedder.encode(query)
        scored_summaries = []
        for s in summaries:
            if s.get("embedding"):
                try:
                    s_emb = np.array(json.loads(s["embedding"]))
                    score = np.dot(query_emb, s_emb) / (np.linalg.norm(query_emb) * np.linalg.norm(s_emb))
                    scored_summaries.append((score, s["summary_text"]))
                except Exception:
                    pass
                    
        scored_summaries.sort(key=lambda x: x[0], reverse=True)
        top_summaries = [s[1] for s in scored_summaries[:15]]
        
        if not top_summaries:
            top_summaries = [s["summary_text"] for s in summaries[:15]]
            
        context = "\n\n".join(top_summaries)

        system = (
            "Sen SPARX AI Service altyapısında çalışan üst düzey bir kurumsal finansman, "
            "kredi tahsis ve yapılandırılmış finansman yöneticisisin. Temel amacın, şirketlerin "
            "faaliyet raporlarından elde edilen verileri analiz ederek kredi risklerini ölçmek, "
            "borç ödeme kapasitesini değerlendirmek ve banka için potansiyel uzun vadeli fonlama "
            "fırsatlarını (proje finansmanı, kurumsal değer ortaklığı, sukuk vb.) tespit etmektir."
        )

        prompt = f"""Aşağıda, şirketin faaliyet raporundan çekilmiş bağlam (context) ve kullanıcının sorusu (query) yer almaktadır:

BAĞLAM:
{context}

KULLANICI SORUSU:
{query}

LÜTFEN YANITINI KESİNLİKLE AŞAĞIDAKİ YAPIYA SADIK KALARAK İKİ AŞAMALI ŞEKİLDE VER:

<akil_yurutme>
(Bu bölümde nihai raporu yazmadan önce kendi kendine düşün, hesaplamalarını yap ve stratejini kur. Şu adımları izle:
1. Veri Taraması: Bağlam (context) içinde kullanıcının sorusuna yanıt verecek hangi kritik finansal veriler, oranlar veya tablolar var?
2. Risk ve Fırsat Analizi: Bu veriler bir bankacı gözüyle ne anlama geliyor? (Örneğin; FAVÖK düşüşü refinansman riski yaratır mı? Yatırım planları proje finansmanına uygun mu?)
3. Doğrulama: Çıkardığım sonuçlar bağlamdaki verilerle birebir örtüşüyor mu? Halüsinasyon veya eksik bilgi var mı?)
</akil_yurutme>

<yonetici_ozeti>
(Bu bölümde akıl yürütme sürecinden elde ettiğin sonuçları son kullanıcı için profesyonel, net ve veri destekli bir bankacı raporu olarak sun.
- Markdown formatını kullan.
- Varsa önemli finansal metrikleri kısa bir tablo veya madde imleri ile vurgula.
- Cümlelerin objektif, analitik ve stratejik karar almaya yönelik olsun.)
</yonetici_ozeti>"""
        
        response = tasks.query_vllm(prompt, system=system)
        return jsonify({"answer": response, "document_id": doc_id, "query": query})
    except Exception as e:
        return jsonify({"error": f"Failed to analyze: {e}"}), 502

@app.route("/api/health", methods=["GET"])
def api_health():
    try:
        import time
        conn = rag_db.get_db()
        # Find the most recently active document
        active_doc_row = conn.execute("SELECT document_id FROM document_tasks WHERE status IN ('Pending', 'Processing', 'Running') ORDER BY updated_at DESC LIMIT 1").fetchone()
        
        is_processing = False
        msg = "Idle"
        tasks_list = []
        
        if active_doc_row:
            active_doc_id = active_doc_row["document_id"]
            # Fetch all tasks for this document
            rows = conn.execute("SELECT * FROM document_tasks WHERE document_id=? ORDER BY updated_at ASC", (active_doc_id,)).fetchall()
            conn.close()
            
            is_processing = True
            
            # Find the active one for the main message
            active_row = None
            for r in rows:
                try:
                    start_time = r["start_time"]
                except IndexError:
                    start_time = None
                    
                task_obj = {
                    "task_type": r["task_type"],
                    "status": r["status"],
                    "progress_message": r["progress_message"],
                    "percent_complete": r["percent_complete"],
                    "start_time": start_time,
                    "updated_at": r["updated_at"]
                }
                
                # Calculate ETA if processing
                if r["status"] in ('Pending', 'Processing', 'Running'):
                    active_row = r
                    pct = r["percent_complete"] or 0
                    now = time.time()
                    if start_time and pct > 0:
                        elapsed = now - start_time
                        total_est = elapsed / (pct / 100.0)
                        rem = total_est - elapsed
                        if rem < 0: rem = 0
                        mins = int(rem // 60)
                        secs = int(rem % 60)
                        task_obj["eta"] = f"~{mins}m {secs}s remaining"
                    elif start_time:
                        task_obj["eta"] = "Calculating..."
                elif r["status"] == 'Completed':
                    end = r["updated_at"]
                    if start_time and end and end > start_time:
                        duration = int(end - start_time)
                        mins = duration // 60
                        secs = duration % 60
                        task_obj["eta"] = f"Took {mins}m {secs}s"
                        
                tasks_list.append(task_obj)
                
            if active_row:
                msg = f"{active_row['task_type']} - {active_row['progress_message']}"
                pct = active_row["percent_complete"] or 0
                if pct > 0:
                    msg += f" ({pct}% complete)"
        else:
            conn.close()
            
        return jsonify({
            "status": "Online",
            "active_process": is_processing,
            "message": msg,
            "tasks": tasks_list
        })
    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({"status": "Error", "message": str(e), "active_process": False, "tasks": []}), 500

@app.route("/api/logs", methods=["GET"])
def api_logs():
    try:
        document_id = request.args.get("document_id")
        last_id = request.args.get("last_id", 0, type=int)
        if not document_id:
            # find active doc if not provided
            conn = rag_db.get_db()
            active_doc_row = conn.execute("SELECT document_id FROM document_tasks WHERE status IN ('Pending', 'Processing', 'Running') ORDER BY updated_at DESC LIMIT 1").fetchone()
            conn.close()
            if active_doc_row:
                document_id = active_doc_row["document_id"]
            else:
                return jsonify({"logs": []})
                
        logs = rag_db.get_logs(document_id, last_id)
        return jsonify({"logs": logs, "document_id": document_id})
    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({"error": str(e)}), 500

@app.route("/api/reset", methods=["POST"])
def api_reset():
    try:
        conn = rag_db.get_db()
        conn.execute("UPDATE document_tasks SET status='Failed', progress_message='Task aborted by administrator.' WHERE status='Pending' OR status='Running'")
        conn.commit()
        conn.close()
        return jsonify({"success": True, "message": "Pending tasks cleared."})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(port=5002, debug=True)
