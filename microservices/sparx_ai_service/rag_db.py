import sqlite3
import os
import time

DB_PATH = os.path.join(os.path.dirname(__file__), 'rag_state.db')

def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=20.0)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()
    # Document Tasks Table
    c.execute('''
        CREATE TABLE IF NOT EXISTS document_tasks (
            document_id TEXT,
            task_type TEXT,
            status TEXT,
            progress_message TEXT,
            percent_complete INTEGER,
            updated_at REAL,
            start_time REAL,
            PRIMARY KEY (document_id, task_type)
        )
    ''')
    
    # Document Logs Table
    c.execute('''
        CREATE TABLE IF NOT EXISTS document_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            document_id TEXT,
            timestamp REAL,
            message TEXT
        )
    ''')
    
    # Processed Chunks Table
    c.execute('''
        CREATE TABLE IF NOT EXISTS processed_chunks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            document_id TEXT,
            chunk_hash TEXT,
            raw_text TEXT,
            created_at REAL
        )
    ''')
    
    # Graph Summaries Table
    c.execute('''
        CREATE TABLE IF NOT EXISTS graph_summaries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            document_id TEXT,
            community_id INTEGER,
            summary_text TEXT,
            embedding TEXT
        )
    ''')
    try:
        c.execute("ALTER TABLE graph_summaries ADD COLUMN embedding TEXT")
    except Exception:
        pass
    try:
        c.execute("ALTER TABLE document_tasks ADD COLUMN start_time REAL")
    except Exception:
        pass
    conn.commit()
    conn.close()

def upsert_task(document_id, task_type, status, progress_message, percent_complete=0):
    conn = get_db()
    c = conn.cursor()
    now = time.time()
    if percent_complete == 0:
        c.execute('''
            INSERT INTO document_tasks (document_id, task_type, status, progress_message, percent_complete, updated_at, start_time)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(document_id, task_type) DO UPDATE SET
                status=excluded.status,
                progress_message=excluded.progress_message,
                percent_complete=excluded.percent_complete,
                updated_at=excluded.updated_at,
                start_time=excluded.start_time
        ''', (document_id, task_type, status, progress_message, percent_complete, now, now))
    else:
        c.execute('''
            INSERT INTO document_tasks (document_id, task_type, status, progress_message, percent_complete, updated_at, start_time)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(document_id, task_type) DO UPDATE SET
                status=excluded.status,
                progress_message=excluded.progress_message,
                percent_complete=excluded.percent_complete,
                updated_at=excluded.updated_at
        ''', (document_id, task_type, status, progress_message, percent_complete, now, now))
    conn.commit()
    conn.close()

def get_task_status(document_id):
    conn = get_db()
    c = conn.cursor()
    tasks = c.execute('SELECT * FROM document_tasks WHERE document_id = ?', (document_id,)).fetchall()
    conn.close()
    return [dict(t) for t in tasks]

def save_chunk(document_id, chunk_hash, raw_text):
    conn = get_db()
    c = conn.cursor()
    c.execute('''
        INSERT INTO processed_chunks (document_id, chunk_hash, raw_text, created_at)
        VALUES (?, ?, ?, ?)
    ''', (document_id, chunk_hash, raw_text, time.time()))
    conn.commit()
    conn.close()

def get_chunks(document_id):
    conn = get_db()
    c = conn.cursor()
    chunks = c.execute('SELECT * FROM processed_chunks WHERE document_id = ?', (document_id,)).fetchall()
    conn.close()
    return [dict(ch) for ch in chunks]

def clear_chunks(document_id):
    conn = get_db()
    c = conn.cursor()
    c.execute('DELETE FROM processed_chunks WHERE document_id = ?', (document_id,))
    conn.commit()
    conn.close()

def append_log(document_id, message):
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute('''
            INSERT INTO document_logs (document_id, timestamp, message)
            VALUES (?, ?, ?)
        ''', (document_id, time.time(), message))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Failed to append log: {e}")

def get_logs(document_id, last_id=0):
    conn = get_db()
    c = conn.cursor()
    logs = c.execute('SELECT * FROM document_logs WHERE document_id = ? AND id > ? ORDER BY id ASC', (document_id, last_id)).fetchall()
    conn.close()
    return [dict(l) for l in logs]


def save_summary(document_id, community_id, summary_text, embedding=None):
    conn = get_db()
    c = conn.cursor()
    c.execute('''
        INSERT INTO graph_summaries (document_id, community_id, summary_text, embedding)
        VALUES (?, ?, ?, ?)
    ''', (document_id, community_id, summary_text, embedding))
    conn.commit()
    conn.close()

def get_summaries(document_id):
    conn = get_db()
    c = conn.cursor()
    summaries = c.execute('SELECT * FROM graph_summaries WHERE document_id = ?', (document_id,)).fetchall()
    conn.close()
    return [dict(s) for s in summaries]

def clear_summaries(document_id):
    conn = get_db()
    c = conn.cursor()
    c.execute('DELETE FROM graph_summaries WHERE document_id = ?', (document_id,))
    conn.commit()
    conn.close()

if __name__ == '__main__':
    init_db()
    print("rag_state.db initialized.")
