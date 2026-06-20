"""AP Purchase Service — ใบแจ้งหนี้เจ้าหนี้ (PJ)."""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.context import AppContext, DrCr, JournalType
from app.core.engine import (
    JournalEntryInput,
    JournalLineInput,
    PostingEngine,
    PermissionError as PostingPermissionError,
)
from app.core.editor import EditorService
from app.modules.ap.models import APPurchase, APPurchaseLine
from app.modules.ap.schemas import (
    PurchaseCreate,
    PurchaseDetail,
    PurchaseFilter,
    PurchaseLineOut,
    PurchaseOut,
)
from app.modules.ar.models import Contact

_TWO = Decimal("0.01")

# บัญชีค่าเริ่มต้นตาม purchase_type
_DEFAULT_AP_ACCOUNT = "2101"   # เจ้าหนี้การค้า
_VAT_INPUT_ACCOUNT  = "1140"   # ภาษีซื้อ


class PurchaseService:
    """
    บริการจัดการใบแจ้งหนี้เจ้าหนี้ (AP Purchase / Supplier Invoice).

    Journal (PJ):
        Dr [expense/inventory accounts]    subtotal
        Dr 1140 ภาษีซื้อ                  vat_amount
          Cr 2101 เจ้าหนี้การค้า          total_amount
    """

    def __init__(self, session: AsyncSession) -> None:
        self._db = session

    # ── Create ────────────────────────────────────────────────────────────────

    async def create_purchase(
        self, data: PurchaseCreate, ctx: AppContext
    ) -> PurchaseDetail:
        """
        สร้าง AP Purchase และ post Journal Entry (PJ).

        1. ตรวจสิทธิ์ (can_post)
        2. โหลด Contact → credit_days, wht_rate, default_ap_account
        3. คำนวณ subtotal / vat / total
        4. บันทึก APPurchase + APPurchaseLine
        5. สร้าง JournalEntry ผ่าน PostingEngine
        6. อัปเดต status, journal_entry_no
        """
        if not ctx.can_post:
            raise HTTPException(403, "ไม่มีสิทธิ์บันทึกรายการ")

        contact = None
        if data.contact_id:
            contact = await self._get_contact(data.contact_id, ctx.company_id)

        if data.payment_mode == "cash":
            due_date = data.purchase_date
        elif data.due_date:
            due_date = data.due_date
        elif contact:
            due_date = _add_days(data.purchase_date, contact.credit_days)
        else:
            due_date = data.purchase_date

        # คำนวณยอด
        subtotal = Decimal(0)
        vat_amount = Decimal(0)
        line_records: list[APPurchaseLine] = []

        for i, ln in enumerate(data.lines, start=1):
            amt = (ln.quantity * ln.unit_price).quantize(_TWO, ROUND_HALF_UP)
            vat_r = Decimal(0) if data.vat_exempt else ln.vat_rate
            vat_a = (amt * vat_r / 100).quantize(_TWO, ROUND_HALF_UP)
            subtotal += amt
            vat_amount += vat_a
            line_records.append(APPurchaseLine(
                line_no=i,
                product_id=getattr(ln, "product_id", None),
                description=ln.description,
                account_code=ln.account_code,
                unit=ln.unit,
                quantity=ln.quantity,
                unit_price=ln.unit_price,
                amount=amt,
                vat_rate=vat_r,
                vat_amount=vat_a,
            ))

        total = subtotal + vat_amount
        wht_amount = Decimal(0)
        if contact and contact.wht_rate:
            wht_amount = (subtotal * contact.wht_rate / 100).quantize(_TWO, ROUND_HALF_UP)

        purchase_no = await self._next_purchase_no(ctx, data.purchase_date)
        contact_name = contact.name if contact else "ผู้ขายทั่วไป"

        # กำหนด status เริ่มต้น — cash = paid ทันที, credit = draft
        initial_status = "paid" if data.payment_mode == "cash" else "draft"
        initial_paid = total if data.payment_mode == "cash" else Decimal(0)
        initial_balance = Decimal(0) if data.payment_mode == "cash" else total

        purchase = APPurchase(
            company_id=ctx.company_id,
            branch_id=ctx.branch_id,
            purchase_no=purchase_no,
            supplier_invoice_no=data.supplier_invoice_no,
            purchase_date=data.purchase_date,
            due_date=due_date,
            contact_id=contact.id if contact else None,
            po_id=data.po_id,
            grn_id=data.grn_id,
            purchase_type=data.purchase_type,
            payment_mode=data.payment_mode,
            payment_account_code=data.payment_account_code,
            subtotal=subtotal,
            vat_amount=vat_amount,
            wht_amount=wht_amount,
            total_amount=total,
            paid_amount=initial_paid,
            balance=initial_balance,
            status=initial_status,
            description=data.description,
            created_by=ctx.user_id,
        )
        purchase.lines = line_records
        self._db.add(purchase)
        await self._db.flush()

        # สร้าง Journal lines
        journal_lines: list[JournalLineInput] = []

        # Dr expense/inventory lines (แยกตาม account_code)
        dr_by_account: dict[str, Decimal] = {}
        for lr in line_records:
            dr_by_account[lr.account_code] = (
                dr_by_account.get(lr.account_code, Decimal(0)) + lr.amount
            )

        for acc_code, acc_total in dr_by_account.items():
            journal_lines.append(JournalLineInput(
                account_code=acc_code,
                side=DrCr.DR,
                amount=acc_total,
                description=f"ซื้อ {contact_name} | {purchase_no}",
            ))

        # Dr 1140 ภาษีซื้อ
        if vat_amount > 0:
            journal_lines.append(JournalLineInput(
                account_code=_VAT_INPUT_ACCOUNT,
                side=DrCr.DR,
                amount=vat_amount,
                description=f"ภาษีซื้อ {purchase_no}",
            ))

        if data.payment_mode == "cash":
            # Cr เงินสด/ธนาคาร (จ่ายทันที)
            journal_lines.append(JournalLineInput(
                account_code=data.payment_account_code,
                side=DrCr.CR,
                amount=total,
                description=f"จ่ายสด {contact_name} | {purchase_no}",
            ))
            journal_type = JournalType.CP
        else:
            # Cr 2101 เจ้าหนี้
            ap_account = contact.default_ap_account if contact else _DEFAULT_AP_ACCOUNT
            journal_lines.append(JournalLineInput(
                account_code=ap_account,
                side=DrCr.CR,
                amount=total,
                description=f"เจ้าหนี้ {contact_name} | {purchase_no}",
            ))
            journal_type = JournalType.PJ

        entry_input = JournalEntryInput(
            journal_type=journal_type,
            entry_date=data.purchase_date,
            description=data.description or f"ซื้อ {contact_name} | {purchase_no}",
            lines=journal_lines,
            reference=data.supplier_invoice_no or purchase_no,
            source_module="ap",
            source_id=purchase.id,
        )

        engine = PostingEngine(self._db)
        try:
            entry_no = await engine.post(entry_input, ctx)
        except PostingPermissionError as e:
            raise HTTPException(403, str(e))
        except Exception as e:
            raise HTTPException(422, str(e))

        purchase.journal_entry_no = entry_no
        if data.payment_mode == "credit":
            purchase.status = "posted"
        await self._db.flush()

        # ── Inventory integration: รับสต็อกเข้าสำหรับบรรทัดที่ผูกสินค้า ──
        await self._receive_stock_for_lines(purchase, line_records, ctx)

        return _to_detail(purchase, contact, line_records)

    async def _receive_stock_for_lines(
        self, purchase: APPurchase, line_records: list[APPurchaseLine], ctx: AppContext
    ) -> None:
        """รับสต็อกเข้าคลังสำหรับบรรทัด purchase ที่ผูก product_id.

        Additive — ไม่กระทบ logic AP เดิม. หมายเหตุ: JE รับสินค้าถูก post โดย
        AP แล้ว (Dr 1130) จึงเรียก receive แบบ post_journal=False เพื่อเลี่ยง
        การ post ซ้ำ — InventoryService.receive จะอัปเดต lot/cost/qty เท่านั้น.
        """
        product_lines = [lr for lr in line_records if getattr(lr, "product_id", None)]
        if not product_lines:
            return
        from app.modules.inv.inventory_service import InventoryService
        from app.modules.inv.schemas import ReceiveStockIn
        for lr in product_lines:
            await InventoryService.receive(
                ReceiveStockIn(
                    product_id=lr.product_id,
                    movement_date=purchase.purchase_date,
                    quantity=lr.quantity,
                    unit_cost=lr.unit_price,
                    source="purchase",
                    source_ref=purchase.purchase_no,
                    reference=purchase.purchase_no,
                    ap_purchase_id=purchase.id,
                    post_journal=False,
                ),
                ctx,
                self._db,
            )

    # ── List ──────────────────────────────────────────────────────────────────

    async def list_purchases(
        self, ctx: AppContext, filters: PurchaseFilter
    ) -> tuple[list[PurchaseOut], int]:
        from datetime import date as date_type

        stmt = (
            select(APPurchase)
            .where(APPurchase.company_id == ctx.company_id)
            .options(selectinload(APPurchase.lines), selectinload(APPurchase.lines))
        )
        # join contact for search
        needs_join = bool(filters.search)

        if filters.contact_id:
            stmt = stmt.where(APPurchase.contact_id == filters.contact_id)
        if filters.status:
            stmt = stmt.where(APPurchase.status == filters.status)
        if filters.purchase_type:
            stmt = stmt.where(APPurchase.purchase_type == filters.purchase_type)
        if filters.date_from:
            stmt = stmt.where(APPurchase.purchase_date >= filters.date_from)
        if filters.date_to:
            stmt = stmt.where(APPurchase.purchase_date <= filters.date_to)
        if filters.overdue_only:
            stmt = stmt.where(
                APPurchase.status.not_in(["paid", "cancelled"]),
                APPurchase.due_date < date_type.today(),
            )
        if filters.po_id:
            stmt = stmt.where(APPurchase.po_id == filters.po_id)
        if filters.search:
            like = f"%{filters.search}%"
            stmt = stmt.join(Contact, APPurchase.contact_id == Contact.id).where(
                APPurchase.purchase_no.ilike(like)
                | APPurchase.supplier_invoice_no.ilike(like)
                | Contact.name.ilike(like)
            )

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await self._db.execute(count_stmt)).scalar_one()

        stmt = stmt.order_by(
            APPurchase.purchase_date.desc(), APPurchase.purchase_no.desc()
        ).limit(filters.limit).offset(filters.offset)
        rows = (await self._db.execute(stmt)).scalars().all()

        # โหลด contacts
        contact_ids = list({r.contact_id for r in rows})
        contacts: dict[int, Contact] = {}
        if contact_ids:
            c_rows = (await self._db.execute(
                select(Contact).where(Contact.id.in_(contact_ids))
            )).scalars().all()
            contacts = {c.id: c for c in c_rows}

        out = []
        for p in rows:
            c = contacts.get(p.contact_id) if p.contact_id else None
            out.append(_purchase_to_out(p, c.name if c else "ผู้ขายทั่วไป"))
        return out, total

    # ── Get ───────────────────────────────────────────────────────────────────

    async def get_purchase(self, purchase_id: int, ctx: AppContext) -> PurchaseDetail:
        purchase = await self._load(purchase_id, ctx.company_id)
        contact = None
        if purchase.contact_id:
            contact = await self._get_contact(purchase.contact_id, ctx.company_id)
        return _to_detail(purchase, contact, purchase.lines)

    # ── Cancel ────────────────────────────────────────────────────────────────

    async def cancel_purchase(
        self, purchase_id: int, reason: str, ctx: AppContext
    ) -> str:
        if not ctx.can_approve:
            raise HTTPException(403, "ต้องเป็น accountant ขึ้นไปเพื่อยกเลิก")
        purchase = await self._load(purchase_id, ctx.company_id)

        if purchase.status == "cancelled":
            raise HTTPException(409, f"Purchase {purchase.purchase_no} ถูกยกเลิกแล้ว")
        if purchase.status == "paid":
            raise HTTPException(409, f"Purchase {purchase.purchase_no} ชำระครบแล้ว")
        if purchase.paid_amount > 0:
            raise HTTPException(
                409,
                f"Purchase {purchase.purchase_no} มีชำระบางส่วนแล้ว กรุณายกเลิกใบสำคัญจ่ายก่อน",
            )
        if not purchase.journal_entry_no:
            raise HTTPException(400, "ไม่พบ journal entry สำหรับ purchase นี้")

        editor = EditorService(self._db)
        rev_no = await editor.reverse(purchase.journal_entry_no, reason, ctx)

        purchase.status = "cancelled"
        await self._db.flush()
        return rev_no

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

    async def _load(self, purchase_id: int, company_id: int) -> APPurchase:
        result = await self._db.execute(
            select(APPurchase)
            .where(APPurchase.id == purchase_id, APPurchase.company_id == company_id)
            .options(selectinload(APPurchase.lines))
        )
        p = result.scalar_one_or_none()
        if p is None:
            raise HTTPException(404, f"ไม่พบ purchase id={purchase_id}")
        return p

    async def _next_purchase_no(self, ctx: AppContext, entry_date: "date") -> str:  # noqa: F821
        from datetime import date
        ym = entry_date.strftime("%Y%m")
        prefix = f"PUR{ym}-"
        result = await self._db.execute(
            select(func.count(APPurchase.id)).where(
                APPurchase.company_id == ctx.company_id,
                APPurchase.purchase_no.like(f"{prefix}%"),
            )
        )
        seq = (result.scalar_one() or 0) + 1
        return f"{prefix}{seq:04d}"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _add_days(d: "date", days: int) -> "date":  # noqa: F821
    from datetime import timedelta
    return d + timedelta(days=days)


