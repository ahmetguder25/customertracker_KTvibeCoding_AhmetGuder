from flask import Blueprint, render_template, request, jsonify
import requests
import os
import json
from app.shared.config import BASE_DIR

MICROSERVICES_FILE = os.path.join(BASE_DIR, "data", "microservices.json")

def get_microservices_state():
    if not os.path.exists(MICROSERVICES_FILE):
        return {
            "chatbot": {"enabled": True},
            "sparx_ai": {"enabled": True},
            "web_crawler": {"enabled": True},
            "news_crawler": {"enabled": True},
            "financial_reports": {"enabled": True},
            "reference_rates": {"enabled": True},
            "tuik_sdmx": {"enabled": True}
        }
    try:
        with open(MICROSERVICES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {
            "chatbot": {"enabled": True},
            "sparx_ai": {"enabled": True},
            "web_crawler": {"enabled": True},
            "news_crawler": {"enabled": True},
            "financial_reports": {"enabled": True},
            "reference_rates": {"enabled": True},
            "tuik_sdmx": {"enabled": True}
        }

def set_microservice_state(service_id: str, enabled: bool):
    state = get_microservices_state()
    if service_id not in state:
        state[service_id] = {}
    state[service_id]["enabled"] = enabled
    
    os.makedirs(os.path.dirname(MICROSERVICES_FILE), exist_ok=True)
    with open(MICROSERVICES_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)

from . import microservices_bp

@microservices_bp.route("/microservices")
def microservices():
    return render_template("management/microservices.html", state=get_microservices_state())

@microservices_bp.route("/microservices/crawler")
def microservices_crawler():
    if not get_microservices_state().get('web_crawler', {}).get('enabled', True):
        return "Crawler Microservice is Disabled", 403
    return render_template("management/crawler_detail.html")

@microservices_bp.route("/microservices/news_crawler")
def microservices_news_crawler():
    if not get_microservices_state().get('news_crawler', {}).get('enabled', True):
        return "News Crawler Microservice is Disabled", 403
        
    from app.shared.db import get_db
    from app.shared.utils import load_query
    
    conn = get_db()
    customers = conn.execute(load_query("list_customers_simple")).fetchall()
    conn.close()
    
    return render_template("management/news_crawler_detail.html", customers=customers)

@microservices_bp.route("/api/microservices/toggle", methods=["POST"])
def api_microservices_toggle():
    data = request.get_json() or {}
    service_id = data.get("service_id")
    enabled = data.get("enabled")
    if not service_id or enabled is None:
        return jsonify({"error": "Missing parameters"}), 400
    set_microservice_state(service_id, bool(enabled))
    return jsonify({"success": True, "state": get_microservices_state()})

@microservices_bp.route("/api/microservices/reset", methods=["POST"])
def api_microservices_reset():
    data = request.get_json() or {}
    service_id = data.get("service_id")
    
    port_map = {"chatbot": 5001, "sparx_ai": 5002, "web_crawler": 5003, "news_crawler": 5004, "financial_reports": 5005, "reference_rates": 5006, "tuik_sdmx": 5007}
    port = port_map.get(service_id)
    if not port:
        return jsonify({"error": "Unknown service"}), 400
        
    try:
        res = requests.post(f"http://127.0.0.1:{port}/api/reset", timeout=5)
        if res.status_code == 200:
            return jsonify({"success": True})
        return jsonify({"error": f"Service returned {res.status_code}"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 502


@microservices_bp.route("/referans-oranlar")
@microservices_bp.route("/microservices/reference_rates")
def referans_oranlar_page():
    if not get_microservices_state().get('reference_rates', {}).get('enabled', True):
        return "Reference Rates Microservice is Disabled", 403
    return render_template("management/reference_rates_detail.html")


@microservices_bp.route("/api/referans-oranlar/latest")
def api_referans_oranlar_latest():
    try:
        res = requests.get("http://127.0.0.1:5006/api/v1/rates/latest", timeout=10)
        return jsonify(res.json()), res.status_code
    except Exception as e:
        return jsonify({"error": f"Reference rates microservice unreachable: {str(e)}"}), 502


@microservices_bp.route("/api/referans-oranlar/history")
def api_referans_oranlar_history():
    rate_type = request.args.get("type", "ALL")
    limit = request.args.get("limit", 500)
    try:
        res = requests.get(f"http://127.0.0.1:5006/api/v1/rates/history?type={rate_type}&limit={limit}", timeout=10)
        return jsonify(res.json()), res.status_code
    except Exception as e:
        return jsonify({"error": f"Reference rates microservice unreachable: {str(e)}"}), 502


@microservices_bp.route("/api/referans-oranlar/fetch", methods=["POST"])
def api_referans_oranlar_fetch():
    try:
        res = requests.post("http://127.0.0.1:5006/api/v1/rates/fetch", timeout=30)
        return jsonify(res.json()), res.status_code
    except Exception as e:
        return jsonify({"error": f"Reference rates microservice unreachable: {str(e)}"}), 502


@microservices_bp.route("/tuik-data")
@microservices_bp.route("/microservices/tuik_sdmx")
def tuik_data_page():
    if not get_microservices_state().get('tuik_sdmx', {}).get('enabled', True):
        return "TUIK SDMX Microservice is Disabled", 403
    return render_template("management/tuik_sdmx_detail.html")


@microservices_bp.route("/api/tuik-data/latest")
def api_tuik_data_latest():
    try:
        res = requests.get("http://127.0.0.1:5007/api/v1/tuik/latest", timeout=10)
        return jsonify(res.json()), res.status_code
    except Exception as e:
        return jsonify({"error": f"TUIK SDMX microservice unreachable: {str(e)}"}), 502


@microservices_bp.route("/api/tuik-data/history")
def api_tuik_data_history():
    indicator = request.args.get("indicator", "TUFE_MONTHLY")
    limit = request.args.get("limit", 100)
    try:
        res = requests.get(f"http://127.0.0.1:5007/api/v1/tuik/history?indicator={indicator}&limit={limit}", timeout=10)
        return jsonify(res.json()), res.status_code
    except Exception as e:
        return jsonify({"error": f"TUIK SDMX microservice unreachable: {str(e)}"}), 502


@microservices_bp.route("/api/tuik-data/fetch", methods=["POST"])
def api_tuik_data_fetch():
    try:
        res = requests.post("http://127.0.0.1:5007/api/v1/tuik/fetch", timeout=30)
        return jsonify(res.json()), res.status_code
    except Exception as e:
        return jsonify({"error": f"TUIK SDMX microservice unreachable: {str(e)}"}), 502


@microservices_bp.route("/api/tuik-data/api-key", methods=["GET", "POST"])
def api_tuik_data_key():
    try:
        if request.method == "POST":
            res = requests.post("http://127.0.0.1:5007/api/v1/tuik/api-key", json=request.get_json(), timeout=10)
        else:
            res = requests.get("http://127.0.0.1:5007/api/v1/tuik/api-key", timeout=10)
        return jsonify(res.json()), res.status_code
    except Exception as e:
        return jsonify({"error": f"TUIK SDMX microservice unreachable: {str(e)}"}), 502


