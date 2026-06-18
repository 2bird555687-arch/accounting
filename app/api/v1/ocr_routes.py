"""OCR API Routes — upload, confirm, history."""

from __future__ import annotations

import json
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, UploadFile, File

from app.api.deps import CTX, CompanyDB
from app.ocr import classifier, extractor
from app.ocr.models import OCRHistory
from app.ocr.reader import read_file
from app.ocr.schemas import (
    ContactSuggestion,
    OCRConfirmIn,
    OCRConfirmResponse,
    OCRHistoryOut,
    OCRUploadResponse,
)

router = APIRouter(prefix="/ocr", tags=["OCR"])


@router.post("/upload", response_model=OCRUploadResponse, status_code=201)
async def upload_document(
    ctx: CTX,
    db: CompanyDB,
    file: UploadFile = File(...),
    document_type: Optional[str] = Query(None, description="invoice|receipt|wht — ถ้าไม่ระบุจะ detect อัตโนมัติ"),
):
    """อัปโหลดเอกสาร → OCR → จับคู่ contact → แนะนำ COA."""
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="ไฟล์ว่างเปล่า")

    filename = file.filename or ""
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else None

    try:
        images = read_file(raw) if ext is None else read_file(raw)
    except (ImportError, ValueError) as e:
        raise HTTPException(status_code=422, detail=str(e))

    # ── Extract with Claude Vision ───────────────────────────────────────────
    try:
        result = extractor.auto_extract(images, hint=document_type)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"OCR failed: {e}")

    # ── Contact matching ─────────────────────────────────────────────────────
    contact = await classifier.match_contact(result.vendor_name, result.vendor_tax_id, ctx, db)
    contact_suggestion = ContactSuggestion(
        contact_id=contact.id if contact else None,
        name=contact.name if contact else None,
        tax_id=contact.tax_id if contact else None,
        matched=contact is not None,
    )

    # ── COA suggestion ───────────────────────────────────────────────────────
    description = (result.line_items[0].description if result.line_items else None)
    suggested_coa = classifier.suggest_coa(description) or await classifier.get_learned_coa(
        result.vendor_name, ctx, db
    )

    # ── Save OCR history ─────────────────────────────────────────────────────
    history = OCRHistory(
        company_id=ctx.company_id,
        branch_id=ctx.branch_id,
        document_type=result.document_type,
        original_filename=filename,
        extracted_json=json.dumps(result.model_dump(), default=str),
        overall_confidence=result.confidence,
        contact_id=contact.id if contact else None,
        created_by=ctx.user_id,
        status="extracted",
    )
    db.add(history)
    await db.flush()
    history_id = history.id

    return OCRUploadResponse(
        ocr_history_id=history_id,
        document_type=result.document_type,
        result=result,
        contact_suggestion=contact_suggestion,
        suggested_account_code=suggested_coa,
        low_confidence_fields=result.low_confidence_fields,
    )


@router.post("/confirm", response_model=OCRConfirmResponse)
async def confirm_document(data: OCRConfirmIn, ctx: CTX, db: CompanyDB):
    """ยืนยันข้อมูล OCR และบันทึกรายการ journal entry."""
    from sqlalchemy import select
    from app.core.engine import PostingEngine, JournalEntryInput, JournalLineInput
    from app.context import DrCr, JournalType

    history = await db.scalar(
        select(OCRHistory).where(
            OCRHistory.id == data.ocr_history_id,
            OCRHistory.company_id == ctx.company_id,
        )
    )
    if not history:
        raise HTTPException(status_code=404, detail="ไม่พบประวัติ OCR")
    if history.status == "posted":
        raise HTTPException(status_code=400, detail="บันทึกรายการนี้แล้ว")

    if not ctx.can_post:
        raise HTTPException(status_code=403, detail="ไม่มีสิทธิ์บันทึกรายการ")

    # ── Build journal lines ──────────────────────────────────────────────────
    account_code = data.account_code or "6999"  # misc expense fallback
    ap_code = "2101"  # AP trade
    vat_code = "1151"  # VAT input

    total = float(data.total or 0)
    subtotal = float(data.subtotal or total)
    vat = float(data.vat_amount or 0)
    wht = float(data.wht_amount or 0)

    lines: list[JournalLineInput] = [
        JournalLineInput(account_code=account_code, side=DrCr.DR, amount=subtotal),
    ]
    if vat > 0:
        lines.append(JournalLineInput(account_code=vat_code, side=DrCr.DR, amount=vat))
    if wht > 0:
        lines.append(JournalLineInput(account_code="2102", side=DrCr.CR, amount=wht))

    net_ap = total - wht
    lines.append(JournalLineInput(account_code=ap_code, side=DrCr.CR, amount=net_ap))

    from datetime import date
    try:
        doc_date = date.fromisoformat(data.doc_date)
    except (ValueError, TypeError):
        doc_date = ctx.period

    entry = JournalEntryInput(
        journal_type=JournalType.GJ,
        entry_date=doc_date,
        description=f"OCR {data.document_type} {data.doc_number or ''} {data.vendor_name or ''}".strip(),
        lines=lines,
        source_module="ocr",
        source_id=data.ocr_history_id,
    )

    try:
        journal_no = await PostingEngine(db).post(entry, ctx)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    # ── Update history ───────────────────────────────────────────────────────
    history.status = "posted"
    history.journal_no = journal_no
    history.contact_id = data.contact_id

    # ── Save learned mapping ─────────────────────────────────────────────────
    if data.vendor_name:
        await classifier.save_mapping(data.vendor_name, data.contact_id, data.account_code, ctx, db)

    return OCRConfirmResponse(ocr_history_id=data.ocr_history_id, journal_no=journal_no)


@router.get("/history", response_model=list[OCRHistoryOut])
async def get_history(
    ctx: CTX,
    db: CompanyDB,
    document_type: Optional[str] = None,
    status: Optional[str] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, le=200),
):
    """ดูประวัติการ OCR ของบริษัท."""
    from sqlalchemy import select
    stmt = (
        select(OCRHistory)
        .where(OCRHistory.company_id == ctx.company_id)
        .order_by(OCRHistory.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    if document_type:
        stmt = stmt.where(OCRHistory.document_type == document_type)
    if status:
        stmt = stmt.where(OCRHistory.status == status)

    rows = await db.scalars(stmt)
    return [OCRHistoryOut.model_validate(r) for r in rows]
