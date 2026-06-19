"""TAX Module Models — WHTRecord."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    Boolean, Date, DateTime, ForeignKey, Integer,
    Numeric, String, Text, UniqueConstraint, func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import CompanyBase as Base


# ── WHT Record ────────────────────────────────────────────────────────────────

class WHTRecord(Base):
    """
    บันทึก Withholding Tax รายการ (สำหรับออกหนังสือรับรอง 50 ทวิ).

    direction:
        "collected"  — เราหักณที่จ่าย (บัญชี 2121) → นำส่งกรมสรรพากร
        "withheld"   — เราถูกหักณที่จ่าย (บัญชี 1141) → รับหนังสือรับรอง
    """

    __tablename__ = "tax_wht_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    company_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    branch_id: Mapped[int] = mapped_column(Integer, nullable=False)

    direction: Mapped[str] = mapped_column(String(10), nullable=False)
    # "collected" | "withheld"

    contact_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    # FK→contacts (ไม่ใส่ ForeignKey เพราะ contacts อยู่ใน Base ต่างกัน)

    # ประเภทเงินได้ (ตามแบบ ภงด.)
    income_type: Mapped[str] = mapped_column(String(5), nullable=False, default="3")
    # "1"=ดอกเบี้ย "2"=เงินปันผล "3"=ค่าจ้าง/ค่าบริการ "5"=ค่าเช่า "6"=ค่าวิชาชีพ

    wht_type: Mapped[str] = mapped_column(String(5), nullable=False)
    # "1" | "3" | "5" | "15" | "53" (อัตรา %)

    payment_date: Mapped[date] = mapped_column(Date, nullable=False)
    fiscal_year: Mapped[int] = mapped_column(Integer, nullable=False)
    month: Mapped[int] = mapped_column(Integer, nullable=False)

    base_amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    wht_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    wht_amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)

    source_module: Mapped[Optional[str]] = mapped_column(String(20))
    source_id: Mapped[Optional[int]] = mapped_column(Integer)
    journal_entry_no: Mapped[Optional[str]] = mapped_column(String(20))

    # หนังสือรับรอง
    certificate_no: Mapped[Optional[str]] = mapped_column(String(30))

    # การนำส่ง (เฉพาะ direction=collected)
    is_submitted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    submitted_period: Mapped[Optional[str]] = mapped_column(String(10))  # "202601"
    submitted_journal_no: Mapped[Optional[str]] = mapped_column(String(20))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
