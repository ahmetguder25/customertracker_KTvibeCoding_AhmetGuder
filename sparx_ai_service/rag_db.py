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
            PRIMARY KEY (document_id, task_type)
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
            summary_text TEXT
        )
    ''')
    conn.commit()
    conn.close()

def upsert_task(document_id, task_type, status, progress_message, percent_complete=0):
    conn = get_db()
    c = conn.cursor()
    c.execute('''
        INSERT INTO document_tasks (document_id, task_type, status, progress_message, percent_complete, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(document_id, task_type) DO UPDATE SET
            status=excluded.status,
            progress_message=excluded.progress_message,
            percent_complete=excluded.percent_complete,
            updated_at=excluded.updated_at
    ''', (document_id, task_type, status, progress_message, percent_complete, time.time()))
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

def save_summary(document_id, community_id, summary_text):
    conn = get_db()
    c = conn.cursor()
    c.execute('''
        INSERT INTO graph_summaries (document_id, community_id, summary_text)
        VALUES (?, ?, ?)
    ''', (document_id, community_id, summary_text))
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
