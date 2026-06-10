import sys
import os
sys.path.append(os.getcwd())
from app import get_db

try:
    conn = get_db()
    rows = conn.execute("SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME = 'User'").fetchall()
    print([r["COLUMN_NAME"] for r in rows])
except Exception as e:
    print(f"Error: {e}")
