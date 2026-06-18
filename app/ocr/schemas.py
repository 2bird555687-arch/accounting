"""Pydantic schemas สำหรับ OCR results."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field


class LineItemOCR(BaseModel):
    description: str | None = None
    qty: Decimal | None = None
    unit_price: Decimal | None = None
    amount: Decimal | None = None


class FieldConfidence(BaseModel):
    value: Any = None
    confidence: float = Field(ge=0, le=100)
    low_confidence: bool = False


class BaseOCRResult(BaseModel):
    document_type: str
    confidence: float = Field(ge=0, le=100, description="Overall confidence score")
    vendor_name: str | None = None
    vendor_tax_id: str | None = None
    vendor_branch: str | None = None
    buyer_name: str | None = None
    buyer_tax_id: str | None = None
    doc_number: str | None = None
    doc_date: str | None = None
    due_date: str | None = None
    line_items: list[LineItemOCR] = []
    subtotal: Decimal | None = None
    vat_rate: Decimal | None = None
    vat_amount: Decimal | None = None
    wht_rate: Decimal | None = None
    wht_amount: Decimal | None = None
    total: Decimal | None = None
    payment_method: str | None = None
    low_confidence_fields: list[str] = []
    field_confidences: dict[str, float] = {}


class InvoiceOCRResult(BaseOCRResult):
    document_type: str = "invoice"


class ReceiptOCRResult(BaseOCRResult):
    document_type: str = "receipt"


class WHTOCRResult(BaseOCRResult):
    document_type: str = "wht_certificate"
    wht_income_type: str | None = None
    wht_payment_date: str | None = None


class ContactSuggestion(BaseModel):
    contact_id: int | None = None
    name: str | None = None
    tax_id: str | None = None
    matched: bool = False


class OCRUploadResponse(BaseModel):
    ocr_history_id: int
    document_type: str
    result: BaseOCRResult
    contact_suggestion: ContactSuggestion
    suggested_account_code: str | None = None
    low_confidence_fields: list[str] = []


class OCRConfirmIn(BaseModel):
    ocr_history_id: int
    document_type: str
    doc_date: str
    vendor_name: str | None = None
    vendor_tax_id: str | None = None
    doc_number: str | None = None
    subtotal: Decimal | None = None
    vat_amount: Decimal | None = None
    wht_amount: Decimal | None = None
    total: Decimal | None = None
    contact_id: int | None = None
    account_code: str | None = None
    payment_method: str | None = None


class OCRConfirmResponse(BaseModel):
    ocr_history_id: int
    journal_no: str
    message: str = "บันทึกรายการสำเร็จ"


class OCRHistoryOut(BaseModel):
    id: int
    document_type: str
    original_filename: str | None
    overall_confidence: float | None
    status: str
    journal_no: str | None
    contact_id: int | None
    created_at: datetime

    model_config = {"from_attributes": True}
