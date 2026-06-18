"""Trial Balance Report."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.context import AppContext
from app.reports._base import BaseReport
from app.reports._queries import get_account_balances, get_period


class TrialBalanceLine(BaseModel):
    account_code: str
    account_name: str
    category: str
    debit_balance: Decimal
    credit_balance: Decimal


class TrialBalanceReport(BaseReport):
    period: str
    lines: list[TrialBalanceLine]
    total_debit: Decimal
    total_credit: Decimal
    is_balanced: bool

    def _to_html(self, title: str) -> str:
        rows = "".join(
            f"<tr><td>{ln.account_code}</td><td>{ln.account_name}</td>"
            f"<td class='number'>{ln.debit_balance:,.2f}</td>"
            f"<td class='number'>{ln.credit_balance:,.2f}</td></tr>"
            for ln in self.lines
        )
        balanced_cls = "" if self.is_balanced else "style='color:red'"
        return f"""<html><head><meta charset='utf-8'></head><body>
<h1>{title}</h1><p>งวด: {self.period}</p>
<table><tr><th>รหัสบัญชี</th><th>ชื่อบัญชี</th><th>เดบิต</th><th>เครดิต</th></tr>
{rows}
<tr class='total'><td colspan='2'>รวม</td>
<td class='number'>{self.total_debit:,.2f}</td>
<td class='number'>{self.total_credit:,.2f}</td></tr>
</table>
<p {balanced_cls}>{'✓ งบดุล' if self.is_balanced else '✗ ไม่สมดุล! Dr ≠ Cr'}</p>
</body></html>"""


async def generate(
    ctx: AppContext,
    db: AsyncSession,
    year: int,
    month: int,
    branch_ids: Optional[list[int]] = None,
) -> TrialBalanceReport:
    """สร้าง Trial Balance สำหรับงวดที่ระบุ."""
    period = await get_period(year, month, db)
    if not period:
        raise ValueError(f"ไม่พบงวด {year}/{month:02d}")

    branches = branch_ids or [ctx.branch_id]
    rows = await get_account_balances([period.id], branches, db)

    lines: list[TrialBalanceLine] = []
    total_dr = Decimal(0)
    total_cr = Decimal(0)

    for coa, opening, dr, cr, closing in rows:
        if dr == 0 and cr == 0:
            continue

        # Trial balance แสดงยอดสุทธิตามด้านปกติ
        net = opening + dr - cr if coa.normal_balance == "DR" else opening + cr - dr
        if net >= 0:
            line = TrialBalanceLine(
                account_code=coa.code,
                account_name=coa.name,
                category=coa.category,
                debit_balance=net if coa.normal_balance == "DR" else Decimal(0),
                credit_balance=net if coa.normal_balance == "CR" else Decimal(0),
            )
        else:
            net = abs(net)
            line = TrialBalanceLine(
                account_code=coa.code,
                account_name=coa.name,
                category=coa.category,
                debit_balance=net if coa.normal_balance == "CR" else Decimal(0),
                credit_balance=net if coa.normal_balance == "DR" else Decimal(0),
            )
        lines.append(line)
        total_dr += line.debit_balance
        total_cr += line.credit_balance

    is_balanced = abs(total_dr - total_cr) < Decimal("0.01")
    if not is_balanced:
        # ไม่บล็อก — แค่ flag
        pass

    return TrialBalanceReport(
        period=f"{year}/{month:02d}",
        lines=lines,
        total_debit=total_dr,
        total_credit=total_cr,
        is_balanced=is_balanced,
    )
