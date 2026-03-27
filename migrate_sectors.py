import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "customer_tracker.db")

sector_definitions = [
    # code, en_desc, tr_desc
    ("1", "Retail", "Perakende"),
    ("2", "Technology", "Teknoloji"),
    ("3", "Infrastructure", "Altyapı"),
    ("4", "Financials", "Finans"),
    ("5", "Healthcare", "Sağlık"),
    ("6", "Energy", "Enerji"),
    ("7", "Telecom", "Telekomünikasyon"),
    ("8", "Manufacturing", "Üretim"),
    ("9", "Real Estate", "Gayrimenkul"),
    ("10", "Automotive", "Otomotiv"),
    ("11", "Other", "Diğer")
]

def migrate_sectors():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # 1. Insert Sectors into Parameter table
    for code, en_desc, tr_desc in sector_definitions:
        # EN
        cur.execute(
            "INSERT OR REPLACE INTO Parameter (ParamType, ParamCode, ParamDescription, ParamValue, LanguageId) VALUES (?, ?, ?, ?, 0)",
            ("Sector", code, en_desc, "")
        )
        # TR
        cur.execute(
            "INSERT OR REPLACE INTO Parameter (ParamType, ParamCode, ParamDescription, ParamValue, LanguageId) VALUES (?, ?, ?, ?, 1)",
            ("Sector", code, tr_desc, "")
        )

    # 2. Update existing customers
    # We will map existing case-insensitive matches to the Code. Any unaccounted strings get mapped to 11 (Other)
    cur.execute("SELECT Customerid, sector FROM Customer WHERE sector IS NOT NULL AND sector != ''")
    customers = cur.fetchall()

    mapping = {desc.lower(): code for code, desc, _ in sector_definitions}
    
    for cid, sect in customers:
        sect_lower = str(sect).strip().lower()
        new_code = mapping.get(sect_lower, "11") # Default 11
        cur.execute("UPDATE Customer SET sector=? WHERE Customerid=?", (new_code, cid))

    conn.commit()
    print(f"Successfully migrated sectors for {len(customers)} customers.")
    conn.close()

if __name__ == "__main__":
    migrate_sectors()
