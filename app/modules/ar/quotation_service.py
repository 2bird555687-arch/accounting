"""AR Quotation Service — ใบเสนอราคา + แปลงเป็น Invoice."""

from __future__ import annotations

from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from fastapi import HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.context import AppContext
from app.modules.ar.models import ARInvoice, Contact, Quotation, QuotationLine

_TWO = Decimal("0.01")


# ── Schemas ───────────────────────────────────────────────────────────────────

class QuotationLineCreate(BaseModel):
    description: str
    account_code: str
    unit: Optional[str] = None
    quantity: Decimal = Decimal(1)
    unit_price: Decimal = Decimal(0)
    vat_rate: Decimal = Decimal("7")


class QuotationCreate(BaseModel):
    contact_id: int
    quotation_date: date
    valid_until: Optional[date] = None  # default: +30 days
    lines: list[QuotationLineCreate]
    description: Optional[str] = None
    reference: Optional[str] = None
    vat_exempt: bool = False


class QuotationLineOut(BaseModel):
    id: int
    line_no: int
    description: str
    account_code: str
    unit: Optional[str]
    quantity: Decimal
    unit_price: Decimal
    amount: Decimal
    vat_rate: Decimal
    vat_amount: Decimal

    model_config = {"from_attributes": True}


class QuotationOut(BaseModel):
    id: int
    company_id: int
    quotation_no: str
    quotation_date: date
    valid_until: date
    contact_id: int
    contact_name: str
    subtotal: Decimal
    vat_amount: Decimal
    total_amount: Decimal
    status: str
    description: Optional[str]
    reference: Optional[str]
    converted_invoice_id: Optional[int]
    lines: list[QuotationLineOut]
    created_by: int
    created_at: object
    is_expired: bool

    model_config = {"from_attributes": True}


# ── Service ───────────────────────────────────────────────────────────────────

