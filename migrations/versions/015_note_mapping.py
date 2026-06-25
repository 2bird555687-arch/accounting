"""Add note_id mapping to COA + NoteTemplate + EquityChange models

Revision ID: 015
Revises: 014
Create Date: 2026-06-25

NOTE: migration นี้ run กับ company database (data/firm_X/company_Y/db.sqlite)
      ผ่าน init_company_db() / create_all — ตาราง note_templates และ equity_changes
      จะถูกสร้างอัตโนมัติเมื่อมีการสร้าง company ใหม่
      สำหรับ company เก่า ให้ run alembic upgrade กับ company DB แต่ละตัว
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "015"
down_revision: Union[str, None] = "014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Note: columns added to chart_of_accounts (company DB)
    # These run via create_all for new companies.
    # For existing companies, manual migration is needed per company DB.
    # The platform DB does not have these tables, so this migration is a no-op
    # for the shared DB tracked by this alembic chain.
    pass


def downgrade() -> None:
    pass
