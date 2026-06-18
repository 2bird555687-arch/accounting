"""AP Routes — Purchase Order, Purchases, Payments, AP Aging."""

from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, status

from app.api.deps import CTX, CompanyDB
from app.api.responses import ok, paginated
from app.modules.ap.payment_service import PaymentService
from app.modules.ap.purchase_order_service import POService
from app.modules.ap.purchase_service import PurchaseService
from app.modules.ap.schemas import (
    CancelPurchaseIn,
    GRNCreate,
    GRNOut,
    PaymentCreate,
    PaymentFilter,
    PaymentOut,
    POCreate,
    PODetail,
    POFilter,
    POOut,
    PurchaseCreate,
    PurchaseDetail,
    PurchaseFilter,
    PurchaseOut,
)

router = APIRouter(prefix="/ap", tags=["AP - เจ้าหนี้การค้า"])


# ══════════════════════════════════════════════════════════════════════════════
# PURCHASE ORDERS
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/purchase-orders", response_model=dict, summary="รายการใบสั่งซื้อ")
async def list_pos(
    ctx: CTX,
    company_db: CompanyDB,
    contact_id: Optional[int] = Query(None),
    status_: Optional[str] = Query(None, alias="status",
                                   description="draft/approved/goods_received/invoiced/cancelled"),
    purchase_type: Optional[str] = Query(None, description="goods/service/expense"),
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    search: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
) -> dict:
    """รายการ PO พร้อม filter สถานะ / ประเภท / วันที่."""
    filters = POFilter(
        contact_id=contact_id,
        status=status_,
        purchase_type=purchase_type,
        date_from=date_from,
        date_to=date_to,
        search=search,
        limit=page_size,
        offset=(page - 1) * page_size,
    )
    svc = POService(company_db)
    pos, total = await svc.list_pos(ctx, filters)
    return paginated(data=pos, total=total, page=page, page_size=page_size)


@router.post(
    "/purchase-orders",
    response_model=dict,
    status_code=status.HTTP_201_CREATED,
    summary="สร้างใบสั่งซื้อ",
)
async def create_po(data: POCreate, ctx: CTX, company_db: CompanyDB) -> dict:
    """สร้าง PO ใหม่ (status=draft, ยังไม่ post journal)."""
    svc = POService(company_db)
    po = await svc.create_po(data, ctx)
    return ok(po, f"สร้าง PO {po.po_no} สำเร็จ")


@router.get("/purchase-orders/{po_id}", response_model=dict, summary="ข้อมูล PO")
async def get_po(po_id: int, ctx: CTX, company_db: CompanyDB) -> dict:
    svc = POService(company_db)
    return ok(await svc.get_po(po_id, ctx))


@router.post(
    "/purchase-orders/{po_id}/approve",
    response_model=dict,
    summary="อนุมัติ PO",
)
async def approve_po(po_id: int, ctx: CTX, company_db: CompanyDB) -> dict:
    """อนุมัติ PO: draft → approved (ต้องเป็น accountant ขึ้นไป)."""
    svc = POService(company_db)
    po = await svc.approve_po(po_id, ctx)
    return ok(po, f"อนุมัติ PO {po.po_no} สำเร็จ")


@router.post(
    "/purchase-orders/{po_id}/cancel",
    response_model=dict,
    summary="ยกเลิก PO",
)
async def cancel_po(po_id: int, ctx: CTX, company_db: CompanyDB) -> dict:
    """ยกเลิก PO (ได้เฉพาะ draft/approved)."""
    svc = POService(company_db)
    po = await svc.cancel_po(po_id, ctx)
    return ok(po, f"ยกเลิก PO {po.po_no} สำเร็จ")


@router.post(
    "/purchase-orders/{po_id}/convert",
    response_model=dict,
    status_code=status.HTTP_201_CREATED,
    summary="แปลง PO → APPurchase (3-way match)",
)
async def convert_po_to_purchase(
    po_id: int,
    ctx: CTX,
    company_db: CompanyDB,
    supplier_invoice_no: Optional[str] = Query(None, description="เลขที่ใบแจ้งหนี้จาก supplier"),
) -> dict:
    """
    แปลง PO → APPurchase หลังรับสินค้าครบ (3-way match).

    ตรวจ:
    - PO ต้อง status = goods_received
    - ทุก line ต้องมี received_qty > 0
    - สร้าง Journal Entry (PJ) อัตโนมัติ
    """
    svc = POService(company_db)
    purchase = await svc.convert_to_purchase(
        po_id, ctx, supplier_invoice_no=supplier_invoice_no
    )
    return ok(purchase, f"สร้าง Purchase {purchase.purchase_no} จาก PO สำเร็จ")


