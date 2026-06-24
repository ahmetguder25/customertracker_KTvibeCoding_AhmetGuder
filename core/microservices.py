import os
import json

from core.config import BASE_DIR

MICROSERVICES_FILE = os.path.join(BASE_DIR, "data", "microservices.json")

def get_microservices_state():
    """Returns the microservices state dict. Creates default if not exists."""
    if not os.path.exists(MICROSERVICES_FILE):
        return {
            "chatbot": {"enabled": True},
            "sparx_ai": {"enabled": True},
            "web_crawler": {"enabled": True}
        }
    try:
        with open(MICROSERVICES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {
            "chatbot": {"enabled": True},
            "sparx_ai": {"enabled": True},
            "web_crawler": {"enabled": True}
        }

def set_microservice_state(service_id: str, enabled: bool):
    """Updates the enabled state of a specific microservice."""
    state = get_microservices_state()
    if service_id not in state:
        state[service_id] = {}
    state[service_id]["enabled"] = enabled
    
    os.makedirs(os.path.dirname(MICROSERVICES_FILE), exist_ok=True)
    with open(MICROSERVICES_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)
