import subprocess
import sys
import time
import os
import json
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

MICROSERVICES_FILE = os.path.join(os.path.dirname(__file__), "data", "microservices.json")

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

def main():
    print("Starting Flask Web Server...")
    # Start the Flask app
    flask_process = subprocess.Popen(
        [sys.executable, "-m", "app"],
        env=dict(os.environ, FLASK_DEBUG="1"),
        stdout=sys.stdout,
        stderr=sys.stderr
    )

    services = {
        "chatbot": {
            "module": "microservices.chatbot_service.app",
            "process": None
        },
        "sparx_ai": {
            "module": "microservices.sparx_ai_service.app",
            "process": None
        },
        "web_crawler": {
            "module": "microservices.crawler_service.app",
            "process": None
        },
        "news_crawler": {
            "module": "microservices.news_crawler_service.app",
            "process": None
        },
        "financial_reports": {
            "module": "microservices.financial_reports_service.app",
            "process": None
        },
        "reference_rates": {
            "module": "microservices.reference_rates_service.app",
            "process": None
        },
        "tuik_sdmx": {
            "module": "microservices.tuik_sdmx_service.app",
            "process": None
        }
    }

    try:
        # Keep the main thread alive waiting for subprocesses
        while True:
            time.sleep(1)
            
            # If main process exits, we should exit the whole runner
            if flask_process.poll() is not None:
                break
                
            state = get_microservices_state()
            for svc_id, info in services.items():
                is_enabled = state.get(svc_id, {}).get("enabled", True)
                
                if is_enabled:
                    # If not running or died, start it
                    if info["process"] is None or info["process"].poll() is not None:
                        print(f"Starting {svc_id} microservice...")
                        
                        env = os.environ.copy()
                        env["PYTHONPATH"] = os.path.dirname(os.path.abspath(__file__))
                        
                        info["process"] = subprocess.Popen(
                            [sys.executable, "-m", info["module"]],
                            stdout=sys.stdout,
                            stderr=sys.stderr,
                            env=env
                        )
                else:
                    # If it is running, kill it
                    if info["process"] is not None and info["process"].poll() is None:
                        print(f"Stopping {svc_id} microservice...")
                        info["process"].terminate()
                        info["process"].wait()
                        info["process"] = None

    except KeyboardInterrupt:
        print("\nShutting down gracefully...")
    finally:
        flask_process.terminate()
        flask_process.wait()
        
        for svc_id, info in services.items():
            if info["process"] is not None and info["process"].poll() is None:
                info["process"].terminate()
                info["process"].wait()
                
        print("Shutdown complete.")

if __name__ == '__main__':
    main()
