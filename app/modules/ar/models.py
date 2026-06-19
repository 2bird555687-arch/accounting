"""AR Module Models — Contact, ARInvoice, ARInvoiceLine, ARReceipt, ARReceiptAllocation,
BillingNote, BillingNoteInvoice, Quotation, QuotationLine."""

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
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import CompanyBase as Base


# ── Contact Master ────────────────────────────────────────────────────────────

class Contact(Base):
    """
    ผู้ติดต่อ (ลูกค้า/เจ้าหนี้) — Contact Master ใช้ร่วมกัน AR และ AP.

    contact_type: "customer" | "supplier" | "both"
    """

    __tablename__ = "contacts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    company_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    contact_type: Mapped[str] = mapped_column(String(10), nullable=False, default="customer")
    # customer / supplier / both

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    name_en: Mapped[Optional[str]] = mapped_column(String(200))
    tax_id: Mapped[Optional[str]] = mapped_column(String(13))  # เลขประจำตัวผู้เสียภาษี 13 หลัก
    branch_code: Mapped[Optional[str]] = mapped_column(String(5), default="00000")  # สาขาของผู้ติดต่อ
    address: Mapped[Optional[str]] = mapped_column(Text)
    phone: Mapped[Optional[str]] = mapped_column(String(50))
    email: Mapped[Optional[str]] = mapped_column(String(200))

    # Defaults สำหรับ AR/AP integration
    credit_days: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    wht_rate: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2))  # % เช่น 3.00
    wht_type: Mapped[Optional[str]] = mapped_column(String(5))  # "3" | "53" | "1"
    default_ar_account: Mapped[str] = mapped_column(String(10), default="1110", nullable=False)
    default_ap_account: Mapped[str] = mapped_column(String(10), default="2101", nullable=False)
    default_revenue_account: Mapped[str] = mapped_column(String(10), default="4101", nullable=False)

    # เครดิต
    credit_limit: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=Decimal(0))

    # บัญชีธนาคารสำหรับโอนเงิน
    bank_name: Mapped[Optional[str]] = mapped_column(String(100))
    bank_branch: Mapped[Optional[str]] = mapped_column(String(100))
    bank_account_no: Mapped[Optional[str]] = mapped_column(String(30))
    bank_account_name: Mapped[Optional[str]] = mapped_column(String(200))

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # Relationships
    invoices: Mapped[list[ARInvoice]] = relationship("ARInvoice", back_populates="contact")
    receipts: Mapped[list[ARReceipt]] = relationship("ARReceipt", back_populates="contact")


# ── AR Invoice ────────────────────────────────────────────────────────────────

class ARInvoice(Base):
    """
    ใบแจ้งหนี้ (Invoice) — เอกสารเรียกเก็บเงินจากลูกค้า.

    status:
        draft       — ยังไม่ post
        posted      — post journal แล้ว, ยังไม่ได้รับชำระ
        partially_paid — รับชำระบางส่วน
        paid        — รับชำระครบแล้ว
        cancelled   — ยกเลิก (Reversing Entry ถูกสร้างแล้ว)
    """

    __tablename__ = "ar_invoices"
    __table_args__ = (UniqueConstraint("company_id", "invoice_no", name="uq_ar_invoice_no"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    company_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    branch_id: Mapped[int] = mapped_column(Integer, nullable=False)

    invoice_no: Mapped[str] = mapped_column(String(20), nullable=False)
    invoice_date: Mapped[date] = mapped_column(Date, nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)

    contact_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("contacts.id"), nullable=True)

    payment_mode: Mapped[str] = mapped_column(String(10), nullable=False, default="credit")
    # "cash" | "credit"
    payment_account_code: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    # account code เงินสด/ธนาคาร — ใช้เฉพาะ payment_mode="cash"

    # ยอดเงิน
    subtotal: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=Decimal(0))
    vat_amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=Decimal(0))
    wht_amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=Decimal(0))
    # WHT ที่ลูกค้าจะหักณที่จ่าย (เก็บไว้อ้างอิง ไม่ได้ post ที่ invoice)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=Decimal(0))
    # = subtotal + vat_amount
    paid_amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=Decimal(0))
    balance: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=Decimal(0))
    # = total_amount - paid_amount

    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    description: Mapped[Optional[str]] = mapped_column(Text)
    reference: Mapped[Optional[str]] = mapped_column(String(100))  # เลขที่ใบสั่งซื้อลูกค้า (PO#)

    # ลิงก์ Billing Note
    billing_note_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("billing_notes.id"), nullable=True
    )

    # ลิงก์กลับไปยัง journal
    journal_entry_no: Mapped[Optional[str]] = mapped_column(String(20))

    created_by: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # Relationships
    contact: Mapped[Optional[Contact]] = relationship("Contact", back_populates="invoices")
    lines: Mapped[list[ARInvoiceLine]] = relationship(
        "ARInvoiceLine", back_populates="invoice", order_by="ARInvoiceLine.line_no",
        cascade="all, delete-orphan",
    )
    allocations: Mapped[list[ARReceiptAllocation]] = relationship(
        "ARReceiptAllocation", back_populates="invoice"
    )

    @property
    def is_overdue(self) -> bool:
        return self.status not in ("paid", "cancelled") and date.today() > self.due_date


