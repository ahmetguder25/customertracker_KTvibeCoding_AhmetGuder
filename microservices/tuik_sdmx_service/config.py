import os
import json

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)

DATABASE_PATH = os.path.join(DATA_DIR, "tuik_sdmx_journal.db")
DATABASE_URL = f"sqlite:///{DATABASE_PATH}"

SERVER_HOST = "127.0.0.1"
SERVER_PORT = 5007

API_KEY_FILES = [
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "tuik_api_key.json"),
    os.path.join(BASE_DIR, "tuik_api_key.json"),
    os.path.join(BASE_DIR, "tuik_api_key.txt")
]

def get_tuik_api_key() -> str:
    """
    Retrieves the TUİK API key from gitignored file or environment variable.
    """
    env_key = os.environ.get("TUIK_API_KEY", "").strip()
    if env_key:
        return env_key
        
    for file_path in API_KEY_FILES:
        if os.path.exists(file_path):
            try:
                if file_path.endswith(".json"):
                    with open(file_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        key = data.get("api_key") or data.get("key") or ""
                        if key.strip():
                            return key.strip()
                else:
                    with open(file_path, "r", encoding="utf-8") as f:
                        content = f.read().strip()
                        if content:
                            return content
            except Exception as e:
                print(f"[TUIK SDMX Config] Error reading key from {file_path}: {e}")
    return ""