class QuotationService:
    """บริการจัดการใบเสนอราคา."""

    def __init__(self, session: AsyncSession) -> None:
        self._db = session

    # ── Create ────────────────────────────────────────────────────────────────

    async def create_quotation(
        self, data: QuotationCreate, ctx: AppContext
    ) -> QuotationOut:
        """สร้างใบเสนอราคาใหม่ (ไม่ post Journal)."""
        if not ctx.can_post:
            raise HTTPException(403, "ไม่มีสิทธิ์บันทึกรายการ")

        contact = await self._get_contact(data.contact_id, ctx.company_id)

        from datetime import timedelta
        valid_until = data.valid_until or (data.quotation_date + timedelta(days=30))

        subtotal = Decimal(0)
        vat_total = Decimal(0)
        line_records: list[QuotationLine] = []

        for i, ln in enumerate(data.lines, start=1):
            amt = (ln.quantity * ln.unit_price).quantize(_TWO, ROUND_HALF_UP)
            vat_r = Decimal(0) if data.vat_exempt else ln.vat_rate
            vat_a = (amt * vat_r / 100).quantize(_TWO, ROUND_HALF_UP)
            subtotal += amt
            vat_total += vat_a
            line_records.append(QuotationLine(
                line_no=i,
                description=ln.description,
                account_code=ln.account_code,
                unit=ln.unit,
                quantity=ln.quantity,
                unit_price=ln.unit_price,
                amount=amt,
                vat_rate=vat_r,
                vat_amount=vat_a,
            ))

        total = subtotal + vat_total
        quotation_no = await self._next_no(ctx, data.quotation_date)

        quotation = Quotation(
            company_id=ctx.company_id,
            branch_id=ctx.branch_id,
            quotation_no=quotation_no,
            quotation_date=data.quotation_date,
            valid_until=valid_until,
            contact_id=data.contact_id,
            subtotal=subtotal,
            vat_amount=vat_total,
            total_amount=total,
            status="draft",
            description=data.description,
            reference=data.reference,
            created_by=ctx.user_id,
        )
        quotation.lines = line_records
        self._db.add(quotation)
        await self._db.flush()

        return _to_out(quotation, contact)

    # ── List ──────────────────────────────────────────────────────────────────

    async def list_quotations(
        self, ctx: AppContext,
        contact_id: Optional[int] = None,
        status: Optional[str] = None,
        page: int = 1, page_size: int = 50,
    ) -> tuple[list[QuotationOut], int]:
        stmt = (
            select(Quotation)
            .where(Quotation.company_id == ctx.company_id)
            .options(selectinload(Quotation.contact), selectinload(Quotation.lines))
        )
        if contact_id:
            stmt = stmt.where(Quotation.contact_id == contact_id)
        if status:
            stmt = stmt.where(Quotation.status == status)

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await self._db.execute(count_stmt)).scalar_one()

        stmt = stmt.order_by(Quotation.quotation_date.desc())
        stmt = stmt.limit(page_size).offset((page - 1) * page_size)
        rows = (await self._db.execute(stmt)).scalars().all()

        return [_to_out(q, q.contact) for q in rows], total

    # ── Get ───────────────────────────────────────────────────────────────────

    async def get_quotation(self, quotation_id: int, ctx: AppContext) -> QuotationOut:
        q = await self._load_quotation(quotation_id, ctx.company_id)
        contact = await self._get_contact(q.contact_id, ctx.company_id)
        return _to_out(q, contact)

    # ── Convert to Invoice ────────────────────────────────────────────────────

    async def convert_to_invoice(
        self, quotation_id: int, ctx: AppContext
    ) -> ARInvoice:
        """
        แปลง Quotation → ARInvoice และ post Journal Entry (SJ).

        คืน ARInvoice ที่สร้างแล้ว (ผ่าน InvoiceService)
        """
        if not ctx.can_post:
            raise HTTPException(403, "ไม่มีสิทธิ์บันทึกรายการ")

        q = await self._load_quotation(quotation_id, ctx.company_id)

        if q.status == "converted":
            raise HTTPException(409, f"Quotation {q.quotation_no} แปลงเป็น Invoice แล้ว")
        if q.status == "cancelled":
            raise HTTPException(409, f"Quotation {q.quotation_no} ถูกยกเลิกแล้ว")

        # สร้าง Invoice ผ่าน InvoiceService
        from app.modules.ar.sales_service import InvoiceService
        from app.modules.ar.schemas import InvoiceCreate, InvoiceLineCreate

        invoice_data = InvoiceCreate(
            contact_id=q.contact_id,
            invoice_date=date.today(),
            lines=[
                InvoiceLineCreate(
                    description=ln.description,
                    account_code=ln.account_code,
                    unit=ln.unit,
                    quantity=ln.quantity,
                    unit_price=ln.unit_price,
                    vat_rate=ln.vat_rate,
                )
                for ln in q.lines
            ],
            description=q.description or f"แปลงจาก {q.quotation_no}",
            reference=q.quotation_no,
        )

        svc = InvoiceService(self._db)
        invoice_detail = await svc.create_invoice(invoice_data, ctx)

        # อัปเดต quotation
        q.status = "converted"
        q.converted_invoice_id = invoice_detail.id
        await self._db.flush()

        # คืน invoice detail (เป็น InvoiceDetail schema)
        return invoice_detail

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

    async def _load_quotation(self, quotation_id: int, company_id: int) -> Quotation:
        result = await self._db.execute(
            select(Quotation)
            .where(Quotation.id == quotation_id, Quotation.company_id == company_id)
            .options(selectinload(Quotation.lines), selectinload(Quotation.contact))
        )
        q = result.scalar_one_or_none()
        if q is None:
            raise HTTPException(404, f"ไม่พบใบเสนอราคา id={quotation_id}")
        return q

    async def _next_no(self, ctx: AppContext, d: date) -> str:
        ym = d.strftime("%Y%m")
        prefix = f"QT{ym}-"
        result = await self._db.execute(
            select(func.count(Quotation.id)).where(
                Quotation.company_id == ctx.company_id,
                Quotation.quotation_no.like(f"{prefix}%"),
            )
        )
        seq = (result.scalar_one() or 0) + 1
        return f"{prefix}{seq:04d}"


# ── Helper ────────────────────────────────────────────────────────────────────

def _to_out(q: Quotation, contact: Optional[Contact]) -> QuotationOut:
    lines_out = [
        QuotationLineOut(
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
        for ln in (q.lines or [])
    ]
    return QuotationOut(
        id=q.id,
        company_id=q.company_id,
        quotation_no=q.quotation_no,
        quotation_date=q.quotation_date,
        valid_until=q.valid_until,
        contact_id=q.contact_id,
        contact_name=contact.name if contact else "",
        subtotal=q.subtotal,
        vat_amount=q.vat_amount,
        total_amount=q.total_amount,
        status=q.status,
        description=q.description,
        reference=q.reference,
        converted_invoice_id=q.converted_invoice_id,
        lines=lines_out,
        created_by=q.created_by,
        created_at=q.created_at,
        is_expired=q.is_expired,
    )
