"""AR Sales Service — Invoice lifecycle (SJ)."""

from __future__ import annotations

from datetime import date
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
from app.modules.ar.models import ARInvoice, ARInvoiceLine, Contact
from app.modules.ar.schemas import (
    InvoiceCreate,
    InvoiceDetail,
    InvoiceFilter,
    InvoiceLineOut,
    InvoiceOut,
)

_TWO = Decimal("0.01")


class InvoiceService:
    """
    บริการจัดการ Invoice ลูกหนี้การค้า.

    Journal (SJ):
        Dr 1110  ลูกหนี้การค้า  = subtotal + vat
          Cr [revenue accounts]     subtotal (แบ่งตาม lines)
          Cr 2120 ภาษีขาย           vat_amount
    """

    def __init__(self, session: AsyncSession) -> None:
        self._db = session

    # ── Create ────────────────────────────────────────────────────────────────

    async def create_invoice(self, data: InvoiceCreate, ctx: AppContext) -> InvoiceDetail:
        """
        สร้าง Invoice และ post Journal Entry (SJ).

        1. ตรวจสิทธิ์ (can_post)
        2. โหลด Contact → credit_days, wht_rate, default_ar_account
        3. คำนวณ subtotal / vat / total
        4. บันทึก ARInvoice + ARInvoiceLine
        5. สร้าง JournalEntry ผ่าน PostingEngine
        6. อัปเดต journal_entry_no
        """
        if not ctx.can_post:
            raise HTTPException(403, "ไม่มีสิทธิ์บันทึกรายการ")

        # โหลด contact (optional สำหรับ cash)
        contact = None
        if data.contact_id:
            contact = await self._get_contact(data.contact_id, ctx.company_id)

        # due_date
        if data.payment_mode == "cash":
            due_date = data.invoice_date
        elif data.due_date:
            due_date = data.due_date
        elif contact:
            due_date = _add_days(data.invoice_date, contact.credit_days)
        else:
            due_date = data.invoice_date

        # คำนวณยอด
        subtotal = Decimal(0)
        vat_amount = Decimal(0)
        line_records: list[ARInvoiceLine] = []

        for i, ln in enumerate(data.lines, start=1):
            amt = (ln.quantity * ln.unit_price).quantize(_TWO, ROUND_HALF_UP)
            vat_r = Decimal(0) if data.vat_exempt else ln.vat_rate
            vat_a = (amt * vat_r / 100).quantize(_TWO, ROUND_HALF_UP)
            subtotal += amt
            vat_amount += vat_a
            line_records.append(ARInvoiceLine(
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

        total = subtotal + vat_amount
        wht_amount = Decimal(0)
        if contact and contact.wht_rate:
            wht_amount = (subtotal * contact.wht_rate / 100).quantize(_TWO, ROUND_HALF_UP)

        # สร้าง invoice number
        invoice_no = await self._next_invoice_no(ctx, data.invoice_date)

        contact_name = contact.name if contact else "ลูกค้าทั่วไป"

        # กำหนด status เริ่มต้น — cash = paid ทันที, credit = draft
        initial_status = "paid" if data.payment_mode == "cash" else "draft"
        initial_paid = total if data.payment_mode == "cash" else Decimal(0)
        initial_balance = Decimal(0) if data.payment_mode == "cash" else total

        # บันทึก Invoice ORM
        invoice = ARInvoice(
            company_id=ctx.company_id,
            branch_id=ctx.branch_id,
            invoice_no=invoice_no,
            invoice_date=data.invoice_date,
            due_date=due_date,
            contact_id=contact.id if contact else None,
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
            reference=data.reference,
            created_by=ctx.user_id,
        )
        invoice.lines = line_records
        self._db.add(invoice)
        await self._db.flush()  # ได้ invoice.id

        # สร้าง JournalEntry lines
        journal_lines: list[JournalLineInput] = []

        if data.payment_mode == "cash":
            # Cash sale: Dr เงินสด/ธนาคาร | Cr รายได้ + Cr ภาษีขาย
            # journal_type = CR (รับเงิน)
            journal_lines.append(JournalLineInput(
                account_code=data.payment_account_code,
                side=DrCr.DR,
                amount=total,
                description=f"รับเงินสด {contact_name} | {invoice_no}",
            ))

            # Cr revenue lines
            rev_by_account: dict[str, Decimal] = {}
            for lr in line_records:
                rev_by_account[lr.account_code] = (
                    rev_by_account.get(lr.account_code, Decimal(0)) + lr.amount
                )
            for acc_code, acc_total in rev_by_account.items():
                journal_lines.append(JournalLineInput(
                    account_code=acc_code,
                    side=DrCr.CR,
                    amount=acc_total,
                    description=f"รายได้ {invoice_no}",
                ))

            if vat_amount > 0:
                journal_lines.append(JournalLineInput(
                    account_code="2120",
                    side=DrCr.CR,
                    amount=vat_amount,
                    description=f"ภาษีขาย {invoice_no}",
                ))

            journal_type = JournalType.CR

        else:
            # Credit sale: Dr ลูกหนี้ | Cr รายได้ + Cr ภาษีขาย
            # journal_type = SJ
            ar_account = contact.default_ar_account if contact else "1110"
            journal_lines.append(JournalLineInput(
                account_code=ar_account,
                side=DrCr.DR,
                amount=total,
                description=f"ลูกหนี้ {contact_name} | {invoice_no}",
            ))

            rev_by_account: dict[str, Decimal] = {}
            for lr in line_records:
                rev_by_account[lr.account_code] = (
                    rev_by_account.get(lr.account_code, Decimal(0)) + lr.amount
                )
            for acc_code, acc_total in rev_by_account.items():
                journal_lines.append(JournalLineInput(
                    account_code=acc_code,
                    side=DrCr.CR,
                    amount=acc_total,
                    description=f"รายได้ {invoice_no}",
                ))

            if vat_amount > 0:
                journal_lines.append(JournalLineInput(
                    account_code="2120",
                    side=DrCr.CR,
                    amount=vat_amount,
                    description=f"ภาษีขาย {invoice_no}",
                ))

            journal_type = JournalType.SJ

        entry_input = JournalEntryInput(
            journal_type=journal_type,
            entry_date=data.invoice_date,
            description=data.description or f"ขาย {contact_name} | {invoice_no}",
            lines=journal_lines,
            reference=invoice_no,
            source_module="ar",
            source_id=invoice.id,
        )

        engine = PostingEngine(self._db)
        try:
            entry_no = await engine.post(entry_input, ctx)
        except PostingPermissionError as e:
            raise HTTPException(403, str(e))
        except Exception as e:
            raise HTTPException(422, str(e))

        # อัปเดต journal_entry_no (status ถูก set ตาม payment_mode แล้ว)
        invoice.journal_entry_no = entry_no
        if data.payment_mode == "credit":
            invoice.status = "posted"
        await self._db.flush()

        return await self._to_detail(invoice, contact)

    # ── List ──────────────────────────────────────────────────────────────────

    async def list_invoices(
        self, ctx: AppContext, filters: InvoiceFilter
    ) -> tuple[list[InvoiceOut], int]:
        """คืน (invoices, total_count) ตาม filter."""
        stmt = (
            select(ARInvoice)
            .where(ARInvoice.company_id == ctx.company_id)
            .options(selectinload(ARInvoice.contact))
        )

        if filters.contact_id:
            stmt = stmt.where(ARInvoice.contact_id == filters.contact_id)
        if filters.status:
            stmt = stmt.where(ARInvoice.status == filters.status)
        if filters.date_from:
            stmt = stmt.where(ARInvoice.invoice_date >= filters.date_from)
        if filters.date_to:
            stmt = stmt.where(ARInvoice.invoice_date <= filters.date_to)
        if filters.overdue_only:
            stmt = stmt.where(
                ARInvoice.status.not_in(["paid", "cancelled"]),
                ARInvoice.due_date < date.today(),
            )
        if filters.search:
            like = f"%{filters.search}%"
            stmt = stmt.join(Contact, ARInvoice.contact_id == Contact.id).where(
                ARInvoice.invoice_no.ilike(like) | Contact.name.ilike(like)
            )

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await self._db.execute(count_stmt)).scalar_one()

        stmt = stmt.order_by(ARInvoice.invoice_date.desc(), ARInvoice.invoice_no.desc())
        stmt = stmt.limit(filters.limit).offset(filters.offset)
        rows = (await self._db.execute(stmt)).scalars().all()

        return [_invoice_to_out(inv) for inv in rows], total

    # ── Get ───────────────────────────────────────────────────────────────────

    async def get_invoice(self, invoice_id: int, ctx: AppContext) -> InvoiceDetail:
        invoice = await self._load_invoice(invoice_id, ctx.company_id)
        contact = None
        if invoice.contact_id:
            contact = await self._get_contact(invoice.contact_id, ctx.company_id)
        return await self._to_detail(invoice, contact)

    # ── Cancel ────────────────────────────────────────────────────────────────

    async def cancel_invoice(
        self, invoice_id: int, reason: str, ctx: AppContext
    ) -> str:
        """
        ยกเลิก Invoice → สร้าง Reversing Entry.

        คืน reversing entry_no
        """
        if not ctx.can_approve:
            raise HTTPException(403, "ต้องเป็น accountant ขึ้นไปเพื่อยกเลิก invoice")

        invoice = await self._load_invoice(invoice_id, ctx.company_id)

        if invoice.status == "cancelled":
            raise HTTPException(409, f"Invoice {invoice.invoice_no} ถูกยกเลิกแล้ว")
        if invoice.status == "paid":
            raise HTTPException(409, f"Invoice {invoice.invoice_no} ชำระครบแล้ว ยกเลิกไม่ได้")
        if invoice.paid_amount > 0:
            raise HTTPException(
                409,
                f"Invoice {invoice.invoice_no} มีการชำระบางส่วนแล้ว ({invoice.paid_amount})"
                " กรุณายกเลิกใบรับเงินก่อน",
            )
        if not invoice.journal_entry_no:
            raise HTTPException(400, "ไม่พบเลขที่ journal สำหรับ invoice นี้")

        editor = EditorService(self._db)
        rev_no = await editor.reverse(invoice.journal_entry_no, reason, ctx)

        invoice.status = "cancelled"
        await self._db.flush()

        return rev_no

    # ── Contact helper ────────────────────────────────────────────────────────

    async def create_contact(self, data: "ContactCreate", ctx: AppContext) -> Contact:  # noqa: F821
        from app.modules.ar.schemas import ContactCreate
        contact = Contact(
            company_id=ctx.company_id,
            **data.model_dump(),
        )
        self._db.add(contact)
        await self._db.flush()
        return contact

    async def list_contacts(
        self, ctx: AppContext, contact_type: Optional[str] = None, active_only: bool = True
    ) -> list[Contact]:
        stmt = select(Contact).where(Contact.company_id == ctx.company_id)
        if contact_type:
            stmt = stmt.where(Contact.contact_type == contact_type)
        if active_only:
            stmt = stmt.where(Contact.is_active == True)  # noqa: E712
        stmt = stmt.order_by(Contact.name)
        return list((await self._db.execute(stmt)).scalars().all())

    async def get_contact(self, contact_id: int, ctx: AppContext) -> Contact:
        return await self._get_contact(contact_id, ctx.company_id)

    async def update_contact(
        self, contact_id: int, data: "ContactUpdate", ctx: AppContext  # noqa: F821
    ) -> Contact:
        contact = await self._get_contact(contact_id, ctx.company_id)
        from app.modules.ar.schemas import ContactUpdate
        for k, v in data.model_dump(exclude_none=True).items():
            setattr(contact, k, v)
        await self._db.flush()
        return contact

    # ── Privates ──────────────────────────────────────────────────────────────

    async def _get_contact(self, contact_id: int, company_id: int) -> Contact:
        result = await self._db.execute(
            select(Contact).where(
                Contact.id == contact_id,
                Contact.company_id == company_id,
                Contact.is_active == True,  # noqa: E712
            )
        )
        contact = result.scalar_one_or_none()
        if contact is None:
            raise HTTPException(404, f"ไม่พบ contact id={contact_id}")
        return contact

    async def _load_invoice(self, invoice_id: int, company_id: int) -> ARInvoice:
        result = await self._db.execute(
            select(ARInvoice)
            .where(ARInvoice.id == invoice_id, ARInvoice.company_id == company_id)
            .options(selectinload(ARInvoice.lines), selectinload(ARInvoice.contact))
        )
        inv = result.scalar_one_or_none()
        if inv is None:
            raise HTTPException(404, f"ไม่พบ invoice id={invoice_id}")
        return inv

    async def _next_invoice_no(self, ctx: AppContext, entry_date: date) -> str:
        ym = entry_date.strftime("%Y%m")
        prefix = f"INV{ym}-"
        result = await self._db.execute(
            select(func.count(ARInvoice.id)).where(
                ARInvoice.company_id == ctx.company_id,
                ARInvoice.invoice_no.like(f"{prefix}%"),
            )
        )
        seq = (result.scalar_one() or 0) + 1
        return f"{prefix}{seq:04d}"

    async def _to_detail(self, invoice: ARInvoice, contact: Contact) -> InvoiceDetail:
        lines_out = [
            InvoiceLineOut(
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
            for ln in (invoice.lines or [])
        ]
        from app.modules.ar.schemas import ContactOut, InvoiceDetail
        return InvoiceDetail(
            id=invoice.id,
            company_id=invoice.company_id,
            branch_id=invoice.branch_id,
            invoice_no=invoice.invoice_no,
            invoice_date=invoice.invoice_date,
            due_date=invoice.due_date,
            contact_id=invoice.contact_id,
            contact_name=contact.name if contact else "ลูกค้าทั่วไป",
            payment_mode=invoice.payment_mode,
            payment_account_code=invoice.payment_account_code,
            subtotal=invoice.subtotal,
            vat_amount=invoice.vat_amount,
            wht_amount=invoice.wht_amount,
            total_amount=invoice.total_amount,
            paid_amount=invoice.paid_amount,
            balance=invoice.balance,
            status=invoice.status,
            description=invoice.description,
            reference=invoice.reference,
            journal_entry_no=invoice.journal_entry_no,
            is_overdue=invoice.is_overdue,
            created_by=invoice.created_by,
            created_at=invoice.created_at,
            lines=lines_out,
            contact=ContactOut.model_validate(contact) if contact else None,
        )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _add_days(d: date, days: int) -> date:
    from datetime import timedelta
    return d + timedelta(days=days)


def _invoice_to_out(inv: ARInvoice) -> InvoiceOut:
    return InvoiceOut(
        id=inv.id,
        company_id=inv.company_id,
        branch_id=inv.branch_id,
        invoice_no=inv.invoice_no,
        invoice_date=inv.invoice_date,
        due_date=inv.due_date,
        contact_id=inv.contact_id,
        contact_name=inv.contact.name if inv.contact else "ลูกค้าทั่วไป",
        payment_mode=getattr(inv, "payment_mode", "credit"),
        payment_account_code=getattr(inv, "payment_account_code", None),
        subtotal=inv.subtotal,
        vat_amount=inv.vat_amount,
        wht_amount=inv.wht_amount,
        total_amount=inv.total_amount,
        paid_amount=inv.paid_amount,
        balance=inv.balance,
        status=inv.status,
        description=inv.description,
        reference=inv.reference,
        journal_entry_no=inv.journal_entry_no,
        is_overdue=inv.is_overdue,
        created_by=inv.created_by,
        created_at=inv.created_at,
    )
