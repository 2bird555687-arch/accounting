"""Add fiscal_years table (platform DB)

Revision ID: 017
Revises: 016
Create Date: 2026-06-26

NOTE: migration นี้ run กับ platform database (data/shared.sqlite)
      สร้าง fiscal_years table และ seed ปีปัจจุบันให้ทุก company
"""

from __future__ import annotations

from datetime import date
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "017"
down_revision: Union[str, None] = "016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.has_table(conn, "fiscal_years"):
        return  # ตารางมีอยู่แล้ว ข้าม

    op.create_table(
        "fiscal_years",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("company_id", sa.Integer, nullable=False),
        sa.Column("year", sa.Integer, nullable=False),
        sa.Column("start_date", sa.Date, nullable=False),
        sa.Column("end_date", sa.Date, nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("is_locked", sa.Boolean, nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("company_id", "year", name="uq_fiscal_year"),
    )
    op.create_index("idx_fiscal_year_company", "fiscal_years", ["company_id"])

    # seed ปีปัจจุบันให้ทุก company ที่มีอยู่
    current_year = date.today().year
    op.execute(f"""
        INSERT INTO fiscal_years (company_id, year, start_date, end_date, status)
        SELECT id, {current_year},
               '{current_year}-01-01',
               '{current_year}-12-31',
               'active'
        FROM companies
        WHERE NOT EXISTS (
            SELECT 1 FROM fiscal_years
            WHERE fiscal_years.company_id = companies.id
              AND fiscal_years.year = {current_year}
        )
    """)


def downgrade() -> None:
    op.drop_index("idx_fiscal_year_company", table_name="fiscal_years")
    op.drop_table("fiscal_years")
