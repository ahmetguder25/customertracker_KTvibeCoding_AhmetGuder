"""Initialize the SQLite database and seed it with dummy data."""
import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "customer_tracker.db")


def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS customers (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            company_name  TEXT    NOT NULL,
            contact_name  TEXT    NOT NULL,
            deal_size     REAL    NOT NULL,
            status        TEXT    NOT NULL DEFAULT 'Lead',
            sector        TEXT,
            notes         TEXT,
            created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Only seed if table is empty
    cur.execute("SELECT COUNT(*) FROM customers")
    if cur.fetchone()[0] == 0:
        dummy_data = [
            ("Apex Capital",       "John Miller",    5000000,  "Lead",           "Energy",          "Initial outreach completed"),
            ("BlueWave Holdings",  "Sarah Chen",     12500000, "Proposal",       "Real Estate",     "Term sheet under review"),
            ("Crestline Partners", "David Okonkwo",  8750000,  "Due Diligence",  "Infrastructure",  "Site visit scheduled Q2"),
            ("Delta Structured",   "Maria Gonzalez", 20000000, "Closed Won",     "Technology",      "Deal closed March 2026"),
            ("Evergreen Finance",  "James Park",     3200000,  "Closed Lost",    "Healthcare",      "Lost to competing bid"),
        ]
        cur.executemany(
            "INSERT INTO customers (company_name, contact_name, deal_size, status, sector, notes) VALUES (?, ?, ?, ?, ?, ?)",
            dummy_data,
        )
        print(f"Inserted {len(dummy_data)} dummy rows.")

    conn.commit()
    conn.close()
    print(f"Database ready at {DB_PATH}")


if __name__ == "__main__":
    init_db()
