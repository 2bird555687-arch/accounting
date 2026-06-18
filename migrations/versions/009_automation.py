"""009 — Automation: recurring columns, period_close_logs, adjusting_entries, tax_deadlines.

Revision ID: 009
Revises: 008
Create Date: 2026-06-18
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "009"
down_revision = "008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Add columns to recurring_templates (company DB) ───────────────────────
    with op.batch_alter_table("recurring_templates", schema=None) as batch_op:
        batch_op.add_column(sa.Column("end_date", sa.Date()))
        batch_op.add_column(sa.Column("company_id", sa.Integer()))

    # ── PeriodCloseLog (company DB) ───────────────────────────────────────────
    op.create_table(
        "period_close_logs",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("period_id", sa.Integer, sa.ForeignKey("periods.id"), nullable=False),
        sa.Column("action", sa.String(20), nullable=False),
        sa.Column("user_id", sa.Integer, nullable=False),
        sa.Column("user_role", sa.String(30), nullable=False),
        sa.Column("reason", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # ── AdjustingEntry (company DB) ────────────────────────────────────────────
    op.create_table(
        "adjusting_entries",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("period_id", sa.Integer, sa.ForeignKey("periods.id"), nullable=False),
        sa.Column("item_type", sa.String(30), nullable=False),
        sa.Column("description", sa.String(500), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("journal_no", sa.String(30)),
        sa.Column("source_id", sa.Integer),
        sa.Column("created_by", sa.Integer, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # ── TaxDeadline (shared DB) ────────────────────────────────────────────────
    op.create_table(
        "tax_deadlines",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("firm_id", sa.Integer, nullable=False, index=True),
        sa.Column("company_id", sa.Integer, nullable=False),
        sa.Column("year_month", sa.String(7), nullable=False),
        sa.Column("deadline_type", sa.String(20), nullable=False),
        sa.Column("due_date", sa.Date, nullable=False),
        sa.Column("filed_date", sa.Date),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("notes", sa.String(500)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("firm_id", "company_id", "year_month", "deadline_type",
                            name="uq_tax_deadline"),
    )


def downgrade() -> None:
    op.drop_table("tax_deadlines")
    op.drop_table("adjusting_entries")
    op.drop_table("period_close_logs")

    with op.batch_alter_table("recurring_templates", schema=None) as batch_op:
        batch_op.drop_column("company_id")
        batch_op.drop_column("end_date")
