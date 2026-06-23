"""add exchange_rates table

Revision ID: 013
Revises: 012
Create Date: 2026-06-23

NOTE: migration นี้ run กับ company database (data/firm_X/company_Y/db.sqlite)
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "013"
down_revision = "012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "exchange_rates",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("currency_code", sa.String(3), nullable=False),
        sa.Column("rate_date", sa.Date(), nullable=False),
        sa.Column("rate", sa.Numeric(18, 6), nullable=False),
        sa.Column("source", sa.String(50), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "company_id", "currency_code", "rate_date", name="uq_exchange_rate"
        ),
    )
    op.create_index(
        "ix_exchange_rates_company_id", "exchange_rates", ["company_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_exchange_rates_company_id", table_name="exchange_rates")
    op.drop_table("exchange_rates")
