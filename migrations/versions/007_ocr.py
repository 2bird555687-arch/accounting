"""007 — OCR history and mapping tables.

Revision ID: 007
Revises: 006
Create Date: 2026-06-18
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "007"
down_revision = "006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ocr_history",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("company_id", sa.Integer, nullable=False, index=True),
        sa.Column("branch_id", sa.Integer, nullable=False),
        sa.Column("document_type", sa.String(30), nullable=False),
        sa.Column("original_filename", sa.String(500)),
        sa.Column("extracted_json", sa.Text),
        sa.Column("overall_confidence", sa.Numeric(5, 2)),
        sa.Column("status", sa.String(20), nullable=False, server_default="extracted"),
        sa.Column("journal_no", sa.String(20)),
        sa.Column("contact_id", sa.Integer),
        sa.Column("created_by", sa.Integer, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "ocr_mappings",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("company_id", sa.Integer, nullable=False, index=True),
        sa.Column("raw_vendor_name", sa.String(500), nullable=False),
        sa.Column("contact_id", sa.Integer),
        sa.Column("account_code", sa.String(10)),
        sa.Column("hit_count", sa.Integer, nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("ocr_mappings")
    op.drop_table("ocr_history")
