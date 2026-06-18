"""005 — INV / FA / TAX module tables.

Revision ID: 005
Revises: 004
Create Date: 2026-06-18
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── INV: Products ─────────────────────────────────────────────────────────
    op.create_table(
        "inv_products",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("company_id", sa.Integer, nullable=False, index=True),
        sa.Column("sku", sa.String(50), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("name_en", sa.String(200)),
        sa.Column("description", sa.Text),
        sa.Column("category", sa.String(100)),
        sa.Column("unit", sa.String(20), nullable=False, server_default="ชิ้น"),
        sa.Column("cost_method", sa.String(10), nullable=False, server_default="average"),
        sa.Column("inventory_account", sa.String(10), nullable=False, server_default="1130"),
        sa.Column("cogs_account", sa.String(10), nullable=False, server_default="5101"),
        sa.Column("current_cost", sa.Numeric(15, 4), nullable=False, server_default="0"),
        sa.Column("standard_cost", sa.Numeric(15, 4), nullable=False, server_default="0"),
        sa.Column("quantity_on_hand", sa.Numeric(15, 4), nullable=False, server_default="0"),
        sa.Column("total_value", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("reorder_point", sa.Numeric(15, 4), nullable=False, server_default="0"),
        sa.Column("min_stock", sa.Numeric(15, 4), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("company_id", "sku", name="uq_inv_product_sku"),
    )

    # ── INV: Product Lots ─────────────────────────────────────────────────────
    op.create_table(
        "inv_product_lots",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("product_id", sa.Integer, sa.ForeignKey("inv_products.id"), nullable=False),
        sa.Column("lot_no", sa.String(30), nullable=False),
        sa.Column("received_date", sa.Date, nullable=False),
        sa.Column("quantity", sa.Numeric(15, 4), nullable=False),
        sa.Column("remaining_qty", sa.Numeric(15, 4), nullable=False),
        sa.Column("unit_cost", sa.Numeric(15, 4), nullable=False),
        sa.Column("source", sa.String(20), nullable=False, server_default="purchase"),
        sa.Column("source_ref", sa.String(50)),
    )

    # ── INV: Stock Movements ──────────────────────────────────────────────────
    op.create_table(
        "inv_stock_movements",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("company_id", sa.Integer, nullable=False, index=True),
        sa.Column("branch_id", sa.Integer, nullable=False),
        sa.Column("product_id", sa.Integer, sa.ForeignKey("inv_products.id"), nullable=False),
        sa.Column("movement_no", sa.String(20), nullable=False),
        sa.Column("movement_date", sa.Date, nullable=False),
        sa.Column("movement_type", sa.String(20), nullable=False),
        sa.Column("quantity", sa.Numeric(15, 4), nullable=False),
        sa.Column("unit_cost", sa.Numeric(15, 4), nullable=False, server_default="0"),
        sa.Column("total_cost", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("qty_after", sa.Numeric(15, 4), nullable=False, server_default="0"),
        sa.Column("value_after", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("lot_id", sa.Integer, sa.ForeignKey("inv_product_lots.id")),
        sa.Column("journal_entry_no", sa.String(20)),
        sa.Column("reference", sa.String(100)),
        sa.Column("reason", sa.Text),
        sa.Column("source_module", sa.String(20)),
        sa.Column("source_id", sa.Integer),
        sa.Column("created_by", sa.Integer, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # ── FA: Assets ────────────────────────────────────────────────────────────
    op.create_table(
        "fa_assets",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("company_id", sa.Integer, nullable=False, index=True),
        sa.Column("branch_id", sa.Integer, nullable=False),
        sa.Column("asset_code", sa.String(20), nullable=False),
        sa.Column("asset_name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text),
        sa.Column("serial_no", sa.String(100)),
        sa.Column("location", sa.String(200)),
        sa.Column("category", sa.String(20), nullable=False, server_default="equipment"),
        sa.Column("asset_account", sa.String(10), nullable=False),
        sa.Column("acc_depr_account", sa.String(10)),
        sa.Column("depr_expense_account", sa.String(10), nullable=False, server_default="6505"),
        sa.Column("purchase_date", sa.Date, nullable=False),
        sa.Column("cost", sa.Numeric(15, 2), nullable=False),
        sa.Column("salvage_value", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("useful_life_months", sa.Integer, nullable=False),
        sa.Column("depr_method", sa.String(20), nullable=False, server_default="straight_line"),
        sa.Column("declining_rate", sa.Numeric(5, 4)),
        sa.Column("accumulated_depr", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("book_value", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("months_depreciated", sa.Integer, nullable=False, server_default="0"),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("purchase_journal_no", sa.String(20)),
        sa.Column("disposal_journal_no", sa.String(20)),
        sa.Column("disposed_at", sa.Date),
        sa.Column("disposal_proceeds", sa.Numeric(15, 2)),
        sa.Column("created_by", sa.Integer, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("company_id", "asset_code", name="uq_fa_asset_code"),
    )

    # ── FA: Depreciation Records ──────────────────────────────────────────────
    op.create_table(
        "fa_depreciation_records",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("asset_id", sa.Integer, sa.ForeignKey("fa_assets.id"), nullable=False, index=True),
        sa.Column("fiscal_year", sa.Integer, nullable=False),
        sa.Column("month", sa.Integer, nullable=False),
        sa.Column("depr_amount", sa.Numeric(15, 2), nullable=False),
        sa.Column("accumulated_depr_after", sa.Numeric(15, 2), nullable=False),
        sa.Column("book_value_after", sa.Numeric(15, 2), nullable=False),
        sa.Column("journal_entry_no", sa.String(20)),
        sa.Column("posted_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("asset_id", "fiscal_year", "month", name="uq_fa_depr_period"),
    )

    # ── TAX: WHT Records ──────────────────────────────────────────────────────
    op.create_table(
        "tax_wht_records",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("company_id", sa.Integer, nullable=False, index=True),
        sa.Column("branch_id", sa.Integer, nullable=False),
        sa.Column("direction", sa.String(10), nullable=False),
        sa.Column("contact_id", sa.Integer, nullable=False, index=True),
        sa.Column("income_type", sa.String(5), nullable=False, server_default="3"),
        sa.Column("wht_type", sa.String(5), nullable=False),
        sa.Column("payment_date", sa.Date, nullable=False),
        sa.Column("fiscal_year", sa.Integer, nullable=False),
        sa.Column("month", sa.Integer, nullable=False),
        sa.Column("base_amount", sa.Numeric(15, 2), nullable=False),
        sa.Column("wht_rate", sa.Numeric(5, 2), nullable=False),
        sa.Column("wht_amount", sa.Numeric(15, 2), nullable=False),
        sa.Column("source_module", sa.String(20)),
        sa.Column("source_id", sa.Integer),
        sa.Column("journal_entry_no", sa.String(20)),
        sa.Column("certificate_no", sa.String(30)),
        sa.Column("is_submitted", sa.Boolean, nullable=False, server_default="0"),
        sa.Column("submitted_period", sa.String(10)),
        sa.Column("submitted_journal_no", sa.String(20)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("tax_wht_records")
    op.drop_table("fa_depreciation_records")
    op.drop_table("fa_assets")
    op.drop_table("inv_stock_movements")
    op.drop_table("inv_product_lots")
    op.drop_table("inv_products")
