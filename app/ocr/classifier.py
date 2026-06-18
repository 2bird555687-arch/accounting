"""OCR Classifier — จับคู่ contact และแนะนำ COA account code."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.context import AppContext
from app.modules.ar.models import Contact
from app.ocr.models import OCRMapping


# keyword → account_code สำหรับ expense classification
KEYWORD_RULES: dict[str, str] = {
    "ค่าเช่า": "6502",
    "ดอกเบี้ย": "7101",
    "ไฟฟ้า": "6503",
    "น้ำประปา": "6503",
    "โทรศัพท์": "6504",
    "อินเตอร์เน็ต": "6504",
    "ค่าขนส่ง": "6505",
    "ค่าน้ำมัน": "6506",
    "ซ่อมแซม": "6507",
    "ประกันภัย": "6508",
    "โฆษณา": "6509",
    "ค่าจ้าง": "5101",
    "เงินเดือน": "5101",
    "วัตถุดิบ": "5001",
    "สินค้า": "5001",
    "เครื่องเขียน": "6510",
    "อุปกรณ์": "6510",
}


async def match_contact(
    vendor_name: str | None,
    tax_id: str | None,
    ctx: AppContext,
    db: AsyncSession,
) -> Contact | None:
    """ค้นหา Contact ที่ตรงกับ vendor_name หรือ tax_id."""
    if not vendor_name and not tax_id:
        return None

    if tax_id:
        result = await db.scalar(
            select(Contact).where(
                Contact.company_id == ctx.company_id,
                Contact.tax_id == tax_id,
            )
        )
        if result:
            return result

    if vendor_name:
        # ลอง exact match ก่อน
        result = await db.scalar(
            select(Contact).where(
                Contact.company_id == ctx.company_id,
                Contact.name.ilike(vendor_name),
            )
        )
        if result:
            return result

        # ลอง learned mapping
        mapping = await db.scalar(
            select(OCRMapping).where(
                OCRMapping.company_id == ctx.company_id,
                OCRMapping.raw_vendor_name == vendor_name,
                OCRMapping.contact_id.isnot(None),
            )
        )
        if mapping and mapping.contact_id:
            contact = await db.scalar(
                select(Contact).where(Contact.id == mapping.contact_id)
            )
            return contact

    return None


def suggest_coa(description: str | None, amount: float | None = None) -> str | None:
    """แนะนำ account_code จาก description โดยใช้ keyword rules."""
    if not description:
        return None
    desc_lower = description.lower()
    for keyword, code in KEYWORD_RULES.items():
        if keyword in description or keyword.lower() in desc_lower:
            return code
    return None


async def get_learned_coa(
    vendor_name: str | None,
    ctx: AppContext,
    db: AsyncSession,
) -> str | None:
    """ดึง account_code จาก learned mapping."""
    if not vendor_name:
        return None
    mapping = await db.scalar(
        select(OCRMapping).where(
            OCRMapping.company_id == ctx.company_id,
            OCRMapping.raw_vendor_name == vendor_name,
            OCRMapping.account_code.isnot(None),
        )
    )
    return mapping.account_code if mapping else None


async def save_mapping(
    raw_name: str,
    contact_id: int | None,
    account_code: str | None,
    ctx: AppContext,
    db: AsyncSession,
) -> None:
    """บันทึกหรืออัปเดต OCR mapping สำหรับ vendor."""
    existing = await db.scalar(
        select(OCRMapping).where(
            OCRMapping.company_id == ctx.company_id,
            OCRMapping.raw_vendor_name == raw_name,
        )
    )
    if existing:
        existing.contact_id = contact_id
        existing.account_code = account_code
        existing.hit_count = (existing.hit_count or 0) + 1
        existing.updated_at = datetime.utcnow()
    else:
        db.add(OCRMapping(
            company_id=ctx.company_id,
            raw_vendor_name=raw_name,
            contact_id=contact_id,
            account_code=account_code,
        ))
