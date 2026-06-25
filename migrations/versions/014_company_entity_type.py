"""Add entity_type and income_statement_format to companies

Revision ID: 014
Revises: 013
Create Date: 2026-06-25

NOTE: migration นี้ run กับ shared (platform) database
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "014"
down_revision: Union[str, None] = "013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("companies") as batch_op:
        batch_op.add_column(
            sa.Column(
                "entity_type",
                sa.String(20),
                nullable=False,
                server_default="company",
            )
        )
        batch_op.add_column(
            sa.Column(
                "income_statement_format",
                sa.String(30),
                nullable=False,
                server_default="by_nature",
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("companies") as batch_op:
        batch_op.drop_column("income_statement_format")
        batch_op.drop_column("entity_type")
