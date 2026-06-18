"""006 — Contact Master fields + Employee + Payroll + Petty Cash tables.

Revision ID: 006
Revises: 005
Create Date: 2026-06-18
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Add new columns to contacts ───────────────────────────────────────────
    with op.batch_alter_table("contacts", schema=None) as batch_op:
        batch_op.add_column(sa.Column("credit_limit", sa.Numeric(15, 2), nullable=False, server_default="0"))
        batch_op.add_column(sa.Column("bank_name", sa.String(100)))
        batch_op.add_column(sa.Column("bank_branch", sa.String(100)))
        batch_op.add_column(sa.Column("bank_account_no", sa.String(30)))
        batch_op.add_column(sa.Column("bank_account_name", sa.String(200)))

    # ── Employees ─────────────────────────────────────────────────────────────
    op.create_table(
        "employees",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("company_id", sa.Integer, nullable=False, index=True),
        sa.Column("branch_id", sa.Integer, nullable=False),
        sa.Column("employee_code", sa.String(20), nullable=False),
        sa.Column("name_th", sa.String(200), nullable=False),
        sa.Column("name_en", sa.String(200)),
        sa.Column("tax_id", sa.String(13)),
        sa.Column("department", sa.String(100)),
        sa.Column("position", sa.String(100)),
        sa.Column("start_date", sa.Date, nullable=False),
        sa.Column("end_date", sa.Date),
        sa.Column("salary", sa.Numeric(12, 2), nullable=False),
        sa.Column("ot_rate", sa.Numeric(10, 4), nullable=False, server_default="0"),
        sa.Column("sso_rate", sa.Numeric(5, 4), nullable=False, server_default="0.05"),
        sa.Column("sso_ceiling", sa.Numeric(10, 2), nullable=False, server_default="15000"),
        sa.Column("bank_name", sa.String(100)),
        sa.Column("bank_account_no", sa.String(30)),
        sa.Column("bank_account_name", sa.String(200)),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("company_id", "employee_code", name="uq_employee_code"),
    )

    # ── Payroll Records ───────────────────────────────────────────────────────
    op.create_table(
        "payroll_records",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("company_id", sa.Integer, nullable=False, index=True),
        sa.Column("branch_id", sa.Integer, nullable=False),
        sa.Column("period", sa.String(10), nullable=False),
        sa.Column("employee_id", sa.Integer, sa.ForeignKey("employees.id"), nullable=False, index=True),
        sa.Column("gross", sa.Numeric(12, 2), nullable=False),
        sa.Column("sso_employee", sa.Numeric(10, 2), nullable=False),
        sa.Column("sso_employer", sa.Numeric(10, 2), nullable=False),
        sa.Column("wht", sa.Numeric(10, 2), nullable=False, server_default="0"),
        sa.Column("net", sa.Numeric(12, 2), nullable=False),
        sa.Column("ot_hours", sa.Numeric(8, 2), nullable=False, server_default="0"),
        sa.Column("ot_amount", sa.Numeric(10, 2), nullable=False, server_default="0"),
        sa.Column("bonus", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("status", sa.String(20), nullable=False, server_default="calculated"),
        sa.Column("posted_journal_no", sa.String(20)),
        sa.Column("payment_journal_no", sa.String(20)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("company_id", "period", "employee_id", name="uq_payroll_period_emp"),
    )

    # ── Petty Cash Funds ──────────────────────────────────────────────────────
    op.create_table(
        "petty_cash_funds",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("company_id", sa.Integer, nullable=False, index=True),
        sa.Column("branch_id", sa.Integer, nullable=False),
        sa.Column("fund_no", sa.String(20), nullable=False),
        sa.Column("description", sa.String(200)),
        sa.Column("petty_cash_account", sa.String(10), nullable=False, server_default="1103"),
        sa.Column("bank_account", sa.String(10), nullable=False, server_default="1102"),
        sa.Column("initial_amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("current_balance", sa.Numeric(12, 2), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("setup_journal_no", sa.String(20)),
        sa.Column("created_by", sa.Integer, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("company_id", "fund_no", name="uq_petty_fund_no"),
    )

    # ── Petty Cash Expenses ───────────────────────────────────────────────────
    op.create_table(
        "petty_cash_expenses",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("fund_id", sa.Integer, sa.ForeignKey("petty_cash_funds.id"), nullable=False, index=True),
        sa.Column("company_id", sa.Integer, nullable=False),
        sa.Column("branch_id", sa.Integer, nullable=False),
        sa.Column("expense_date", sa.Date, nullable=False),
        sa.Column("description", sa.String(500), nullable=False),
        sa.Column("account_code", sa.String(10), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("receipt_no", sa.String(50)),
        sa.Column("is_replenished", sa.Boolean, nullable=False, server_default="0"),
        sa.Column("replenish_journal_no", sa.String(20)),
        sa.Column("expense_journal_no", sa.String(20)),
        sa.Column("created_by", sa.Integer, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("petty_cash_expenses")
    op.drop_table("petty_cash_funds")
    op.drop_table("payroll_records")
    op.drop_table("employees")

    with op.batch_alter_table("contacts", schema=None) as batch_op:
        batch_op.drop_column("credit_limit")
        batch_op.drop_column("bank_name")
        batch_op.drop_column("bank_branch")
        batch_op.drop_column("bank_account_no")
        batch_op.drop_column("bank_account_name")
