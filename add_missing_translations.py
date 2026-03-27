import sqlite3
import os

db_path = os.path.join(os.path.dirname(__file__), 'customer_tracker.db')

def add_translations():
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    
    translations = [
        ("dash_total_deals", "Total Deals", "Toplam Fırsat"),
        ("dash_active_pipeline", "Active Pipeline", "Aktif Fırsatlar"),
        ("dash_win_rate", "Win Rate", "Kazanma Oranı")
    ]
    
    for key, en, tr in translations:
        # EN
        cur.execute(
            "INSERT OR IGNORE INTO Dictionary (Id, Description, LanguageId) VALUES (?, ?, 0)",
            (key, en)
        )
        cur.execute(
            "UPDATE Dictionary SET Description = ? WHERE Id = ? AND LanguageId = 0",
            (en, key)
        )
        
        # TR
        cur.execute(
            "INSERT OR IGNORE INTO Dictionary (Id, Description, LanguageId) VALUES (?, ?, 1)",
            (key, tr)
        )
        cur.execute(
            "UPDATE Dictionary SET Description = ? WHERE Id = ? AND LanguageId = 1",
            (tr, key)
        )
        
    conn.commit()
    conn.close()
    print("Successfully added missing KPI translations!")

if __name__ == '__main__':
    add_translations()
