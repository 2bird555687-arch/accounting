import sqlite3
conn = sqlite3.connect("data/firm_1/company_1/db.sqlite")
sql = "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
tables = [r[0] for r in conn.execute(sql).fetchall()]
conn.close()
for t in tables:
    print(t)
