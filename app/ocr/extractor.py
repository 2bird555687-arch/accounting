"""OCR Extractor — เรียก Claude Vision API เพื่อแยกข้อมูลจากเอกสาร."""

from __future__ import annotations

import json
import re

import anthropic

from app.config import settings
from app.ocr.schemas import InvoiceOCRResult, ReceiptOCRResult, WHTOCRResult, BaseOCRResult

_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    return _client


_BASE_SCHEMA = """
{
  "document_type": "invoice|receipt|wht_certificate",
  "confidence": 0-100,
  "vendor_name": "...",
  "vendor_tax_id": "...",
  "vendor_branch": "...",
  "buyer_name": "...",
  "buyer_tax_id": "...",
  "doc_number": "...",
  "doc_date": "YYYY-MM-DD",
  "due_date": "YYYY-MM-DD",
  "line_items": [{"description": "...", "qty": 0, "unit_price": 0, "amount": 0}],
  "subtotal": 0,
  "vat_rate": 7,
  "vat_amount": 0,
  "wht_rate": 0,
  "wht_amount": 0,
  "total": 0,
  "payment_method": "cash|transfer|cheque|credit",
  "field_confidences": {
    "vendor_name": 0-100,
    "vendor_tax_id": 0-100,
    "doc_number": 0-100,
    "doc_date": 0-100,
    "total": 0-100
  },
  "low_confidence_fields": ["field_name_if_confidence_lt_80"]
}"""


def _build_content(images: list[dict[str, str]], prompt: str) -> list[dict]:
    content: list[dict] = []
    for img in images:
        content.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": img["media_type"],
                "data": img["data"],
            },
        })
    content.append({"type": "text", "text": prompt})
    return content


def _parse_json(text: str) -> dict:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError("No JSON found in Claude response")
    return json.loads(match.group())


def _mark_low_confidence(data: dict) -> dict:
    confidences = data.get("field_confidences", {})
    low_fields: list[str] = data.get("low_confidence_fields", [])
    for field, score in confidences.items():
        if score < 80 and field not in low_fields:
            low_fields.append(field)
    data["low_confidence_fields"] = low_fields
    return data


def extract_invoice(images: list[dict[str, str]], ctx=None) -> InvoiceOCRResult:
    prompt = f"""อ่านใบแจ้งหนี้/ใบกำกับภาษีในภาพ และแยกข้อมูลเป็น JSON ตามโครงสร้างนี้:
{_BASE_SCHEMA}

กฎ:
- document_type ให้ใส่ "invoice"
- confidence คือความมั่นใจรวมทั้งเอกสาร 0-100
- field_confidences ให้ให้คะแนน 0-100 สำหรับแต่ละฟิลด์หลัก
- low_confidence_fields ให้ระบุฟิลด์ที่ confidence < 80
- ถ้าอ่านไม่ได้ให้ใส่ null
- ตอบเฉพาะ JSON เท่านั้น ไม่ต้องมีคำอธิบาย"""

    msg = _get_client().messages.create(
        model=settings.OCR_MODEL,
        max_tokens=settings.OCR_MAX_TOKENS,
        messages=[{"role": "user", "content": _build_content(images, prompt)}],
    )
    data = _parse_json(msg.content[0].text)
    data = _mark_low_confidence(data)
    data["document_type"] = "invoice"
    return InvoiceOCRResult(**data)


def extract_receipt(images: list[dict[str, str]], ctx=None) -> ReceiptOCRResult:
    prompt = f"""อ่านใบเสร็จรับเงิน/receipt ในภาพ และแยกข้อมูลเป็น JSON ตามโครงสร้างนี้:
{_BASE_SCHEMA}

กฎ:
- document_type ให้ใส่ "receipt"
- confidence คือความมั่นใจรวมทั้งเอกสาร 0-100
- field_confidences ให้ให้คะแนน 0-100 สำหรับแต่ละฟิลด์หลัก
- low_confidence_fields ให้ระบุฟิลด์ที่ confidence < 80
- ถ้าอ่านไม่ได้ให้ใส่ null
- ตอบเฉพาะ JSON เท่านั้น ไม่ต้องมีคำอธิบาย"""

    msg = _get_client().messages.create(
        model=settings.OCR_MODEL,
        max_tokens=settings.OCR_MAX_TOKENS,
        messages=[{"role": "user", "content": _build_content(images, prompt)}],
    )
    data = _parse_json(msg.content[0].text)
    data = _mark_low_confidence(data)
    data["document_type"] = "receipt"
    return ReceiptOCRResult(**data)


def extract_wht_certificate(images: list[dict[str, str]], ctx=None) -> WHTOCRResult:
    wht_schema = _BASE_SCHEMA.rstrip("}")
    wht_schema += ',\n  "wht_income_type": "...",\n  "wht_payment_date": "YYYY-MM-DD"\n}'

    prompt = f"""อ่านหนังสือรับรองการหักภาษี ณ ที่จ่าย (ภ.ง.ด. 1/3/53) ในภาพ
และแยกข้อมูลเป็น JSON ตามโครงสร้างนี้:
{wht_schema}

กฎ:
- document_type ให้ใส่ "wht_certificate"
- wht_income_type คือประเภทเงินได้ เช่น "เงินเดือน", "ค่าจ้าง", "ค่าบริการ"
- confidence คือความมั่นใจรวม 0-100
- field_confidences ให้ให้คะแนน 0-100 สำหรับแต่ละฟิลด์หลัก
- low_confidence_fields ให้ระบุฟิลด์ที่ confidence < 80
- ถ้าอ่านไม่ได้ให้ใส่ null
- ตอบเฉพาะ JSON เท่านั้น"""

    msg = _get_client().messages.create(
        model=settings.OCR_MODEL,
        max_tokens=settings.OCR_MAX_TOKENS,
        messages=[{"role": "user", "content": _build_content(images, prompt)}],
    )
    data = _parse_json(msg.content[0].text)
    data = _mark_low_confidence(data)
    data["document_type"] = "wht_certificate"
    return WHTOCRResult(**data)


def auto_extract(images: list[dict[str, str]], hint: str | None = None) -> BaseOCRResult:
    """ตรวจจับประเภทเอกสารอัตโนมัติแล้ว extract."""
    if hint == "invoice":
        return extract_invoice(images)
    if hint == "receipt":
        return extract_receipt(images)
    if hint == "wht":
        return extract_wht_certificate(images)

    # Auto-detect: ask Claude to classify first
    detect_prompt = """ดูภาพเอกสารนี้แล้วตอบว่าเป็นประเภทไหน (ตอบเพียงคำเดียว):
- invoice
- receipt
- wht_certificate"""
    msg = _get_client().messages.create(
        model=settings.OCR_MODEL,
        max_tokens=20,
        messages=[{"role": "user", "content": _build_content(images, detect_prompt)}],
    )
    doc_type = msg.content[0].text.strip().lower()
    if "wht" in doc_type:
        return extract_wht_certificate(images)
    if "receipt" in doc_type:
        return extract_receipt(images)
    return extract_invoice(images)
