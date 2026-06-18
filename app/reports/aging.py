"""Aging Report — AR และ AP."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.context import AppContext
from app.modules.ar.models import ARInvoice, Contact
from app.modules.ap.models import APPurchase
from app.reports._base import BaseReport


class AgingRow(BaseModel):
    contact_id: int
    contact_name: str
    tax_id: Optional[str] = None
    current: Decimal       # ยังไม่ถึงกำหนด
    days_30: Decimal       # 1–30 วัน
    days_60: Decimal       # 31–60 วัน
    days_90: Decimal       # 61–90 วัน
    over_90: Decimal       # > 90 วัน
    total_due: Decimal
    oldest_invoice: Optional[str] = None
    overdue_amount: Decimal = Decimal(0)


class AgingReport(BaseReport):
    as_of_date: str
    report_type: str  # AR | AP
    rows: list[AgingRow]
    total_current: Decimal
    total_30: Decimal
    total_60: Decimal
    total_90: Decimal
    total_over_90: Decimal
    grand_total: Decimal

    def _to_html(self, title: str) -> str:
        rows_html = "".join(
            f"<tr><td>{r.contact_name}</td><td>{r.tax_id or ''}</td>"
            f"<td class='number'>{r.current:,.2f}</td>"
            f"<td class='number'>{r.days_30:,.2f}</td>"
            f"<td class='number'>{r.days_60:,.2f}</td>"
            f"<td class='number'>{r.days_90:,.2f}</td>"
            f"<td class='number'>{r.over_90:,.2f}</td>"
            f"<td class='number'>{r.total_due:,.2f}</td></tr>"
            for r in self.rows
        )
        return (f"<html><head><meta charset='utf-8'></head><body>"
                f"<h1>{title}</h1><p>ณ วันที่ {self.as_of_date}</p>"
                f"<table>"
                f"<tr><th>ชื่อ</th><th>เลขภาษี</th>"
                f"<th>ยังไม่ถึงกำหนด</th><th>1-30 วัน</th>"
                f"<th>31-60 วัน</th><th>61-90 วัน</th><th>&gt;90 วัน</th><th>รวม</th></tr>"
                f"{rows_html}"
                f"<tr class='total'><td colspan='2'>รวมทั้งสิ้น</td>"
                f"<td class='number'>{self.total_current:,.2f}</td>"
                f"<td class='number'>{self.total_30:,.2f}</td>"
                f"<td class='number'>{self.total_60:,.2f}</td>"
                f"<td class='number'>{self.total_90:,.2f}</td>"
                f"<td class='number'>{self.total_over_90:,.2f}</td>"
                f"<td class='number'>{self.grand_total:,.2f}</td></tr>"
                f"</table></body></html>")


def _bucket(days_overdue: int) -> str:
    if days_overdue <= 0:
        return "current"
    elif days_overdue <= 30:
        return "30"
    elif days_overdue <= 60:
        return "60"
    elif days_overdue <= 90:
        return "90"
    return "over90"


async def ar_aging(
    ctx: AppContext,
    db: AsyncSession,
    as_of_date: date,
    branch_ids: Optional[list[int]] = None,
) -> AgingReport:
    """AR Aging Report."""
    branches = branch_ids or [ctx.branch_id]

    invoices = list(await db.scalars(
        select(ARInvoice).where(
            ARInvoice.company_id == ctx.company_id,
            ARInvoice.branch_id.in_(branches),
            ARInvoice.status.in_(["posted", "partially_paid"]),
            ARInvoice.invoice_date <= as_of_date,
        )
    ))

    # จัดกลุ่มต่อ contact
    contact_map: dict[int, AgingRow] = {}
    oldest_map: dict[int, date] = {}
    oldest_no_map: dict[int, str] = {}

    for inv in invoices:
        balance = inv.balance
        if balance <= 0:
            continue
        days_late = (as_of_date - inv.due_date).days

        if inv.contact_id not in contact_map:
            contact = await db.scalar(select(Contact).where(Contact.id == inv.contact_id))
            contact_map[inv.contact_id] = AgingRow(
                contact_id=inv.contact_id,
                contact_name=contact.name if contact else f"Contact {inv.contact_id}",
                tax_id=contact.tax_id if contact else None,
                current=Decimal(0), days_30=Decimal(0), days_60=Decimal(0),
                days_90=Decimal(0), over_90=Decimal(0), total_due=Decimal(0),
            )

        row = contact_map[inv.contact_id]
        bucket = _bucket(days_late)
        if bucket == "current":
            contact_map[inv.contact_id] = row.model_copy(update={"current": row.current + balance})
        elif bucket == "30":
            contact_map[inv.contact_id] = row.model_copy(update={"days_30": row.days_30 + balance})
        elif bucket == "60":
            contact_map[inv.contact_id] = row.model_copy(update={"days_60": row.days_60 + balance})
        elif bucket == "90":
            contact_map[inv.contact_id] = row.model_copy(update={"days_90": row.days_90 + balance})
        else:
            contact_map[inv.contact_id] = row.model_copy(update={"over_90": row.over_90 + balance})

        if inv.contact_id not in oldest_map or inv.due_date < oldest_map[inv.contact_id]:
            oldest_map[inv.contact_id] = inv.due_date
            oldest_no_map[inv.contact_id] = inv.invoice_no

    result_rows = []
    for cid, row in contact_map.items():
        total = row.current + row.days_30 + row.days_60 + row.days_90 + row.over_90
        overdue = row.days_30 + row.days_60 + row.days_90 + row.over_90
        result_rows.append(row.model_copy(update={
            "total_due": total,
            "overdue_amount": overdue,
            "oldest_invoice": oldest_no_map.get(cid),
        }))

    result_rows.sort(key=lambda r: r.total_due, reverse=True)

    return AgingReport(
        as_of_date=str(as_of_date),
        report_type="AR",
        rows=result_rows,
        total_current=sum(r.current for r in result_rows),
        total_30=sum(r.days_30 for r in result_rows),
        total_60=sum(r.days_60 for r in result_rows),
        total_90=sum(r.days_90 for r in result_rows),
        total_over_90=sum(r.over_90 for r in result_rows),
        grand_total=sum(r.total_due for r in result_rows),
    )


async def ap_aging(
    ctx: AppContext,
    db: AsyncSession,
    as_of_date: date,
    branch_ids: Optional[list[int]] = None,
) -> AgingReport:
    """AP Aging Report."""
    branches = branch_ids or [ctx.branch_id]

    purchases = list(await db.scalars(
        select(APPurchase).where(
            APPurchase.company_id == ctx.company_id,
            APPurchase.branch_id.in_(branches),
            APPurchase.status.in_(["posted", "partially_paid"]),
            APPurchase.purchase_date <= as_of_date,
        )
    ))

    contact_map: dict[int, AgingRow] = {}
    oldest_map: dict[int, date] = {}
    oldest_no_map: dict[int, str] = {}

    for pur in purchases:
        balance = pur.balance
        if balance <= 0:
            continue
        days_late = (as_of_date - pur.due_date).days

        if pur.contact_id not in contact_map:
            contact = await db.scalar(select(Contact).where(Contact.id == pur.contact_id))
            contact_map[pur.contact_id] = AgingRow(
                contact_id=pur.contact_id,
                contact_name=contact.name if contact else f"Contact {pur.contact_id}",
                tax_id=contact.tax_id if contact else None,
                current=Decimal(0), days_30=Decimal(0), days_60=Decimal(0),
                days_90=Decimal(0), over_90=Decimal(0), total_due=Decimal(0),
            )

        row = contact_map[pur.contact_id]
        bucket = _bucket(days_late)
        updates = {}
        if bucket == "current":
            updates["current"] = row.current + balance
        elif bucket == "30":
            updates["days_30"] = row.days_30 + balance
        elif bucket == "60":
            updates["days_60"] = row.days_60 + balance
        elif bucket == "90":
            updates["days_90"] = row.days_90 + balance
        else:
            updates["over_90"] = row.over_90 + balance
        contact_map[pur.contact_id] = row.model_copy(update=updates)

        if pur.contact_id not in oldest_map or pur.due_date < oldest_map[pur.contact_id]:
            oldest_map[pur.contact_id] = pur.due_date
            oldest_no_map[pur.contact_id] = pur.purchase_no

    result_rows = []
    for cid, row in contact_map.items():
        total = row.current + row.days_30 + row.days_60 + row.days_90 + row.over_90
        overdue = row.days_30 + row.days_60 + row.days_90 + row.over_90
        result_rows.append(row.model_copy(update={
            "total_due": total,
            "overdue_amount": overdue,
            "oldest_invoice": oldest_no_map.get(cid),
        }))

    result_rows.sort(key=lambda r: r.total_due, reverse=True)

    return AgingReport(
        as_of_date=str(as_of_date),
        report_type="AP",
        rows=result_rows,
        total_current=sum(r.current for r in result_rows),
        total_30=sum(r.days_30 for r in result_rows),
        total_60=sum(r.days_60 for r in result_rows),
        total_90=sum(r.days_90 for r in result_rows),
        total_over_90=sum(r.over_90 for r in result_rows),
        grand_total=sum(r.total_due for r in result_rows),
    )
