"""AP Purchase Order Service — PO lifecycle + 3-way match."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.context import AppContext
from app.modules.ap.models import (
    APPurchase,
    GoodsReceivedNote,
    GRNLine,
    PurchaseOrder,
    PurchaseOrderLine,
)
from app.modules.ap.purchase_service import PurchaseService, _add_days
from app.modules.ap.schemas import (
    GRNCreate,
    GRNLineOut,
    GRNOut,
    POCreate,
    PODetail,
    POFilter,
    POLineOut,
    POOut,
    PurchaseCreate,
    PurchaseDetail,
    PurchaseLineCreate,
)
from app.modules.ar.models import Contact

_TWO = Decimal("0.01")


class POService:
    """
    บริการจัดการ Purchase Order + 3-Way Match.

    3-Way Match:
        PO (สั่งซื้อ) → GRN (รับสินค้า) → Invoice (ใบแจ้งหนี้)

    กฎ:
        - ต้อง approve PO ก่อนรับสินค้า
        - invoiced_qty ≤ received_qty ≤ ordered_qty
        - convert_to_purchase ตรวจ match ก่อน post
    """

    def __init__(self, session: AsyncSession) -> None:
        self._db = session

    # ── PO CRUD ───────────────────────────────────────────────────────────────

    async def create_po(self, data: POCreate, ctx: AppContext) -> PODetail:
        """สร้าง PO ใหม่ (status=draft)."""
        if not ctx.can_post:
            raise HTTPException(403, "ไม่มีสิทธิ์สร้าง PO")

        contact = await self._get_contact(data.contact_id, ctx.company_id)
        po_no = await self._next_po_no(ctx, data.po_date)

        subtotal = Decimal(0)
        vat_amount = Decimal(0)
        line_records: list[PurchaseOrderLine] = []

        for i, ln in enumerate(data.lines, start=1):
            amt = (ln.quantity * ln.unit_price).quantize(_TWO, ROUND_HALF_UP)
            vat_a = (amt * ln.vat_rate / 100).quantize(_TWO, ROUND_HALF_UP)
            subtotal += amt
            vat_amount += vat_a
            line_records.append(PurchaseOrderLine(
                line_no=i,
                description=ln.description,
                account_code=ln.account_code,
                unit=ln.unit,
                quantity=ln.quantity,
                unit_price=ln.unit_price,
                amount=amt,
                vat_rate=ln.vat_rate,
                vat_amount=vat_a,
                received_qty=Decimal(0),
            ))

        po = PurchaseOrder(
            company_id=ctx.company_id,
            branch_id=ctx.branch_id,
            po_no=po_no,
            po_date=data.po_date,
            expected_date=data.expected_date,
            contact_id=contact.id,
            purchase_type=data.purchase_type,
            subtotal=subtotal,
            vat_amount=vat_amount,
            total_amount=subtotal + vat_amount,
            status="draft",
            notes=data.notes,
            created_by=ctx.user_id,
        )
        po.lines = line_records
        self._db.add(po)
        await self._db.flush()

        return _po_to_detail(po, contact)

    async def approve_po(self, po_id: int, ctx: AppContext) -> PODetail:
        """อนุมัติ PO: draft → approved."""
        if not ctx.can_approve:
            raise HTTPException(403, "ต้องเป็น accountant ขึ้นไปเพื่ออนุมัติ PO")

        po = await self._load_po(po_id, ctx.company_id)
        if po.status != "draft":
            raise HTTPException(409, f"PO {po.po_no} สถานะ {po.status!r} ไม่สามารถอนุมัติได้")

        po.status = "approved"
        po.approved_by = ctx.user_id
        po.approved_at = datetime.now(tz=timezone.utc)
        await self._db.flush()

        contact = await self._get_contact(po.contact_id, ctx.company_id)
        return _po_to_detail(po, contact)

    async def cancel_po(self, po_id: int, ctx: AppContext) -> PODetail:
        """ยกเลิก PO (ได้เฉพาะ draft/approved)."""
        if not ctx.can_approve:
            raise HTTPException(403, "ต้องเป็น accountant ขึ้นไปเพื่อยกเลิก PO")

        po = await self._load_po(po_id, ctx.company_id)
        if po.status not in ("draft", "approved"):
            raise HTTPException(409, f"PO {po.po_no} สถานะ {po.status!r} ยกเลิกไม่ได้")

        po.status = "cancelled"
        await self._db.flush()

        contact = await self._get_contact(po.contact_id, ctx.company_id)
        return _po_to_detail(po, contact)

    async def list_pos(
        self, ctx: AppContext, filters: POFilter
    ) -> tuple[list[POOut], int]:
        stmt = (
            select(PurchaseOrder)
            .where(PurchaseOrder.company_id == ctx.company_id)
        )

        if filters.contact_id:
            stmt = stmt.where(PurchaseOrder.contact_id == filters.contact_id)
        if filters.status:
            stmt = stmt.where(PurchaseOrder.status == filters.status)
        if filters.purchase_type:
            stmt = stmt.where(PurchaseOrder.purchase_type == filters.purchase_type)
        if filters.date_from:
            stmt = stmt.where(PurchaseOrder.po_date >= filters.date_from)
        if filters.date_to:
            stmt = stmt.where(PurchaseOrder.po_date <= filters.date_to)
        if filters.search:
            like = f"%{filters.search}%"
            stmt = stmt.join(Contact, PurchaseOrder.contact_id == Contact.id).where(
                PurchaseOrder.po_no.ilike(like) | Contact.name.ilike(like)
            )

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await self._db.execute(count_stmt)).scalar_one()

        stmt = stmt.order_by(PurchaseOrder.po_date.desc()).limit(filters.limit).offset(filters.offset)
        rows = (await self._db.execute(stmt)).scalars().all()

        contact_ids = list({r.contact_id for r in rows})
        contacts: dict[int, Contact] = {}
        if contact_ids:
            c_rows = (await self._db.execute(
                select(Contact).where(Contact.id.in_(contact_ids))
            )).scalars().all()
            contacts = {c.id: c for c in c_rows}

        return [_po_to_out(po, contacts.get(po.contact_id)) for po in rows], total

    async def get_po(self, po_id: int, ctx: AppContext) -> PODetail:
        po = await self._load_po(po_id, ctx.company_id)
        contact = await self._get_contact(po.contact_id, ctx.company_id)
        return _po_to_detail(po, contact)

    # ── GRN (รับสินค้า) ───────────────────────────────────────────────────────

    async def receive_goods(self, data: GRNCreate, ctx: AppContext) -> GRNOut:
        """
        บันทึกการรับสินค้า (GRN) — 3-way match step 2.

        ตรวจ:
        - PO ต้อง approved
        - received_qty + existing_received ≤ ordered_qty
        """
        if not ctx.can_post:
            raise HTTPException(403, "ไม่มีสิทธิ์บันทึกการรับสินค้า")

        po = await self._load_po(data.po_id, ctx.company_id)
        if po.status not in ("approved", "goods_received"):
            raise HTTPException(
                409,
                f"PO {po.po_no} สถานะ {po.status!r} ต้อง approve ก่อนรับสินค้า",
            )

        # โหลด PO lines map
        po_lines: dict[int, PurchaseOrderLine] = {ln.id: ln for ln in po.lines}

        grn_no = await self._next_grn_no(ctx, data.grn_date)
        grn = GoodsReceivedNote(
            company_id=ctx.company_id,
            branch_id=ctx.branch_id,
            grn_no=grn_no,
            grn_date=data.grn_date,
            po_id=po.id,
            notes=data.notes,
            status="posted",
            received_by=ctx.user_id,
        )
        self._db.add(grn)
        await self._db.flush()

        grn_lines: list[GRNLine] = []
        for ln_in in data.lines:
            po_line = po_lines.get(ln_in.po_line_id)
            if po_line is None:
                raise HTTPException(400, f"po_line_id={ln_in.po_line_id} ไม่ใช่ของ PO นี้")

            # ตรวจ over-receive
            remaining = po_line.quantity - po_line.received_qty
            if ln_in.received_qty > remaining:
                raise HTTPException(
                    422,
                    f"line {po_line.line_no}: รับเกิน — สั่งซื้อ {po_line.quantity}, "
                    f"รับแล้ว {po_line.received_qty}, รับได้อีก {remaining}",
                )

            po_line.received_qty = (po_line.received_qty + ln_in.received_qty).quantize(
                Decimal("0.0001"), ROUND_HALF_UP
            )
            grn_lines.append(GRNLine(
                grn_id=grn.id,
                po_line_id=ln_in.po_line_id,
                description=po_line.description,
                ordered_qty=po_line.quantity,
                received_qty=ln_in.received_qty,
                unit=po_line.unit,
            ))

        self._db.add_all(grn_lines)
        po.status = "goods_received"
        await self._db.flush()

        contact = await self._get_contact(po.contact_id, ctx.company_id)
        grn.lines = grn_lines
        return _grn_to_out(grn, po, contact.name)

    async def list_grns(
        self, ctx: AppContext, po_id: Optional[int] = None
    ) -> list[GRNOut]:
        stmt = (
            select(GoodsReceivedNote)
            .where(GoodsReceivedNote.company_id == ctx.company_id)
            .options(
                selectinload(GoodsReceivedNote.lines),
                selectinload(GoodsReceivedNote.po),
            )
        )
        if po_id:
            stmt = stmt.where(GoodsReceivedNote.po_id == po_id)
        stmt = stmt.order_by(GoodsReceivedNote.grn_date.desc())
        rows = (await self._db.execute(stmt)).scalars().all()

        results = []
        for grn in rows:
            if grn.po:
                contact_r = await self._db.execute(
                    select(Contact).where(Contact.id == grn.po.contact_id)
                )
                c = contact_r.scalar_one_or_none()
                results.append(_grn_to_out(grn, grn.po, c.name if c else ""))
        return results

    async def get_grn(self, grn_id: int, ctx: AppContext) -> GRNOut:
        result = await self._db.execute(
            select(GoodsReceivedNote)
            .where(
                GoodsReceivedNote.id == grn_id,
                GoodsReceivedNote.company_id == ctx.company_id,
            )
            .options(
                selectinload(GoodsReceivedNote.lines),
                selectinload(GoodsReceivedNote.po).selectinload(PurchaseOrder.lines),
            )
        )
        grn = result.scalar_one_or_none()
        if grn is None:
            raise HTTPException(404, f"ไม่พบ GRN id={grn_id}")
        contact = await self._get_contact(grn.po.contact_id, ctx.company_id)
        return _grn_to_out(grn, grn.po, contact.name)

    # ── Convert PO → Purchase ─────────────────────────────────────────────────

    async def convert_to_purchase(
        self,
        po_id: int,
        ctx: AppContext,
        supplier_invoice_no: Optional[str] = None,
    ) -> PurchaseDetail:
        """
        แปลง PO → APPurchase หลังผ่าน 3-way match.

        ตรวจ:
        - PO status = goods_received
        - ทุก line ต้องมี received_qty > 0
        - สร้าง PurchaseCreate จาก PO lines (ใช้ received_qty เป็น quantity)
        """
        po = await self._load_po(po_id, ctx.company_id)

        if po.status == "invoiced":
            raise HTTPException(409, f"PO {po.po_no} ถูกสร้าง invoice แล้ว")
        if po.status not in ("goods_received",):
            raise HTTPException(
                409,
                f"PO {po.po_no} สถานะ {po.status!r} — ต้องรับสินค้าก่อน (goods_received)",
            )

        # ตรวจว่าทุก line มีของมาครบ
        undelivered = [ln for ln in po.lines if ln.received_qty <= 0]
        if undelivered:
            descs = ", ".join(str(ln.line_no) for ln in undelivered)
            raise HTTPException(
                422, f"PO line {descs} ยังไม่ได้รับสินค้า — ตรวจ GRN อีกครั้ง"
            )

        # หา GRN ล่าสุด
        grn_result = await self._db.execute(
            select(GoodsReceivedNote.id)
            .where(GoodsReceivedNote.po_id == po.id)
            .order_by(GoodsReceivedNote.created_at.desc())
            .limit(1)
        )
        grn_id = grn_result.scalar_one_or_none()

        # สร้าง PurchaseCreate จาก PO lines
        contact = await self._get_contact(po.contact_id, ctx.company_id)
        purchase_lines = [
            PurchaseLineCreate(
                description=ln.description,
                account_code=ln.account_code,
                unit=ln.unit,
                quantity=ln.received_qty,      # ใช้ received qty
                unit_price=ln.unit_price,
                vat_rate=ln.vat_rate,
            )
            for ln in po.lines
        ]

        data = PurchaseCreate(
            contact_id=po.contact_id,
            purchase_date=po.po_date,
            purchase_type=po.purchase_type,
            lines=purchase_lines,
            supplier_invoice_no=supplier_invoice_no,
            po_id=po.id,
            grn_id=grn_id,
        )

        svc = PurchaseService(self._db)
        result = await svc.create_purchase(data, ctx)

        # อัปเดต PO status → invoiced
        po.status = "invoiced"
        await self._db.flush()

        return result

    # ── Privates ──────────────────────────────────────────────────────────────

    async def _get_contact(self, contact_id: int, company_id: int) -> Contact:
        result = await self._db.execute(
            select(Contact).where(
                Contact.id == contact_id,
                Contact.company_id == company_id,
                Contact.is_active == True,  # noqa: E712
            )
        )
        c = result.scalar_one_or_none()
        if c is None:
            raise HTTPException(404, f"ไม่พบ contact id={contact_id}")
        return c

    async def _load_po(self, po_id: int, company_id: int) -> PurchaseOrder:
        result = await self._db.execute(
            select(PurchaseOrder)
            .where(PurchaseOrder.id == po_id, PurchaseOrder.company_id == company_id)
            .options(selectinload(PurchaseOrder.lines))
        )
        po = result.scalar_one_or_none()
        if po is None:
            raise HTTPException(404, f"ไม่พบ PO id={po_id}")
        return po

    async def _next_po_no(self, ctx: AppContext, po_date: "date") -> str:  # noqa: F821
        from datetime import date
        ym = po_date.strftime("%Y%m")
        prefix = f"PO{ym}-"
        result = await self._db.execute(
            select(func.count(PurchaseOrder.id)).where(
                PurchaseOrder.company_id == ctx.company_id,
                PurchaseOrder.po_no.like(f"{prefix}%"),
            )
        )
        seq = (result.scalar_one() or 0) + 1
        return f"{prefix}{seq:04d}"

    async def _next_grn_no(self, ctx: AppContext, grn_date: "date") -> str:  # noqa: F821
        from datetime import date
        ym = grn_date.strftime("%Y%m")
        prefix = f"GRN{ym}-"
        result = await self._db.execute(
            select(func.count(GoodsReceivedNote.id)).where(
                GoodsReceivedNote.company_id == ctx.company_id,
                GoodsReceivedNote.grn_no.like(f"{prefix}%"),
            )
        )
        seq = (result.scalar_one() or 0) + 1
        return f"{prefix}{seq:04d}"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _po_to_out(po: PurchaseOrder, contact: "Contact | None") -> POOut:
    return POOut(
        id=po.id,
        company_id=po.company_id,
        branch_id=po.branch_id,
        po_no=po.po_no,
        po_date=po.po_date,
        expected_date=po.expected_date,
        contact_id=po.contact_id,
        contact_name=contact.name if contact else "",
        purchase_type=po.purchase_type,
        subtotal=po.subtotal,
        vat_amount=po.vat_amount,
        total_amount=po.total_amount,
        status=po.status,
        notes=po.notes,
        approved_by=po.approved_by,
        approved_at=po.approved_at,
        created_by=po.created_by,
        created_at=po.created_at,
    )


def _po_to_detail(po: PurchaseOrder, contact: Contact) -> PODetail:
    lines_out = [
        POLineOut(
            id=ln.id,
            line_no=ln.line_no,
            description=ln.description,
            account_code=ln.account_code,
            unit=ln.unit,
            quantity=ln.quantity,
            unit_price=ln.unit_price,
            amount=ln.amount,
            vat_rate=ln.vat_rate,
            vat_amount=ln.vat_amount,
            received_qty=ln.received_qty,
        )
        for ln in (po.lines or [])
    ]
    return PODetail(**_po_to_out(po, contact).__dict__, lines=lines_out)


def _grn_to_out(
    grn: GoodsReceivedNote, po: PurchaseOrder, contact_name: str
) -> GRNOut:
    lines_out = [
        GRNLineOut(
            id=ln.id,
            po_line_id=ln.po_line_id,
            description=ln.description,
            ordered_qty=ln.ordered_qty,
            received_qty=ln.received_qty,
            unit=ln.unit,
        )
        for ln in (grn.lines or [])
    ]
    return GRNOut(
        id=grn.id,
        company_id=grn.company_id,
        branch_id=grn.branch_id,
        grn_no=grn.grn_no,
        grn_date=grn.grn_date,
        po_id=po.id,
        po_no=po.po_no,
        contact_name=contact_name,
        status=grn.status,
        notes=grn.notes,
        received_by=grn.received_by,
        created_at=grn.created_at,
        lines=lines_out,
    )
