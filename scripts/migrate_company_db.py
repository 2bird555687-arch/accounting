"""
Script to migrate all company DBs to add missing columns/tables.
Run: py -3 scripts/migrate_company_db.py
"""
import sqlite3
import glob

for db_path in glob.glob("data/firm_*/company_*/db.sqlite"):
    print(f"=== Migrating: {db_path}")
    c = sqlite3.connect(db_path)

    # 1. ar_invoices: add billing_note_id if missing
    existing = {r[1] for r in c.execute("PRAGMA table_info(ar_invoices)")}
    if "billing_note_id" not in existing:
        print("  + ALTER TABLE ar_invoices ADD COLUMN billing_note_id INTEGER")
        c.execute("ALTER TABLE ar_invoices ADD COLUMN billing_note_id INTEGER")

    # 2. AP tables — create if missing
    tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}

    if "ap_purchase_orders" not in tables:
        print("  + CREATE TABLE ap_purchase_orders")
        c.execute("""
            CREATE TABLE ap_purchase_orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company_id INTEGER NOT NULL,
                branch_id INTEGER NOT NULL,
                po_no VARCHAR(20) NOT NULL,
                po_date DATE NOT NULL,
                expected_date DATE,
                contact_id INTEGER NOT NULL REFERENCES contacts(id),
                subtotal NUMERIC(15,2) NOT NULL DEFAULT 0,
                vat_amount NUMERIC(15,2) NOT NULL DEFAULT 0,
                total_amount NUMERIC(15,2) NOT NULL DEFAULT 0,
                status VARCHAR(20) NOT NULL DEFAULT 'draft',
                purchase_type VARCHAR(20) NOT NULL DEFAULT 'goods',
                notes TEXT,
                approved_by INTEGER,
                approved_at DATETIME,
                created_by INTEGER NOT NULL,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(company_id, po_no)
            )
        """)
        c.execute("CREATE INDEX ix_ap_purchase_orders_company_id ON ap_purchase_orders(company_id)")

    if "ap_po_lines" not in tables:
        print("  + CREATE TABLE ap_po_lines")
        c.execute("""
            CREATE TABLE ap_po_lines (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                po_id INTEGER NOT NULL REFERENCES ap_purchase_orders(id) ON DELETE CASCADE,
                line_no INTEGER NOT NULL,
                description VARCHAR(500) NOT NULL,
                account_code VARCHAR(10) NOT NULL,
                unit VARCHAR(20),
                quantity NUMERIC(15,4) NOT NULL DEFAULT 1,
                unit_price NUMERIC(15,4) NOT NULL DEFAULT 0,
                amount NUMERIC(15,2) NOT NULL DEFAULT 0,
                vat_rate NUMERIC(5,2) NOT NULL DEFAULT 7,
                vat_amount NUMERIC(15,2) NOT NULL DEFAULT 0,
                received_qty NUMERIC(15,4) NOT NULL DEFAULT 0
            )
        """)

    if "ap_grns" not in tables:
        print("  + CREATE TABLE ap_grns")
        c.execute("""
            CREATE TABLE ap_grns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company_id INTEGER NOT NULL,
                branch_id INTEGER NOT NULL,
                grn_no VARCHAR(20) NOT NULL,
                grn_date DATE NOT NULL,
                po_id INTEGER NOT NULL REFERENCES ap_purchase_orders(id),
                notes TEXT,
                status VARCHAR(20) NOT NULL DEFAULT 'posted',
                received_by INTEGER NOT NULL,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(company_id, grn_no)
            )
        """)
        c.execute("CREATE INDEX ix_ap_grns_company_id ON ap_grns(company_id)")

    if "ap_grn_lines" not in tables:
        print("  + CREATE TABLE ap_grn_lines")
        c.execute("""
            CREATE TABLE ap_grn_lines (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                grn_id INTEGER NOT NULL REFERENCES ap_grns(id) ON DELETE CASCADE,
                po_line_id INTEGER NOT NULL REFERENCES ap_po_lines(id),
                description VARCHAR(500) NOT NULL,
                ordered_qty NUMERIC(15,4) NOT NULL,
                received_qty NUMERIC(15,4) NOT NULL,
                unit VARCHAR(20)
            )
        """)

    if "ap_purchases" not in tables:
        print("  + CREATE TABLE ap_purchases")
        c.execute("""
            CREATE TABLE ap_purchases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company_id INTEGER NOT NULL,
                branch_id INTEGER NOT NULL,
                purchase_no VARCHAR(20) NOT NULL,
                supplier_invoice_no VARCHAR(100),
                purchase_date DATE NOT NULL,
                due_date DATE NOT NULL,
                contact_id INTEGER NOT NULL REFERENCES contacts(id),
                po_id INTEGER REFERENCES ap_purchase_orders(id),
                grn_id INTEGER REFERENCES ap_grns(id),
                purchase_type VARCHAR(20) NOT NULL DEFAULT 'goods',
                subtotal NUMERIC(15,2) NOT NULL DEFAULT 0,
                vat_amount NUMERIC(15,2) NOT NULL DEFAULT 0,
                wht_amount NUMERIC(15,2) NOT NULL DEFAULT 0,
                total_amount NUMERIC(15,2) NOT NULL DEFAULT 0,
                paid_amount NUMERIC(15,2) NOT NULL DEFAULT 0,
                balance NUMERIC(15,2) NOT NULL DEFAULT 0,
                status VARCHAR(20) NOT NULL DEFAULT 'draft',
                description TEXT,
                journal_entry_no VARCHAR(20),
                created_by INTEGER NOT NULL,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(company_id, purchase_no)
            )
        """)
        c.execute("CREATE INDEX ix_ap_purchases_company_id ON ap_purchases(company_id)")

    if "ap_purchase_lines" not in tables:
        print("  + CREATE TABLE ap_purchase_lines")
        c.execute("""
            CREATE TABLE ap_purchase_lines (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                purchase_id INTEGER NOT NULL REFERENCES ap_purchases(id) ON DELETE CASCADE,
                line_no INTEGER NOT NULL,
                description VARCHAR(500) NOT NULL,
                account_code VARCHAR(10) NOT NULL,
                unit VARCHAR(20),
                quantity NUMERIC(15,4) NOT NULL DEFAULT 1,
                unit_price NUMERIC(15,4) NOT NULL DEFAULT 0,
                amount NUMERIC(15,2) NOT NULL DEFAULT 0,
                vat_rate NUMERIC(5,2) NOT NULL DEFAULT 7,
                vat_amount NUMERIC(15,2) NOT NULL DEFAULT 0
            )
        """)

    if "ap_payments" not in tables:
        print("  + CREATE TABLE ap_payments")
        c.execute("""
            CREATE TABLE ap_payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company_id INTEGER NOT NULL,
                branch_id INTEGER NOT NULL,
                payment_no VARCHAR(20) NOT NULL,
                payment_date DATE NOT NULL,
                contact_id INTEGER NOT NULL REFERENCES contacts(id),
                bank_account_code VARCHAR(10) NOT NULL DEFAULT '1102',
                total_paid NUMERIC(15,2) NOT NULL,
                wht_amount NUMERIC(15,2) NOT NULL DEFAULT 0,
                total_applied NUMERIC(15,2) NOT NULL DEFAULT 0,
                status VARCHAR(20) NOT NULL DEFAULT 'posted',
                description TEXT,
                reference VARCHAR(100),
                journal_entry_no VARCHAR(20),
                created_by INTEGER NOT NULL,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(company_id, payment_no)
            )
        """)
        c.execute("CREATE INDEX ix_ap_payments_company_id ON ap_payments(company_id)")

    if "ap_payment_allocations" not in tables:
        print("  + CREATE TABLE ap_payment_allocations")
        c.execute("""
            CREATE TABLE ap_payment_allocations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                payment_id INTEGER NOT NULL REFERENCES ap_payments(id) ON DELETE CASCADE,
                purchase_id INTEGER NOT NULL REFERENCES ap_purchases(id),
                allocated_amount NUMERIC(15,2) NOT NULL
            )
        """)

    # 3. AR/AP lines: add product_id if missing
    ar_line_cols = {r[1] for r in c.execute("PRAGMA table_info(ar_invoice_lines)")}
    if ar_line_cols and "product_id" not in ar_line_cols:
        print("  + ALTER TABLE ar_invoice_lines ADD COLUMN product_id INTEGER")
        c.execute("ALTER TABLE ar_invoice_lines ADD COLUMN product_id INTEGER")
    ap_line_cols = {r[1] for r in c.execute("PRAGMA table_info(ap_purchase_lines)")}
    if ap_line_cols and "product_id" not in ap_line_cols:
        print("  + ALTER TABLE ap_purchase_lines ADD COLUMN product_id INTEGER")
        c.execute("ALTER TABLE ap_purchase_lines ADD COLUMN product_id INTEGER")

    # 4. Inventory tables — create if missing
    tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}

    if "inv_products" not in tables:
        print("  + CREATE TABLE inv_products")
        c.execute("""
            CREATE TABLE inv_products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company_id INTEGER NOT NULL,
                sku VARCHAR(50) NOT NULL,
                name VARCHAR(200) NOT NULL,
                name_en VARCHAR(200),
                description TEXT,
                category VARCHAR(100),
                unit VARCHAR(20) NOT NULL DEFAULT 'ชิ้น',
                cost_method VARCHAR(10) NOT NULL DEFAULT 'average',
                inventory_account VARCHAR(10) NOT NULL DEFAULT '1130',
                cogs_account VARCHAR(10) NOT NULL DEFAULT '5101',
                current_cost NUMERIC(15,4) NOT NULL DEFAULT 0,
                standard_cost NUMERIC(15,4) NOT NULL DEFAULT 0,
                quantity_on_hand NUMERIC(15,4) NOT NULL DEFAULT 0,
                total_value NUMERIC(15,2) NOT NULL DEFAULT 0,
                reorder_point NUMERIC(15,4) NOT NULL DEFAULT 0,
                min_stock NUMERIC(15,4) NOT NULL DEFAULT 0,
                is_active BOOLEAN NOT NULL DEFAULT 1,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(company_id, sku)
            )
        """)
        c.execute("CREATE INDEX ix_inv_products_company_id ON inv_products(company_id)")

    if "inv_product_lots" not in tables:
        print("  + CREATE TABLE inv_product_lots")
        c.execute("""
            CREATE TABLE inv_product_lots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id INTEGER NOT NULL REFERENCES inv_products(id),
                lot_no VARCHAR(30) NOT NULL,
                received_date DATE NOT NULL,
                quantity NUMERIC(15,4) NOT NULL,
                remaining_qty NUMERIC(15,4) NOT NULL,
                unit_cost NUMERIC(15,4) NOT NULL,
                source VARCHAR(20) NOT NULL DEFAULT 'purchase',
                source_ref VARCHAR(50)
            )
        """)
        c.execute("CREATE INDEX ix_inv_product_lots_product_id ON inv_product_lots(product_id)")

    if "inv_stock_movements" not in tables:
        print("  + CREATE TABLE inv_stock_movements")
        c.execute("""
            CREATE TABLE inv_stock_movements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company_id INTEGER NOT NULL,
                branch_id INTEGER NOT NULL,
                product_id INTEGER NOT NULL REFERENCES inv_products(id),
                movement_no VARCHAR(20) NOT NULL,
                movement_date DATE NOT NULL,
                movement_type VARCHAR(20) NOT NULL,
                quantity NUMERIC(15,4) NOT NULL,
                unit_cost NUMERIC(15,4) NOT NULL DEFAULT 0,
                total_cost NUMERIC(15,2) NOT NULL DEFAULT 0,
                qty_after NUMERIC(15,4) NOT NULL DEFAULT 0,
                value_after NUMERIC(15,2) NOT NULL DEFAULT 0,
                lot_id INTEGER REFERENCES inv_product_lots(id),
                journal_entry_no VARCHAR(20),
                reference VARCHAR(100),
                reason TEXT,
                source_module VARCHAR(20),
                source_id INTEGER,
                created_by INTEGER NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        c.execute("CREATE INDEX ix_inv_stock_movements_company_id ON inv_stock_movements(company_id)")
        c.execute("CREATE INDEX ix_inv_stock_movements_product_id ON inv_stock_movements(product_id)")

    c.commit()
    c.close()
    print(f"  Done: {db_path}")

print("\nAll company DBs migrated successfully.")
