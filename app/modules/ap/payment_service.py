"""AP Payment Service — ใบสำคัญจ่าย (CP)."""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

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
from app.modules.ap.models import APPayment, APPaymentAllocation, APPurchase
from app.modules.ap.schemas import (
    PaymentAllocationOut,
    PaymentCreate,
    PaymentFilter,
    PaymentOut,
)
from app.modules.ar.models import Contact

_TWO = Decimal("0.01")
_PAID_STATUSES = {"paid", "cancelled"}

_AP_ACCOUNT  = "2101"   # เจ้าหนี้การค้า
_WHT_ACCOUNT = "2121"   # WHT ค้างนำส่ง


class PaymentService:
    """
    บริการบันทึกการจ่ายชำระหนี้ให้เจ้าหนี้.

    Journal (CP):
        Dr 2101 เจ้าหนี้           total_applied
          Cr 1102 ธนาคาร           total_paid (= total_applied - wht_amount)
          Cr 2121 WHT ค้างนำส่ง    wht_amount (ถ้ามี)
    """

    def __init__(self, session: AsyncSession) -> None:
        self._db = session

    # ── Create ────────────────────────────────────────────────────────────────

    async def create_payment(self, data: PaymentCreate, ctx: AppContext) -> PaymentOut:
        """
        บันทึกการจ่ายชำระหนี้.

        1. ตรวจสิทธิ์
        2. โหลดและตรวจ AP purchases ใน allocations
        3. สร้าง Journal Entry (CP)
        4. อัปเดต purchase.paid_amount / balance / status
        5. สร้าง APPayment + APPaymentAllocation
        """
        if not ctx.can_post:
            raise HTTPException(403, "ไม่มีสิทธิ์บันทึกรายการ")

        contact = await self._get_contact(data.contact_id, ctx.company_id)

        # ตรวจ purchases
        total_applied = Decimal(0)
        purchase_map: dict[int, APPurchase] = {}

        for alloc in data.allocations:
            pur = await self._load_open_purchase(alloc.purchase_id, ctx.company_id)
            if pur.contact_id != data.contact_id:
                raise HTTPException(
                    400, f"Purchase {pur.purchase_no} ไม่ใช่ของ contact นี้"
                )
            if alloc.allocated_amount > pur.balance:
                raise HTTPException(
                    422,
                    f"Purchase {pur.purchase_no}: ยอด match ({alloc.allocated_amount}) "
                    f"เกิน balance ({pur.balance})",
                )
            purchase_map[alloc.purchase_id] = pur
            total_applied += alloc.allocated_amount

        wht = data.wht_amount.quantize(_TWO, ROUND_HALF_UP)
        total_paid = (total_applied - wht).quantize(_TWO, ROUND_HALF_UP)

        if total_paid < 0:
            raise HTTPException(422, "wht_amount มากกว่ายอดรวม")

        payment_no = await self._next_payment_no(ctx, data.payment_date)

        # สร้าง Journal lines
        ap_account = contact.default_ap_account  # default 2101

        journal_lines: list[JournalLineInput] = [
            JournalLineInput(
                account_code=ap_account,
                side=DrCr.DR,
                amount=total_applied,
                description=f"จ่าย {contact.name} | {payment_no}",
            ),
            JournalLineInput(
                account_code=data.bank_account_code,
                side=DrCr.CR,
                amount=total_paid,
                description=f"จ่ายเงิน {contact.name} | {payment_no}",
            ),
        ]

        if wht > 0:
            journal_lines.append(JournalLineInput(
                account_code=_WHT_ACCOUNT,
                side=DrCr.CR,
                amount=wht,
                description=f"WHT หัก ณ ที่จ่าย {contact.name} | {payment_no}",
            ))

        pur_nos = ", ".join(purchase_map[a.purchase_id].purchase_no for a in data.allocations)
        entry_input = JournalEntryInput(
            journal_type=JournalType.CP,
            entry_date=data.payment_date,
            description=data.description or f"จ่ายชำระ {contact.name} {pur_nos}",
            lines=journal_lines,
            reference=data.reference or payment_no,
            source_module="ap",
        )

        engine = PostingEngine(self._db)
        try:
            entry_no = await engine.post(entry_input, ctx)
        except PostingPermissionError as e:
            raise HTTPException(403, str(e))
        except Exception as e:
            raise HTTPException(422, str(e))

        # บันทึก APPayment
        payment = APPayment(
            company_id=ctx.company_id,
            branch_id=ctx.branch_id,
            payment_no=payment_no,
            payment_date=data.payment_date,
            contact_id=data.contact_id,
            bank_account_code=data.bank_account_code,
            total_paid=total_paid,
            wht_amount=wht,
            total_applied=total_applied,
            status="posted",
            description=data.description,
            reference=data.reference,
            journal_entry_no=entry_no,
            created_by=ctx.user_id,
        )
        self._db.add(payment)
        await self._db.flush()

        alloc_records: list[APPaymentAllocation] = []
        for alloc in data.allocations:
            pur = purchase_map[alloc.purchase_id]
            pur.paid_amount = (pur.paid_amount + alloc.allocated_amount).quantize(_TWO)
            pur.balance = (pur.balance - alloc.allocated_amount).quantize(_TWO)

            if pur.balance <= 0:
                pur.status = "paid"
            elif pur.paid_amount > 0:
                pur.status = "partially_paid"

            alloc_records.append(APPaymentAllocation(
                payment_id=payment.id,
                purchase_id=alloc.purchase_id,
                allocated_amount=alloc.allocated_amount,
            ))

        self._db.add_all(alloc_records)
        await self._db.flush()

        return _payment_to_out(payment, contact, alloc_records, purchase_map)

    # ── List ──────────────────────────────────────────────────────────────────

    async def list_payments(
        self, ctx: AppContext, filters: PaymentFilter
    ) -> tuple[list[PaymentOut], int]:
        stmt = (
            select(APPayment)
            .where(APPayment.company_id == ctx.company_id)
            .options(selectinload(APPayment.allocations))
        )

        if filters.contact_id:
            stmt = stmt.where(APPayment.contact_id == filters.contact_id)
        if filters.date_from:
            stmt = stmt.where(APPayment.payment_date >= filters.date_from)
        if filters.date_to:
            stmt = stmt.where(APPayment.payment_date <= filters.date_to)
        if filters.search:
            like = f"%{filters.search}%"
            stmt = stmt.join(Contact, APPayment.contact_id == Contact.id).where(
                APPayment.payment_no.ilike(like) | Contact.name.ilike(like)
            )

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await self._db.execute(count_stmt)).scalar_one()

        stmt = stmt.order_by(APPayment.payment_date.desc()).limit(filters.limit).offset(filters.offset)
        rows = (await self._db.execute(stmt)).scalars().all()

        results = []
        for pmt in rows:
            contact_result = await self._db.execute(
                select(Contact).where(Contact.id == pmt.contact_id)
            )
            c = contact_result.scalar_one_or_none()
            pur_map: dict[int, APPurchase] = {}
            for a in pmt.allocations:
                pur_r = await self._db.execute(
                    select(APPurchase).where(APPurchase.id == a.purchase_id)
                )
                pur = pur_r.scalar_one_or_none()
                if pur:
                    pur_map[a.purchase_id] = pur
            results.append(_payment_to_out(pmt, c, pmt.allocations, pur_map))

        return results, total

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

    async def _load_open_purchase(self, purchase_id: int, company_id: int) -> APPurchase:
        result = await self._db.execute(
            select(APPurchase).where(
                APPurchase.id == purchase_id,
                APPurchase.company_id == company_id,
            )
        )
        p = result.scalar_one_or_none()
        if p is None:
            raise HTTPException(404, f"ไม่พบ purchase id={purchase_id}")
        if p.status in _PAID_STATUSES:
            raise HTTPException(409, f"Purchase {p.purchase_no} สถานะ {p.status}")
        return p

    async def _next_payment_no(self, ctx: AppContext, entry_date: "date") -> str:  # noqa: F821
        from datetime import date
        ym = entry_date.strftime("%Y%m")
        prefix = f"PAY{ym}-"
        result = await self._db.execute(
            select(func.count(APPayment.id)).where(
                APPayment.company_id == ctx.company_id,
                APPayment.payment_no.like(f"{prefix}%"),
            )
        )
        seq = (result.scalar_one() or 0) + 1
        return f"{prefix}{seq:04d}"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _payment_to_out(
    pmt: APPayment,
    contact: "Contact | None",
    allocs: list[APPaymentAllocation],
    pur_map: dict[int, APPurchase],
) -> PaymentOut:
    alloc_outs = [
        PaymentAllocationOut(
            id=a.id,
            purchase_id=a.purchase_id,
            purchase_no=pur_map[a.purchase_id].purchase_no if a.purchase_id in pur_map else "",
            allocated_amount=a.allocated_amount,
        )
        for a in allocs
    ]
    return PaymentOut(
        id=pmt.id,
        company_id=pmt.company_id,
        branch_id=pmt.branch_id,
        payment_no=pmt.payment_no,
        payment_date=pmt.payment_date,
        contact_id=pmt.contact_id,
        contact_name=contact.name if contact else "",
        bank_account_code=pmt.bank_account_code,
        total_paid=pmt.total_paid,
        wht_amount=pmt.wht_amount,
        total_applied=pmt.total_applied,
        status=pmt.status,
        description=pmt.description,
        reference=pmt.reference,
        journal_entry_no=pmt.journal_entry_no,
        allocations=alloc_outs,
        created_by=pmt.created_by,
        created_at=pmt.created_at,
    )
