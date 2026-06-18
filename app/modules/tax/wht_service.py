"""TAX — WHT Service (get_wht_summary / generate_certificate / post_wht_payment)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import select, func as sqlfunc
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.tax.models import WHTRecord
from app.modules.tax.schemas import (
    PostWHTPaymentIn,
    WHTCertificateOut,
    WHTPaymentResult,
    WHTRecordCreate,
    WHTRecordOut,
    WHTSummaryItem,
)
from app.modules.ar.models import Contact
from app.core.context import AppContext
from app.core.posting_engine import PostingEngine, JournalLineIn


class WHTService:

    @staticmethod
    async def create_wht_record(
        data: WHTRecordCreate, ctx: AppContext, db: AsyncSession
    ) -> WHTRecordOut:
        """บันทึก WHT record รายการ."""
        rec = WHTRecord(
            company_id=ctx.company_id,
            branch_id=ctx.branch_id,
            direction=data.direction,
            contact_id=data.contact_id,
            income_type=data.income_type,
            wht_type=data.wht_type,
            payment_date=data.payment_date,
            fiscal_year=data.payment_date.year,
            month=data.payment_date.month,
            base_amount=data.base_amount,
            wht_rate=data.wht_rate,
            wht_amount=data.wht_amount,
            source_module=data.source_module,
            source_id=data.source_id,
            journal_entry_no=data.journal_entry_no,
        )
        db.add(rec)
        await db.flush()
        await db.refresh(rec)
        return WHTRecordOut.model_validate(rec)

    @staticmethod
    async def get_wht_summary(
        ctx: AppContext,
        db: AsyncSession,
        fiscal_year: int,
        month: int,
        direction: str = "collected",
    ) -> list[WHTSummaryItem]:
        """สรุป WHT รายผู้รับเงิน/ผู้จ่ายเงิน."""
        rows = await db.execute(
            select(
                WHTRecord.contact_id,
                WHTRecord.income_type,
                WHTRecord.wht_type,
                sqlfunc.sum(WHTRecord.base_amount).label("total_base"),
                sqlfunc.sum(WHTRecord.wht_amount).label("total_wht"),
                sqlfunc.count(WHTRecord.id).label("record_count"),
            ).where(
                WHTRecord.company_id == ctx.company_id,
                WHTRecord.direction == direction,
                WHTRecord.fiscal_year == fiscal_year,
                WHTRecord.month == month,
            ).group_by(
                WHTRecord.contact_id,
                WHTRecord.income_type,
                WHTRecord.wht_type,
            )
        )

        results: list[WHTSummaryItem] = []
        for r in rows:
            contact = await db.scalar(
                select(Contact).where(Contact.id == r.contact_id)
            )
            results.append(WHTSummaryItem(
                contact_id=r.contact_id,
                contact_name=contact.name if contact else str(r.contact_id),
                tax_id=contact.tax_id if contact else None,
                income_type=r.income_type,
                wht_type=r.wht_type,
                total_base=r.total_base or Decimal(0),
                total_wht=r.total_wht or Decimal(0),
                record_count=r.record_count,
            ))

        return results

    @staticmethod
    async def generate_certificate(
        ctx: AppContext,
        db: AsyncSession,
        contact_id: int,
        fiscal_year: int,
        month: int,
        direction: str = "collected",
    ) -> WHTCertificateOut:
        """ออกหนังสือรับรองหัก ณ ที่จ่าย (50 ทวิ)."""
        rows = await db.scalars(
            select(WHTRecord).where(
                WHTRecord.company_id == ctx.company_id,
                WHTRecord.contact_id == contact_id,
                WHTRecord.direction == direction,
                WHTRecord.fiscal_year == fiscal_year,
                WHTRecord.month == month,
            ).order_by(WHTRecord.payment_date)
        )
        records = list(rows)
        if not records:
            raise ValueError("ไม่พบรายการ WHT สำหรับผู้รับเงินและงวดที่ระบุ")

        contact = await db.scalar(select(Contact).where(Contact.id == contact_id))

        # Generate certificate_no สำหรับทุก record ที่ยังไม่มี
        cert_no = f"WHT-{ctx.company_id}-{fiscal_year}{month:02d}-{contact_id:04d}"
        for rec in records:
            if not rec.certificate_no:
                rec.certificate_no = cert_no
        await db.flush()

        total_base = sum(r.base_amount for r in records)
        total_wht = sum(r.wht_amount for r in records)

        return WHTCertificateOut(
            certificate_no=cert_no,
            contact_name=contact.name if contact else str(contact_id),
            contact_tax_id=contact.tax_id if contact else None,
            contact_address=None,
            payer_name=f"Company {ctx.company_id}",
            payer_tax_id=None,
            records=[WHTRecordOut.model_validate(r) for r in records],
            total_base=total_base,
            total_wht=total_wht,
            issued_date=date.today(),
        )

    @staticmethod
    async def post_wht_payment(
        data: PostWHTPaymentIn, ctx: AppContext, db: AsyncSession
    ) -> WHTPaymentResult:
        """นำส่ง WHT ให้กรมสรรพากร — Dr 2121 | Cr 1102 (CP)."""
        if ctx.user_role not in ("firm_admin", "accountant"):
            raise PermissionError("ต้องการสิทธิ์ accountant ขึ้นไป")

        q = select(WHTRecord).where(
            WHTRecord.company_id == ctx.company_id,
            WHTRecord.direction == "collected",
            WHTRecord.fiscal_year == data.fiscal_year,
            WHTRecord.month == data.month,
            WHTRecord.is_submitted.is_(False),
        )
        if data.wht_record_ids:
            q = q.where(WHTRecord.id.in_(data.wht_record_ids))

        rows = await db.scalars(q)
        records = list(rows)

        if not records:
            raise ValueError("ไม่มีรายการ WHT ที่ยังไม่ได้นำส่งในงวดนี้")

        total_wht = sum(r.wht_amount for r in records)
        period_str = f"{data.fiscal_year}{data.month:02d}"

        lines = [
            JournalLineIn(account_code="2121", dr_cr="DR", amount=total_wht),
            JournalLineIn(account_code=data.bank_account_code, dr_cr="CR", amount=total_wht),
        ]
        je = await PostingEngine(db).post(
            ctx=ctx,
            journal_type="CP",
            lines=lines,
            description=f"นำส่ง WHT งวด {period_str}",
            source_module="TAX",
            source_id=None,
        )

        for rec in records:
            rec.is_submitted = True
            rec.submitted_period = period_str
            rec.submitted_journal_no = je.entry_no

        await db.flush()

        return WHTPaymentResult(
            journal_entry_no=je.entry_no,
            total_wht_paid=total_wht,
            record_count=len(records),
            period=period_str,
        )

    @staticmethod
    async def list_wht_records(
        ctx: AppContext,
        db: AsyncSession,
        direction: str | None = None,
        fiscal_year: int | None = None,
        month: int | None = None,
        contact_id: int | None = None,
    ) -> list[WHTRecordOut]:
        q = select(WHTRecord).where(WHTRecord.company_id == ctx.company_id)
        if direction:
            q = q.where(WHTRecord.direction == direction)
        if fiscal_year:
            q = q.where(WHTRecord.fiscal_year == fiscal_year)
        if month:
            q = q.where(WHTRecord.month == month)
        if contact_id:
            q = q.where(WHTRecord.contact_id == contact_id)
        q = q.order_by(WHTRecord.payment_date.desc())
        rows = await db.scalars(q)
        return [WHTRecordOut.model_validate(r) for r in rows]
