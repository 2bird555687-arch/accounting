"""010 — BudgetItem table.

Revision ID: 010
Revises: 009
Create Date: 2026-06-18
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "010"
down_revision = "009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "budget_items",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("fiscal_year", sa.Integer, nullable=False),
        sa.Column("month", sa.Integer),
        sa.Column("account_id", sa.Integer, sa.ForeignKey("chart_of_accounts.id"), nullable=False),
        sa.Column("branch_id", sa.Integer, nullable=False),
        sa.Column("budget_amount", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("created_by", sa.Integer, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("fiscal_year", "month", "account_id", "branch_id",
                            name="uq_budget_item"),
    )


def downgrade() -> None:
    op.drop_table("budget_items")