# ── AR Invoice Line ───────────────────────────────────────────────────────────

class ARInvoiceLine(Base):
    """บรรทัดรายการใน Invoice."""

    __tablename__ = "ar_invoice_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    invoice_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("ar_invoices.id", ondelete="CASCADE"), nullable=False
    )
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)

    description: Mapped[str] = mapped_column(String(500), nullable=False)
    account_code: Mapped[str] = mapped_column(String(10), nullable=False)  # รหัสบัญชีรายได้
    unit: Mapped[Optional[str]] = mapped_column(String(20))
    quantity: Mapped[Decimal] = mapped_column(Numeric(15, 4), nullable=False, default=Decimal(1))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(15, 4), nullable=False, default=Decimal(0))
    amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=Decimal(0))
    # = quantity * unit_price
    vat_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, default=Decimal("7"))
    vat_amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=Decimal(0))

    invoice: Mapped[ARInvoice] = relationship("ARInvoice", back_populates="lines")


# ── AR Receipt ────────────────────────────────────────────────────────────────

class ARReceipt(Base):
    """
    ใบรับเงิน (Receipt) — บันทึกการรับชำระหนี้จากลูกค้า.

    Journal: Dr ธนาคาร (1102) + Dr WHT ถูกหัก (1141) | Cr ลูกหนี้ (1110)
    """

    __tablename__ = "ar_receipts"
    __table_args__ = (UniqueConstraint("company_id", "receipt_no", name="uq_ar_receipt_no"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    company_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    branch_id: Mapped[int] = mapped_column(Integer, nullable=False)

    receipt_no: Mapped[str] = mapped_column(String(20), nullable=False)
    receipt_date: Mapped[date] = mapped_column(Date, nullable=False)

    contact_id: Mapped[int] = mapped_column(Integer, ForeignKey("contacts.id"), nullable=False)

    bank_account_code: Mapped[str] = mapped_column(String(10), nullable=False, default="1102")
    total_received: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    # เงินที่ได้รับจริง (หลังหัก WHT แล้ว)
    wht_amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=Decimal(0))
    # WHT ที่ลูกค้าหักณที่จ่าย → Dr 1141
    total_applied: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=Decimal(0))
    # รวมยอดที่ match กับ invoice = total_received + wht_amount

    status: Mapped[str] = mapped_column(String(20), nullable=False, default="posted")
    description: Mapped[Optional[str]] = mapped_column(Text)
    reference: Mapped[Optional[str]] = mapped_column(String(100))

    journal_entry_no: Mapped[Optional[str]] = mapped_column(String(20))

    created_by: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    contact: Mapped[Contact] = relationship("Contact", back_populates="receipts")
    allocations: Mapped[list[ARReceiptAllocation]] = relationship(
        "ARReceiptAllocation", back_populates="receipt", cascade="all, delete-orphan"
    )


# ── AR Receipt Allocation ─────────────────────────────────────────────────────

class ARReceiptAllocation(Base):
    """การ match ใบรับเงินกับ Invoice (Many-to-Many with amount)."""

    __tablename__ = "ar_receipt_allocations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    receipt_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("ar_receipts.id", ondelete="CASCADE"), nullable=False
    )
    invoice_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("ar_invoices.id"), nullable=False
    )
    allocated_amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)

    receipt: Mapped[ARReceipt] = relationship("ARReceipt", back_populates="allocations")
    invoice: Mapped[ARInvoice] = relationship("ARInvoice", back_populates="allocations")


