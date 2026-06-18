"""Journal routes — สมุดรายวัน, reverse, audit trail."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel

from app.api.deps import CTX, CompanyDB
from app.api.responses import ok, paginated
from app.context import JournalType
from app.core.editor import (
    AlreadyReversedError,
    EditorError,
    EditorService,
    EntryNotFoundError,
)
from app.core.engine import (
    JournalEntryInput,
    JournalLineInput,
    PostingEngine,
    ClosedPeriodError,
    ImbalancedEntryError,
    InvalidEntryError,
    AccountNotFoundError,
    PermissionError as PostingPermissionError,
    VATInfo,
    WHTInfo,
)
from app.core.journals import JournalEntryResult, JournalFilter, JournalService

router = APIRouter(prefix="/journals", tags=["Journals"])


# ── Request schemas ───────────────────────────────────────────────────────────

class JournalLineIn(BaseModel):
    account_code: str
    side: str           # DR / CR
    amount: Decimal
    description: Optional[str] = None
    tax_rate: Optional[Decimal] = None
    tax_base_amount: Optional[Decimal] = None
    cost_center: Optional[str] = None


class VATInfoIn(BaseModel):
    tax_base: Decimal
    vat_rate: Decimal = Decimal("7")
    input_tax: bool = True


class WHTInfoIn(BaseModel):
    base_amount: Decimal
    wht_rate: Decimal
    wht_type: str
    is_payer: bool = True
    payee_tax_id: Optional[str] = None


class PostJournalIn(BaseModel):
    journal_type: str       # GJ / PJ / SJ / CP / CR
    entry_date: date
    description: str
    lines: list[JournalLineIn]
    reference: Optional[str] = None
    source_module: Optional[str] = None
    source_id: Optional[int] = None
    vat_info: Optional[VATInfoIn] = None
    auto_vat: bool = False
    wht_info: Optional[WHTInfoIn] = None


class ReverseIn(BaseModel):
    reason: str
    reverse_date: Optional[date] = None


# ── Response schemas ──────────────────────────────────────────────────────────

class JournalLineOut(BaseModel):
    line_no: int
    account_code: str
    account_name: str
    description: Optional[str]
    debit_amount: Decimal
    credit_amount: Decimal
    tax_rate: Optional[Decimal]
    tax_base_amount: Optional[Decimal]
    cost_center: Optional[str]


class JournalEntryOut(BaseModel):
    id: int
    entry_no: str
    journal_type: str
    entry_date: date
    description: str
    reference: Optional[str]
    status: str
    is_reversing: bool
    reversed_entry_id: Optional[int]
    source_module: Optional[str]
    branch_id: int
    user_id: int
    period_fiscal_year: int
    period_month: int
    total_debit: Decimal
    total_credit: Decimal
    lines: list[JournalLineOut]


def _to_entry_out(r: JournalEntryResult) -> JournalEntryOut:
    return JournalEntryOut(
        id=r.id,
        entry_no=r.entry_no,
        journal_type=r.journal_type,
        entry_date=r.entry_date,
        description=r.description,
        reference=r.reference,
        status=r.status,
        is_reversing=r.is_reversing,
        reversed_entry_id=r.reversed_entry_id,
        source_module=r.source_module,
        branch_id=r.branch_id,
        user_id=r.user_id,
        period_fiscal_year=r.period_fiscal_year,
        period_month=r.period_month,
        total_debit=r.total_debit,
        total_credit=r.total_credit,
        lines=[JournalLineOut(**ln.__dict__) for ln in r.lines],
    )


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("", response_model=dict, summary="ค้นหารายการสมุดรายวัน")
async def search_journals(
    ctx: CTX,
    company_db: CompanyDB,
    journal_type: Optional[str] = Query(None, description="GJ/PJ/SJ/CP/CR"),
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    status: Optional[str] = Query(None, description="draft/posted/reversed"),
    reference: Optional[str] = Query(None),
    account_code: Optional[str] = Query(None, description="กรองตามรหัสบัญชี"),
    search: Optional[str] = Query(None, description="ค้นหาใน description"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
) -> dict:
    """
    ค้นหารายการสมุดรายวัน พร้อม filter หลายแบบ

    - `journal_type`: GJ, PJ, SJ, CP, CR
    - `account_code`: แสดงเฉพาะ entry ที่มีบัญชีนี้
    - `search`: ค้นหาใน description
    """
    jt = None
    if journal_type:
        try:
            jt = JournalType(journal_type.upper())
        except ValueError:
            raise HTTPException(400, f"journal_type ไม่ถูกต้อง: {journal_type}")

    filters = JournalFilter(
        journal_type=jt,
        date_from=date_from,
        date_to=date_to,
        status=status,
        reference=reference,
        account_code=account_code,
        description_contains=search,
        limit=page_size,
        offset=(page - 1) * page_size,
    )

    svc = JournalService(company_db)
    entries = await svc.search(ctx, filters)
    total = await svc.count(ctx, filters)

    return paginated(
        data=[_to_entry_out(e) for e in entries],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{ref}", response_model=dict, summary="ดูรายการด้วยเลขที่")
async def get_journal(ref: str, ctx: CTX, company_db: CompanyDB) -> dict:
    """ดูรายการสมุดรายวันด้วยเลขที่ เช่น GJ202601-0001."""
    svc = JournalService(company_db)
    entry = await svc.get_by_ref(ref, ctx)
    if entry is None:
        raise HTTPException(404, f"ไม่พบรายการ {ref!r}")
    return ok(_to_entry_out(entry))


@router.post(
    "",
    response_model=dict,
    status_code=status.HTTP_201_CREATED,
    summary="บันทึกรายการบัญชี (ผ่าน PostingEngine)",
)
async def post_journal(data: PostJournalIn, ctx: CTX, company_db: CompanyDB) -> dict:
    """
    บันทึกรายการบัญชีผ่าน PostingEngine

    - ตรวจ Dr == Cr อัตโนมัติ
    - ตรวจงวดเปิด/ปิด
    - สร้างเลขที่รายการอัตโนมัติ
    - เพิ่ม VAT/WHT line อัตโนมัติถ้าระบุ
    """
    # แปลง input
    try:
        jt = JournalType(data.journal_type.upper())
    except ValueError:
        raise HTTPException(400, f"journal_type ไม่ถูกต้อง: {data.journal_type}")

    from app.context import DrCr

    lines = []
    for ln in data.lines:
        try:
            side = DrCr(ln.side.upper())
        except ValueError:
            raise HTTPException(400, f"side ต้องเป็น DR หรือ CR ได้รับ: {ln.side!r}")
        lines.append(JournalLineInput(
            account_code=ln.account_code,
            side=side,
            amount=ln.amount,
            description=ln.description,
            tax_rate=ln.tax_rate,
            tax_base_amount=ln.tax_base_amount,
            cost_center=ln.cost_center,
        ))

    vat_info = None
    if data.vat_info:
        vat_info = VATInfo(
            tax_base=data.vat_info.tax_base,
            vat_rate=data.vat_info.vat_rate,
            input_tax=data.vat_info.input_tax,
        )

    wht_info = None
    if data.wht_info:
        wht_info = WHTInfo(
            base_amount=data.wht_info.base_amount,
            wht_rate=data.wht_info.wht_rate,
            wht_type=data.wht_info.wht_type,
            is_payer=data.wht_info.is_payer,
            payee_tax_id=data.wht_info.payee_tax_id,
        )

    entry_input = JournalEntryInput(
        journal_type=jt,
        entry_date=data.entry_date,
        description=data.description,
        lines=lines,
        reference=data.reference,
        source_module=data.source_module,
        source_id=data.source_id,
        vat_info=vat_info,
        auto_vat=data.auto_vat,
        wht_info=wht_info,
    )

    try:
        engine = PostingEngine(company_db)
        entry_no = await engine.post(entry_input, ctx)
    except PostingPermissionError as e:
        raise HTTPException(403, str(e))
    except ClosedPeriodError as e:
        raise HTTPException(409, str(e))
    except ImbalancedEntryError as e:
        raise HTTPException(422, str(e))
    except AccountNotFoundError as e:
        raise HTTPException(404, str(e))
    except InvalidEntryError as e:
        raise HTTPException(400, str(e))

    svc = JournalService(company_db)
    entry = await svc.get_by_ref(entry_no, ctx)
    return ok(_to_entry_out(entry), f"บันทึกรายการสำเร็จ: {entry_no}")


@router.post("/{ref}/reverse", response_model=dict, summary="กลับรายการ (Reversing Entry)")
async def reverse_journal(
    ref: str,
    data: ReverseIn,
    ctx: CTX,
    company_db: CompanyDB,
) -> dict:
    """
    กลับรายการบัญชี — สร้าง Reversing Entry ใหม่

    - ต้องมีสิทธิ์ approve (accountant ขึ้นไป)
    - คืนเลขที่รายการใหม่ที่สร้างขึ้น
    """
    editor = EditorService(company_db)
    try:
        new_ref = await editor.reverse(ref, data.reason, ctx, reverse_date=data.reverse_date)
    except EntryNotFoundError:
        raise HTTPException(404, f"ไม่พบรายการ {ref!r}")
    except AlreadyReversedError as e:
        raise HTTPException(409, str(e))
    except EditorError as e:
        raise HTTPException(400, str(e))
    except PostingPermissionError as e:
        raise HTTPException(403, str(e))

    svc = JournalService(company_db)
    new_entry = await svc.get_by_ref(new_ref, ctx)
    return ok(
        {"original_ref": ref, "reversing_ref": new_ref, "entry": _to_entry_out(new_entry)},
        f"กลับรายการสำเร็จ → {new_ref}",
    )


@router.patch("/{ref}/meta", response_model=dict, summary="แก้ไข meta fields")
async def edit_journal_meta(
    ref: str,
    fields: dict[str, str],
    ctx: CTX,
    company_db: CompanyDB,
) -> dict:
    """
    แก้ไข non-accounting fields (description, reference, ocr_ref)

    ห้ามแก้: journal_type, entry_date, lines หรือ accounting fields ใดๆ
    """
    editor = EditorService(company_db)
    try:
        result = await editor.edit_meta(ref, fields, ctx)
    except EntryNotFoundError:
        raise HTTPException(404, f"ไม่พบรายการ {ref!r}")
    except Exception as e:
        raise HTTPException(400, str(e))
    return ok(_to_entry_out(result), "แก้ไขสำเร็จ")


@router.get("/{ref}/audit-trail", response_model=dict, summary="ประวัติการแก้ไข")
async def get_audit_trail(ref: str, ctx: CTX, company_db: CompanyDB) -> dict:
    """ดู audit trail ทั้งหมดของรายการ."""
    editor = EditorService(company_db)
    trail = await editor.get_audit_trail(ref, ctx)
    return ok(trail)


@router.delete(
    "/{ref}/void",
    response_model=dict,
    summary="ยกเลิก draft entry",
)
async def void_draft(
    ref: str,
    reason: str,
    ctx: CTX,
    company_db: CompanyDB,
) -> dict:
    """ยกเลิก draft entry ที่ยังไม่ได้ post (ไม่ต้องสร้าง reversing entry)."""
    editor = EditorService(company_db)
    try:
        await editor.void_draft(ref, reason, ctx)
    except EntryNotFoundError:
        raise HTTPException(404, f"ไม่พบรายการ {ref!r}")
    except EditorError as e:
        raise HTTPException(400, str(e))
    except PostingPermissionError as e:
        raise HTTPException(403, str(e))
    return ok(None, f"ยกเลิก {ref} สำเร็จ")