# ══════════════════════════════════════════════════════════════════════════════
# GOODS RECEIVED NOTES
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/grns", response_model=dict, summary="รายการใบรับสินค้า")
async def list_grns(
    ctx: CTX,
    company_db: CompanyDB,
    po_id: Optional[int] = Query(None, description="กรองตาม PO"),
) -> dict:
    """ดึงรายการ GRN ทั้งหมด / กรองตาม PO."""
    svc = POService(company_db)
    grns = await svc.list_grns(ctx, po_id=po_id)
    return ok(grns)


@router.post(
    "/grns",
    response_model=dict,
    status_code=status.HTTP_201_CREATED,
    summary="บันทึกรับสินค้า (GRN)",
)
async def receive_goods(data: GRNCreate, ctx: CTX, company_db: CompanyDB) -> dict:
    """
    บันทึกการรับสินค้า (Goods Received Note).

    - PO ต้อง status=approved
    - ตรวจ received_qty ไม่เกิน ordered_qty
    - อัปเดต PO status → goods_received
    """
    svc = POService(company_db)
    grn = await svc.receive_goods(data, ctx)
    return ok(grn, f"บันทึกรับสินค้า {grn.grn_no} สำเร็จ")


@router.get("/grns/{grn_id}", response_model=dict, summary="ข้อมูล GRN")
async def get_grn(grn_id: int, ctx: CTX, company_db: CompanyDB) -> dict:
    svc = POService(company_db)
    return ok(await svc.get_grn(grn_id, ctx))


# ══════════════════════════════════════════════════════════════════════════════
# AP PURCHASES (Supplier Invoices)
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/purchases", response_model=dict, summary="รายการใบแจ้งหนี้เจ้าหนี้")
async def list_purchases(
    ctx: CTX,
    company_db: CompanyDB,
    contact_id: Optional[int] = Query(None),
    status_: Optional[str] = Query(None, alias="status"),
    purchase_type: Optional[str] = Query(None),
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    overdue_only: bool = Query(False, description="ค้างชำระเกินกำหนด"),
    po_id: Optional[int] = Query(None),
    search: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
) -> dict:
    """รายการ AP Purchase (ใบแจ้งหนี้จาก supplier)."""
    filters = PurchaseFilter(
        contact_id=contact_id,
        status=status_,
        purchase_type=purchase_type,
        date_from=date_from,
        date_to=date_to,
        overdue_only=overdue_only,
        po_id=po_id,
        search=search,
        limit=page_size,
        offset=(page - 1) * page_size,
    )
    svc = PurchaseService(company_db)
    purchases, total = await svc.list_purchases(ctx, filters)
    return paginated(data=purchases, total=total, page=page, page_size=page_size)


@router.post(
    "/purchases",
    response_model=dict,
    status_code=status.HTTP_201_CREATED,
    summary="บันทึกใบแจ้งหนี้เจ้าหนี้ (PJ)",
)
async def create_purchase(data: PurchaseCreate, ctx: CTX, company_db: CompanyDB) -> dict:
    """
    บันทึก AP Purchase (Supplier Invoice) และ post Journal Entry (PJ).

    Journal:
    - Dr [inventory/expense accounts]
    - Dr 1140 ภาษีซื้อ
    - Cr 2101 เจ้าหนี้การค้า

    สามารถสร้างโดยตรง (ไม่มี PO) หรือผ่าน /purchase-orders/{id}/convert
    """
    svc = PurchaseService(company_db)
    purchase = await svc.create_purchase(data, ctx)
    return ok(purchase, f"บันทึก Purchase {purchase.purchase_no} สำเร็จ")


@router.get("/purchases/{purchase_id}", response_model=dict, summary="ข้อมูล Purchase")
async def get_purchase(purchase_id: int, ctx: CTX, company_db: CompanyDB) -> dict:
    svc = PurchaseService(company_db)
    return ok(await svc.get_purchase(purchase_id, ctx))


@router.post(
    "/purchases/{purchase_id}/cancel",
    response_model=dict,
    summary="ยกเลิก Purchase (Reversing Entry)",
)
async def cancel_purchase(
    purchase_id: int,
    data: CancelPurchaseIn,
    ctx: CTX,
    company_db: CompanyDB,
) -> dict:
    """
    ยกเลิก AP Purchase โดยสร้าง Reversing Entry.

    - ต้องเป็น accountant ขึ้นไป
    - ไม่ยกเลิกได้ถ้ามีการจ่ายแล้ว
    """
    svc = PurchaseService(company_db)
    rev_no = await svc.cancel_purchase(purchase_id, data.reason, ctx)
    return ok({"reversing_entry_no": rev_no}, f"ยกเลิก purchase สำเร็จ → {rev_no}")


