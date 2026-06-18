"""Bank Statement OCR — แยกรายการเดินบัญชีด้วย Claude Vision API."""

from __future__ import annotations

import json
import re
from decimal import Decimal

import anthropic

from app.config import settings

_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    return _client


# ── Bank-specific prompt hints ─────────────────────────────────────────────────

_BANK_HINTS: dict[str, str] = {
    "กรุงไทย": (
        "ธนาคารกรุงไทย (KTB): คอลัมน์มักเป็น วันที่ | รายการ | ถอน/เดบิต | ฝาก/เครดิต | ยอดคงเหลือ "
        "ref อยู่ในคอลัมน์รายการ เช่น 'โอนเงิน REF12345'"
    ),
    "กสิกร": (
        "ธนาคารกสิกรไทย (KBank): คอลัมน์ วันที่ | เวลา | รายการ | จำนวนเงิน (- คือถอน + คือฝาก) | ยอดคงเหลือ "
        "Ref No อยู่ท้ายคำอธิบาย"
    ),
    "scb": (
        "ธนาคารไทยพาณิชย์ (SCB): คอลัมน์ Date | Time | Description | Withdrawal | Deposit | Balance "
        "Transaction Ref อยู่ใน Description field"
    ),
    "กรุงเทพ": (
        "ธนาคารกรุงเทพ (BBL): คอลัมน์ วันที่ | รหัสรายการ | คำอธิบาย | จำนวนเงิน (เดบิต/เครดิต) | ยอดคงเหลือ"
    ),
    "ttb": (
        "ธนาคาร TTB (ทหารไทยธนชาต): คอลัมน์ Date | Description | Debit | Credit | Balance "
        "รหัสอ้างอิงอยู่ใน Description"
    ),
}

_STATEMENT_SCHEMA = """
{
  "account_no": "เลขที่บัญชี",
  "account_name": "ชื่อบัญชี",
  "bank_name": "ชื่อธนาคาร",
  "period_from": "YYYY-MM-DD",
  "period_to": "YYYY-MM-DD",
  "opening_balance": 0.00,
  "closing_balance": 0.00,
  "total_debit": 0.00,
  "total_credit": 0.00,
  "transactions": [
    {
      "date": "YYYY-MM-DD",
      "description": "คำอธิบายรายการ",
      "debit": 0.00,
      "credit": 0.00,
      "balance": 0.00,
      "ref_no": "รหัสอ้างอิงหรือ null"
    }
  ],
  "confidence": 0-100
}"""


class BankTransactionOCR:
    def __init__(self, **kw):
        self.date: str = kw.get("date", "")
        self.description: str = kw.get("description", "")
        self.debit: Decimal = Decimal(str(kw.get("debit") or 0))
        self.credit: Decimal = Decimal(str(kw.get("credit") or 0))
        self.balance: Decimal = Decimal(str(kw.get("balance") or 0))
        self.ref_no: str | None = kw.get("ref_no")

    def to_dict(self) -> dict:
        return {
            "date": self.date,
            "description": self.description,
            "debit": float(self.debit),
            "credit": float(self.credit),
            "balance": float(self.balance),
            "ref_no": self.ref_no,
        }


class BankStatementOCRResult:
    def __init__(self, **kw):
        self.account_no: str = kw.get("account_no", "")
        self.account_name: str = kw.get("account_name", "")
        self.bank_name: str = kw.get("bank_name", "")
        self.period_from: str = kw.get("period_from", "")
        self.period_to: str = kw.get("period_to", "")
        self.opening_balance: Decimal = Decimal(str(kw.get("opening_balance") or 0))
        self.closing_balance: Decimal = Decimal(str(kw.get("closing_balance") or 0))
        self.total_debit: Decimal = Decimal(str(kw.get("total_debit") or 0))
        self.total_credit: Decimal = Decimal(str(kw.get("total_credit") or 0))
        self.transactions: list[BankTransactionOCR] = [
            BankTransactionOCR(**t) for t in (kw.get("transactions") or [])
        ]
        self.confidence: float = float(kw.get("confidence") or 0)
        self.validation_ok: bool = False
        self.validation_diff: Decimal = Decimal(0)

    def to_dict(self) -> dict:
        return {
            "account_no": self.account_no,
            "account_name": self.account_name,
            "bank_name": self.bank_name,
            "period_from": self.period_from,
            "period_to": self.period_to,
            "opening_balance": float(self.opening_balance),
            "closing_balance": float(self.closing_balance),
            "total_debit": float(self.total_debit),
            "total_credit": float(self.total_credit),
            "transactions": [t.to_dict() for t in self.transactions],
            "confidence": self.confidence,
            "validation_ok": self.validation_ok,
            "validation_diff": float(self.validation_diff),
        }


def _parse_json(text: str) -> dict:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError("No JSON found in Claude response")
    return json.loads(match.group())


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


def extract_statement(
    images: list[dict[str, str]],
    bank_name: str | None = None,
    ctx=None,
) -> BankStatementOCRResult:
    """แยกรายการเดินบัญชีจาก bank statement images."""
    bank_hint = ""
    if bank_name:
        key = bank_name.lower().strip()
        for k, hint in _BANK_HINTS.items():
            if k in key:
                bank_hint = f"\nคำแนะนำสำหรับ {bank_name}:\n{hint}\n"
                break

    prompt = f"""อ่านใบแสดงรายการเดินบัญชีธนาคาร (Bank Statement) ในภาพ
และแยกข้อมูลทุกรายการเป็น JSON ตามโครงสร้างนี้:
{_STATEMENT_SCHEMA}
{bank_hint}
กฎสำคัญ:
- date ต้องเป็น YYYY-MM-DD เสมอ
- debit = เงินออก/ถอน (ลดยอด), credit = เงินเข้า/ฝาก (เพิ่มยอด)
- ต้องแยกทุกรายการในเอกสาร ไม่ข้ามรายการ
- total_debit และ total_credit ให้รวมจากรายการ
- ถ้าอ่านไม่ได้ให้ใส่ null หรือ 0
- ตอบเฉพาะ JSON เท่านั้น"""

    msg = _get_client().messages.create(
        model=settings.OCR_MODEL,
        max_tokens=settings.OCR_MAX_TOKENS,
        messages=[{"role": "user", "content": _build_content(images, prompt)}],
    )
    data = _parse_json(msg.content[0].text)
    result = BankStatementOCRResult(**data)
    validate_statement(result)
    return result


def validate_statement(result: BankStatementOCRResult) -> BankStatementOCRResult:
    """ตรวจว่า opening_balance + credit - debit == closing_balance."""
    computed = result.opening_balance + result.total_credit - result.total_debit
    diff = abs(computed - result.closing_balance)

    # คำนวณ total_debit/credit จากรายการจริงถ้า server ไม่ได้ส่งมา
    if result.total_debit == 0 and result.total_credit == 0 and result.transactions:
        result.total_debit = sum(t.debit for t in result.transactions)
        result.total_credit = sum(t.credit for t in result.transactions)
        computed = result.opening_balance + result.total_credit - result.total_debit
        diff = abs(computed - result.closing_balance)

    result.validation_diff = diff
    result.validation_ok = diff < Decimal("0.01")
    return result
