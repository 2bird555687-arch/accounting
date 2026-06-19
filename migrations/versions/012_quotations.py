"""Quotations + Quotation Lines tables

Revision ID: 012
Revises: 011
Create Date: 2026-06-19

NOTE: migration นี้ run กับ company database (data/firm_X/company_Y/db.sqlite)
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "012"
down_revision: Union[str, None] = "011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # quotations และ quotation_lines อยู่ใน company DB
    # manage โดย init_company_db() ผ่าน metadata.create_all — no-op สำหรับ shared DB
    pass


def downgrade() -> None:
    pass
