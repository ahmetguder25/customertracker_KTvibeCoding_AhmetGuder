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

    conn.commit()
    conn.close()
    print(f"Database schema synced at {DB_PATH}")

if __name__ == "__main__":
    init_db()
