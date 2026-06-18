"""Budget vs Actual Report."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.context import AppContext
from app.core.models import AccountBalance, BudgetItem, ChartOfAccount, Period
from app.reports._base import BaseReport
from app.reports._queries import get_period


class BudgetLine(BaseModel):
    account_code: str
    account_name: str
    category: str
    budget: Decimal
    actual: Decimal
    variance: Decimal
    variance_pct: Decimal
    over_budget: bool  # variance > 10%


class BudgetActualReport(BaseReport):
    period: str
    lines: list[BudgetLine]
    total_budget: Decimal
    total_actual: Decimal
    total_variance: Decimal
    over_budget_count: int

    def _to_html(self, title: str) -> str:
        rows = ""
        for ln in self.lines:
            cls = "class='negative'" if ln.over_budget else ""
            rows += (f"<tr {cls}><td>{ln.account_code}</td><td>{ln.account_name}</td>"
                     f"<td class='number'>{ln.budget:,.2f}</td>"
                     f"<td class='number'>{ln.actual:,.2f}</td>"
                     f"<td class='number'>{ln.variance:,.2f}</td>"
                     f"<td class='number'>{ln.variance_pct:.1f}%</td>"
                     f"<td>{'⚠' if ln.over_budget else '✓'}</td></tr>")
        return (f"<html><head><meta charset='utf-8'></head><body>"
                f"<h1>{title}</h1><p>งวด: {self.period}</p>"
                f"<table>"
                f"<tr><th>รหัส</th><th>ชื่อบัญชี</th><th>งบประมาณ</th>"
                f"<th>จริง</th><th>ส่วนต่าง</th><th>%</th><th>สถานะ</th></tr>"
                f"{rows}"
                f"<tr class='total'><td colspan='2'>รวม</td>"
                f"<td class='number'>{self.total_budget:,.2f}</td>"
                f"<td class='number'>{self.total_actual:,.2f}</td>"
                f"<td class='number'>{self.total_variance:,.2f}</td>"
                f"<td></td><td></td></tr>"
                f"</table><p>บัญชีที่เกิน 10%: {self.over_budget_count} รายการ</p>"
                f"</body></html>")


async def generate(
    ctx: AppContext,
    db: AsyncSession,
    year: int,
    month: int,
    branch_ids: Optional[list[int]] = None,
) -> BudgetActualReport:
    """Budget vs Actual สำหรับงวดที่ระบุ."""
    branches = branch_ids or [ctx.branch_id]
    period = await get_period(year, month, db)
    if not period:
        raise ValueError(f"ไม่พบงวด {year}/{month:02d}")

    # โหลด budget items
    budget_rows = list(await db.execute(
        select(BudgetItem, ChartOfAccount)
        .join(ChartOfAccount, BudgetItem.account_id == ChartOfAccount.id)
        .where(
            BudgetItem.fiscal_year == year,
            BudgetItem.month == month,
            BudgetItem.branch_id.in_(branches),
        )
        .order_by(ChartOfAccount.code)
    ))

    # โหลด actual balances
    actual_map: dict[int, Decimal] = {}
    actual_rows = list(await db.execute(
        select(AccountBalance, ChartOfAccount)
        .join(ChartOfAccount, AccountBalance.account_id == ChartOfAccount.id)
        .where(
            AccountBalance.period_id == period.id,
            AccountBalance.branch_id.in_(branches),
        )
    ))
    for ab, coa in actual_rows:
        # ใช้ total expense/revenue ตามด้านปกติ
        if coa.normal_balance == "DR":
            actual_map[coa.id] = ab.total_debit - ab.total_credit
        else:
            actual_map[coa.id] = ab.total_credit - ab.total_debit

    lines = []
    for bi, coa in budget_rows:
        budget = bi.budget_amount
        actual = actual_map.get(coa.id, Decimal(0))
        variance = actual - budget
        variance_pct = (variance / budget * 100) if budget != 0 else Decimal(0)
        over = abs(variance_pct) > Decimal(10)
        lines.append(BudgetLine(
            account_code=coa.code,
            account_name=coa.name,
            category=coa.category,
            budget=budget,
            actual=actual,
            variance=variance,
            variance_pct=variance_pct.quantize(Decimal("0.01")),
            over_budget=over,
        ))

    total_b = sum(ln.budget for ln in lines)
    total_a = sum(ln.actual for ln in lines)
    return BudgetActualReport(
        period=f"{year}/{month:02d}",
        lines=lines,
        total_budget=total_b,
        total_actual=total_a,
        total_variance=total_a - total_b,
        over_budget_count=sum(1 for ln in lines if ln.over_budget),
    )


async def set_budget(
    ctx: AppContext,
    db: AsyncSession,
    year: int,
    month: int,
    account_code: str,
    amount: Decimal,
) -> BudgetItem:
    """บันทึกหรืออัปเดต budget สำหรับบัญชีที่ระบุ."""
    coa = await db.scalar(select(ChartOfAccount).where(ChartOfAccount.code == account_code))
    if not coa:
        raise ValueError(f"ไม่พบบัญชี {account_code}")

    existing = await db.scalar(
        select(BudgetItem).where(
            BudgetItem.fiscal_year == year,
            BudgetItem.month == month,
            BudgetItem.account_id == coa.id,
            BudgetItem.branch_id == ctx.branch_id,
        )
    )
    if existing:
        existing.budget_amount = amount
        return existing

    bi = BudgetItem(
        fiscal_year=year,
        month=month,
        account_id=coa.id,
        branch_id=ctx.branch_id,
        budget_amount=amount,
        created_by=ctx.user_id,
    )
    db.add(bi)
    return bi
