"""Master Module Models — Employee, PettyCashFund, PettyCashExpense."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    Boolean, Date, DateTime, Integer,
    Numeric, String, Text, UniqueConstraint, ForeignKey, func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import CompanyBase as Base


# ── Employee ──────────────────────────────────────────────────────────────────

class Employee(Base):
    """พนักงาน (Employee Master)."""

    __tablename__ = "employees"
    __table_args__ = (UniqueConstraint("company_id", "employee_code", name="uq_employee_code"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    company_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    branch_id: Mapped[int] = mapped_column(Integer, nullable=False)

    employee_code: Mapped[str] = mapped_column(String(20), nullable=False)
    name_th: Mapped[str] = mapped_column(String(200), nullable=False)
    name_en: Mapped[Optional[str]] = mapped_column(String(200))
    tax_id: Mapped[Optional[str]] = mapped_column(String(13))   # เลขประจำตัวผู้เสียภาษี
    department: Mapped[Optional[str]] = mapped_column(String(100))
    position: Mapped[Optional[str]] = mapped_column(String(100))
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[Optional[date]] = mapped_column(Date)       # วันสิ้นสุดสัญญา/ลาออก

    # เงินเดือนและค่าตอบแทน
    salary: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    ot_rate: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False, default=Decimal(0))
    # อัตรา OT ต่อชั่วโมง

    # ประกันสังคม
    sso_rate: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False, default=Decimal("0.05"))
    # อัตราส่วนพนักงาน เช่น 0.05 = 5%
    sso_ceiling: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, default=Decimal(15000))
    # ฐานเงินเดือน SSO สูงสุด (ปัจจุบัน 15,000 บาท)

    # ธนาคาร (สำหรับโอนเงินเดือน)
    bank_name: Mapped[Optional[str]] = mapped_column(String(100))
    bank_account_no: Mapped[Optional[str]] = mapped_column(String(30))
    bank_account_name: Mapped[Optional[str]] = mapped_column(String(200))

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    payroll_records: Mapped[list[PayrollRecord]] = relationship(
        "PayrollRecord", back_populates="employee"
    )


# ── Payroll Record ────────────────────────────────────────────────────────────

class PayrollRecord(Base):
    """รายการเงินเดือนรายงวด."""

    __tablename__ = "payroll_records"
    __table_args__ = (UniqueConstraint("company_id", "period", "employee_id", name="uq_payroll_period_emp"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    company_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    branch_id: Mapped[int] = mapped_column(Integer, nullable=False)

    period: Mapped[str] = mapped_column(String(10), nullable=False)   # "202601"
    employee_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("employees.id"), nullable=False, index=True
    )

    # ยอดคำนวณ
    gross: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)         # เงินเดือน + OT + bonus
    sso_employee: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)  # SSO ส่วนพนักงาน
    sso_employer: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)  # SSO ส่วนนายจ้าง
    wht: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, default=Decimal(0))
    net: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)           # gross - sso_employee - wht

    # OT / bonus (ถ้ามี)
    ot_hours: Mapped[Decimal] = mapped_column(Numeric(8, 2), nullable=False, default=Decimal(0))
    ot_amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, default=Decimal(0))
    bonus: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=Decimal(0))

    status: Mapped[str] = mapped_column(String(20), nullable=False, default="calculated")
    # "calculated" | "posted" | "paid"

    posted_journal_no: Mapped[Optional[str]] = mapped_column(String(20))
    payment_journal_no: Mapped[Optional[str]] = mapped_column(String(20))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    employee: Mapped[Employee] = relationship("Employee", back_populates="payroll_records")


# ── Petty Cash Fund ───────────────────────────────────────────────────────────

class PettyCashFund(Base):
    """กองทุนเงินสดย่อย."""

    __tablename__ = "petty_cash_funds"
    __table_args__ = (UniqueConstraint("company_id", "fund_no", name="uq_petty_fund_no"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    company_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    branch_id: Mapped[int] = mapped_column(Integer, nullable=False)

    fund_no: Mapped[str] = mapped_column(String(20), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(200))

    petty_cash_account: Mapped[str] = mapped_column(String(10), nullable=False, default="1103")
    bank_account: Mapped[str] = mapped_column(String(10), nullable=False, default="1102")

    initial_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    current_balance: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)

    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    # "active" | "closed"

    setup_journal_no: Mapped[Optional[str]] = mapped_column(String(20))
    created_by: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    expenses: Mapped[list[PettyCashExpense]] = relationship(
        "PettyCashExpense", back_populates="fund", order_by="PettyCashExpense.expense_date"
    )


# ── Petty Cash Expense ────────────────────────────────────────────────────────

class PettyCashExpense(Base):
    """รายการค่าใช้จ่ายเงินสดย่อย."""

    __tablename__ = "petty_cash_expenses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    fund_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("petty_cash_funds.id"), nullable=False, index=True
    )
    company_id: Mapped[int] = mapped_column(Integer, nullable=False)
    branch_id: Mapped[int] = mapped_column(Integer, nullable=False)

    expense_date: Mapped[date] = mapped_column(Date, nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    account_code: Mapped[str] = mapped_column(String(10), nullable=False)  # รหัสค่าใช้จ่าย
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    receipt_no: Mapped[Optional[str]] = mapped_column(String(50))   # เลขที่ใบเสร็จ

    is_replenished: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    replenish_journal_no: Mapped[Optional[str]] = mapped_column(String(20))

    expense_journal_no: Mapped[Optional[str]] = mapped_column(String(20))
    created_by: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    fund: Mapped[PettyCashFund] = relationship("PettyCashFund", back_populates="expenses")
