import sqlite3
import os

db_path = os.path.join(os.path.dirname(__file__), 'customer_tracker.db')

def migrate_db():
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    try:
        cur.execute("ALTER TABLE CustomerAnalysis ADD COLUMN LanguageId INTEGER DEFAULT 0")
        print("Successfully added LanguageId to CustomerAnalysis.")
    except Exception as e:
        print("Migration info:", e)
    conn.commit()
    conn.close()

if __name__ == '__main__':
    migrate_db()