def _purchase_to_out(p: APPurchase, contact_name: str) -> PurchaseOut:
    return PurchaseOut(
        id=p.id,
        company_id=p.company_id,
        branch_id=p.branch_id,
        purchase_no=p.purchase_no,
        supplier_invoice_no=p.supplier_invoice_no,
        purchase_date=p.purchase_date,
        due_date=p.due_date,
        contact_id=p.contact_id,
        contact_name=contact_name,
        payment_mode=getattr(p, "payment_mode", "credit"),
        payment_account_code=getattr(p, "payment_account_code", None),
        purchase_type=p.purchase_type,
        po_id=p.po_id,
        grn_id=p.grn_id,
        subtotal=p.subtotal,
        vat_amount=p.vat_amount,
        wht_amount=p.wht_amount,
        total_amount=p.total_amount,
        paid_amount=p.paid_amount,
        balance=p.balance,
        status=p.status,
        description=p.description,
        journal_entry_no=p.journal_entry_no,
        is_overdue=p.is_overdue,
        created_by=p.created_by,
        created_at=p.created_at,
    )


def _to_detail(
    p: APPurchase,
    contact: "Optional[Contact]",
    lines: list[APPurchaseLine],
) -> PurchaseDetail:
    lines_out = [
        PurchaseLineOut(
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
        )
        for ln in lines
    ]
    return PurchaseDetail(
        **_purchase_to_out(p, contact.name if contact else "ผู้ขายทั่วไป").__dict__,
        lines=lines_out,
    )
