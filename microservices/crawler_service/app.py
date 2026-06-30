from flask import Flask, jsonify, request
from flask_cors import CORS
from microservices.crawler_service import crawler_db

app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": "*"}})

@app.route("/api/health", methods=["GET"])
def api_health():
    try:
        conn = crawler_db.get_db()
        row = conn.execute("SELECT COUNT(*) as count FROM crawler_jobs WHERE status='Running'").fetchone()
        conn.close()
        is_processing = (row["count"] > 0) if row else False
        return jsonify({
            "status": "Online",
            "active_process": is_processing,
            "message": "Crawling in progress..." if is_processing else "Idle"
        })
    except Exception as e:
        return jsonify({"status": "Error", "message": str(e), "active_process": False}), 500

@app.route("/api/reset", methods=["POST"])
def api_reset():
    try:
        conn = crawler_db.get_db()
        conn.execute("UPDATE crawler_jobs SET status='Idle', last_message='Reset by administrator' WHERE status='Running'")
        conn.commit()
        conn.close()
        return jsonify({"success": True, "message": "Pending tasks cleared."})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/jobs", methods=["GET"])
def get_jobs():
    jobs = crawler_db.get_jobs()
    return jsonify({"jobs": jobs})

@app.route("/api/jobs", methods=["POST"])
def add_job():
    data = request.json
    crawler_db.add_job(
        data.get("job_name", "Untitled"),
        data.get("target_url", ""),
        data.get("search_query", ""),
        data.get("systematic_base_name", ""),
        int(data.get("crawl_depth", 0)),
        data.get("file_types", ".pdf")
    )
    return jsonify({"success": True})

@app.route("/api/jobs/<int:job_id>", methods=["DELETE"])
def delete_job(job_id):
    crawler_db.delete_job(job_id)
    return jsonify({"success": True})

@app.route("/api/jobs/<int:job_id>/run", methods=["POST"])
def run_job(job_id):
    from microservices.crawler_service.tasks import crawl_task
    crawler_db.update_job_status(job_id, "Running", "Task queued...")
    crawl_task(job_id)
    return jsonify({"success": True})

@app.route("/api/history", methods=["GET"])
def get_history():
    conn = crawler_db.get_db()
    rows = conn.execute("""
        SELECT cd.*, cj.job_name 
        FROM crawled_documents cd
        LEFT JOIN crawler_jobs cj ON cd.job_id = cj.id
        ORDER BY cd.id DESC LIMIT 50
    """).fetchall()
    conn.close()
    return jsonify({"history": [dict(r) for r in rows]})

if __name__ == "__main__":
    crawler_db.init_db()
    app.run(port=5003, debug=True)
