"""Balance Sheet Report."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.context import AppContext
from app.core.models import AccountBalance, ChartOfAccount, Period
from pydantic import BaseModel
from app.reports._base import BaseReport
from app.reports._queries import get_account_balances, get_period


class BSLine(BaseModel):
    account_code: str
    account_name: str
    amount: Decimal


class BSSection(BaseModel):
    label: str
    lines: list[BSLine]
    total: Decimal


class BalanceSheetReport(BaseReport):
    as_of_date: str
    current_assets: BSSection
    non_current_assets: BSSection
    total_assets: Decimal
    current_liabilities: BSSection
    non_current_liabilities: BSSection
    total_liabilities: Decimal
    equity: BSSection
    total_equity: Decimal
    total_liabilities_equity: Decimal
    is_balanced: bool

    def _to_html(self, title: str) -> str:
        def section_html(sec: BSSection) -> str:
            rows = "".join(
                f"<tr><td>{ln.account_code} {ln.account_name}</td>"
                f"<td class='number'>{ln.amount:,.2f}</td></tr>"
                for ln in sec.lines
            )
            return (f"<h3>{sec.label}</h3><table>"
                    f"<tr><th>บัญชี</th><th>จำนวนเงิน</th></tr>{rows}"
                    f"<tr class='total'><td>รวม {sec.label}</td>"
                    f"<td class='number'>{sec.total:,.2f}</td></tr></table>")

        return (f"<html><head><meta charset='utf-8'></head><body>"
                f"<h1>{title}</h1><p>ณ วันที่ {self.as_of_date}</p>"
                f"<h2>สินทรัพย์</h2>"
                f"{section_html(self.current_assets)}"
                f"{section_html(self.non_current_assets)}"
                f"<p><strong>รวมสินทรัพย์: {self.total_assets:,.2f}</strong></p>"
                f"<h2>หนี้สินและส่วนของเจ้าของ</h2>"
                f"{section_html(self.current_liabilities)}"
                f"{section_html(self.non_current_liabilities)}"
                f"<p><strong>รวมหนี้สิน: {self.total_liabilities:,.2f}</strong></p>"
                f"{section_html(self.equity)}"
                f"<p><strong>รวมหนี้สินและส่วนของเจ้าของ: {self.total_liabilities_equity:,.2f}</strong></p>"
                f"</body></html>")


# COA code ranges
def _is_current_asset(code: str) -> bool:
    return code.startswith("11")


def _is_noncurrent_asset(code: str) -> bool:
    c = int(code[:2]) if code[:2].isdigit() else 0
    return code.startswith("1") and not code.startswith("11")


def _is_current_liability(code: str) -> bool:
    return code.startswith("21")


def _is_noncurrent_liability(code: str) -> bool:
    return code.startswith("2") and not code.startswith("21")


async def generate(
    ctx: AppContext,
    db: AsyncSession,
    as_of_date: date,
    branch_ids: Optional[list[int]] = None,
) -> BalanceSheetReport:
    """สร้างงบดุล ณ วันที่ที่ระบุ."""
    branches = branch_ids or [ctx.branch_id]

    # หา period ที่ครอบ as_of_date
    period = await db.scalar(
        select(Period).where(
            Period.start_date <= as_of_date,
            Period.end_date >= as_of_date,
        )
    )
    if not period:
        raise ValueError(f"ไม่พบงวดสำหรับวันที่ {as_of_date}")

    rows = await get_account_balances([period.id], branches, db, category_filter=["1", "2", "3"])

    ca_lines, nca_lines, cl_lines, ncl_lines, eq_lines = [], [], [], [], []

    for coa, opening, dr, cr, closing in rows:
        # สำหรับ B/S ใช้ closing_balance
        if coa.normal_balance == "DR":
            amount = closing
        else:
            amount = closing

        ln = BSLine(account_code=coa.code, account_name=coa.name, amount=amount)

        cat = coa.category
        code = coa.code
        if cat == "1":
            if _is_current_asset(code):
                ca_lines.append(ln)
            else:
                nca_lines.append(ln)
        elif cat == "2":
            if _is_current_liability(code):
                cl_lines.append(ln)
            else:
                ncl_lines.append(ln)
        elif cat == "3":
            eq_lines.append(ln)

    def section(label: str, lines: list[BSLine]) -> BSSection:
        return BSSection(label=label, lines=lines, total=sum(ln.amount for ln in lines))

    ca = section("สินทรัพย์หมุนเวียน", ca_lines)
    nca = section("สินทรัพย์ไม่หมุนเวียน", nca_lines)
    cl = section("หนี้สินหมุนเวียน", cl_lines)
    ncl = section("หนี้สินไม่หมุนเวียน", ncl_lines)
    eq = section("ส่วนของเจ้าของ", eq_lines)

    total_assets = ca.total + nca.total
    total_liab = cl.total + ncl.total
    total_equity = eq.total
    total_le = total_liab + total_equity

    return BalanceSheetReport(
        as_of_date=str(as_of_date),
        current_assets=ca,
        non_current_assets=nca,
        total_assets=total_assets,
        current_liabilities=cl,
        non_current_liabilities=ncl,
        total_liabilities=total_liab,
        equity=eq,
        total_equity=total_equity,
        total_liabilities_equity=total_le,
        is_balanced=abs(total_assets - total_le) < Decimal("0.01"),
    )
