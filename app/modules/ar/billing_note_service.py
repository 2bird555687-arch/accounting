"""AR Billing Note Service — ใบวางบิล (ไม่สร้าง Journal Entry)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Optional

from fastapi import HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.context import AppContext
from app.modules.ar.models import ARInvoice, BillingNote, BillingNoteInvoice, Contact

_TWO = Decimal("0.01")


# ── Schemas ───────────────────────────────────────────────────────────────────

class BillingNoteCreate(BaseModel):
    contact_id: int
    billing_date: date
    due_date: Optional[date] = None
    invoice_ids: list[int]
    description: Optional[str] = None


class BillingNoteOut(BaseModel):
    id: int
    company_id: int
    billing_note_no: str
    billing_date: date
    due_date: date
    contact_id: int
    contact_name: str
    total_amount: Decimal
    status: str
    description: Optional[str]
    invoice_ids: list[int]
    created_by: int
    created_at: object

    model_config = {"from_attributes": True}


# ── Service ───────────────────────────────────────────────────────────────────

class BillingNoteService:
    """
    บริการจัดการใบวางบิล.

    ใบวางบิลไม่สร้าง Journal Entry — เป็นเพียงเอกสารรวม Invoice เพื่อส่งให้ลูกค้า.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._db = session

    # ── Create ────────────────────────────────────────────────────────────────

    async def create_billing_note(
        self, data: BillingNoteCreate, ctx: AppContext
    ) -> BillingNoteOut:
        """สร้างใบวางบิลจาก Invoice หลายใบ."""
        if not ctx.can_post:
            raise HTTPException(403, "ไม่มีสิทธิ์บันทึกรายการ")

        contact = await self._get_contact(data.contact_id, ctx.company_id)

        # โหลด invoices และตรวจสอบ
        invoices: list[ARInvoice] = []
        total = Decimal(0)
        for inv_id in data.invoice_ids:
            inv = await self._load_invoice(inv_id, ctx.company_id)
            if inv.contact_id != data.contact_id:
                raise HTTPException(
                    400,
                    f"Invoice {inv.invoice_no} ไม่ใช่ของ contact นี้",
                )
            if inv.status in ("cancelled", "paid"):
                raise HTTPException(
                    409,
                    f"Invoice {inv.invoice_no} สถานะ {inv.status} ไม่สามารถวางบิลได้",
                )
            invoices.append(inv)
            total += inv.balance

        due_date = data.due_date or data.billing_date

        billing_note_no = await self._next_no(ctx, data.billing_date)

        billing_note = BillingNote(
            company_id=ctx.company_id,
            branch_id=ctx.branch_id,
            billing_note_no=billing_note_no,
            billing_date=data.billing_date,
            due_date=due_date,
            contact_id=data.contact_id,
            total_amount=total,
            status="draft",
            description=data.description,
            created_by=ctx.user_id,
        )
        self._db.add(billing_note)
        await self._db.flush()

        links = [
            BillingNoteInvoice(billing_note_id=billing_note.id, invoice_id=inv.id)
            for inv in invoices
        ]
        self._db.add_all(links)

        # อัปเดต ar_invoices.billing_note_id
        for inv in invoices:
            inv.billing_note_id = billing_note.id

        await self._db.flush()

        return BillingNoteOut(
            id=billing_note.id,
            company_id=billing_note.company_id,
            billing_note_no=billing_note.billing_note_no,
            billing_date=billing_note.billing_date,
            due_date=billing_note.due_date,
            contact_id=billing_note.contact_id,
            contact_name=contact.name,
            total_amount=billing_note.total_amount,
            status=billing_note.status,
            description=billing_note.description,
            invoice_ids=[inv.id for inv in invoices],
            created_by=billing_note.created_by,
            created_at=billing_note.created_at,
        )

    # ── List ──────────────────────────────────────────────────────────────────

    async def list_billing_notes(
        self, ctx: AppContext, contact_id: Optional[int] = None,
        status: Optional[str] = None, page: int = 1, page_size: int = 50,
    ) -> tuple[list[BillingNoteOut], int]:
        stmt = (
            select(BillingNote)
            .where(BillingNote.company_id == ctx.company_id)
            .options(selectinload(BillingNote.contact), selectinload(BillingNote.invoice_links))
        )
        if contact_id:
            stmt = stmt.where(BillingNote.contact_id == contact_id)
        if status:
            stmt = stmt.where(BillingNote.status == status)

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await self._db.execute(count_stmt)).scalar_one()

        stmt = stmt.order_by(BillingNote.billing_date.desc())
        stmt = stmt.limit(page_size).offset((page - 1) * page_size)
        rows = (await self._db.execute(stmt)).scalars().all()

        return [_to_out(bn) for bn in rows], total

    # ── Get ───────────────────────────────────────────────────────────────────

    async def get_billing_note(self, bn_id: int, ctx: AppContext) -> BillingNoteOut:
        result = await self._db.execute(
            select(BillingNote)
            .where(BillingNote.id == bn_id, BillingNote.company_id == ctx.company_id)
            .options(selectinload(BillingNote.contact), selectinload(BillingNote.invoice_links))
        )
        bn = result.scalar_one_or_none()
        if bn is None:
            raise HTTPException(404, f"ไม่พบใบวางบิล id={bn_id}")
        return _to_out(bn)

    # ── Privates ──────────────────────────────────────────────────────────────

    async def _get_contact(self, contact_id: int, company_id: int) -> Contact:
        result = await self._db.execute(
            select(Contact).where(
                Contact.id == contact_id, Contact.company_id == company_id,
                Contact.is_active == True,  # noqa: E712
            )
        )
        c = result.scalar_one_or_none()
        if c is None:
            raise HTTPException(404, f"ไม่พบ contact id={contact_id}")
        return c

    async def _load_invoice(self, invoice_id: int, company_id: int) -> ARInvoice:
        result = await self._db.execute(
            select(ARInvoice).where(
                ARInvoice.id == invoice_id, ARInvoice.company_id == company_id,
            )
        )
        inv = result.scalar_one_or_none()
        if inv is None:
            raise HTTPException(404, f"ไม่พบ invoice id={invoice_id}")
        return inv

    async def _next_no(self, ctx: AppContext, d: date) -> str:
        ym = d.strftime("%Y%m")
        prefix = f"BN{ym}-"
        result = await self._db.execute(
            select(func.count(BillingNote.id)).where(
                BillingNote.company_id == ctx.company_id,
                BillingNote.billing_note_no.like(f"{prefix}%"),
            )
        )
        seq = (result.scalar_one() or 0) + 1
        return f"{prefix}{seq:04d}"


# ── Helper ────────────────────────────────────────────────────────────────────

def _to_out(bn: BillingNote) -> BillingNoteOut:
    return BillingNoteOut(
        id=bn.id,
        company_id=bn.company_id,
        billing_note_no=bn.billing_note_no,
        billing_date=bn.billing_date,
        due_date=bn.due_date,
        contact_id=bn.contact_id,
        contact_name=bn.contact.name if bn.contact else "",
        total_amount=bn.total_amount,
        status=bn.status,
        description=bn.description,
        invoice_ids=[lnk.invoice_id for lnk in (bn.invoice_links or [])],
        created_by=bn.created_by,
        created_at=bn.created_at,
    )
