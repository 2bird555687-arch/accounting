"""Balance Tracker — AR/AP aging report."""

from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.context import AppContext
from app.master.schemas import AgingBucket
from app.modules.ar.models import ARInvoice, Contact
from app.modules.ap.models import APPurchase


class BalanceTrackerService:

    @staticmethod
    async def get_aging_ar(
        ctx: AppContext, db: AsyncSession, as_of_date: date | None = None
    ) -> list[AgingBucket]:
        """AR Aging — ลูกหนี้การค้า แบ่งตามวันค้างชำระ."""
        as_of = as_of_date or date.today()

        unpaid = await db.scalars(
            select(ARInvoice).where(
                ARInvoice.company_id == ctx.company_id,
                ARInvoice.status.in_(["posted", "partially_paid"]),
                ARInvoice.balance > 0,
            )
        )

        buckets: dict[int, AgingBucket] = {}
        for inv in unpaid:
            days = (as_of - inv.due_date).days
            cid = inv.contact_id
            if cid not in buckets:
                contact = await db.scalar(select(Contact).where(Contact.id == cid))
                buckets[cid] = AgingBucket(
                    contact_id=cid,
                    contact_name=contact.name if contact else str(cid),
                    current=0, overdue_1_30=0, overdue_31_60=0,
                    overdue_61_90=0, overdue_90_plus=0, total=0,
                )
            b = buckets[cid]
            bal = inv.balance
            if days <= 0:
                b.current += bal
            elif days <= 30:
                b.overdue_1_30 += bal
            elif days <= 60:
                b.overdue_31_60 += bal
            elif days <= 90:
                b.overdue_61_90 += bal
            else:
                b.overdue_90_plus += bal
            b.total += bal

        return list(buckets.values())

    @staticmethod
    async def get_aging_ap(
        ctx: AppContext, db: AsyncSession, as_of_date: date | None = None
    ) -> list[AgingBucket]:
        """AP Aging — เจ้าหนี้การค้า แบ่งตามวันครบกำหนดชำระ."""
        as_of = as_of_date or date.today()

        unpaid = await db.scalars(
            select(APPurchase).where(
                APPurchase.company_id == ctx.company_id,
                APPurchase.status.in_(["posted", "partially_paid"]),
                APPurchase.balance > 0,
            )
        )

        buckets: dict[int, AgingBucket] = {}
        for pur in unpaid:
            days = (as_of - pur.due_date).days
            cid = pur.contact_id
            if cid not in buckets:
                contact = await db.scalar(select(Contact).where(Contact.id == cid))
                buckets[cid] = AgingBucket(
                    contact_id=cid,
                    contact_name=contact.name if contact else str(cid),
                    current=0, overdue_1_30=0, overdue_31_60=0,
                    overdue_61_90=0, overdue_90_plus=0, total=0,
                )
            b = buckets[cid]
            bal = pur.balance
            if days <= 0:
                b.current += bal
            elif days <= 30:
                b.overdue_1_30 += bal
            elif days <= 60:
                b.overdue_31_60 += bal
            elif days <= 90:
                b.overdue_61_90 += bal
            else:
                b.overdue_90_plus += bal
            b.total += bal

        return list(buckets.values())

    @staticmethod
    async def update_ar_balance(
        contact_id: int, amount_delta: "Decimal", ctx: AppContext, db: AsyncSession
    ) -> None:
        """อัปเดต AR balance ของ contact (ถ้ามี balance cache ใน contact)."""
        # ปัจจุบัน balance ถูก track ใน ARInvoice.balance โดยตรง
        # method นี้ reserve ไว้ถ้าต้องการ denormalized balance ใน Contact ในอนาคต
        pass

    @staticmethod
    async def update_ap_balance(
        contact_id: int, amount_delta: "Decimal", ctx: AppContext, db: AsyncSession
    ) -> None:
        """อัปเดต AP balance ของ contact."""
        pass
