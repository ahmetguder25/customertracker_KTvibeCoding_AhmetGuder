import sqlite3
import os
import time

DB_PATH = os.path.join(os.path.dirname(__file__), 'news_crawler.db')

def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=20.0)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS news_jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            keywords TEXT,
            time_limit TEXT,
            customer_id TEXT,
            status TEXT,
            last_message TEXT,
            created_at REAL
        )
    ''')
    
    c.execute('''
        CREATE TABLE IF NOT EXISTS news_articles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id INTEGER,
            title TEXT,
            url TEXT,
            snippet TEXT,
            ai_summary TEXT,
            published_date TEXT,
            created_at REAL,
            FOREIGN KEY(job_id) REFERENCES news_jobs(id)
        )
    ''')
    conn.commit()
    conn.close()

def add_job(keywords, time_limit, customer_id):
    conn = get_db()
    c = conn.cursor()
    c.execute('''
        INSERT INTO news_jobs (keywords, time_limit, customer_id, status, last_message, created_at)
        VALUES (?, ?, ?, 'Pending', 'Waiting to start...', ?)
    ''', (keywords, time_limit, customer_id, time.time()))
    job_id = c.lastrowid
    conn.commit()
    conn.close()
    return job_id

def get_jobs(customer_id=None):
    conn = get_db()
    c = conn.cursor()
    if customer_id:
        jobs = c.execute('SELECT * FROM news_jobs WHERE customer_id = ? ORDER BY id DESC', (str(customer_id),)).fetchall()
    else:
        jobs = c.execute('SELECT * FROM news_jobs ORDER BY id DESC').fetchall()
    conn.close()
    return [dict(j) for j in jobs]

def get_job(job_id):
    conn = get_db()
    c = conn.cursor()
    job = c.execute('SELECT * FROM news_jobs WHERE id = ?', (job_id,)).fetchone()
    conn.close()
    return dict(job) if job else None

def delete_job(job_id):
    conn = get_db()
    c = conn.cursor()
    c.execute('DELETE FROM news_articles WHERE job_id = ?', (job_id,))
    c.execute('DELETE FROM news_jobs WHERE id = ?', (job_id,))
    conn.commit()
    conn.close()

def update_job_status(job_id, status, message):
    conn = get_db()
    c = conn.cursor()
    c.execute('UPDATE news_jobs SET status=?, last_message=? WHERE id=?', (status, message, job_id))
    conn.commit()
    conn.close()

def save_article(job_id, title, url, snippet, ai_summary, published_date):
    conn = get_db()
    c = conn.cursor()
    c.execute('''
        INSERT INTO news_articles (job_id, title, url, snippet, ai_summary, published_date, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (job_id, title, url, snippet, ai_summary, published_date, time.time()))
    conn.commit()
    conn.close()

def get_articles(job_id):
    conn = get_db()
    c = conn.cursor()
    articles = c.execute('SELECT * FROM news_articles WHERE job_id = ? ORDER BY id ASC', (job_id,)).fetchall()
    conn.close()
    return [dict(a) for a in articles]

def url_exists(url):
    conn = get_db()
    c = conn.cursor()
    row = c.execute('SELECT id FROM news_articles WHERE url = ?', (url,)).fetchone()
    conn.close()
    return row is not None

if __name__ == '__main__':
    init_db()
    print("news_crawler.db initialized.")