# ── Billing Note ──────────────────────────────────────────────────────────────

class BillingNote(Base):
    """
    ใบวางบิล (Billing Note) — รวม Invoice หลายใบเพื่อเสนอลูกค้า.

    ไม่สร้าง Journal Entry — เป็นเอกสารทางการค้าอย่างเดียว.
    status: draft / sent / cancelled
    """

    __tablename__ = "billing_notes"
    __table_args__ = (UniqueConstraint("company_id", "billing_note_no", name="uq_billing_note_no"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    company_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    branch_id: Mapped[int] = mapped_column(Integer, nullable=False)

    billing_note_no: Mapped[str] = mapped_column(String(20), nullable=False)
    billing_date: Mapped[date] = mapped_column(Date, nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)

    contact_id: Mapped[int] = mapped_column(Integer, ForeignKey("contacts.id"), nullable=False)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=Decimal(0))

    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    description: Mapped[Optional[str]] = mapped_column(Text)

    created_by: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # Relationships
    contact: Mapped[Contact] = relationship("Contact")
    invoice_links: Mapped[list[BillingNoteInvoice]] = relationship(
        "BillingNoteInvoice", back_populates="billing_note", cascade="all, delete-orphan"
    )


class BillingNoteInvoice(Base):
    """Invoice ที่อยู่ใน Billing Note (Many-to-Many)."""

    __tablename__ = "billing_note_invoices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    billing_note_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("billing_notes.id", ondelete="CASCADE"), nullable=False
    )
    invoice_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("ar_invoices.id"), nullable=False
    )

    billing_note: Mapped[BillingNote] = relationship("BillingNote", back_populates="invoice_links")
    invoice: Mapped[ARInvoice] = relationship("ARInvoice")


# ── Quotation ─────────────────────────────────────────────────────────────────

class Quotation(Base):
    """
    ใบเสนอราคา (Quotation).

    status flow: draft → sent → accepted → converted / rejected / expired
    converted_invoice_id: ลิงก์ไปยัง Invoice ที่สร้างจาก Quotation นี้
    """

    __tablename__ = "quotations"
    __table_args__ = (UniqueConstraint("company_id", "quotation_no", name="uq_quotation_no"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    company_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    branch_id: Mapped[int] = mapped_column(Integer, nullable=False)

    quotation_no: Mapped[str] = mapped_column(String(20), nullable=False)
    quotation_date: Mapped[date] = mapped_column(Date, nullable=False)
    valid_until: Mapped[date] = mapped_column(Date, nullable=False)

    contact_id: Mapped[int] = mapped_column(Integer, ForeignKey("contacts.id"), nullable=False)

    subtotal: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=Decimal(0))
    vat_amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=Decimal(0))
    total_amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=Decimal(0))

    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    description: Mapped[Optional[str]] = mapped_column(Text)
    reference: Mapped[Optional[str]] = mapped_column(String(100))

    converted_invoice_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("ar_invoices.id"), nullable=True
    )

    created_by: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # Relationships
    contact: Mapped[Contact] = relationship("Contact")
    lines: Mapped[list[QuotationLine]] = relationship(
        "QuotationLine", back_populates="quotation",
        order_by="QuotationLine.line_no",
        cascade="all, delete-orphan",
    )
    converted_invoice: Mapped[Optional[ARInvoice]] = relationship("ARInvoice", foreign_keys=[converted_invoice_id])

    @property
    def is_expired(self) -> bool:
        return self.status not in ("converted", "cancelled") and date.today() > self.valid_until


class QuotationLine(Base):
    """บรรทัดรายการใน Quotation."""

    __tablename__ = "quotation_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    quotation_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("quotations.id", ondelete="CASCADE"), nullable=False
    )
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)

    description: Mapped[str] = mapped_column(String(500), nullable=False)
    account_code: Mapped[str] = mapped_column(String(10), nullable=False)
    unit: Mapped[Optional[str]] = mapped_column(String(20))
    quantity: Mapped[Decimal] = mapped_column(Numeric(15, 4), nullable=False, default=Decimal(1))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(15, 4), nullable=False, default=Decimal(0))
    amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=Decimal(0))
    vat_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, default=Decimal("7"))
    vat_amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=Decimal(0))

    quotation: Mapped[Quotation] = relationship("Quotation", back_populates="lines")