# ══════════════════════════════════════════════════════════════════════════════
# AP PAYMENTS
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/payments", response_model=dict, summary="รายการใบสำคัญจ่าย")
async def list_payments(
    ctx: CTX,
    company_db: CompanyDB,
    contact_id: Optional[int] = Query(None),
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    search: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
) -> dict:
    """รายการใบสำคัญจ่าย (Payment Voucher)."""
    filters = PaymentFilter(
        contact_id=contact_id,
        date_from=date_from,
        date_to=date_to,
        search=search,
        limit=page_size,
        offset=(page - 1) * page_size,
    )
    svc = PaymentService(company_db)
    payments, total = await svc.list_payments(ctx, filters)
    return paginated(data=payments, total=total, page=page, page_size=page_size)


@router.post(
    "/payments",
    response_model=dict,
    status_code=status.HTTP_201_CREATED,
    summary="บันทึกจ่ายชำระหนี้ (CP)",
)
async def create_payment(data: PaymentCreate, ctx: CTX, company_db: CompanyDB) -> dict:
    """
    บันทึกการจ่ายชำระหนี้ให้เจ้าหนี้.

    Journal:
    - Dr 2101 เจ้าหนี้การค้า
    - Cr 1102 ธนาคาร (เงินที่จ่ายออกจริง)
    - Cr 2121 WHT ค้างนำส่ง (ถ้ามี)

    ระบุ `allocations` เพื่อ match กับ purchase ที่ค้างอยู่
    """
    svc = PaymentService(company_db)
    payment = await svc.create_payment(data, ctx)
    return ok(payment, f"บันทึกจ่ายสำเร็จ {payment.payment_no}")


# ══════════════════════════════════════════════════════════════════════════════
# AP AGING
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/aging", response_model=dict, summary="ตารางอายุหนี้เจ้าหนี้ (AP Aging)")
async def ap_aging(
    ctx: CTX,
    company_db: CompanyDB,
    as_of_date: Optional[date] = Query(None, description="ณ วันที่ (default: วันนี้)"),
    contact_id: Optional[int] = Query(None),
) -> dict:
    """
    ตาราง AP Aging แบ่งตาม:
    - ยังไม่ครบกำหนด
    - ค้างชำระ 1-30 วัน
    - ค้างชำระ 31-60 วัน
    - ค้างชำระ 61-90 วัน
    - ค้างชำระ > 90 วัน
    """
    from datetime import date as date_type
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload
    from app.modules.ap.models import APPurchase
    from app.modules.ar.models import Contact

    today = as_of_date or date_type.today()

    stmt = (
        select(APPurchase)
        .where(
            APPurchase.company_id == ctx.company_id,
            APPurchase.status.in_(["posted", "partially_paid"]),
        )
        .options(selectinload(APPurchase.lines))
    )
    if contact_id:
        stmt = stmt.where(APPurchase.contact_id == contact_id)

    rows = (await company_db.execute(stmt)).scalars().all()

    # โหลด contact names
    contact_ids = list({r.contact_id for r in rows})
    contacts: dict[int, str] = {}
    if contact_ids:
        c_rows = (await company_db.execute(
            select(Contact).where(Contact.id.in_(contact_ids))
        )).scalars().all()
        contacts = {c.id: c.name for c in c_rows}

    buckets: dict[str, list] = {
        "current": [],
        "1_30": [],
        "31_60": [],
        "61_90": [],
        "over_90": [],
    }

    for pur in rows:
        days_overdue = (today - pur.due_date).days
        item = {
            "purchase_id": pur.id,
            "purchase_no": pur.purchase_no,
            "supplier_invoice_no": pur.supplier_invoice_no,
            "contact_name": contacts.get(pur.contact_id, ""),
            "purchase_date": pur.purchase_date.isoformat(),
            "due_date": pur.due_date.isoformat(),
            "balance": float(pur.balance),
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

    return ok({
        "as_of_date": today.isoformat(),
        "buckets": {
            "current": {"items": buckets["current"], "total": _total(buckets["current"])},
            "1_30_days": {"items": buckets["1_30"], "total": _total(buckets["1_30"])},
            "31_60_days": {"items": buckets["31_60"], "total": _total(buckets["31_60"])},
            "61_90_days": {"items": buckets["61_90"], "total": _total(buckets["61_90"])},
            "over_90_days": {"items": buckets["over_90"], "total": _total(buckets["over_90"])},
        },
        "grand_total": _total([i for lst in buckets.values() for i in lst]),
    })
