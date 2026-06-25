"""Equity Changes Report — งบแสดงการเปลี่ยนแปลงส่วนของเจ้าของ."""

from __future__ import annotations

import calendar
from datetime import date
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.context import AppContext
from app.core.models import AccountBalance, ChartOfAccount, EquityChange, Period
from app.reports._base import BaseReport
from app.reports._queries import get_account_balances, get_period


class EquityLine(BaseModel):
    label: str
    opening: Decimal
    net_profit: Decimal
    dividends: Decimal
    other: Decimal
    closing: Decimal


class EquityReport(BaseReport):
    period: str
    entity_type: str
    lines: list[EquityLine]
    total_opening: Decimal
    total_closing: Decimal

    def _to_html(self, title: str) -> str:
        rows = "".join(
            f"<tr><td>{ln.label}</td>"
            f"<td class='number'>{ln.opening:,.2f}</td>"
            f"<td class='number'>{ln.net_profit:,.2f}</td>"
            f"<td class='number'>{ln.dividends:,.2f}</td>"
            f"<td class='number'>{ln.other:,.2f}</td>"
            f"<td class='number'>{ln.closing:,.2f}</td></tr>"
            for ln in self.lines
        )
        return (f"<html><head><meta charset='utf-8'></head><body>"
                f"<h1>{title}</h1><p>งวด {self.period}</p>"
                f"<table><tr><th>รายการ</th><th>ยอดต้น</th><th>กำไร(ขาดทุน)</th>"
                f"<th>เงินปันผล</th><th>อื่นๆ</th><th>ยอดปลาย</th></tr>"
                f"{rows}"
                f"<tr class='total'><td>รวม</td><td class='number'>{self.total_opening:,.2f}</td>"
                f"<td></td><td></td><td></td>"
                f"<td class='number'>{self.total_closing:,.2f}</td></tr>"
                f"</table></body></html>")


def _period_dates(period_str: str) -> tuple[date, date]:
    """แปลง YYYY-MM เป็น (date_from, date_to)."""
    year, month = int(period_str[:4]), int(period_str[5:7])
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, last_day)


async def _get_equity_balance(
    db: AsyncSession,
    period_id: int,
    branch_ids: list[int],
    category: str = "3",
    account_type_filter: Optional[str] = None,
) -> list[tuple[ChartOfAccount, Decimal]]:
    """คืนรายการบัญชีทุนพร้อม closing balance."""
    rows = await get_account_balances([period_id], branch_ids, db, category_filter=[category])
    result = []
    for coa, opening, dr, cr, closing in rows:
        if account_type_filter and coa.account_type != account_type_filter:
            continue
        result.append((coa, closing))
    return result


async def _get_dividends(
    db: AsyncSession,
    company_id: int,
    period_str: str,
) -> Decimal:
    """ดึงยอดเงินปันผลจาก equity_changes."""
    try:
        result = await db.scalar(
            select(func.sum(EquityChange.amount)).where(
                EquityChange.company_id == company_id,
                EquityChange.period == period_str,
                EquityChange.change_type == "dividend",
            )
        )
        return Decimal(str(result or 0))
    except Exception:
        return Decimal(0)


async def _get_other_changes(
    db: AsyncSession,
    company_id: int,
    period_str: str,
) -> Decimal:
    """ดึงยอดการเปลี่ยนแปลงอื่น (ไม่ใช่ dividend)."""
    try:
        result = await db.scalar(
            select(func.sum(EquityChange.amount)).where(
                EquityChange.company_id == company_id,
                EquityChange.period == period_str,
                EquityChange.change_type != "dividend",
            )
        )
        return Decimal(str(result or 0))
    except Exception:
        return Decimal(0)


async def generate(
    ctx: AppContext,
    db: AsyncSession,
    period_str: str,
) -> EquityReport:
    """สร้างงบแสดงการเปลี่ยนแปลงส่วนของเจ้าของ."""
    # Fetch entity_type from company record in shared DB
    entity_type = "company"
    try:
        from app.database import get_shared_session
        from app.platform.models import Company as PlatformCompany
        async with get_shared_session() as shared_db:
            company_obj = await shared_db.scalar(
                select(PlatformCompany).where(PlatformCompany.id == ctx.company_id)
            )
            if company_obj:
                entity_type = company_obj.entity_type or "company"
    except Exception:
        pass

    year, month = int(period_str[:4]), int(period_str[5:7])
    period = await get_period(year, month, db)
    branches = [ctx.branch_id]

    if not period:
        return EquityReport(
            period=period_str,
            entity_type=entity_type,
            lines=[],
            total_opening=Decimal(0),
            total_closing=Decimal(0),
        )

    # คำนวณ net_profit จาก income statement
    net_profit = Decimal(0)
    try:
        from app.reports import income_statement as ist
        date_from, date_to = _period_dates(period_str)
        is_report = await ist.generate(ctx, db, date_from, date_to)
        net_profit = is_report.net_profit
    except Exception:
        pass

    dividends = await _get_dividends(db, ctx.company_id, period_str)
    other = await _get_other_changes(db, ctx.company_id, period_str)

    lines: list[EquityLine] = []

    if entity_type == "company":
        # บริษัท: ทุนจดทะเบียน, ส่วนเกินมูลค่าหุ้น, กำไรสะสม
        equity_rows = await get_account_balances([period.id], branches, db, category_filter=["3"])

        paid_capital_open = Decimal(0)
        paid_capital_close = Decimal(0)
        share_premium_open = Decimal(0)
        share_premium_close = Decimal(0)
        retained_open = Decimal(0)
        retained_close = Decimal(0)

        for coa, opening, dr, cr, closing in equity_rows:
            acct_type = coa.account_type.lower()
            if "paid" in acct_type or "capital" in acct_type or coa.code.startswith("31"):
                paid_capital_open += opening
                paid_capital_close += closing
            elif "premium" in acct_type or "surplus" in acct_type or coa.code.startswith("32"):
                share_premium_open += opening
                share_premium_close += closing
            else:
                retained_open += opening
                retained_close += closing

        lines = [
            EquityLine(
                label="ทุนจดทะเบียนและชำระแล้ว",
                opening=paid_capital_open,
                net_profit=Decimal(0),
                dividends=Decimal(0),
                other=Decimal(0),
                closing=paid_capital_close,
            ),
            EquityLine(
                label="ส่วนเกินมูลค่าหุ้น",
                opening=share_premium_open,
                net_profit=Decimal(0),
                dividends=Decimal(0),
                other=Decimal(0),
                closing=share_premium_close,
            ),
            EquityLine(
                label="กำไรสะสม",
                opening=retained_open,
                net_profit=net_profit,
                dividends=dividends,
                other=other,
                closing=retained_open + net_profit - dividends + other,
            ),
        ]
    else:
        # ห้างหุ้นส่วน: แยกตามบัญชีทุน
        equity_rows = await get_account_balances([period.id], branches, db, category_filter=["3"])
        for coa, opening, dr, cr, closing in equity_rows:
            lines.append(EquityLine(
                label=f"{coa.code} {coa.name}",
                opening=opening,
                net_profit=net_profit,
                dividends=dividends,
                other=other,
                closing=closing,
            ))

    total_opening = sum(ln.opening for ln in lines)
    total_closing = sum(ln.closing for ln in lines)

    return EquityReport(
        period=period_str,
        entity_type=entity_type,
        lines=lines,
        total_opening=total_opening,
        total_closing=total_closing,
    )
