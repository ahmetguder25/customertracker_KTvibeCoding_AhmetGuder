import sqlite3
import os
import time

DB_PATH = os.path.join(os.path.dirname(__file__), 'crawler_state.db')

def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=20.0)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()
    # Crawler Jobs
    c.execute('''
        CREATE TABLE IF NOT EXISTS crawler_jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_name TEXT NOT NULL,
            target_url TEXT NOT NULL,
            search_query TEXT NOT NULL,
            systematic_base_name TEXT NOT NULL,
            crawl_depth INTEGER DEFAULT 0,
            file_types TEXT DEFAULT '.pdf',
            status TEXT DEFAULT 'Idle',
            last_run REAL,
            last_message TEXT
        )
    ''')
    
    try:
        c.execute("ALTER TABLE crawler_jobs ADD COLUMN crawl_depth INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass
        
    try:
        c.execute("ALTER TABLE crawler_jobs ADD COLUMN file_types TEXT DEFAULT '.pdf'")
    except sqlite3.OperationalError:
        pass
    # Document History
    c.execute('''
        CREATE TABLE IF NOT EXISTS crawled_documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id INTEGER,
            found_url TEXT,
            systematic_name TEXT,
            extracted_date TEXT,
            status TEXT,
            timestamp REAL
        )
    ''')
    conn.commit()
    conn.close()

def add_job(job_name, target_url, search_query, systematic_base_name, crawl_depth=0, file_types='.pdf'):
    conn = get_db()
    conn.execute('''
        INSERT INTO crawler_jobs (job_name, target_url, search_query, systematic_base_name, crawl_depth, file_types)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (job_name, target_url, search_query, systematic_base_name, crawl_depth, file_types))
    conn.commit()
    conn.close()

def delete_job(job_id):
    conn = get_db()
    conn.execute("DELETE FROM crawler_jobs WHERE id=?", (job_id,))
    conn.commit()
    conn.close()

def get_jobs():
    conn = get_db()
    rows = conn.execute("SELECT * FROM crawler_jobs ORDER BY id DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]

def update_job_status(job_id, status, message=None):
    conn = get_db()
    now = time.time()
    if message:
        conn.execute("UPDATE crawler_jobs SET status=?, last_run=?, last_message=? WHERE id=?", (status, now, message, job_id))
    else:
        conn.execute("UPDATE crawler_jobs SET status=?, last_run=? WHERE id=?", (status, now, job_id))
    conn.commit()
    conn.close()

def log_document(job_id, found_url, systematic_name, extracted_date, status):
    conn = get_db()
    now = time.time()
    conn.execute('''
        INSERT INTO crawled_documents (job_id, found_url, systematic_name, extracted_date, status, timestamp)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (job_id, found_url, systematic_name, extracted_date, status, now))
    conn.commit()
    conn.close()

if __name__ == "__main__":
    init_db()
