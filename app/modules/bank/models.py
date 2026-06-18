"""Bank Reconciliation models."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, Integer, Numeric, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class BankReconciliation(Base):
    __tablename__ = "bank_reconciliations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    company_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    branch_id: Mapped[int] = mapped_column(Integer, nullable=False)
    bank_account_code: Mapped[str] = mapped_column(String(10), nullable=False)
    bank_name: Mapped[str | None] = mapped_column(String(100))
    account_no: Mapped[str | None] = mapped_column(String(50))
    account_name: Mapped[str | None] = mapped_column(String(200))
    period_from: Mapped[date | None] = mapped_column(Date)
    period_to: Mapped[date | None] = mapped_column(Date)
    opening_balance: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, server_default="0")
    closing_balance: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, server_default="0")
    statement_json: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="pending")
    # pending | matching | confirmed | completed
    book_balance: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    adjusted_balance: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    created_by: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class BankReconLine(Base):
    __tablename__ = "bank_recon_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    recon_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    company_id: Mapped[int] = mapped_column(Integer, nullable=False)

    # ข้อมูลจาก Statement
    stmt_date: Mapped[date | None] = mapped_column(Date)
    stmt_description: Mapped[str | None] = mapped_column(String(500))
    stmt_debit: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, server_default="0")
    stmt_credit: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, server_default="0")
    stmt_balance: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    stmt_ref_no: Mapped[str | None] = mapped_column(String(100))

    # ข้อมูลจากสมุดรายวัน
    journal_line_id: Mapped[int | None] = mapped_column(Integer)
    journal_entry_no: Mapped[str | None] = mapped_column(String(30))
    journal_date: Mapped[date | None] = mapped_column(Date)
    journal_debit: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, server_default="0")
    journal_credit: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, server_default="0")
    journal_description: Mapped[str | None] = mapped_column(String(500))

    # ผลการจับคู่
    match_status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="unmatched")
    # MATCHED | NEAR_MATCH | STATEMENT_ONLY | BOOK_ONLY | MISMATCH | CONFIRMED
    match_confidence: Mapped[int | None] = mapped_column(Integer)
    is_confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="0")
    posted_journal_no: Mapped[str | None] = mapped_column(String(30))
    note: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
