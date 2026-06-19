import requests
import sqlite3
import os

doc_id = "1"
SPARX_API_URL = "http://10.19.57.150:8000"
from app import get_db, CUSTOMER_DOCS_FOLDER

try:
    conn = get_db()
    row = conn.execute("SELECT FileName FROM BOA.COR.CustomerDocument WHERE DocID=?", (doc_id,)).fetchone()
    conn.close()
except Exception as e:
    print(f"Error connecting to DB: {e}")
    row = None

if not row:
    print("Doc not found in DB")
else:
    filepath = os.path.join(CUSTOMER_DOCS_FOLDER, row["FileName"])
    if not os.path.exists(filepath):
        print(f"File {filepath} not found")
    else:
        with open(filepath, 'rb') as f:
            files = {'file': (row["FileName"], f, 'application/pdf')}
            data_payload = {'document_id': doc_id}
            print("Sending request to Sparx...")
            resp = requests.post(f"{SPARX_API_URL}/api/chunk", files=files, data=data_payload, timeout=10)
            print(resp.status_code, resp.text)
