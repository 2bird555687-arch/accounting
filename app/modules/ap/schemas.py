"""AP Module Pydantic Schemas."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, field_validator, model_validator


# ══════════════════════════════════════════════════════════════════════════════
# PURCHASE ORDER SCHEMAS
# ══════════════════════════════════════════════════════════════════════════════

class POLineCreate(BaseModel):
    description: str
    account_code: str          # 1130 / 5102 / 6xxx
    unit: Optional[str] = None
    quantity: Decimal
    unit_price: Decimal
    vat_rate: Decimal = Decimal("7")

    @model_validator(mode="after")
    def positive_qty(self) -> POLineCreate:
        if self.quantity <= 0:
            raise ValueError("quantity ต้องมากกว่า 0")
        if self.unit_price < 0:
            raise ValueError("unit_price ต้องไม่ติดลบ")
        return self


class POCreate(BaseModel):
    contact_id: int
    po_date: date
    expected_date: Optional[date] = None
    purchase_type: str = "goods"          # goods / service / expense
    lines: list[POLineCreate]
    notes: Optional[str] = None

    @field_validator("purchase_type")
    @classmethod
    def validate_type(cls, v: str) -> str:
        if v not in ("goods", "service", "expense"):
            raise ValueError("purchase_type ต้องเป็น goods / service / expense")
        return v

    @field_validator("lines")
    @classmethod
    def lines_not_empty(cls, v: list) -> list:
        if not v:
            raise ValueError("lines ต้องมีอย่างน้อย 1 รายการ")
        return v


class POLineOut(BaseModel):
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
    received_qty: Decimal

    model_config = {"from_attributes": True}


class POOut(BaseModel):
    id: int
    company_id: int
    branch_id: int
    po_no: str
    po_date: date
    expected_date: Optional[date]
    contact_id: int
    contact_name: str
    purchase_type: str
    subtotal: Decimal
    vat_amount: Decimal
    total_amount: Decimal
    status: str
    notes: Optional[str]
    approved_by: Optional[int]
    approved_at: Optional[datetime]
    created_by: int
    created_at: datetime

    model_config = {"from_attributes": True}


class PODetail(POOut):
    lines: list[POLineOut] = []


class POFilter(BaseModel):
    contact_id: Optional[int] = None
    status: Optional[str] = None
    date_from: Optional[date] = None
    date_to: Optional[date] = None
    search: Optional[str] = None
    purchase_type: Optional[str] = None
    limit: int = 50
    offset: int = 0


# ══════════════════════════════════════════════════════════════════════════════
# GRN SCHEMAS
# ══════════════════════════════════════════════════════════════════════════════

class GRNLineCreate(BaseModel):
    po_line_id: int
    received_qty: Decimal

    @field_validator("received_qty")
    @classmethod
    def positive(cls, v: Decimal) -> Decimal:
        if v <= 0:
            raise ValueError("received_qty ต้องมากกว่า 0")
        return v


class GRNCreate(BaseModel):
    po_id: int
    grn_date: date
    lines: list[GRNLineCreate]
    notes: Optional[str] = None

    @field_validator("lines")
    @classmethod
    def lines_not_empty(cls, v: list) -> list:
        if not v:
            raise ValueError("lines ต้องมีอย่างน้อย 1 รายการ")
        return v


class GRNLineOut(BaseModel):
    id: int
    po_line_id: int
    description: str
    ordered_qty: Decimal
    received_qty: Decimal
    unit: Optional[str]

    model_config = {"from_attributes": True}


class GRNOut(BaseModel):
    id: int
    company_id: int
    branch_id: int
    grn_no: str
    grn_date: date
    po_id: int
    po_no: str
    contact_name: str
    status: str
    notes: Optional[str]
    received_by: int
    created_at: datetime
    lines: list[GRNLineOut] = []

    model_config = {"from_attributes": True}


# ══════════════════════════════════════════════════════════════════════════════
# AP PURCHASE SCHEMAS
# ══════════════════════════════════════════════════════════════════════════════

class PurchaseLineCreate(BaseModel):
    description: str
    account_code: str
    unit: Optional[str] = None
    quantity: Decimal = Decimal("1")
    unit_price: Decimal
    vat_rate: Decimal = Decimal("7")

    @model_validator(mode="after")
    def positive(self) -> PurchaseLineCreate:
        if self.quantity <= 0:
            raise ValueError("quantity ต้องมากกว่า 0")
        if self.unit_price < 0:
            raise ValueError("unit_price ต้องไม่ติดลบ")
        return self


class PurchaseCreate(BaseModel):
    contact_id: Optional[int] = None     # required สำหรับ credit, optional สำหรับ cash
    purchase_date: date
    due_date: Optional[date] = None
    supplier_invoice_no: Optional[str] = None
    purchase_type: str = "goods"
    lines: list[PurchaseLineCreate]
    description: Optional[str] = None
    po_id: Optional[int] = None          # ถ้ามี PO
    grn_id: Optional[int] = None         # ถ้ามี GRN
    vat_exempt: bool = False
    payment_mode: str = "credit"         # "cash" | "credit"
    payment_account_code: Optional[str] = None  # account code เงินสด/ธนาคาร (สำหรับ cash)

    @field_validator("payment_mode")
    @classmethod
    def validate_payment_mode(cls, v: str) -> str:
        if v not in ("cash", "credit"):
            raise ValueError("payment_mode ต้องเป็น cash หรือ credit")
        return v

    @field_validator("purchase_type")
    @classmethod
    def validate_type(cls, v: str) -> str:
        if v not in ("goods", "service", "expense"):
            raise ValueError("purchase_type ต้องเป็น goods / service / expense")
        return v

    @field_validator("lines")
    @classmethod
    def lines_not_empty(cls, v: list) -> list:
        if not v:
            raise ValueError("lines ต้องมีอย่างน้อย 1 รายการ")
        return v

    @model_validator(mode="after")
    def validate_payment(self) -> "PurchaseCreate":
        if self.payment_mode == "credit" and not self.contact_id:
            raise ValueError("ต้องระบุผู้ขายสำหรับการซื้อแบบเครดิต")
        if self.payment_mode == "cash" and not self.payment_account_code:
            raise ValueError("ต้องระบุช่องทางจ่ายเงินสำหรับการซื้อสด")
        return self


class PurchaseLineOut(BaseModel):
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


class PurchaseOut(BaseModel):
    id: int
    company_id: int
    branch_id: int
    purchase_no: str
    supplier_invoice_no: Optional[str]
    purchase_date: date
    due_date: date
    contact_id: Optional[int]
    contact_name: str
    payment_mode: str = "credit"
    payment_account_code: Optional[str] = None
    purchase_type: str
    po_id: Optional[int]
    grn_id: Optional[int]
    subtotal: Decimal
    vat_amount: Decimal
    wht_amount: Decimal
    total_amount: Decimal
    paid_amount: Decimal
    balance: Decimal
    status: str
    description: Optional[str]
    journal_entry_no: Optional[str]
    is_overdue: bool
    created_by: int
    created_at: datetime

    model_config = {"from_attributes": True}


class PurchaseDetail(PurchaseOut):
    lines: list[PurchaseLineOut] = []


class PurchaseFilter(BaseModel):
    contact_id: Optional[int] = None
    status: Optional[str] = None
    purchase_type: Optional[str] = None
    date_from: Optional[date] = None
    date_to: Optional[date] = None
    overdue_only: bool = False
    search: Optional[str] = None
    po_id: Optional[int] = None
    limit: int = 50
    offset: int = 0


class CancelPurchaseIn(BaseModel):
    reason: str


# ══════════════════════════════════════════════════════════════════════════════
# AP PAYMENT SCHEMAS
# ══════════════════════════════════════════════════════════════════════════════

class PaymentAllocationIn(BaseModel):
    purchase_id: int
    allocated_amount: Decimal

    @field_validator("allocated_amount")
    @classmethod
    def positive(cls, v: Decimal) -> Decimal:
        if v <= 0:
            raise ValueError("allocated_amount ต้องมากกว่า 0")
        return v


class PaymentCreate(BaseModel):
    contact_id: int
    payment_date: date
    allocations: list[PaymentAllocationIn]
    wht_amount: Decimal = Decimal("0")   # WHT ที่เราหัก → Cr 2121
    bank_account_code: str = "1102"
    description: Optional[str] = None
    reference: Optional[str] = None

    @field_validator("allocations")
    @classmethod
    def alloc_not_empty(cls, v: list) -> list:
        if not v:
            raise ValueError("allocations ต้องมีอย่างน้อย 1 รายการ")
        return v


class PaymentAllocationOut(BaseModel):
    id: int
    purchase_id: int
    purchase_no: str
    allocated_amount: Decimal

    model_config = {"from_attributes": True}


class PaymentOut(BaseModel):
    id: int
    company_id: int
    branch_id: int
    payment_no: str
    payment_date: date
    contact_id: int
    contact_name: str
    bank_account_code: str
    total_paid: Decimal
    wht_amount: Decimal
    total_applied: Decimal
    status: str
    description: Optional[str]
    reference: Optional[str]
    journal_entry_no: Optional[str]
    allocations: list[PaymentAllocationOut] = []
    created_by: int
    created_at: datetime

    model_config = {"from_attributes": True}


class PaymentFilter(BaseModel):
    contact_id: Optional[int] = None
    date_from: Optional[date] = None
    date_to: Optional[date] = None
    search: Optional[str] = None
    limit: int = 50
    offset: int = 0
