"""Billing Notes table + billing_note_id FK on ar_invoices

Revision ID: 011
Revises: 010
Create Date: 2026-06-19

NOTE: migration นี้ run กับ company database (data/firm_X/company_Y/db.sqlite)
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "011"
down_revision: Union[str, None] = "010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # billing_notes, billing_note_invoices, quotations, quotation_lines
    # อยู่ใน company DB ซึ่ง manage โดย init_company_db() ผ่าน metadata.create_all
    # Alembic track เฉพาะ shared DB — migration นี้เป็น no-op เพื่อ stamp revision เท่านั้น
    pass


def downgrade() -> None:
    pass
