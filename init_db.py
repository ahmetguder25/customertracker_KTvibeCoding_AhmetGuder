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
            logo_filename TEXT,
            created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS comments (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id   INTEGER NOT NULL,
            author        TEXT    NOT NULL,
            content       TEXT    NOT NULL,
            created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (customer_id) REFERENCES customers(id) ON DELETE CASCADE
        )
    """)

    # Only seed if table is empty
    cur.execute("SELECT COUNT(*) FROM customers")
    if cur.fetchone()[0] == 0:
        dummy_data = [
            ("Apex Capital",       "John Miller",    5000000,  "Lead",           "Energy",          "Initial outreach completed",  "apex_capital.png"),
            ("BlueWave Holdings",  "Sarah Chen",     12500000, "Proposal",       "Real Estate",     "Term sheet under review",     "bluewave_holdings.png"),
            ("Crestline Partners", "David Okonkwo",  8750000,  "Due Diligence",  "Infrastructure",  "Site visit scheduled Q2",     "crestline_partners.png"),
            ("Delta Structured",   "Maria Gonzalez", 20000000, "Closed Won",     "Technology",      "Deal closed March 2026",      "delta_structured.png"),
            ("Evergreen Finance",  "James Park",     3200000,  "Closed Lost",    "Healthcare",      "Lost to competing bid",       "evergreen_finance.png"),
        ]
        cur.executemany(
            "INSERT INTO customers (company_name, contact_name, deal_size, status, sector, notes, logo_filename) VALUES (?, ?, ?, ?, ?, ?, ?)",
            dummy_data,
        )
        print(f"Inserted {len(dummy_data)} dummy rows.")

        # Seed sample comments
        sample_comments = [
            (1, "Alice Thompson", "Had a great initial call. They're very interested in our energy fund structure."),
            (1, "Bob Martinez",   "Follow-up meeting scheduled for next week to discuss term sheet."),
            (2, "Alice Thompson", "Sarah sent over their latest financials. Looks solid."),
            (3, "Charlie Davis",  "Site visit confirmed for April 15. Engineering team will join."),
            (4, "Bob Martinez",   "Deal fully closed. Outstanding performance from the team!"),
            (5, "Alice Thompson", "They went with a competitor offering lower fees. Lessons learned noted."),
        ]
        cur.executemany(
            "INSERT INTO comments (customer_id, author, content) VALUES (?, ?, ?)",
            sample_comments,
        )
        print(f"Inserted {len(sample_comments)} sample comments.")

    conn.commit()
    conn.close()
    print(f"Database ready at {DB_PATH}")


if __name__ == "__main__":
    init_db()
