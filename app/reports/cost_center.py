"""Cost Center Report — สรุปรายได้/ค่าใช้จ่ายแยกตามศูนย์ต้นทุน."""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.context import AppContext
from app.core.models import JournalLine, JournalEntry, ChartOfAccount
from app.reports._base import BaseReport


class CCLine(BaseModel):
    account_code: str
    account_name: str
    category: str
    debit: Decimal
    credit: Decimal
    net: Decimal  # credit-debit for CR normal; debit-credit for DR normal


class CCSection(BaseModel):
    cost_center: str  # "ไม่ระบุ" if null
    lines: list[CCLine]
    total_debit: Decimal
    total_credit: Decimal
    total_net: Decimal


class CostCenterReport(BaseReport):
    date_from: str
    date_to: str
    sections: list[CCSection]
    grand_total_debit: Decimal
    grand_total_credit: Decimal
    grand_total_net: Decimal

    def _to_html(self, title: str) -> str:
        section_html = ""
        for sec in self.sections:
            rows = ""
            for ln in sec.lines:
                rows += (
                    f"<tr><td>{ln.account_code}</td><td>{ln.account_name}</td>"
                    f"<td>{ln.category}</td>"
                    f"<td class='number'>{ln.debit:,.2f}</td>"
                    f"<td class='number'>{ln.credit:,.2f}</td>"
                    f"<td class='number'>{ln.net:,.2f}</td></tr>"
                )
            rows += (
                f"<tr class='total'><td colspan='3'>รวม {sec.cost_center}</td>"
                f"<td class='number'>{sec.total_debit:,.2f}</td>"
                f"<td class='number'>{sec.total_credit:,.2f}</td>"
                f"<td class='number'>{sec.total_net:,.2f}</td></tr>"
            )
            section_html += (
                f"<h2>ศูนย์ต้นทุน: {sec.cost_center}</h2>"
                f"<table>"
                f"<tr><th>รหัส</th><th>ชื่อบัญชี</th><th>หมวด</th>"
                f"<th>Dr</th><th>Cr</th><th>Net</th></tr>"
                f"{rows}</table>"
            )
        grand = (
            f"<table><tr class='total'>"
            f"<td colspan='3'><strong>รวมทั้งหมด</strong></td>"
            f"<td class='number'><strong>{self.grand_total_debit:,.2f}</strong></td>"
            f"<td class='number'><strong>{self.grand_total_credit:,.2f}</strong></td>"
            f"<td class='number'><strong>{self.grand_total_net:,.2f}</strong></td>"
            f"</tr></table>"
        )
        return (
            f"<html><head><meta charset='utf-8'></head><body>"
            f"<h1>{title}</h1>"
            f"<p>ช่วงวันที่: {self.date_from} ถึง {self.date_to}</p>"
            f"{section_html}{grand}"
            f"</body></html>"
        )


async def generate(
    ctx: AppContext,
    db: AsyncSession,
    date_from: date,
    date_to: date,
    cost_centers: Optional[list[str]] = None,
    branch_ids: Optional[list[int]] = None,
) -> CostCenterReport:
    """สร้าง Cost Center Report สำหรับช่วงวันที่ที่ระบุ."""
    stmt = (
        select(
            func.coalesce(JournalLine.cost_center, "ไม่ระบุ").label("cc"),
            JournalLine.account_id,
            ChartOfAccount.code,
            ChartOfAccount.name,
            ChartOfAccount.category,
            ChartOfAccount.normal_balance,
            func.sum(JournalLine.debit_amount).label("total_debit"),
            func.sum(JournalLine.credit_amount).label("total_credit"),
        )
        .join(JournalEntry, JournalLine.entry_id == JournalEntry.id)
        .join(ChartOfAccount, JournalLine.account_id == ChartOfAccount.id)
        .where(
            JournalEntry.entry_date >= date_from,
            JournalEntry.entry_date <= date_to,
            JournalEntry.status == "posted",
        )
        .group_by(
            func.coalesce(JournalLine.cost_center, "ไม่ระบุ"),
            JournalLine.account_id,
            ChartOfAccount.code,
            ChartOfAccount.name,
            ChartOfAccount.category,
            ChartOfAccount.normal_balance,
        )
        .order_by(
            func.coalesce(JournalLine.cost_center, "ไม่ระบุ"),
            ChartOfAccount.code,
        )
    )

    if branch_ids:
        stmt = stmt.where(JournalEntry.branch_id.in_(branch_ids))
    if cost_centers:
        stmt = stmt.where(JournalLine.cost_center.in_(cost_centers))

    rows = list(await db.execute(stmt))

    # Group rows by cost_center
    grouped: dict[str, list] = defaultdict(list)
    for row in rows:
        grouped[row.cc].append(row)

    sections: list[CCSection] = []
    grand_debit = Decimal(0)
    grand_credit = Decimal(0)
    grand_net = Decimal(0)

    # Sort: alphabetical, "ไม่ระบุ" last
    def sort_key(cc: str) -> tuple:
        return (cc == "ไม่ระบุ", cc)

    for cc in sorted(grouped.keys(), key=sort_key):
        cc_rows = grouped[cc]
        lines: list[CCLine] = []
        sec_debit = Decimal(0)
        sec_credit = Decimal(0)
        sec_net = Decimal(0)

        for row in cc_rows:
            dr = row.total_debit or Decimal(0)
            cr = row.total_credit or Decimal(0)
            net = (cr - dr) if row.normal_balance == "CR" else (dr - cr)
            lines.append(CCLine(
                account_code=row.code,
                account_name=row.name,
                category=row.category,
                debit=dr,
                credit=cr,
                net=net,
            ))
            sec_debit += dr
            sec_credit += cr
            sec_net += net

        sections.append(CCSection(
            cost_center=cc,
            lines=lines,
            total_debit=sec_debit,
            total_credit=sec_credit,
            total_net=sec_net,
        ))
        grand_debit += sec_debit
        grand_credit += sec_credit
        grand_net += sec_net

    return CostCenterReport(
        date_from=date_from.isoformat(),
        date_to=date_to.isoformat(),
        sections=sections,
        grand_total_debit=grand_debit,
        grand_total_credit=grand_credit,
        grand_total_net=grand_net,
    )
