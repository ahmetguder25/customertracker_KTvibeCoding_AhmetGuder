import sqlite3
import shutil
import os

DB_PATH = "customer_tracker.db"
BACKUP_PATH = "customer_tracker_backup.db"

def migrate():
    if not os.path.exists(DB_PATH):
        print("Database not found!")
        return

    # Backup
    shutil.copy2(DB_PATH, BACKUP_PATH)
    print(f"Backed up to {BACKUP_PATH}")

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Check if already migrated
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='CustomerDetail'")
    if cursor.fetchone():
        print("Database already migrated.")
        return

    print("Starting migration...")

    # 1. Rename existing Customer
    cursor.execute("ALTER TABLE Customer RENAME TO Customer_old")

    # 2. Create new Customer table (mimics BOA.CUS.Customer)
    cursor.execute("""
        CREATE TABLE Customer (
            Customerid INTEGER PRIMARY KEY UNIQUE,
            CustomerName TEXT,
            PortfolioOwnerName TEXT,
            BranchName TEXT,
            ValueSegment TEXT,
            RegionalOfficeName TEXT
        )
    """)

    # 3. Create new CustomerDetail table (local app data)
    cursor.execute("""
        CREATE TABLE CustomerDetail (
            Customerid INTEGER PRIMARY KEY UNIQUE,
            credit_limit REAL,
            sector TEXT,
            foreign_trade_volume REAL,
            memzuc_151_volume REAL,
            memzuc_152_volume REAL,
            LogoFilename TEXT,
            FOREIGN KEY (Customerid) REFERENCES Customer(Customerid) ON DELETE CASCADE
        )
    """)

    # 4. Migrate data to Customer
    # The old table used "portfolio_manager", "branch", "region"
    cursor.execute("""
        INSERT INTO Customer (
            Customerid, CustomerName, PortfolioOwnerName, BranchName, ValueSegment, RegionalOfficeName
        )
        SELECT 
            Customerid, CustomerName, portfolio_manager, branch, value_segment, region
        FROM Customer_old
    """)

    # 5. Migrate data to CustomerDetail (only structured ones)
    cursor.execute("""
        INSERT INTO CustomerDetail (
            Customerid, credit_limit, sector, foreign_trade_volume, 
            memzuc_151_volume, memzuc_152_volume, LogoFilename
        )
        SELECT 
            Customerid, credit_limit, sector, foreign_trade_volume, 
            memzuc_151_volume, memzuc_152_volume, LogoFilename
        FROM Customer_old
        WHERE IsStructured = 1
    """)

    # 6. Drop old table
    cursor.execute("DROP TABLE Customer_old")

    conn.commit()
    conn.close()
    print("Migration complete.")

if __name__ == "__main__":
    migrate()
