"""Add equity_changes table

Revision ID: 016
Revises: 015
Create Date: 2026-06-25

NOTE: migration นี้ run กับ company database (data/firm_X/company_Y/db.sqlite)
      ผ่าน init_company_db() / create_all — ตาราง equity_changes
      จะถูกสร้างอัตโนมัติเมื่อมีการสร้าง company ใหม่
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "016"
down_revision: Union[str, None] = "015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
