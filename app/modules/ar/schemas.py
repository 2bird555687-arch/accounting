"""AR Module Pydantic Schemas — Contact, Invoice, Receipt."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, field_validator, model_validator


# ══════════════════════════════════════════════════════════════════════════════
# CONTACT SCHEMAS
# ══════════════════════════════════════════════════════════════════════════════

class ContactCreate(BaseModel):
    name: str
    name_en: Optional[str] = None
    tax_id: Optional[str] = None
    branch_code: str = "00000"
    contact_type: str = "customer"  # customer / supplier / both
    address: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    credit_days: int = 30
    wht_rate: Optional[Decimal] = None
    wht_type: Optional[str] = None
    default_ar_account: str = "1110"
    default_ap_account: str = "2101"
    default_revenue_account: str = "4101"

    @field_validator("contact_type")
    @classmethod
    def validate_type(cls, v: str) -> str:
        if v not in ("customer", "supplier", "both"):
            raise ValueError("contact_type ต้องเป็น customer / supplier / both")
        return v

    @field_validator("tax_id")
    @classmethod
    def validate_tax_id(cls, v: Optional[str]) -> Optional[str]:
        if v and len(v.replace("-", "")) not in (13,):
            raise ValueError("tax_id ต้องมี 13 หลัก")
        return v


class ContactUpdate(BaseModel):
    name: Optional[str] = None
    name_en: Optional[str] = None
    tax_id: Optional[str] = None
    branch_code: Optional[str] = None
    address: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    credit_days: Optional[int] = None
    wht_rate: Optional[Decimal] = None
    wht_type: Optional[str] = None
    default_ar_account: Optional[str] = None
    default_ap_account: Optional[str] = None
    default_revenue_account: Optional[str] = None
    is_active: Optional[bool] = None


class ContactOut(BaseModel):
    id: int
    company_id: int
    contact_type: str
    name: str
    name_en: Optional[str]
    tax_id: Optional[str]
    branch_code: Optional[str]
    address: Optional[str]
    phone: Optional[str]
    email: Optional[str]
    credit_days: int
    wht_rate: Optional[Decimal]
    wht_type: Optional[str]
    default_ar_account: str
    default_ap_account: str
    default_revenue_account: str
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


# ══════════════════════════════════════════════════════════════════════════════
# INVOICE SCHEMAS
# ══════════════════════════════════════════════════════════════════════════════

class InvoiceLineCreate(BaseModel):
    description: str
    account_code: str         # รหัสบัญชีรายได้ เช่น "4101"
    unit: Optional[str] = None
    quantity: Decimal = Decimal("1")
    unit_price: Decimal
    vat_rate: Decimal = Decimal("7")

    @model_validator(mode="after")
    def compute_amounts(self) -> InvoiceLineCreate:
        # validation เท่านั้น — amount คำนวณใน service
        if self.quantity <= 0:
            raise ValueError("quantity ต้องมากกว่า 0")
        if self.unit_price < 0:
            raise ValueError("unit_price ต้องไม่ติดลบ")
        return self


class InvoiceCreate(BaseModel):
    contact_id: Optional[int] = None      # required สำหรับ credit, optional สำหรับ cash
    invoice_date: date
    due_date: Optional[date] = None        # ถ้าไม่ระบุ ใช้ invoice_date + credit_days
    lines: list[InvoiceLineCreate]
    description: Optional[str] = None
    reference: Optional[str] = None       # PO# ของลูกค้า
    bank_account_code: str = "1110"       # บัญชีลูกหนี้ (default 1110)
    vat_exempt: bool = False              # True = ไม่มี VAT (ขายให้ส่งออก ฯลฯ)
    payment_mode: str = "credit"          # "cash" | "credit"
    payment_account_code: Optional[str] = None  # account code เงินสด/ธนาคาร (สำหรับ cash)

    @field_validator("payment_mode")
    @classmethod
    def validate_payment_mode(cls, v: str) -> str:
        if v not in ("cash", "credit"):
            raise ValueError("payment_mode ต้องเป็น cash หรือ credit")
        return v

    @field_validator("lines")
    @classmethod
    def lines_not_empty(cls, v: list) -> list:
        if not v:
            raise ValueError("lines ต้องมีอย่างน้อย 1 รายการ")
        return v

    @model_validator(mode="after")
    def validate_payment(self) -> "InvoiceCreate":
        if self.payment_mode == "credit" and not self.contact_id:
            raise ValueError("ต้องระบุลูกค้าสำหรับการขายแบบเครดิต")
        if self.payment_mode == "cash" and not self.payment_account_code:
            raise ValueError("ต้องระบุช่องทางรับเงินสำหรับการขายสด")
        return self


class InvoiceLineOut(BaseModel):
    id: int
    line_no: int
    description: str
    account_code: str
    unit: Optional[str]
    quantity: Decimal
    unit_price: Decimal
    amount: Decimal
    vat_rate: Decimal
    vat_amount: Decimal

    model_config = {"from_attributes": True}


class InvoiceOut(BaseModel):
    id: int
    company_id: int
    branch_id: int
    invoice_no: str
    invoice_date: date
    due_date: date
    contact_id: Optional[int]
    contact_name: str
    payment_mode: str = "credit"
    payment_account_code: Optional[str] = None
    subtotal: Decimal
    vat_amount: Decimal
    wht_amount: Decimal
    total_amount: Decimal
    paid_amount: Decimal
    balance: Decimal
    status: str
    description: Optional[str]
    reference: Optional[str]
    journal_entry_no: Optional[str]
    is_overdue: bool
    created_by: int
    created_at: datetime

    model_config = {"from_attributes": True}


class InvoiceDetail(InvoiceOut):
    """Invoice พร้อม lines."""
    lines: list[InvoiceLineOut] = []
    contact: Optional[ContactOut] = None


class InvoiceFilter(BaseModel):
    contact_id: Optional[int] = None
    status: Optional[str] = None         # draft/posted/partially_paid/paid/cancelled
    date_from: Optional[date] = None
    date_to: Optional[date] = None
    overdue_only: bool = False
    search: Optional[str] = None          # invoice_no หรือ contact name
    limit: int = 50
    offset: int = 0


class CancelInvoiceIn(BaseModel):
    reason: str


# ══════════════════════════════════════════════════════════════════════════════
# RECEIPT SCHEMAS
# ══════════════════════════════════════════════════════════════════════════════

class ReceiptAllocationIn(BaseModel):
    invoice_id: int
    allocated_amount: Decimal

    @field_validator("allocated_amount")
    @classmethod
    def positive(cls, v: Decimal) -> Decimal:
        if v <= 0:
            raise ValueError("allocated_amount ต้องมากกว่า 0")
        return v


class ReceiptCreate(BaseModel):
    contact_id: int
    receipt_date: date
    allocations: list[ReceiptAllocationIn]   # invoice ที่ต้องการ match
    wht_amount: Decimal = Decimal("0")       # WHT ที่ลูกค้าหักณที่จ่าย
    bank_account_code: str = "1102"
    description: Optional[str] = None
    reference: Optional[str] = None         # เลขที่ใบสำคัญรับ / เช็ค

    @field_validator("allocations")
    @classmethod
    def alloc_not_empty(cls, v: list) -> list:
        if not v:
            raise ValueError("allocations ต้องมีอย่างน้อย 1 รายการ")
        return v


class ReceiptAllocationOut(BaseModel):
    id: int
    invoice_id: int
    invoice_no: str
    allocated_amount: Decimal

    model_config = {"from_attributes": True}


class ReceiptOut(BaseModel):
    id: int
    company_id: int
    branch_id: int
    receipt_no: str
    receipt_date: date
    contact_id: int
    contact_name: str
    bank_account_code: str
    total_received: Decimal
    wht_amount: Decimal
    total_applied: Decimal
    status: str
    description: Optional[str]
    reference: Optional[str]
    journal_entry_no: Optional[str]
    allocations: list[ReceiptAllocationOut] = []
    created_by: int
    created_at: datetime

    model_config = {"from_attributes": True}


class ReceiptFilter(BaseModel):
    contact_id: Optional[int] = None
    date_from: Optional[date] = None
    date_to: Optional[date] = None
    search: Optional[str] = None
    limit: int = 50
    offset: int = 0


# ══════════════════════════════════════════════════════════════════════════════
# ETAX SCHEMAS
# ══════════════════════════════════════════════════════════════════════════════

class ETaxValidationResult(BaseModel):
    is_valid: bool
    errors: list[str] = []
    warnings: list[str] = []
