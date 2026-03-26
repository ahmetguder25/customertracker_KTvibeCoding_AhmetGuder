import sqlite3
conn = sqlite3.connect('customer_tracker.db')
cursor = conn.cursor()

tables = cursor.execute("SELECT name FROM sqlite_master WHERE type='table';").fetchall()
for table_name in tables:
    t_name = table_name[0]
    print(f"--- Table: {t_name} ---")
    columns = cursor.execute(f"PRAGMA table_info({t_name});").fetchall()
    for col in columns:
        print(f"  {col[1]}: {col[2]}")
    print()

data = cursor.execute("SELECT * FROM parameter WHERE ParamType='DealType';").fetchall()
print("--- DealTypes from parameter table ---")
for row in data:
    print(row)

conn.close()
