"""Initialize the SQLite database and seed it with dummy data."""
import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "customer_tracker.db")

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS Customer (
            Customerid            INTEGER PRIMARY KEY AUTOINCREMENT,
            CustomerName          TEXT    NOT NULL,
            credit_limit          REAL,
            value_segment         TEXT,
            branch                TEXT,
            sector                TEXT,
            region                TEXT,
            portfolio_manager     TEXT,
            foreign_trade_volume  REAL,
            memzuc_151_volume     REAL,
            memzuc_152_volume     REAL,
            LogoFilename          TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS CustomerDeals (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            customerid    INTEGER NOT NULL,
            contact_name  TEXT,
            deal_size     REAL,
            expected_pricing_pa  REAL,
            currency      INTEGER DEFAULT 0,
            status        INTEGER,
            dealtype      INTEGER,
            notes         TEXT,
            created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (customerid) REFERENCES Customer(Customerid) ON DELETE CASCADE
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS Comment (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id   INTEGER NOT NULL,
            author        TEXT    NOT NULL,
            content       TEXT    NOT NULL,
            created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (customer_id) REFERENCES Customer(Customerid) ON DELETE CASCADE
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS Parameter (
            ParamType        TEXT,
            ParamCode        TEXT,
            ParamDescription TEXT,
            ParamValue       TEXT,
            ParamValue2      TEXT,
            ParamValue3      TEXT,
            ParamValue4      TEXT,
            ParamValue5      TEXT,
            ParamValue6      TEXT,
            ParamValue7      TEXT,
            PRIMARY KEY (ParamType, ParamCode)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS CustomerAnalysis (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id   INTEGER NOT NULL,
            analysis_text TEXT    NOT NULL,
            created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (customer_id) REFERENCES Customer(Customerid) ON DELETE CASCADE
        )
    """)

    # ── Migrate existing DB: add new columns if missing ─────────────────────
    try:
        cur.execute("ALTER TABLE CustomerDeals ADD COLUMN expected_pricing_pa REAL")
    except Exception:
        pass
    try:
        cur.execute("ALTER TABLE CustomerDeals ADD COLUMN currency INTEGER DEFAULT 0")
    except Exception:
        pass
    try:
        cur.execute("ALTER TABLE Customer ADD COLUMN IsStructured INTEGER DEFAULT 0")
        # Existing customers should remain visible
        cur.execute("UPDATE Customer SET IsStructured=1 WHERE IsStructured IS NULL OR IsStructured=0")
    except Exception:
        pass

    # ── Seed FEC (currency) parameters ──────────────────────────────────────
    fec_params = [
        ("FEC", "0",  "Turkish Lira",     "TRY"),
        ("FEC", "1",  "American Dollar",  "USD"),
        ("FEC", "19", "EURO",             "EUR"),
    ]
    for pt, pc, desc, val in fec_params:
        cur.execute(
            "INSERT OR IGNORE INTO Parameter (ParamType, ParamCode, ParamDescription, ParamValue) VALUES (?, ?, ?, ?)",
            (pt, pc, desc, val)
        )

    # ── Seed Status logos in ParamValue3 ────────────────────────────────────
    status_logos = {
        "1": "🎯",   # Lead
        "2": "📄",   # Proposal
        "3": "🔍",   # Due Diligence
        "4": "✅",   # Closed Won
        "5": "❌",   # Closed Lost
        "6": "🧪",   # Test
    }
    for code, logo in status_logos.items():
        cur.execute(
            "UPDATE Parameter SET ParamValue3=? WHERE ParamType='Status' AND ParamCode=?",
            (logo, code)
        )

    conn.commit()
    conn.close()
    print(f"Database schema synced at {DB_PATH}")

if __name__ == "__main__":
    init_db()
