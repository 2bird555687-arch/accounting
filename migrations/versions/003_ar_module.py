"""AR Module tables — contacts, ar_invoices, ar_invoice_lines, ar_receipts, ar_receipt_allocations

Revision ID: 003
Revises: 002
Create Date: 2026-06-18

NOTE: migration นี้ run กับ company database (data/firm_X/company_Y/db.sqlite)
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── contacts ──────────────────────────────────────────────────────────────
    op.create_table(
        "contacts",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("company_id", sa.Integer, nullable=False, index=True),
        sa.Column("contact_type", sa.String(10), nullable=False, server_default="customer"),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("name_en", sa.String(200)),
        sa.Column("tax_id", sa.String(13)),
        sa.Column("branch_code", sa.String(5), server_default="00000"),
        sa.Column("address", sa.Text),
        sa.Column("phone", sa.String(50)),
        sa.Column("email", sa.String(200)),
        sa.Column("credit_days", sa.Integer, nullable=False, server_default="30"),
        sa.Column("wht_rate", sa.Numeric(5, 2)),
        sa.Column("wht_type", sa.String(5)),
        sa.Column("default_ar_account", sa.String(10), nullable=False, server_default="1110"),
        sa.Column("default_ap_account", sa.String(10), nullable=False, server_default="2101"),
        sa.Column("default_revenue_account", sa.String(10), nullable=False, server_default="4101"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # ── ar_invoices ───────────────────────────────────────────────────────────
    op.create_table(
        "ar_invoices",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("company_id", sa.Integer, nullable=False, index=True),
        sa.Column("branch_id", sa.Integer, nullable=False),
        sa.Column("invoice_no", sa.String(20), nullable=False),
        sa.Column("invoice_date", sa.Date, nullable=False),
        sa.Column("due_date", sa.Date, nullable=False),
        sa.Column("contact_id", sa.Integer, sa.ForeignKey("contacts.id"), nullable=False),
        sa.Column("subtotal", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("vat_amount", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("wht_amount", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("total_amount", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("paid_amount", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("balance", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("description", sa.Text),
        sa.Column("reference", sa.String(100)),
        sa.Column("journal_entry_no", sa.String(20)),
        sa.Column("created_by", sa.Integer, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("company_id", "invoice_no", name="uq_ar_invoice_no"),
    )

    # ── ar_invoice_lines ──────────────────────────────────────────────────────
    op.create_table(
        "ar_invoice_lines",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "invoice_id",
            sa.Integer,
            sa.ForeignKey("ar_invoices.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("line_no", sa.Integer, nullable=False),
        sa.Column("description", sa.String(500), nullable=False),
        sa.Column("account_code", sa.String(10), nullable=False),
        sa.Column("unit", sa.String(20)),
        sa.Column("quantity", sa.Numeric(15, 4), nullable=False, server_default="1"),
        sa.Column("unit_price", sa.Numeric(15, 4), nullable=False, server_default="0"),
        sa.Column("amount", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("vat_rate", sa.Numeric(5, 2), nullable=False, server_default="7"),
        sa.Column("vat_amount", sa.Numeric(15, 2), nullable=False, server_default="0"),
    )

    # ── ar_receipts ───────────────────────────────────────────────────────────
    op.create_table(
        "ar_receipts",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("company_id", sa.Integer, nullable=False, index=True),
        sa.Column("branch_id", sa.Integer, nullable=False),
        sa.Column("receipt_no", sa.String(20), nullable=False),
        sa.Column("receipt_date", sa.Date, nullable=False),
        sa.Column("contact_id", sa.Integer, sa.ForeignKey("contacts.id"), nullable=False),
        sa.Column("bank_account_code", sa.String(10), nullable=False, server_default="1102"),
        sa.Column("total_received", sa.Numeric(15, 2), nullable=False),
        sa.Column("wht_amount", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("total_applied", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("status", sa.String(20), nullable=False, server_default="posted"),
        sa.Column("description", sa.Text),
        sa.Column("reference", sa.String(100)),
        sa.Column("journal_entry_no", sa.String(20)),
        sa.Column("created_by", sa.Integer, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("company_id", "receipt_no", name="uq_ar_receipt_no"),
    )

    # ── ar_receipt_allocations ────────────────────────────────────────────────
    op.create_table(
        "ar_receipt_allocations",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "receipt_id",
            sa.Integer,
            sa.ForeignKey("ar_receipts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("invoice_id", sa.Integer, sa.ForeignKey("ar_invoices.id"), nullable=False),
        sa.Column("allocated_amount", sa.Numeric(15, 2), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("ar_receipt_allocations")
    op.drop_table("ar_receipts")
    op.drop_table("ar_invoice_lines")
    op.drop_table("ar_invoices")
    op.drop_table("contacts")
