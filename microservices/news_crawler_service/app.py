from flask import Flask, jsonify, request
from flask_cors import CORS
from microservices.news_crawler_service import news_db

app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": "*"}})

@app.route("/api/health", methods=["GET"])
def api_health():
    try:
        conn = news_db.get_db()
        row = conn.execute("SELECT COUNT(*) as count FROM news_jobs WHERE status='Running'").fetchone()
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
        conn = news_db.get_db()
        conn.execute("UPDATE news_jobs SET status='Idle', last_message='Reset by administrator' WHERE status='Running'")
        conn.commit()
        conn.close()
        return jsonify({"success": True, "message": "Pending tasks cleared."})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/jobs", methods=["GET"])
def get_jobs():
    customer_id = request.args.get("customer_id")
    jobs = news_db.get_jobs(customer_id)
    return jsonify({"jobs": jobs})

@app.route("/api/crawl", methods=["POST"])
def add_job():
    data = request.json
    job_id = news_db.add_job(
        data.get("keywords", ""),
        data.get("time_limit", "w"),
        data.get("customer_id", "")
    )
    
    from microservices.news_crawler_service.tasks import crawl_news_task
    crawl_news_task(job_id)
    
    return jsonify({"success": True, "job_id": job_id})

@app.route("/api/jobs/<int:job_id>", methods=["DELETE"])
def delete_job(job_id):
    news_db.delete_job(job_id)
    return jsonify({"success": True})

@app.route("/api/jobs/<int:job_id>/articles", methods=["GET"])
def get_articles(job_id):
    articles = news_db.get_articles(job_id)
    return jsonify({"articles": articles})

if __name__ == "__main__":
    news_db.init_db()
    app.run(port=5004, debug=True)
