import sqlite3
import os

DB_PATH = r"c:\Users\AILAB9\Desktop\customer_tracker\customer_tracker.db"

def add_dummy_data():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    customers = [
        ("Global Tech Solutions", 5000000, "Platinum", "Istanbul", "2", "Marmara", "Ahmet Yılmaz", 1200000, 500000, 300000, 1),
        ("Bursa Automotive Parts", 3500000, "Gold", "Bursa", "10", "Marmara", "Mehmet Demir", 800000, 200000, 150000, 1),
        ("Izmir Logistics Hub", 2800000, "Silver", "Izmir", "3", "Aegean", "Ayşe Kaya", 1500000, 400000, 250000, 1),
        ("Ankara Solar Energy", 4200000, "Gold", "Ankara", "6", "Central Anatolia", "Fatma Sahin", 950000, 350000, 200000, 1),
        ("Antalya Tourism Group", 6000000, "Platinum", "Antalya", "11", "Mediterranean", "Mustafa Can", 2000000, 600000, 500000, 1),
        ("Kocaeli Steel Works", 7500000, "Platinum", "Kocaeli", "8", "Marmara", "Elif Arslan", 3000000, 1200000, 1000000, 1),
        ("Denizli Textile Corp", 1800000, "Silver", "Denizli", "1", "Aegean", "Canan Ozturk", 1100000, 300000, 100000, 1),
        ("Adana Farm Fresh", 1200000, "Bronze", "Adana", "1", "Mediterranean", "Murat Yıldız", 400000, 100000, 50000, 0),
        ("Gaziantep Food Expo", 2500000, "Silver", "Gaziantep", "1", "Southeastern Anatolia", "Zeynep Bakır", 700000, 250000, 150000, 0),
        ("Trabzon Port Services", 3000000, "Gold", "Trabzon", "3", "Black Sea", "Hakan Akın", 1300000, 450000, 350000, 0),
    ]

    for name, limit, seg, branch, sector, region, pm, ft, m151, m152, struct in customers:
        cur.execute("""
            INSERT INTO Customer (
                CustomerName, credit_limit, value_segment, branch, sector, region, 
                portfolio_manager, foreign_trade_volume, memzuc_151_volume, memzuc_152_volume, IsStructured
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (name, limit, seg, branch, sector, region, pm, ft, m151, m152, struct))
        
        customer_id = cur.lastrowid
        
        # Add 1 deal for the 7 structured customers
        if struct == 1:
            # Random enough deal data
            cur.execute("""
                INSERT INTO CustomerDeals (
                    customerid, contact_name, deal_size, expected_pricing_pa, currency, status, dealtype, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (customer_id, f"Manager of {name}", limit * 0.2, 3.5, 1, 1, 1, f"Initial discussion for {name} project finance."))

    conn.commit()
    conn.close()
    print("Successfully added 10 dummy customers and 7 deals.")

if __name__ == "__main__":
    add_dummy_data()
