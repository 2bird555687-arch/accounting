"""AR Routes — Contact, Invoice, Receipt, e-Tax, Billing Notes, Quotations."""

from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Response, status

from app.api.deps import CTX, CompanyDB
from app.api.responses import ok, paginated
from app.modules.ar.billing_note_service import BillingNoteCreate, BillingNoteService
from app.modules.ar.etax_service import ETaxService, SellerInfo
from app.modules.ar.quotation_service import QuotationCreate, QuotationService
from app.modules.ar.receipt_service import ReceiptService
from app.modules.ar.sales_service import InvoiceService
from app.modules.ar.schemas import (
    CancelInvoiceIn,
    ContactCreate,
    ContactOut,
    ContactUpdate,
    ETaxValidationResult,
    InvoiceCreate,
    InvoiceDetail,
    InvoiceFilter,
    InvoiceOut,
    ReceiptCreate,
    ReceiptFilter,
    ReceiptOut,
)

router = APIRouter(prefix="/ar", tags=["AR - ลูกหนี้การค้า"])


# ══════════════════════════════════════════════════════════════════════════════
# CONTACTS
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/contacts", response_model=dict, summary="รายการผู้ติดต่อ")
async def list_contacts(
    ctx: CTX,
    company_db: CompanyDB,
    contact_type: Optional[str] = Query(None, description="customer / supplier / both"),
    active_only: bool = Query(True),
) -> dict:
    """ดึงรายการ Contact ของ company."""
    svc = InvoiceService(company_db)
    contacts = await svc.list_contacts(ctx, contact_type=contact_type, active_only=active_only)
    return ok([ContactOut.model_validate(c) for c in contacts])


@router.post(
    "/contacts",
    response_model=dict,
    status_code=status.HTTP_201_CREATED,
    summary="สร้างผู้ติดต่อใหม่",
)
async def create_contact(data: ContactCreate, ctx: CTX, company_db: CompanyDB) -> dict:
    """สร้าง Contact ใหม่ (ลูกค้า / เจ้าหนี้)."""
    if not ctx.can_approve:
        raise HTTPException(403, "ต้องเป็น accountant ขึ้นไปเพื่อสร้าง contact")
    svc = InvoiceService(company_db)
    contact = await svc.create_contact(data, ctx)
    return ok(ContactOut.model_validate(contact), "สร้าง contact สำเร็จ")


@router.get("/contacts/{contact_id}", response_model=dict, summary="ข้อมูลผู้ติดต่อ")
async def get_contact(contact_id: int, ctx: CTX, company_db: CompanyDB) -> dict:
    svc = InvoiceService(company_db)
    contact = await svc.get_contact(contact_id, ctx)
    return ok(ContactOut.model_validate(contact))


@router.put("/contacts/{contact_id}", response_model=dict, summary="แก้ไขผู้ติดต่อ")
async def update_contact(
    contact_id: int,
    data: ContactUpdate,
    ctx: CTX,
    company_db: CompanyDB,
) -> dict:
    if not ctx.can_approve:
        raise HTTPException(403, "ต้องเป็น accountant ขึ้นไปเพื่อแก้ไข contact")
    svc = InvoiceService(company_db)
    contact = await svc.update_contact(contact_id, data, ctx)
    return ok(ContactOut.model_validate(contact), "แก้ไขสำเร็จ")


