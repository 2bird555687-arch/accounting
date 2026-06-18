"""TAX Module Pydantic Schemas."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field


# ── VAT ───────────────────────────────────────────────────────────────────────

class VATSummaryItem(BaseModel):
    account_code: str       # "1140" หรือ "2120"
    direction: str          # "input" | "output"
    period: str             # "202601"
    total_base: Decimal
    total_vat: Decimal
    transaction_count: int


class PP30Data(BaseModel):
    """ข้อมูลสำหรับ ภ.พ.30 (VAT Return)."""
    period: str             # "202601"
    output_vat: Decimal     # ภาษีขาย (บัญชี 2120)
    input_vat: Decimal      # ภาษีซื้อ (บัญชี 1140)
    net_vat: Decimal        # ชำระ/ขอคืน
    due_date: date          # วันครบกำหนด
    output_base: Decimal
    input_base: Decimal


# ── WHT ───────────────────────────────────────────────────────────────────────

class WHTRecordCreate(BaseModel):
    direction: str = Field(pattern="^(collected|withheld)$")
    contact_id: int
    income_type: str = "3"
    wht_type: str
    payment_date: date
    base_amount: Decimal = Field(gt=0)
    wht_rate: Decimal = Field(gt=0)
    wht_amount: Decimal = Field(gt=0)
    source_module: Optional[str] = None
    source_id: Optional[int] = None
    journal_entry_no: Optional[str] = None


class WHTRecordOut(BaseModel):
    id: int
    direction: str
    contact_id: int
    income_type: str
    wht_type: str
    payment_date: date
    fiscal_year: int
    month: int
    base_amount: Decimal
    wht_rate: Decimal
    wht_amount: Decimal
    source_module: Optional[str]
    source_id: Optional[int]
    journal_entry_no: Optional[str]
    certificate_no: Optional[str]
    is_submitted: bool
    submitted_period: Optional[str]
    submitted_journal_no: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


class WHTSummaryItem(BaseModel):
    contact_id: int
    contact_name: str
    tax_id: Optional[str]
    income_type: str
    wht_type: str
    total_base: Decimal
    total_wht: Decimal
    record_count: int


class WHTCertificateOut(BaseModel):
    """หนังสือรับรองหัก ณ ที่จ่าย (ภงด.1/3/53)."""
    certificate_no: str
    contact_name: str
    contact_tax_id: Optional[str]
    contact_address: Optional[str]
    payer_name: str
    payer_tax_id: Optional[str]
    records: list[WHTRecordOut]
    total_base: Decimal
    total_wht: Decimal
    issued_date: date


class PostWHTPaymentIn(BaseModel):
    """นำส่งภาษีหัก ณ ที่จ่าย ให้กรมสรรพากร."""
    fiscal_year: int
    month: int = Field(ge=1, le=12)
    bank_account_code: str = "1102"
    wht_record_ids: Optional[list[int]] = None  # None = นำส่งทั้งหมดที่ยังไม่ได้นำส่งใน period


class WHTPaymentResult(BaseModel):
    journal_entry_no: str
    total_wht_paid: Decimal
    record_count: int
    period: str
