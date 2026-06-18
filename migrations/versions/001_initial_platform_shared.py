"""initial platform and shared tables

Revision ID: 001
Revises:
Create Date: 2026-06-18
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── firms ─────────────────────────────────────────────────────────────────
    op.create_table(
        "firms",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("tax_id", sa.String(13), unique=True),
        sa.Column("address", sa.Text),
        sa.Column("phone", sa.String(20)),
        sa.Column("email", sa.String(200)),
        sa.Column("logo_path", sa.String(500)),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # ── companies ─────────────────────────────────────────────────────────────
    op.create_table(
        "companies",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("firm_id", sa.Integer, sa.ForeignKey("firms.id"), nullable=False),
        sa.Column("code", sa.String(20), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("name_en", sa.String(200)),
        sa.Column("tax_id", sa.String(13)),
        sa.Column("business_type", sa.String(100)),
        sa.Column("address", sa.Text),
        sa.Column("phone", sa.String(20)),
        sa.Column("email", sa.String(200)),
        sa.Column("fiscal_year_start", sa.Integer, nullable=False, server_default="1"),
        sa.Column("vat_registered", sa.Boolean, nullable=False, server_default="0"),
        sa.Column("vat_id", sa.String(13)),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("firm_id", "code", name="uq_company_code"),
    )

    # ── branches ──────────────────────────────────────────────────────────────
    op.create_table(
        "branches",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("company_id", sa.Integer, sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("branch_code", sa.String(5), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("address", sa.Text),
        sa.Column("phone", sa.String(20)),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("company_id", "branch_code", name="uq_branch_code"),
    )

    # ── users ─────────────────────────────────────────────────────────────────
    op.create_table(
        "users",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("firm_id", sa.Integer, sa.ForeignKey("firms.id"), nullable=False),
        sa.Column("username", sa.String(50), unique=True, nullable=False),
        sa.Column("email", sa.String(200), unique=True, nullable=False),
        sa.Column("hashed_password", sa.String(200), nullable=False),
        sa.Column("full_name", sa.String(200), nullable=False),
        sa.Column("phone", sa.String(20)),
        sa.Column("default_role", sa.String(30), nullable=False, server_default="junior"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="1"),
        sa.Column("is_superuser", sa.Boolean, nullable=False, server_default="0"),
        sa.Column("last_login", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # ── user_permissions ──────────────────────────────────────────────────────
    op.create_table(
        "user_permissions",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("company_id", sa.Integer, sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("role", sa.String(30), nullable=False),
        sa.Column("branch_id", sa.Integer, sa.ForeignKey("branches.id")),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="1"),
        sa.Column("granted_by", sa.Integer, sa.ForeignKey("users.id")),
        sa.Column("granted_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", "company_id", "branch_id", name="uq_user_company_branch"),
    )

    # ── audit_logs ────────────────────────────────────────────────────────────
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("firm_id", sa.Integer, nullable=False),
        sa.Column("company_id", sa.Integer, nullable=False),
        sa.Column("branch_id", sa.Integer, nullable=False),
        sa.Column("user_id", sa.Integer, nullable=False),
        sa.Column("user_role", sa.String(30), nullable=False),
        sa.Column("action", sa.String(50), nullable=False),
        sa.Column("resource_type", sa.String(50), nullable=False),
        sa.Column("resource_id", sa.String(100)),
        sa.Column("description", sa.Text),
        sa.Column("before_data", sa.Text),
        sa.Column("after_data", sa.Text),
        sa.Column("ip_address", sa.String(45)),
        sa.Column("user_agent", sa.String(300)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_audit_logs_company_created", "audit_logs", ["company_id", "created_at"])
    op.create_index("ix_audit_logs_user", "audit_logs", ["user_id"])

    # ── ocr_mappings ──────────────────────────────────────────────────────────
    op.create_table(
        "ocr_mappings",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("firm_id", sa.Integer, nullable=False),
        sa.Column("company_id", sa.Integer),
        sa.Column("keyword", sa.String(200), nullable=False),
        sa.Column("account_code", sa.String(10), nullable=False),
        sa.Column("journal_type", sa.String(2)),
        sa.Column("drcr", sa.String(2)),
        sa.Column("confidence", sa.Numeric(4, 3), nullable=False, server_default="0.500"),
        sa.Column("usage_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("last_used_at", sa.DateTime(timezone=True)),
        sa.Column("created_by", sa.Integer, nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # ── bank_accounts ─────────────────────────────────────────────────────────
    op.create_table(
        "bank_accounts",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("firm_id", sa.Integer, nullable=False),
        sa.Column("company_id", sa.Integer, nullable=False),
        sa.Column("branch_id", sa.Integer, nullable=False),
        sa.Column("bank_name", sa.String(100), nullable=False),
        sa.Column("bank_code", sa.String(10)),
        sa.Column("account_number", sa.String(50), nullable=False),
        sa.Column("account_name", sa.String(200), nullable=False),
        sa.Column("account_type", sa.String(30), nullable=False),
        sa.Column("coa_code", sa.String(10), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="THB"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="1"),
        sa.Column("last_reconcile_date", sa.DateTime(timezone=True)),
        sa.Column("last_statement_balance", sa.Numeric(18, 2)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("bank_accounts")
    op.drop_table("ocr_mappings")
    op.drop_index("ix_audit_logs_user", "audit_logs")
    op.drop_index("ix_audit_logs_company_created", "audit_logs")
    op.drop_table("audit_logs")
    op.drop_table("user_permissions")
    op.drop_table("users")
    op.drop_table("branches")
    op.drop_table("companies")
    op.drop_table("firms")
