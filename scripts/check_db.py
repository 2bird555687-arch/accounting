import sqlite3, glob

for db_path in glob.glob("data/firm_*/company_*/db.sqlite"):
    print("=== DB:", db_path)
    c = sqlite3.connect(db_path)
    tables = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    print("Tables:", tables)
    for tbl in ["ar_invoices", "ap_purchases", "ap_purchase_orders"]:
        if tbl in tables:
            cols = [r[1] for r in c.execute(f"PRAGMA table_info({tbl})")]
            print(f"{tbl} cols:", cols)
        else:
            print(f"{tbl}: MISSING")
    print("billing_notes:", "EXISTS" if "billing_notes" in tables else "MISSING")
    print()
    c.close()
