"""initial company core tables (COA, journals, ledger, periods, recurring)

Revision ID: 002
Revises: 001
Create Date: 2026-06-18

NOTE: migration นี้ run กับ company database (data/firm_X/company_Y/db.sqlite)
      ไม่ใช่ shared database
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── chart_of_accounts ─────────────────────────────────────────────────────
    op.create_table(
        "chart_of_accounts",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("code", sa.String(10), unique=True, nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("name_en", sa.String(200)),
        sa.Column("category", sa.String(1), nullable=False),
        sa.Column("account_type", sa.String(50), nullable=False),
        sa.Column("normal_balance", sa.String(2), nullable=False),
        sa.Column("parent_id", sa.Integer, sa.ForeignKey("chart_of_accounts.id")),
        sa.Column("is_header", sa.Boolean, nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="1"),
        sa.Column("is_system", sa.Boolean, nullable=False, server_default="0"),
        sa.Column("description", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_coa_code", "chart_of_accounts", ["code"])
    op.create_index("ix_coa_category", "chart_of_accounts", ["category"])

    # ── periods ───────────────────────────────────────────────────────────────
    op.create_table(
        "periods",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("fiscal_year", sa.Integer, nullable=False),
        sa.Column("month", sa.Integer, nullable=False),
        sa.Column("start_date", sa.Date, nullable=False),
        sa.Column("end_date", sa.Date, nullable=False),
        sa.Column("status", sa.String(10), nullable=False, server_default="open"),
        sa.Column("closed_by", sa.Integer),
        sa.Column("closed_at", sa.DateTime(timezone=True)),
        sa.Column("notes", sa.Text),
        sa.UniqueConstraint("fiscal_year", "month", name="uq_period_year_month"),
        sa.CheckConstraint("month BETWEEN 1 AND 12", name="ck_period_month"),
        sa.CheckConstraint("status IN ('open','closed','locked')", name="ck_period_status"),
    )

    # ── journal_entries ───────────────────────────────────────────────────────
    op.create_table(
        "journal_entries",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("entry_no", sa.String(30), unique=True, nullable=False),
        sa.Column("journal_type", sa.String(2), nullable=False),
        sa.Column("period_id", sa.Integer, sa.ForeignKey("periods.id"), nullable=False),
        sa.Column("entry_date", sa.Date, nullable=False),
        sa.Column("reference", sa.String(100)),
        sa.Column("description", sa.String(500), nullable=False),
        sa.Column("branch_id", sa.Integer, nullable=False),
        sa.Column("user_id", sa.Integer, nullable=False),
        sa.Column("status", sa.String(10), nullable=False, server_default="draft"),
        sa.Column("is_reversing", sa.Boolean, nullable=False, server_default="0"),
        sa.Column("reversed_entry_id", sa.Integer, sa.ForeignKey("journal_entries.id")),
        sa.Column("source_module", sa.String(50)),
        sa.Column("source_id", sa.Integer),
        sa.Column("ocr_ref", sa.String(100)),
        sa.Column("posted_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.CheckConstraint(
            "journal_type IN ('GJ','PJ','SJ','CP','CR')", name="ck_entry_journal_type"
        ),
        sa.CheckConstraint("status IN ('draft','posted','reversed')", name="ck_entry_status"),
    )
    op.create_index("ix_je_period_date", "journal_entries", ["period_id", "entry_date"])
    op.create_index("ix_je_branch", "journal_entries", ["branch_id"])
    op.create_index("ix_je_source", "journal_entries", ["source_module", "source_id"])

    # ── journal_lines ─────────────────────────────────────────────────────────
    op.create_table(
        "journal_lines",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("entry_id", sa.Integer, sa.ForeignKey("journal_entries.id"), nullable=False),
        sa.Column("line_no", sa.Integer, nullable=False),
        sa.Column("account_id", sa.Integer, sa.ForeignKey("chart_of_accounts.id"), nullable=False),
        sa.Column("description", sa.String(300)),
        sa.Column("debit_amount", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("credit_amount", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("tax_rate", sa.Numeric(5, 2)),
        sa.Column("tax_base_amount", sa.Numeric(18, 2)),
        sa.Column("cost_center", sa.String(50)),
        sa.CheckConstraint(
            "NOT (debit_amount > 0 AND credit_amount > 0)", name="ck_line_dr_xor_cr"
        ),
        sa.CheckConstraint(
            "debit_amount >= 0 AND credit_amount >= 0", name="ck_line_amounts_pos"
        ),
    )
    op.create_index("ix_jl_entry", "journal_lines", ["entry_id"])
    op.create_index("ix_jl_account", "journal_lines", ["account_id"])

    # ── ledger_entries ────────────────────────────────────────────────────────
    op.create_table(
        "ledger_entries",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("account_id", sa.Integer, sa.ForeignKey("chart_of_accounts.id"), nullable=False),
        sa.Column("period_id", sa.Integer, sa.ForeignKey("periods.id"), nullable=False),
        sa.Column("entry_id", sa.Integer, sa.ForeignKey("journal_entries.id"), nullable=False),
        sa.Column("line_id", sa.Integer, sa.ForeignKey("journal_lines.id"), nullable=False),
        sa.Column("entry_date", sa.Date, nullable=False),
        sa.Column("debit_amount", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("credit_amount", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("running_balance", sa.Numeric(18, 2), nullable=False),
        sa.Column("branch_id", sa.Integer, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index(
        "ix_ledger_account_period", "ledger_entries", ["account_id", "period_id", "entry_date"]
    )

    # ── account_balances ──────────────────────────────────────────────────────
    op.create_table(
        "account_balances",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("account_id", sa.Integer, sa.ForeignKey("chart_of_accounts.id"), nullable=False),
        sa.Column("period_id", sa.Integer, sa.ForeignKey("periods.id"), nullable=False),
        sa.Column("branch_id", sa.Integer, nullable=False),
        sa.Column("opening_balance", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("total_debit", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("total_credit", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("closing_balance", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("account_id", "period_id", "branch_id", name="uq_balance_key"),
    )
    op.create_index("ix_balance_period", "account_balances", ["period_id"])

    # ── recurring_templates ───────────────────────────────────────────────────
    op.create_table(
        "recurring_templates",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("journal_type", sa.String(2), nullable=False),
        sa.Column("description", sa.String(500), nullable=False),
        sa.Column("frequency", sa.String(20), nullable=False),
        sa.Column("day_of_month", sa.Integer, nullable=False, server_default="1"),
        sa.Column("branch_id", sa.Integer, nullable=False),
        sa.Column("created_by", sa.Integer, nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="1"),
        sa.Column("last_run_date", sa.Date),
        sa.Column("next_run_date", sa.Date),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.CheckConstraint(
            "frequency IN ('monthly','quarterly','yearly')", name="ck_recurring_freq"
        ),
        sa.CheckConstraint("day_of_month BETWEEN 1 AND 31", name="ck_recurring_day"),
    )

    # ── recurring_lines ───────────────────────────────────────────────────────
    op.create_table(
        "recurring_lines",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "template_id",
            sa.Integer,
            sa.ForeignKey("recurring_templates.id"),
            nullable=False,
        ),
        sa.Column("line_no", sa.Integer, nullable=False),
        sa.Column("account_id", sa.Integer, sa.ForeignKey("chart_of_accounts.id"), nullable=False),
        sa.Column("description", sa.String(300)),
        sa.Column("debit_amount", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("credit_amount", sa.Numeric(18, 2), nullable=False, server_default="0"),
    )

    # ── seed: NPAEs standard COA ──────────────────────────────────────────────
    _seed_coa()


def _seed_coa() -> None:
    """Seed ผังบัญชีมาตรฐาน NPAEs."""
    coa_data = [
        # code, name, category, account_type, normal_balance, is_header, is_system
        # 1 สินทรัพย์
        ("1000", "สินทรัพย์", "1", "asset", "DR", True, True),
        ("1100", "สินทรัพย์หมุนเวียน", "1", "asset", "DR", True, True),
        ("1101", "เงินสด", "1", "asset", "DR", False, True),
        ("1102", "ธนาคาร-กระแสรายวัน", "1", "asset", "DR", False, True),
        ("1103", "ธนาคาร-ออมทรัพย์", "1", "asset", "DR", False, True),
        ("1110", "ลูกหนี้การค้า", "1", "asset", "DR", False, True),
        ("1111", "ลูกหนี้อื่น", "1", "asset", "DR", False, True),
        ("1112", "ค่าเผื่อหนี้สงสัยจะสูญ", "1", "asset", "CR", False, True),
        ("1120", "ตั๋วเงินรับ", "1", "asset", "DR", False, True),
        ("1130", "สินค้าคงเหลือ", "1", "asset", "DR", False, True),
        ("1131", "วัตถุดิบ", "1", "asset", "DR", False, True),
        ("1140", "ภาษีซื้อ", "1", "asset", "DR", False, True),
        ("1141", "ภาษีหัก ณ ที่จ่าย-ถูกหัก", "1", "asset", "DR", False, True),
        ("1150", "ค่าใช้จ่ายล่วงหน้า", "1", "asset", "DR", False, True),
        ("1160", "รายได้ค้างรับ", "1", "asset", "DR", False, True),
        ("1200", "สินทรัพย์ไม่หมุนเวียน", "1", "asset", "DR", True, True),
        ("1210", "เงินลงทุนระยะยาว", "1", "asset", "DR", False, True),
        ("1220", "ที่ดิน", "1", "asset", "DR", False, True),
        ("1230", "อาคาร", "1", "asset", "DR", False, True),
        ("1231", "ค่าเสื่อมราคาสะสม-อาคาร", "1", "asset", "CR", False, True),
        ("1240", "เครื่องจักร/อุปกรณ์", "1", "asset", "DR", False, True),
        ("1241", "ค่าเสื่อมราคาสะสม-เครื่องจักร", "1", "asset", "CR", False, True),
        ("1250", "เครื่องใช้สำนักงาน", "1", "asset", "DR", False, True),
        ("1251", "ค่าเสื่อมราคาสะสม-เครื่องใช้สำนักงาน", "1", "asset", "CR", False, True),
        ("1260", "ยานพาหนะ", "1", "asset", "DR", False, True),
        ("1261", "ค่าเสื่อมราคาสะสม-ยานพาหนะ", "1", "asset", "CR", False, True),
        # 2 หนี้สิน
        ("2000", "หนี้สิน", "2", "liability", "CR", True, True),
        ("2100", "หนี้สินหมุนเวียน", "2", "liability", "CR", True, True),
        ("2101", "เจ้าหนี้การค้า", "2", "liability", "CR", False, True),
        ("2102", "เจ้าหนี้อื่น", "2", "liability", "CR", False, True),
        ("2110", "ตั๋วเงินจ่าย", "2", "liability", "CR", False, True),
        ("2120", "ภาษีขาย", "2", "liability", "CR", False, True),
        ("2121", "ภาษีหัก ณ ที่จ่าย-ค้างนำส่ง", "2", "liability", "CR", False, True),
        ("2130", "เงินเดือนค้างจ่าย", "2", "liability", "CR", False, True),
        ("2140", "ค่าใช้จ่ายค้างจ่าย", "2", "liability", "CR", False, True),
        ("2150", "รายได้รับล่วงหน้า", "2", "liability", "CR", False, True),
        ("2160", "เงินกู้ระยะสั้น", "2", "liability", "CR", False, True),
        ("2200", "หนี้สินไม่หมุนเวียน", "2", "liability", "CR", True, True),
        ("2210", "เงินกู้ระยะยาว", "2", "liability", "CR", False, True),
        # 3 ทุน
        ("3000", "ส่วนของเจ้าของ", "3", "equity", "CR", True, True),
        ("3101", "ทุนชำระแล้ว", "3", "equity", "CR", False, True),
        ("3201", "กำไรสะสม", "3", "equity", "CR", False, True),
        ("3202", "กำไร(ขาดทุน)สุทธิปีปัจจุบัน", "3", "equity", "CR", False, True),
        # 4 รายได้
        ("4000", "รายได้", "4", "revenue", "CR", True, True),
        ("4101", "รายได้จากการขายสินค้า", "4", "revenue", "CR", False, True),
        ("4102", "รายได้จากการให้บริการ", "4", "revenue", "CR", False, True),
        ("4103", "รายได้อื่น", "4", "revenue", "CR", False, True),
        ("4201", "ดอกเบี้ยรับ", "4", "revenue", "CR", False, True),
        ("4202", "กำไรจากการขายสินทรัพย์", "4", "revenue", "CR", False, True),
        # 5 ต้นทุน
        ("5000", "ต้นทุนขาย", "5", "cost_of_sales", "DR", True, True),
        ("5101", "ต้นทุนสินค้าขาย", "5", "cost_of_sales", "DR", False, True),
        ("5102", "ต้นทุนการให้บริการ", "5", "cost_of_sales", "DR", False, True),
        # 6 ค่าใช้จ่าย
        ("6000", "ค่าใช้จ่าย", "6", "expense", "DR", True, True),
        ("6100", "ค่าใช้จ่ายในการขาย", "6", "expense", "DR", True, True),
        ("6101", "เงินเดือน-ฝ่ายขาย", "6", "expense", "DR", False, True),
        ("6102", "ค่านายหน้า", "6", "expense", "DR", False, True),
        ("6103", "ค่าโฆษณา", "6", "expense", "DR", False, True),
        ("6104", "ค่าขนส่ง", "6", "expense", "DR", False, True),
        ("6105", "ค่าใช้จ่ายในการขายอื่น", "6", "expense", "DR", False, True),
        ("6500", "ค่าใช้จ่ายในการบริหาร", "6", "expense", "DR", True, True),
        ("6501", "เงินเดือน-ฝ่ายบริหาร", "6", "expense", "DR", False, True),
        ("6502", "ค่าเช่า", "6", "expense", "DR", False, True),
        ("6503", "ค่าสาธารณูปโภค", "6", "expense", "DR", False, True),
        ("6504", "ค่าเสื่อมราคา", "6", "expense", "DR", False, True),
        ("6505", "ค่าซ่อมแซมและบำรุงรักษา", "6", "expense", "DR", False, True),
        ("6506", "ค่าประกันภัย", "6", "expense", "DR", False, True),
        ("6507", "ค่าเบี้ยประกันสังคม-นายจ้าง", "6", "expense", "DR", False, True),
        ("6508", "ค่าสอบบัญชี", "6", "expense", "DR", False, True),
        ("6509", "ค่าใช้จ่ายสำนักงาน", "6", "expense", "DR", False, True),
        ("6510", "ค่าใช้จ่ายในการบริหารอื่น", "6", "expense", "DR", False, True),
        # 7 การเงิน
        ("7000", "รายการทางการเงิน", "7", "finance", "DR", True, True),
        ("7101", "ดอกเบี้ยจ่าย", "7", "finance", "DR", False, True),
        ("7102", "ค่าธรรมเนียมธนาคาร", "7", "finance", "DR", False, True),
        ("7103", "ขาดทุนจากอัตราแลกเปลี่ยน", "7", "finance", "DR", False, True),
        ("7201", "ภาษีเงินได้นิติบุคคล", "7", "finance", "DR", False, True),
    ]

    conn = op.get_bind()
    for row in coa_data:
        code, name, cat, atype, nb, is_hdr, is_sys = row
        conn.execute(
            sa.text(
                """
                INSERT INTO chart_of_accounts
                    (code, name, category, account_type, normal_balance,
                     is_header, is_system, is_active)
                VALUES
                    (:code, :name, :cat, :atype, :nb, :is_hdr, :is_sys, 1)
                """
            ),
            {
                "code": code, "name": name, "cat": cat, "atype": atype,
                "nb": nb, "is_hdr": int(is_hdr), "is_sys": int(is_sys),
            },
        )


def downgrade() -> None:
    op.drop_table("recurring_lines")
    op.drop_table("recurring_templates")
    op.drop_index("ix_balance_period", "account_balances")
    op.drop_table("account_balances")
    op.drop_index("ix_ledger_account_period", "ledger_entries")
    op.drop_table("ledger_entries")
    op.drop_index("ix_jl_account", "journal_lines")
    op.drop_index("ix_jl_entry", "journal_lines")
    op.drop_table("journal_lines")
    op.drop_index("ix_je_source", "journal_entries")
    op.drop_index("ix_je_branch", "journal_entries")
    op.drop_index("ix_je_period_date", "journal_entries")
    op.drop_table("journal_entries")
    op.drop_table("periods")
    op.drop_index("ix_coa_category", "chart_of_accounts")
    op.drop_index("ix_coa_code", "chart_of_accounts")
    op.drop_table("chart_of_accounts")
