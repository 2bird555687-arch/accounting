"""Shared Models — AuditLog, OCRMapping, BankAccount."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Base สำหรับ shared models (firm shared database)."""
    pass


# ── AuditLog ──────────────────────────────────────────────────────────────────

class AuditLog(Base):
    """
    Audit Trail — บันทึกทุกการกระทำสำคัญในระบบ.

    เขียนอย่างเดียว ห้ามแก้ไขหรือลบ.
    """

    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    firm_id: Mapped[int] = mapped_column(Integer, nullable=False)
    company_id: Mapped[int] = mapped_column(Integer, nullable=False)
    branch_id: Mapped[int] = mapped_column(Integer, nullable=False)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False)
    user_role: Mapped[str] = mapped_column(String(30), nullable=False)
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    # CREATE | UPDATE | DELETE | POST | REVERSE | LOGIN | LOGOUT | CLOSE_PERIOD
    resource_type: Mapped[str] = mapped_column(String(50), nullable=False)
    # journal_entry | company | user | period | ...
    resource_id: Mapped[Optional[str]] = mapped_column(String(100))
    description: Mapped[Optional[str]] = mapped_column(Text)
    before_data: Mapped[Optional[str]] = mapped_column(Text)  # JSON snapshot ก่อนแก้
    after_data: Mapped[Optional[str]] = mapped_column(Text)   # JSON snapshot หลังแก้
    ip_address: Mapped[Optional[str]] = mapped_column(String(45))
    user_agent: Mapped[Optional[str]] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return (
            f"<AuditLog id={self.id} action={self.action!r} "
            f"resource={self.resource_type}/{self.resource_id}>"
        )


# ── OCRMapping ────────────────────────────────────────────────────────────────

class OCRMapping(Base):
    """
    Keyword → COA mapping สำหรับ OCR classifier.

    ระบบเรียนรู้จากการแก้ไขของผู้ใช้เพื่อเพิ่มความแม่นยำ.
    """

    __tablename__ = "ocr_mappings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    firm_id: Mapped[int] = mapped_column(Integer, nullable=False)
    company_id: Mapped[Optional[int]] = mapped_column(Integer)
    # None = ใช้ข้ามทุก company ของ firm
    keyword: Mapped[str] = mapped_column(String(200), nullable=False)
    # คำหรือวลีที่พบในเอกสาร
    account_code: Mapped[str] = mapped_column(String(10), nullable=False)
    # รหัสบัญชีที่ map ไป
    journal_type: Mapped[Optional[str]] = mapped_column(String(2))
    # GJ/PJ/SJ/CP/CR — None = ทุกประเภท
    drcr: Mapped[Optional[str]] = mapped_column(String(2))  # DR / CR
    confidence: Mapped[Decimal] = mapped_column(
        Numeric(4, 3), nullable=False, default=Decimal("0.5")
    )
    # 0.000–1.000
    usage_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[int] = mapped_column(Integer, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return f"<OCRMapping {self.keyword!r} → {self.account_code}>"


# ── BankAccount ───────────────────────────────────────────────────────────────

class BankAccount(Base):
    """บัญชีธนาคาร — ใช้ร่วมกับ Bank Reconciliation."""

    __tablename__ = "bank_accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    firm_id: Mapped[int] = mapped_column(Integer, nullable=False)
    company_id: Mapped[int] = mapped_column(Integer, nullable=False)
    branch_id: Mapped[int] = mapped_column(Integer, nullable=False)
    bank_name: Mapped[str] = mapped_column(String(100), nullable=False)
    bank_code: Mapped[Optional[str]] = mapped_column(String(10))  # รหัสธนาคาร
    account_number: Mapped[str] = mapped_column(String(50), nullable=False)
    account_name: Mapped[str] = mapped_column(String(200), nullable=False)
    account_type: Mapped[str] = mapped_column(String(30), nullable=False)
    # current (กระแสรายวัน) | savings (ออมทรัพย์) | fixed (ฝากประจำ)
    coa_code: Mapped[str] = mapped_column(String(10), nullable=False)
    # รหัสบัญชีใน COA เช่น 1102
    currency: Mapped[str] = mapped_column(String(3), default="THB", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_reconcile_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_statement_balance: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return (
            f"<BankAccount {self.bank_name} {self.account_number!r} "
            f"type={self.account_type!r}>"
        )
