"""AP Module tables — ap_purchase_orders, ap_po_lines, ap_grns, ap_grn_lines,
                       ap_purchases, ap_purchase_lines, ap_payments, ap_payment_allocations

Revision ID: 004
Revises: 003
Create Date: 2026-06-18

NOTE: migration นี้ run กับ company database (data/firm_X/company_Y/db.sqlite)
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── ap_purchase_orders ────────────────────────────────────────────────────
    op.create_table(
        "ap_purchase_orders",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("company_id", sa.Integer, nullable=False, index=True),
        sa.Column("branch_id", sa.Integer, nullable=False),
        sa.Column("po_no", sa.String(20), nullable=False),
        sa.Column("po_date", sa.Date, nullable=False),
        sa.Column("expected_date", sa.Date),
        sa.Column("contact_id", sa.Integer, sa.ForeignKey("contacts.id"), nullable=False),
        sa.Column("subtotal", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("vat_amount", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("total_amount", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("purchase_type", sa.String(20), nullable=False, server_default="goods"),
        sa.Column("notes", sa.Text),
        sa.Column("approved_by", sa.Integer),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column("created_by", sa.Integer, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("company_id", "po_no", name="uq_ap_po_no"),
    )

    # ── ap_po_lines ───────────────────────────────────────────────────────────
    op.create_table(
        "ap_po_lines",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "po_id",
            sa.Integer,
            sa.ForeignKey("ap_purchase_orders.id", ondelete="CASCADE"),
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
        sa.Column("received_qty", sa.Numeric(15, 4), nullable=False, server_default="0"),
    )

    # ── ap_grns ───────────────────────────────────────────────────────────────
    op.create_table(
        "ap_grns",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("company_id", sa.Integer, nullable=False, index=True),
        sa.Column("branch_id", sa.Integer, nullable=False),
        sa.Column("grn_no", sa.String(20), nullable=False),
        sa.Column("grn_date", sa.Date, nullable=False),
        sa.Column(
            "po_id",
            sa.Integer,
            sa.ForeignKey("ap_purchase_orders.id"),
            nullable=False,
        ),
        sa.Column("notes", sa.Text),
        sa.Column("status", sa.String(20), nullable=False, server_default="posted"),
        sa.Column("received_by", sa.Integer, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("company_id", "grn_no", name="uq_ap_grn_no"),
    )

    # ── ap_grn_lines ──────────────────────────────────────────────────────────
    op.create_table(
        "ap_grn_lines",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "grn_id",
            sa.Integer,
            sa.ForeignKey("ap_grns.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("po_line_id", sa.Integer, sa.ForeignKey("ap_po_lines.id"), nullable=False),
        sa.Column("description", sa.String(500), nullable=False),
        sa.Column("ordered_qty", sa.Numeric(15, 4), nullable=False),
        sa.Column("received_qty", sa.Numeric(15, 4), nullable=False),
        sa.Column("unit", sa.String(20)),
    )

    # ── ap_purchases ──────────────────────────────────────────────────────────
    op.create_table(
        "ap_purchases",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("company_id", sa.Integer, nullable=False, index=True),
        sa.Column("branch_id", sa.Integer, nullable=False),
        sa.Column("purchase_no", sa.String(20), nullable=False),
        sa.Column("supplier_invoice_no", sa.String(100)),
        sa.Column("purchase_date", sa.Date, nullable=False),
        sa.Column("due_date", sa.Date, nullable=False),
        sa.Column("contact_id", sa.Integer, sa.ForeignKey("contacts.id"), nullable=False),
        sa.Column("po_id", sa.Integer, sa.ForeignKey("ap_purchase_orders.id")),
        sa.Column("grn_id", sa.Integer, sa.ForeignKey("ap_grns.id")),
        sa.Column("purchase_type", sa.String(20), nullable=False, server_default="goods"),
        sa.Column("subtotal", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("vat_amount", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("wht_amount", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("total_amount", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("paid_amount", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("balance", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("description", sa.Text),
        sa.Column("journal_entry_no", sa.String(20)),
        sa.Column("created_by", sa.Integer, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("company_id", "purchase_no", name="uq_ap_purchase_no"),
    )

    # ── ap_purchase_lines ─────────────────────────────────────────────────────
    op.create_table(
        "ap_purchase_lines",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "purchase_id",
            sa.Integer,
            sa.ForeignKey("ap_purchases.id", ondelete="CASCADE"),
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

    # ── ap_payments ───────────────────────────────────────────────────────────
    op.create_table(
        "ap_payments",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("company_id", sa.Integer, nullable=False, index=True),
        sa.Column("branch_id", sa.Integer, nullable=False),
        sa.Column("payment_no", sa.String(20), nullable=False),
        sa.Column("payment_date", sa.Date, nullable=False),
        sa.Column("contact_id", sa.Integer, sa.ForeignKey("contacts.id"), nullable=False),
        sa.Column("bank_account_code", sa.String(10), nullable=False, server_default="1102"),
        sa.Column("total_paid", sa.Numeric(15, 2), nullable=False),
        sa.Column("wht_amount", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("total_applied", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("status", sa.String(20), nullable=False, server_default="posted"),
        sa.Column("description", sa.Text),
        sa.Column("reference", sa.String(100)),
        sa.Column("journal_entry_no", sa.String(20)),
        sa.Column("created_by", sa.Integer, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("company_id", "payment_no", name="uq_ap_payment_no"),
    )

    # ── ap_payment_allocations ────────────────────────────────────────────────
    op.create_table(
        "ap_payment_allocations",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "payment_id",
            sa.Integer,
            sa.ForeignKey("ap_payments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "purchase_id",
            sa.Integer,
            sa.ForeignKey("ap_purchases.id"),
            nullable=False,
        ),
        sa.Column("allocated_amount", sa.Numeric(15, 2), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("ap_payment_allocations")
    op.drop_table("ap_payments")
    op.drop_table("ap_purchase_lines")
    op.drop_table("ap_purchases")
    op.drop_table("ap_grn_lines")
    op.drop_table("ap_grns")
    op.drop_table("ap_po_lines")
    op.drop_table("ap_purchase_orders")
