"""AR Receipt Service — รับชำระหนี้จากลูกค้า (CR)."""

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
from app.modules.ar.models import ARInvoice, ARReceipt, ARReceiptAllocation, Contact
from app.modules.ar.schemas import (
    ReceiptAllocationOut,
    ReceiptCreate,
    ReceiptFilter,
    ReceiptOut,
)

_TWO = Decimal("0.01")

_PAID_STATUSES = {"paid", "cancelled"}


class ReceiptService:
    """
    บริการบันทึกการรับชำระหนี้จากลูกค้า.

    Journal (CR):
        Dr 1102  ธนาคาร        = total_received (เงินที่ได้รับจริง)
        Dr 1141  WHT ถูกหัก    = wht_amount (ถ้ามี)
          Cr 1110 ลูกหนี้      = total_applied (= total_received + wht_amount)
    """

    def __init__(self, session: AsyncSession) -> None:
        self._db = session

    # ── Create ────────────────────────────────────────────────────────────────

    async def create_receipt(self, data: ReceiptCreate, ctx: AppContext) -> ReceiptOut:
        """
        บันทึกการรับชำระหนี้.

        1. ตรวจ invoice ทั้งหมดที่ระบุใน allocations
        2. ตรวจยอด allocated ไม่เกิน balance ของ invoice
        3. สร้าง Journal Entry (CR)
        4. อัปเดต invoice.paid_amount / balance / status
        5. สร้าง ARReceipt + ARReceiptAllocation
        """
        if not ctx.can_post:
            raise HTTPException(403, "ไม่มีสิทธิ์บันทึกรายการ")

        # โหลด contact
        contact = await self._get_contact(data.contact_id, ctx.company_id)

        # โหลดและตรวจ invoices
        total_applied = Decimal(0)
        invoice_map: dict[int, ARInvoice] = {}

        for alloc in data.allocations:
            inv = await self._load_open_invoice(alloc.invoice_id, ctx.company_id)
            if inv.contact_id != data.contact_id:
                raise HTTPException(
                    400,
                    f"Invoice {inv.invoice_no} ไม่ใช่ของ contact นี้",
                )
            if alloc.allocated_amount > inv.balance:
                raise HTTPException(
                    422,
                    f"Invoice {inv.invoice_no}: ยอด match ({alloc.allocated_amount}) "
                    f"เกิน balance ({inv.balance})",
                )
            invoice_map[alloc.invoice_id] = inv
            total_applied += alloc.allocated_amount

        wht = data.wht_amount.quantize(_TWO, ROUND_HALF_UP)
        total_received = (total_applied - wht).quantize(_TWO, ROUND_HALF_UP)

        if total_received < 0:
            raise HTTPException(422, "wht_amount มากกว่ายอดรวม — ตรวจสอบอีกครั้ง")

        # สร้าง receipt_no
        receipt_no = await self._next_receipt_no(ctx, data.receipt_date)

        # สร้าง JournalEntry lines
        ar_account = contact.default_ar_account  # default 1110

        journal_lines: list[JournalLineInput] = []

        # Dr 1102 ธนาคาร
        journal_lines.append(JournalLineInput(
            account_code=data.bank_account_code,
            side=DrCr.DR,
            amount=total_received,
            description=f"รับชำระ {contact.name} | {receipt_no}",
        ))

        # Dr 1141 WHT (ถ้ามี)
        if wht > 0:
            journal_lines.append(JournalLineInput(
                account_code="1141",
                side=DrCr.DR,
                amount=wht,
                description=f"WHT ถูกหัก {contact.name} | {receipt_no}",
            ))

        # Cr 1110 ลูกหนี้
        journal_lines.append(JournalLineInput(
            account_code=ar_account,
            side=DrCr.CR,
            amount=total_applied,
            description=f"ลูกหนี้ {contact.name} | {receipt_no}",
        ))

        # รวม invoice numbers สำหรับ description
        inv_nos = ", ".join(invoice_map[a.invoice_id].invoice_no for a in data.allocations)

        entry_input = JournalEntryInput(
            journal_type=JournalType.CR,
            entry_date=data.receipt_date,
            description=data.description or f"รับชำระ {contact.name} {inv_nos}",
            lines=journal_lines,
            reference=data.reference or receipt_no,
            source_module="ar",
        )

        engine = PostingEngine(self._db)
        try:
            entry_no = await engine.post(entry_input, ctx)
        except PostingPermissionError as e:
            raise HTTPException(403, str(e))
        except Exception as e:
            raise HTTPException(422, str(e))

        # บันทึก Receipt
        receipt = ARReceipt(
            company_id=ctx.company_id,
            branch_id=ctx.branch_id,
            receipt_no=receipt_no,
            receipt_date=data.receipt_date,
            contact_id=data.contact_id,
            bank_account_code=data.bank_account_code,
            total_received=total_received,
            wht_amount=wht,
            total_applied=total_applied,
            status="posted",
            description=data.description,
            reference=data.reference,
            journal_entry_no=entry_no,
            created_by=ctx.user_id,
        )
        self._db.add(receipt)
        await self._db.flush()

        # สร้าง allocations และ update invoice
        alloc_records: list[ARReceiptAllocation] = []
        for alloc in data.allocations:
            inv = invoice_map[alloc.invoice_id]
            inv.paid_amount = (inv.paid_amount + alloc.allocated_amount).quantize(_TWO)
            inv.balance = (inv.balance - alloc.allocated_amount).quantize(_TWO)

            if inv.balance <= 0:
                inv.status = "paid"
            elif inv.paid_amount > 0:
                inv.status = "partially_paid"

            alloc_records.append(ARReceiptAllocation(
                receipt_id=receipt.id,
                invoice_id=alloc.invoice_id,
                allocated_amount=alloc.allocated_amount,
            ))

        self._db.add_all(alloc_records)
        await self._db.flush()

        return _receipt_to_out(receipt, contact, alloc_records, invoice_map)

    # ── List ──────────────────────────────────────────────────────────────────

    async def list_receipts(
        self, ctx: AppContext, filters: ReceiptFilter
    ) -> tuple[list[ReceiptOut], int]:
        stmt = (
            select(ARReceipt)
            .where(ARReceipt.company_id == ctx.company_id)
            .options(
                selectinload(ARReceipt.contact),
                selectinload(ARReceipt.allocations),
            )
        )

        if filters.contact_id:
            stmt = stmt.where(ARReceipt.contact_id == filters.contact_id)
        if filters.date_from:
            stmt = stmt.where(ARReceipt.receipt_date >= filters.date_from)
        if filters.date_to:
            stmt = stmt.where(ARReceipt.receipt_date <= filters.date_to)
        if filters.search:
            like = f"%{filters.search}%"
            stmt = stmt.join(Contact, ARReceipt.contact_id == Contact.id).where(
                ARReceipt.receipt_no.ilike(like) | Contact.name.ilike(like)
            )

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await self._db.execute(count_stmt)).scalar_one()

        stmt = stmt.order_by(ARReceipt.receipt_date.desc()).limit(filters.limit).offset(filters.offset)
        rows = (await self._db.execute(stmt)).scalars().all()

        # โหลด invoice_no สำหรับ allocations
        results = []
        for rec in rows:
            inv_map: dict[int, ARInvoice] = {}
            for a in rec.allocations:
                inv_r = await self._db.execute(
                    select(ARInvoice).where(ARInvoice.id == a.invoice_id)
                )
                inv = inv_r.scalar_one_or_none()
                if inv:
                    inv_map[a.invoice_id] = inv
            results.append(_receipt_to_out(rec, rec.contact, rec.allocations, inv_map))

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

    async def _load_open_invoice(self, invoice_id: int, company_id: int) -> ARInvoice:
        result = await self._db.execute(
            select(ARInvoice).where(
                ARInvoice.id == invoice_id,
                ARInvoice.company_id == company_id,
            )
        )
        inv = result.scalar_one_or_none()
        if inv is None:
            raise HTTPException(404, f"ไม่พบ invoice id={invoice_id}")
        if inv.status in _PAID_STATUSES:
            raise HTTPException(409, f"Invoice {inv.invoice_no} สถานะ {inv.status} ไม่สามารถรับชำระได้")
        return inv

    async def _next_receipt_no(self, ctx: AppContext, entry_date: "date") -> str:  # noqa: F821
        from datetime import date
        ym = entry_date.strftime("%Y%m")
        prefix = f"RCP{ym}-"
        result = await self._db.execute(
            select(func.count(ARReceipt.id)).where(
                ARReceipt.company_id == ctx.company_id,
                ARReceipt.receipt_no.like(f"{prefix}%"),
            )
        )
        seq = (result.scalar_one() or 0) + 1
        return f"{prefix}{seq:04d}"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _receipt_to_out(
    rec: ARReceipt,
    contact: Contact,
    allocs: list[ARReceiptAllocation],
    inv_map: dict[int, ARInvoice],
) -> ReceiptOut:
    alloc_outs = [
        ReceiptAllocationOut(
            id=a.id,
            invoice_id=a.invoice_id,
            invoice_no=inv_map[a.invoice_id].invoice_no if a.invoice_id in inv_map else "",
            allocated_amount=a.allocated_amount,
        )
        for a in allocs
    ]
    return ReceiptOut(
        id=rec.id,
        company_id=rec.company_id,
        branch_id=rec.branch_id,
        receipt_no=rec.receipt_no,
        receipt_date=rec.receipt_date,
        contact_id=rec.contact_id,
        contact_name=contact.name,
        bank_account_code=rec.bank_account_code,
        total_received=rec.total_received,
        wht_amount=rec.wht_amount,
        total_applied=rec.total_applied,
        status=rec.status,
        description=rec.description,
        reference=rec.reference,
        journal_entry_no=rec.journal_entry_no,
        allocations=alloc_outs,
        created_by=rec.created_by,
        created_at=rec.created_at,
    )
