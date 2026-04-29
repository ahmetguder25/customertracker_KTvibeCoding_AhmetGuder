import sys
from app import get_db

def seed():
    conn = get_db()
    print("Seeding dummy data...")
    
    # 1. Stakeholders
    conn.execute("INSERT INTO BOA.ZZZ.Stakeholder (FullName, Organization, Department, Email) VALUES ('Alice Smith', 'Risk Dept', 'Credit Risk', 'alice@example.com')")
    conn.execute("INSERT INTO BOA.ZZZ.Stakeholder (FullName, Organization, Department, Email) VALUES ('Bob Jones', 'Legal Dept', 'Contracts', 'bob@example.com')")
    conn.execute("INSERT INTO BOA.ZZZ.Stakeholder (FullName, Organization, Department, Email) VALUES ('Charlie Davis', 'Operations', 'Settlements', 'charlie@example.com')")
    
    # 2. Customers
    try:
        max_id = conn.execute("SELECT ISNULL(MAX(Customerid), 990000) AS M FROM BOA.ZZZ.Customer").fetchone()["M"]
        c1 = max_id + 1
        c2 = max_id + 2
        c3 = max_id + 3
        conn.execute("INSERT INTO BOA.ZZZ.Customer (Customerid, CustomerName, IsStructured) VALUES (?, 'Acme Corp', 1)", (c1,))
        conn.execute("INSERT INTO BOA.ZZZ.Customer (Customerid, CustomerName, IsStructured) VALUES (?, 'Global Tech AS', 1)", (c2,))
        conn.execute("INSERT INTO BOA.ZZZ.Customer (Customerid, CustomerName, IsStructured) VALUES (?, 'Nexus Industries', 1)", (c3,))
    except Exception as e:
        print("Error inserting customer:", e)
        conn.commit()
        return

    # 3. Products
    p1 = conn.execute("INSERT INTO BOA.ZZZ.Product (ProductCode, ProductName, Description) OUTPUT INSERTED.ProductID VALUES ('P001', 'Green Sukuk 2026', 'Sustainable energy financing')").fetchone()["ProductID"]
    p2 = conn.execute("INSERT INTO BOA.ZZZ.Product (ProductCode, ProductName, Description) OUTPUT INSERTED.ProductID VALUES ('P002', 'Tech Syndication', 'Syndicated loan for IT infrastructure')").fetchone()["ProductID"]

    # 4. Objectives & KRs
    obj1 = conn.execute("INSERT INTO BOA.ZZZ.Objective (Title, Description, Period, Owner) OUTPUT INSERTED.ObjectiveID VALUES ('Expand Green Financing', 'Increase ESG aligned assets', '2026-H1', 'Management')").fetchone()["ObjectiveID"]
    obj2 = conn.execute("INSERT INTO BOA.ZZZ.Objective (Title, Description, Period, Owner) OUTPUT INSERTED.ObjectiveID VALUES ('Grow IT Syndications', 'Target top tech firms for syndicated facilities', '2026-H1', 'Management')").fetchone()["ObjectiveID"]

    kr1 = conn.execute("INSERT INTO BOA.ZZZ.KeyResult (ObjectiveID, Title, TargetValue, Unit, CalcMethod) OUTPUT INSERTED.KRID VALUES (?, 'Close $50M in Green Sukuk', 50000000, 'usd', 'sum_size')", (obj1,)).fetchone()["KRID"]
    kr2 = conn.execute("INSERT INTO BOA.ZZZ.KeyResult (ObjectiveID, Title, TargetValue, Unit, CalcMethod) OUTPUT INSERTED.KRID VALUES (?, '2 Tech Syndication Deals', 2, 'deals', 'count')", (obj2,)).fetchone()["KRID"]

    conn.execute("INSERT INTO BOA.ZZZ.OKRProductLink (KRID, ProductID) VALUES (?, ?)", (kr1, p1))
    conn.execute("INSERT INTO BOA.ZZZ.OKRProductLink (KRID, ProductID) VALUES (?, ?)", (kr2, p2))

    # 5. Projects
    proj1 = conn.execute("INSERT INTO BOA.ZZZ.Project (ProjectName, Description, Status, Owner, ObjectiveID) OUTPUT INSERTED.ProjectID VALUES ('Acme Green Restructuring', 'Preparing structure for Acme', 'Active', 'Alice', ?)", (obj1,)).fetchone()["ProjectID"]
    
    # 6. Deals
    d1 = conn.execute("INSERT INTO BOA.ZZZ.CustomerDeals (customerid, contact_name, deal_size, expected_pricing_pa, currency, status, dealtype, notes, ProductID) OUTPUT INSERTED.id VALUES (?, 'John Doe', 20000000, 0.05, 1, 4, 3, 'First green tranche completed', ?)", (c1, p1)).fetchone()["id"]
    d2 = conn.execute("INSERT INTO BOA.ZZZ.CustomerDeals (customerid, contact_name, deal_size, expected_pricing_pa, currency, status, dealtype, notes, ProductID) OUTPUT INSERTED.id VALUES (?, 'Jane Smith', 10000000, 0.045, 1, 3, 3, 'DD ongoing for second tranche', ?)", (c1, p1)).fetchone()["id"]
    d3 = conn.execute("INSERT INTO BOA.ZZZ.CustomerDeals (customerid, contact_name, deal_size, expected_pricing_pa, currency, status, dealtype, notes, ProductID) OUTPUT INSERTED.id VALUES (?, 'Mike Tech', 15000000, 0.06, 1, 2, 1, 'Proposal sent to Nexus', ?)", (c3, p2)).fetchone()["id"]

    # 7. Work Items
    wi1 = conn.execute("INSERT INTO BOA.ZZZ.WorkItem (ParentType, ParentID, Title, Description, Status) OUTPUT INSERTED.ItemID VALUES ('project', ?, 'Legal Review', 'Review compliance docs', 'in_progress')", (proj1,)).fetchone()["ItemID"]
    wi2 = conn.execute("INSERT INTO BOA.ZZZ.WorkItem (ParentType, ParentID, Title, Description, Status) OUTPUT INSERTED.ItemID VALUES ('project', ?, 'Risk Assessment', 'Analyze risk profile', 'done')", (proj1,)).fetchone()["ItemID"]
    wi3 = conn.execute("INSERT INTO BOA.ZZZ.WorkItem (ParentType, ParentID, Title, Description, Status) OUTPUT INSERTED.ItemID VALUES ('deal', ?, 'Prepare Term Sheet', 'Draft the initial TS', 'not_started')", (d3,)).fetchone()["ItemID"]

    # Prereqs
    conn.execute("INSERT INTO BOA.ZZZ.WorkItemPrerequisite (ItemID, RequiresItemID) VALUES (?, ?)", (wi1, wi2))

    # Stakeholders
    st1 = conn.execute("SELECT TOP 1 StakeholderID FROM BOA.ZZZ.Stakeholder").fetchone()["StakeholderID"]
    conn.execute("INSERT INTO BOA.ZZZ.WorkItemAssignee (ItemID, StakeholderID) VALUES (?, ?)", (wi1, st1))
    conn.execute("INSERT INTO BOA.ZZZ.WorkItemAssignee (ItemID, StakeholderID) VALUES (?, ?)", (wi3, st1))

    # Sub items
    conn.execute("INSERT INTO BOA.ZZZ.WorkSubItem (ParentItemID, Title, Status) VALUES (?, 'Send KYC form', 'done')", (wi1,))
    conn.execute("INSERT INTO BOA.ZZZ.WorkSubItem (ParentItemID, Title, Status) VALUES (?, 'Get sign off', 'not_started')", (wi1,))

    # Comments
    conn.execute("INSERT INTO BOA.ZZZ.Comment (customer_id, author, content) VALUES (?, 'System', 'Initial customer profile created.')", (c1,))
    conn.execute("INSERT INTO BOA.ZZZ.Comment (customer_id, author, content) VALUES (?, 'System', 'Reviewed deal structure.')", (c3,))

    conn.commit()
    conn.close()
    
    # Recalculate KRs
    conn = get_db()
    from app import _recalc_kr
    _recalc_kr(conn, p1)
    _recalc_kr(conn, p2)
    conn.commit()
    conn.close()
    print("Seeding successful!")

if __name__ == "__main__":
    seed()
