import sqlite3
import glob

for db in glob.glob("data/firm_*/company_*/db.sqlite"):
    conn = sqlite3.connect(db)
    tables_cols = {}
    for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'"):
        t = row[0]
        tables_cols[t] = {r[1] for r in conn.execute(f"PRAGMA table_info({t})")}

    changed = []
    if "ar_invoices" in tables_cols:
        if "payment_mode" not in tables_cols["ar_invoices"]:
            conn.execute("ALTER TABLE ar_invoices ADD COLUMN payment_mode TEXT DEFAULT 'credit'")
            changed.append("ar_invoices.payment_mode")
        if "payment_account_code" not in tables_cols["ar_invoices"]:
            conn.execute("ALTER TABLE ar_invoices ADD COLUMN payment_account_code TEXT")
            changed.append("ar_invoices.payment_account_code")

    if "ap_purchases" in tables_cols:
        if "payment_mode" not in tables_cols["ap_purchases"]:
            conn.execute("ALTER TABLE ap_purchases ADD COLUMN payment_mode TEXT DEFAULT 'credit'")
            changed.append("ap_purchases.payment_mode")
        if "payment_account_code" not in tables_cols["ap_purchases"]:
            conn.execute("ALTER TABLE ap_purchases ADD COLUMN payment_account_code TEXT")
            changed.append("ap_purchases.payment_account_code")

    conn.commit()
    conn.close()
    if changed:
        print(f"Updated {db}: {changed}")
    else:
        print(f"No changes needed: {db}")

print("Done.")
