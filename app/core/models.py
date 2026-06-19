"""Core Layer Models — COA, JournalEntry, JournalLine, LedgerEntry, Period, RecurringTemplate."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    CheckConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import CompanyBase as Base


# ── Chart of Accounts ─────────────────────────────────────────────────────────

class ChartOfAccount(Base):
    """
    ผังบัญชี — รหัส 4 หลัก หมวด 1–8 ตามมาตรฐาน NPAEs.

    Examples:
        1101 เงินสด, 2101 เจ้าหนี้การค้า, 4101 ขายสินค้า
    """

    __tablename__ = "chart_of_accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(10), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    name_en: Mapped[Optional[str]] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(1), nullable=False)  # 1–8
    account_type: Mapped[str] = mapped_column(String(50), nullable=False)
    # asset/liability/equity/revenue/expense
    normal_balance: Mapped[str] = mapped_column(String(2), nullable=False)  # DR / CR
    parent_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("chart_of_accounts.id"))
    is_header: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # บัญชีระบบ — ห้ามแก้ไขหรือลบ
    description: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    parent: Mapped[Optional[ChartOfAccount]] = relationship(
        "ChartOfAccount", remote_side="ChartOfAccount.id", back_populates="children"
    )
    children: Mapped[list[ChartOfAccount]] = relationship(
        "ChartOfAccount", back_populates="parent"
    )
    journal_lines: Mapped[list[JournalLine]] = relationship(
        "JournalLine", back_populates="account"
    )
    ledger_entries: Mapped[list[LedgerEntry]] = relationship(
        "LedgerEntry", back_populates="account"
    )

    def __repr__(self) -> str:
        return f"<COA {self.code} {self.name!r}>"


# ── Period ────────────────────────────────────────────────────────────────────

class Period(Base):
    """
    งวดบัญชี — ควบคุมการบันทึก/ปิดงวด.

    status: open → closed → locked
    """

    __tablename__ = "periods"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    fiscal_year: Mapped[int] = mapped_column(Integer, nullable=False)
    month: Mapped[int] = mapped_column(Integer, nullable=False)  # 1–12
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(10), default="open", nullable=False)
    # open | closed | locked
    closed_by: Mapped[Optional[int]] = mapped_column(Integer)  # user_id
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    notes: Mapped[Optional[str]] = mapped_column(Text)

    __table_args__ = (
        UniqueConstraint("fiscal_year", "month", name="uq_period_year_month"),
        CheckConstraint("month BETWEEN 1 AND 12", name="ck_period_month"),
        CheckConstraint("status IN ('open','closed','locked')", name="ck_period_status"),
    )

    journal_entries: Mapped[list[JournalEntry]] = relationship(
        "JournalEntry", back_populates="period"
    )

    @property
    def is_open(self) -> bool:
        return self.status == "open"

    def __repr__(self) -> str:
        return f"<Period {self.fiscal_year}/{self.month:02d} status={self.status!r}>"


# ── JournalEntry ──────────────────────────────────────────────────────────────

class JournalEntry(Base):
    """
    รายการบัญชี — header ของสมุดรายวัน.

    กฎเหล็ก: สร้างผ่าน PostingEngine เท่านั้น ห้าม insert ตรง.
    ห้าม UPDATE/DELETE — ใช้ Reversing Entry แทน.
    """

    __tablename__ = "journal_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    entry_no: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    # รูปแบบ: {journal_type}{YYYYMM}{sequence} เช่น GJ202601-0001
    journal_type: Mapped[str] = mapped_column(String(2), nullable=False)  # GJ/PJ/SJ/CP/CR
    period_id: Mapped[int] = mapped_column(Integer, ForeignKey("periods.id"), nullable=False)
    entry_date: Mapped[date] = mapped_column(Date, nullable=False)
    reference: Mapped[Optional[str]] = mapped_column(String(100))  # เลขที่เอกสาร
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    branch_id: Mapped[int] = mapped_column(Integer, nullable=False)   # จาก AppContext
    user_id: Mapped[int] = mapped_column(Integer, nullable=False)     # จาก AppContext
    status: Mapped[str] = mapped_column(String(10), default="draft", nullable=False)
    # draft | posted | reversed
    is_reversing: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    reversed_entry_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("journal_entries.id")
    )
    source_module: Mapped[Optional[str]] = mapped_column(String(50))
    # ar/ap/inv/fa/tax/gl/payroll/petty/bank
    source_id: Mapped[Optional[int]] = mapped_column(Integer)  # FK ไปยัง record ใน module
    ocr_ref: Mapped[Optional[str]] = mapped_column(String(100))  # reference จาก OCR
    posted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "journal_type IN ('GJ','PJ','SJ','CP','CR')", name="ck_entry_journal_type"
        ),
        CheckConstraint(
            "status IN ('draft','posted','reversed')", name="ck_entry_status"
        ),
    )

    period: Mapped[Period] = relationship("Period", back_populates="journal_entries")
    lines: Mapped[list[JournalLine]] = relationship(
        "JournalLine", back_populates="entry", cascade="all, delete-orphan"
    )
    reversed_entry: Mapped[Optional[JournalEntry]] = relationship(
        "JournalEntry", remote_side="JournalEntry.id"
    )

    @property
    def total_debit(self) -> Decimal:
        return sum((ln.debit_amount for ln in self.lines), Decimal(0))

    @property
    def total_credit(self) -> Decimal:
        return sum((ln.credit_amount for ln in self.lines), Decimal(0))

    @property
    def is_balanced(self) -> bool:
        """ตรวจ Dr == Cr (กฎเหล็กข้อ 2)."""
        return self.total_debit == self.total_credit

    def __repr__(self) -> str:
        return f"<JournalEntry {self.entry_no!r} status={self.status!r}>"


# ── JournalLine ───────────────────────────────────────────────────────────────

class JournalLine(Base):
    """
    รายการบรรทัดในสมุดรายวัน — Dr หรือ Cr ต่อบัญชี.

    debit_amount XOR credit_amount ต้องไม่เป็น 0 (ตรวจผ่าน PostingEngine).
    """

    __tablename__ = "journal_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    entry_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("journal_entries.id"), nullable=False
    )
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)  # ลำดับบรรทัด
    account_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("chart_of_accounts.id"), nullable=False
    )
    description: Mapped[Optional[str]] = mapped_column(String(300))
    debit_amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False, default=Decimal(0)
    )
    credit_amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False, default=Decimal(0)
    )
    # ข้อมูลเพิ่มเติมสำหรับ VAT/WHT
    tax_rate: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2))
    tax_base_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2))
    cost_center: Mapped[Optional[str]] = mapped_column(String(50))

    __table_args__ = (
        CheckConstraint(
            "NOT (debit_amount > 0 AND credit_amount > 0)",
            name="ck_line_dr_xor_cr",
        ),
        CheckConstraint("debit_amount >= 0 AND credit_amount >= 0", name="ck_line_amounts_pos"),
    )

    entry: Mapped[JournalEntry] = relationship("JournalEntry", back_populates="lines")
    account: Mapped[ChartOfAccount] = relationship(
        "ChartOfAccount", back_populates="journal_lines"
    )

    @property
    def drcr(self) -> str:
        return "DR" if self.debit_amount > 0 else "CR"

    @property
    def amount(self) -> Decimal:
        return self.debit_amount if self.debit_amount > 0 else self.credit_amount

    def __repr__(self) -> str:
        return (
            f"<JournalLine entry={self.entry_id} line={self.line_no} "
            f"acct={self.account_id} DR={self.debit_amount} CR={self.credit_amount}>"
        )


# ── LedgerEntry ───────────────────────────────────────────────────────────────

class LedgerEntry(Base):
    """
    บัญชีแยกประเภท — PostingEngine เขียนพร้อมกับ JournalLine.

    running_balance คือยอดสะสมต่อบัญชีต่อ period.
    """

    __tablename__ = "ledger_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("chart_of_accounts.id"), nullable=False
    )
    period_id: Mapped[int] = mapped_column(Integer, ForeignKey("periods.id"), nullable=False)
    entry_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("journal_entries.id"), nullable=False
    )
    line_id: Mapped[int] = mapped_column(Integer, ForeignKey("journal_lines.id"), nullable=False)
    entry_date: Mapped[date] = mapped_column(Date, nullable=False)
    debit_amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False, default=Decimal(0)
    )
    credit_amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False, default=Decimal(0)
    )
    running_balance: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    branch_id: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    account: Mapped[ChartOfAccount] = relationship(
        "ChartOfAccount", back_populates="ledger_entries"
    )
    period: Mapped[Period] = relationship("Period")
    entry: Mapped[JournalEntry] = relationship("JournalEntry")
    line: Mapped[JournalLine] = relationship("JournalLine")

    def __repr__(self) -> str:
        return (
            f"<LedgerEntry acct={self.account_id} date={self.entry_date} "
            f"balance={self.running_balance}>"
        )


# ── AccountBalance ────────────────────────────────────────────────────────────

class AccountBalance(Base):
    """
    ยอดคงเหลือบัญชีต่องวด — denormalized สำหรับ performance.

    PostingEngine อัปเดตตารางนี้ทุกครั้งที่ post entry.
    """

    __tablename__ = "account_balances"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("chart_of_accounts.id"), nullable=False
    )
    period_id: Mapped[int] = mapped_column(Integer, ForeignKey("periods.id"), nullable=False)
    branch_id: Mapped[int] = mapped_column(Integer, nullable=False)
    opening_balance: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False, default=Decimal(0)
    )
    total_debit: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False, default=Decimal(0)
    )
    total_credit: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False, default=Decimal(0)
    )
    closing_balance: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False, default=Decimal(0)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("account_id", "period_id", "branch_id", name="uq_balance_key"),
    )

    account: Mapped[ChartOfAccount] = relationship("ChartOfAccount")
    period: Mapped[Period] = relationship("Period")

    def __repr__(self) -> str:
        return (
            f"<AccountBalance acct={self.account_id} period={self.period_id} "
            f"closing={self.closing_balance}>"
        )


# ── BudgetItem ────────────────────────────────────────────────────────────────

class BudgetItem(Base):
    """งบประมาณต่อบัญชีต่องวด."""

    __tablename__ = "budget_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    fiscal_year: Mapped[int] = mapped_column(Integer, nullable=False)
    month: Mapped[Optional[int]] = mapped_column(Integer)
    account_id: Mapped[int] = mapped_column(Integer, ForeignKey("chart_of_accounts.id"), nullable=False)
    branch_id: Mapped[int] = mapped_column(Integer, nullable=False)
    budget_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal(0))
    created_by: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("fiscal_year", "month", "account_id", "branch_id", name="uq_budget_item"),
    )

    account: Mapped[ChartOfAccount] = relationship("ChartOfAccount")


# ── RecurringTemplate ─────────────────────────────────────────────────────────

class RecurringTemplate(Base):
    """รายการบัญชีที่เกิดซ้ำ — สร้าง JournalEntry อัตโนมัติตามกำหนด."""

    __tablename__ = "recurring_templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    journal_type: Mapped[str] = mapped_column(String(2), nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    frequency: Mapped[str] = mapped_column(String(20), nullable=False)
    # monthly | quarterly | yearly
    day_of_month: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    branch_id: Mapped[int] = mapped_column(Integer, nullable=False)
    created_by: Mapped[int] = mapped_column(Integer, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_run_date: Mapped[Optional[date]] = mapped_column(Date)
    next_run_date: Mapped[Optional[date]] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "frequency IN ('monthly','quarterly','yearly')", name="ck_recurring_freq"
        ),
        CheckConstraint("day_of_month BETWEEN 1 AND 31", name="ck_recurring_day"),
    )

    end_date: Mapped[Optional[date]] = mapped_column(Date)
    company_id: Mapped[Optional[int]] = mapped_column(Integer)

    lines: Mapped[list[RecurringLine]] = relationship(
        "RecurringLine", back_populates="template", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<RecurringTemplate id={self.id} name={self.name!r} freq={self.frequency!r}>"


class RecurringLine(Base):
    """บรรทัดของ RecurringTemplate."""

    __tablename__ = "recurring_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    template_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("recurring_templates.id"), nullable=False
    )
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    account_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("chart_of_accounts.id"), nullable=False
    )
    description: Mapped[Optional[str]] = mapped_column(String(300))
    debit_amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False, default=Decimal(0)
    )
    credit_amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False, default=Decimal(0)
    )

    template: Mapped[RecurringTemplate] = relationship("RecurringTemplate", back_populates="lines")
    account: Mapped[ChartOfAccount] = relationship("ChartOfAccount")

    def __repr__(self) -> str:
        return f"<RecurringLine tmpl={self.template_id} line={self.line_no}>"


# ── PeriodCloseLog ────────────────────────────────────────────────────────────

class PeriodCloseLog(Base):
    """Audit log สำหรับการปิด/เปิดงวดบัญชี."""

    __tablename__ = "period_close_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    period_id: Mapped[int] = mapped_column(Integer, ForeignKey("periods.id"), nullable=False)
    action: Mapped[str] = mapped_column(String(20), nullable=False)  # closed | reopened
    user_id: Mapped[int] = mapped_column(Integer, nullable=False)
    user_role: Mapped[str] = mapped_column(String(30), nullable=False)
    reason: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


# ── AdjustingEntry ────────────────────────────────────────────────────────────

class AdjustingEntry(Base):
    """ติดตาม adjusting entries ที่ต้องทำในแต่ละงวด."""

    __tablename__ = "adjusting_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    period_id: Mapped[int] = mapped_column(Integer, ForeignKey("periods.id"), nullable=False)
    item_type: Mapped[str] = mapped_column(String(30), nullable=False)
    # depreciation | accrual | prepaid | deferred_revenue | allowance
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, server_default="0")
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="pending")
    # pending | posted | skipped
    journal_no: Mapped[Optional[str]] = mapped_column(String(30))
    source_id: Mapped[Optional[int]] = mapped_column(Integer)
    created_by: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
