"""008 — Bank reconciliation tables.

Revision ID: 008
Revises: 007
Create Date: 2026-06-18
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "008"
down_revision = "007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "bank_reconciliations",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("company_id", sa.Integer, nullable=False, index=True),
        sa.Column("branch_id", sa.Integer, nullable=False),
        sa.Column("bank_account_code", sa.String(10), nullable=False),
        sa.Column("bank_name", sa.String(100)),
        sa.Column("account_no", sa.String(50)),
        sa.Column("account_name", sa.String(200)),
        sa.Column("period_from", sa.Date),
        sa.Column("period_to", sa.Date),
        sa.Column("opening_balance", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("closing_balance", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("statement_json", sa.Text),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("book_balance", sa.Numeric(18, 2)),
        sa.Column("adjusted_balance", sa.Numeric(18, 2)),
        sa.Column("created_by", sa.Integer, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "bank_recon_lines",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("recon_id", sa.Integer, nullable=False, index=True),
        sa.Column("company_id", sa.Integer, nullable=False),
        sa.Column("stmt_date", sa.Date),
        sa.Column("stmt_description", sa.String(500)),
        sa.Column("stmt_debit", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("stmt_credit", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("stmt_balance", sa.Numeric(18, 2)),
        sa.Column("stmt_ref_no", sa.String(100)),
        sa.Column("journal_line_id", sa.Integer),
        sa.Column("journal_entry_no", sa.String(30)),
        sa.Column("journal_date", sa.Date),
        sa.Column("journal_debit", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("journal_credit", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("journal_description", sa.String(500)),
        sa.Column("match_status", sa.String(20), nullable=False, server_default="unmatched"),
        sa.Column("match_confidence", sa.Integer),
        sa.Column("is_confirmed", sa.Boolean, nullable=False, server_default="0"),
        sa.Column("posted_journal_no", sa.String(30)),
        sa.Column("note", sa.String(500)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("bank_recon_lines")
    op.drop_table("bank_reconciliations")