# ══════════════════════════════════════════════════════════════════════════════
# INVOICES
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/invoices", response_model=dict, summary="รายการ Invoice")
async def list_invoices(
    ctx: CTX,
    company_db: CompanyDB,
    contact_id: Optional[int] = Query(None),
    status_: Optional[str] = Query(None, alias="status",
                                    description="draft/posted/partially_paid/paid/cancelled"),
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    overdue_only: bool = Query(False, description="แสดงเฉพาะค้างชำระเกินกำหนด"),
    search: Optional[str] = Query(None, description="ค้นหา invoice_no หรือชื่อลูกค้า"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
) -> dict:
    """
    รายการ Invoice ลูกหนี้การค้า พร้อม filter หลายแบบ.

    ใช้ `overdue_only=true` เพื่อดู invoice ค้างชำระเกินกำหนด
    """
    filters = InvoiceFilter(
        contact_id=contact_id,
        status=status_,
        date_from=date_from,
        date_to=date_to,
        overdue_only=overdue_only,
        search=search,
        limit=page_size,
        offset=(page - 1) * page_size,
    )
    svc = InvoiceService(company_db)
    invoices, total = await svc.list_invoices(ctx, filters)
    return paginated(data=invoices, total=total, page=page, page_size=page_size)


@router.post(
    "/invoices",
    response_model=dict,
    status_code=status.HTTP_201_CREATED,
    summary="สร้าง Invoice (SJ)",
)
async def create_invoice(data: InvoiceCreate, ctx: CTX, company_db: CompanyDB) -> dict:
    """
    สร้าง Invoice และ post รายการบัญชี (SJ) อัตโนมัติ.

    Journal:
    - Dr 1110 ลูกหนี้การค้า
    - Cr [revenue account] + Cr 2120 ภาษีขาย
    """
    svc = InvoiceService(company_db)
    detail = await svc.create_invoice(data, ctx)
    return ok(detail, f"สร้าง Invoice {detail.invoice_no} สำเร็จ")


@router.get("/invoices/{invoice_id}", response_model=dict, summary="ข้อมูล Invoice")
async def get_invoice(invoice_id: int, ctx: CTX, company_db: CompanyDB) -> dict:
    """ดู Invoice detail พร้อม lines."""
    svc = InvoiceService(company_db)
    detail = await svc.get_invoice(invoice_id, ctx)
    return ok(detail)


@router.post(
    "/invoices/{invoice_id}/cancel",
    response_model=dict,
    summary="ยกเลิก Invoice (Reversing Entry)",
)
async def cancel_invoice(
    invoice_id: int,
    data: CancelInvoiceIn,
    ctx: CTX,
    company_db: CompanyDB,
) -> dict:
    """
    ยกเลิก Invoice โดยสร้าง Reversing Entry อัตโนมัติ.

    - ต้องมีสิทธิ์ accountant ขึ้นไป
    - ไม่สามารถยกเลิก invoice ที่ชำระแล้วหรือที่มีการรับชำระบางส่วน
    """
    svc = InvoiceService(company_db)
    rev_no = await svc.cancel_invoice(invoice_id, data.reason, ctx)
    return ok({"reversing_entry_no": rev_no}, f"ยกเลิก invoice สำเร็จ → {rev_no}")


# ══════════════════════════════════════════════════════════════════════════════
# RECEIPTS
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/receipts", response_model=dict, summary="รายการใบรับเงิน")
async def list_receipts(
    ctx: CTX,
    company_db: CompanyDB,
    contact_id: Optional[int] = Query(None),
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    search: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
) -> dict:
    """รายการใบรับเงินจากลูกค้า."""
    filters = ReceiptFilter(
        contact_id=contact_id,
        date_from=date_from,
        date_to=date_to,
        search=search,
        limit=page_size,
        offset=(page - 1) * page_size,
    )
    svc = ReceiptService(company_db)
    receipts, total = await svc.list_receipts(ctx, filters)
    return paginated(data=receipts, total=total, page=page, page_size=page_size)


@router.post(
    "/receipts",
    response_model=dict,
    status_code=status.HTTP_201_CREATED,
    summary="บันทึกรับชำระหนี้ (CR)",
)
async def create_receipt(data: ReceiptCreate, ctx: CTX, company_db: CompanyDB) -> dict:
    """
    บันทึกการรับชำระหนี้จากลูกค้า.

    Journal:
    - Dr 1102 ธนาคาร (เงินที่ได้รับจริง)
    - Dr 1141 WHT ถูกหัก (ถ้ามี)
    - Cr 1110 ลูกหนี้การค้า

    ระบุ `allocations` เพื่อ match กับ invoice ที่ค้างอยู่
    """
    svc = ReceiptService(company_db)
    receipt = await svc.create_receipt(data, ctx)
    return ok(receipt, f"บันทึกรับชำระสำเร็จ {receipt.receipt_no}")


# ══════════════════════════════════════════════════════════════════════════════
# E-TAX
# ══════════════════════════════════════════════════════════════════════════════

@router.get(
    "/invoices/{invoice_id}/etax.xml",
    summary="ดาวน์โหลด e-Tax Invoice XML",
    response_class=Response,
)
async def download_etax_xml(
    invoice_id: int,
    ctx: CTX,
    company_db: CompanyDB,
    seller_tax_id: Optional[str] = Query(None, description="TaxID ผู้ขาย 13 หลัก"),
    seller_name: Optional[str] = Query(None, description="ชื่อกิจการ"),
    seller_address: Optional[str] = Query(None, description="ที่อยู่กิจการ"),
    seller_branch: str = Query("00000", description="รหัสสาขา"),
) -> Response:
    """
    สร้างและดาวน์โหลด e-Tax Invoice XML (UBL 2.1 ตาม RD Thailand).

    ถ้าไม่ระบุข้อมูลผู้ขาย จะใช้ค่า placeholder (กรุณาตั้งค่า company profile)
    """
    seller = None
    if seller_tax_id and seller_name:
        seller = SellerInfo(
            tax_id=seller_tax_id,
            branch_code=seller_branch,
            name=seller_name,
            address_line=seller_address or "",
        )

    svc = ETaxService(company_db)
    xml_str = await svc.generate_etax_xml(invoice_id, ctx, seller=seller)

    # ดึง invoice_no สำหรับ filename
    from app.modules.ar.models import ARInvoice
    from sqlalchemy import select
    result = await company_db.execute(
        select(ARInvoice.invoice_no).where(
            ARInvoice.id == invoice_id,
            ARInvoice.company_id == ctx.company_id,
        )
    )
    invoice_no = result.scalar_one_or_none() or str(invoice_id)

    filename = f"etax_{invoice_no.replace('/', '-')}.xml"
    return Response(
        content=xml_str,
        media_type="application/xml",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post(
    "/etax/validate",
    response_model=ETaxValidationResult,
    summary="ตรวจสอบ e-Tax XML",
)
async def validate_etax(
    xml_content: str,
    ctx: CTX,
    company_db: CompanyDB,
) -> ETaxValidationResult:
    """ตรวจสอบความถูกต้องของ XML string."""
    svc = ETaxService(company_db)
    return svc.validate_xml(xml_content)


# ══════════════════════════════════════════════════════════════════════════════
# AR SUMMARY / AGING
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/aging", response_model=dict, summary="ตารางอายุหนี้ (AR Aging)")
async def ar_aging(
    ctx: CTX,
    company_db: CompanyDB,
    as_of_date: Optional[date] = Query(None, description="ณ วันที่ (default: วันนี้)"),
    contact_id: Optional[int] = Query(None),
) -> dict:
    """
    ตาราง AR Aging แบ่งตาม:
    - ยังไม่ครบกำหนด
    - ค้างชำระ 1-30 วัน
    - ค้างชำระ 31-60 วัน
    - ค้างชำระ 61-90 วัน
    - ค้างชำระ > 90 วัน
    """
    from datetime import date as date_type, timedelta
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload
    from app.modules.ar.models import ARInvoice, Contact

    today = as_of_date or date_type.today()

    stmt = (
        select(ARInvoice)
        .where(
            ARInvoice.company_id == ctx.company_id,
            ARInvoice.status.in_(["posted", "partially_paid"]),
        )
        .options(selectinload(ARInvoice.contact))
    )
    if contact_id:
        stmt = stmt.where(ARInvoice.contact_id == contact_id)

    rows = (await company_db.execute(stmt)).scalars().all()

    buckets = {
        "current": [],
        "1_30": [],
        "31_60": [],
        "61_90": [],
        "over_90": [],
    }

    for inv in rows:
        days_overdue = (today - inv.due_date).days
        item = {
            "invoice_id": inv.id,
            "invoice_no": inv.invoice_no,
            "contact_name": inv.contact.name if inv.contact else "",
            "invoice_date": inv.invoice_date.isoformat(),
            "due_date": inv.due_date.isoformat(),
            "balance": float(inv.balance),
            "days_overdue": max(days_overdue, 0),
        }

        if days_overdue <= 0:
            buckets["current"].append(item)
        elif days_overdue <= 30:
            buckets["1_30"].append(item)
        elif days_overdue <= 60:
            buckets["31_60"].append(item)
        elif days_overdue <= 90:
            buckets["61_90"].append(item)
        else:
            buckets["over_90"].append(item)

    def _total(items: list) -> float:
        return sum(i["balance"] for i in items)

    summary = {
        "as_of_date": today.isoformat(),
        "buckets": {
            "current": {"items": buckets["current"], "total": _total(buckets["current"])},
            "1_30_days": {"items": buckets["1_30"], "total": _total(buckets["1_30"])},
            "31_60_days": {"items": buckets["31_60"], "total": _total(buckets["31_60"])},
            "61_90_days": {"items": buckets["61_90"], "total": _total(buckets["61_90"])},
            "over_90_days": {"items": buckets["over_90"], "total": _total(buckets["over_90"])},
        },
        "grand_total": _total([i for lst in buckets.values() for i in lst]),
    }

    return ok(summary)


# ══════════════════════════════════════════════════════════════════════════════
# BILLING NOTES
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/billing-notes", response_model=dict, summary="รายการใบวางบิล")
async def list_billing_notes(
    ctx: CTX,
    company_db: CompanyDB,
    contact_id: Optional[int] = Query(None),
    status_: Optional[str] = Query(None, alias="status", description="draft/sent/cancelled"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
) -> dict:
    """รายการใบวางบิลทั้งหมด."""
    svc = BillingNoteService(company_db)
    items, total = await svc.list_billing_notes(
        ctx, contact_id=contact_id, status=status_, page=page, page_size=page_size
    )
    return paginated(data=items, total=total, page=page, page_size=page_size)


@router.post(
    "/billing-notes",
    response_model=dict,
    status_code=status.HTTP_201_CREATED,
    summary="สร้างใบวางบิล",
)
async def create_billing_note(data: BillingNoteCreate, ctx: CTX, company_db: CompanyDB) -> dict:
    """
    สร้างใบวางบิลจาก Invoice หลายใบ.

    ใบวางบิลไม่สร้าง Journal Entry — เป็นเอกสารทางการค้าเพื่อเสนอลูกค้า.
    """
    svc = BillingNoteService(company_db)
    bn = await svc.create_billing_note(data, ctx)
    return ok(bn, f"สร้างใบวางบิล {bn.billing_note_no} สำเร็จ")


@router.get("/billing-notes/{bn_id}", response_model=dict, summary="ข้อมูลใบวางบิล")
async def get_billing_note(bn_id: int, ctx: CTX, company_db: CompanyDB) -> dict:
    svc = BillingNoteService(company_db)
    return ok(await svc.get_billing_note(bn_id, ctx))


# ══════════════════════════════════════════════════════════════════════════════
# QUOTATIONS
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/quotations", response_model=dict, summary="รายการใบเสนอราคา")
async def list_quotations(
    ctx: CTX,
    company_db: CompanyDB,
    contact_id: Optional[int] = Query(None),
    status_: Optional[str] = Query(None, alias="status",
                                   description="draft/sent/accepted/rejected/converted/expired"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
) -> dict:
    """รายการใบเสนอราคาทั้งหมด."""
    svc = QuotationService(company_db)
    items, total = await svc.list_quotations(
        ctx, contact_id=contact_id, status=status_, page=page, page_size=page_size
    )
    return paginated(data=items, total=total, page=page, page_size=page_size)


@router.post(
    "/quotations",
    response_model=dict,
    status_code=status.HTTP_201_CREATED,
    summary="สร้างใบเสนอราคา",
)
async def create_quotation(data: QuotationCreate, ctx: CTX, company_db: CompanyDB) -> dict:
    """สร้างใบเสนอราคาใหม่ (ไม่สร้าง Journal Entry)."""
    svc = QuotationService(company_db)
    qt = await svc.create_quotation(data, ctx)
    return ok(qt, f"สร้างใบเสนอราคา {qt.quotation_no} สำเร็จ")


@router.get("/quotations/{quotation_id}", response_model=dict, summary="ข้อมูลใบเสนอราคา")
async def get_quotation(quotation_id: int, ctx: CTX, company_db: CompanyDB) -> dict:
    svc = QuotationService(company_db)
    return ok(await svc.get_quotation(quotation_id, ctx))


@router.post(
    "/quotations/{quotation_id}/convert",
    response_model=dict,
    status_code=status.HTTP_201_CREATED,
    summary="แปลงใบเสนอราคา → Invoice (SJ)",
)
async def convert_quotation(quotation_id: int, ctx: CTX, company_db: CompanyDB) -> dict:
    """
    แปลง Quotation → Invoice พร้อม post Journal Entry (SJ) อัตโนมัติ.

    - Quotation ต้องไม่ใช่สถานะ converted / cancelled
    - คืน Invoice ที่สร้างแล้ว
    """
    svc = QuotationService(company_db)
    invoice = await svc.convert_to_invoice(quotation_id, ctx)
    return ok(invoice, f"แปลงใบเสนอราคาเป็น Invoice {invoice.invoice_no} สำเร็จ")
