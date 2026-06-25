"""Working Paper Report — กระดาษทำการ 6/8/10 ช่อง."""

from __future__ import annotations

from decimal import Decimal
from typing import Optional

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.context import AppContext
from app.reports._base import BaseReport


class WPLine(BaseModel):
    account_code: str
    account_name: str
    category: str
    trial_dr: Decimal = Decimal(0)
    trial_cr: Decimal = Decimal(0)
    adjust_dr: Decimal = Decimal(0)
    adjust_cr: Decimal = Decimal(0)
    pl_dr: Decimal = Decimal(0)
    pl_cr: Decimal = Decimal(0)
    bs_dr: Decimal = Decimal(0)
    bs_cr: Decimal = Decimal(0)


class WorkingPaperReport(BaseReport):
    period: str
    columns: int
    lines: list[WPLine]
    total_trial_dr: Decimal
    total_trial_cr: Decimal
    total_adjust_dr: Decimal = Decimal(0)
    total_adjust_cr: Decimal = Decimal(0)
    total_pl_dr: Decimal = Decimal(0)
    total_pl_cr: Decimal = Decimal(0)
    net_profit_loss: Decimal = Decimal(0)
    total_bs_dr: Decimal = Decimal(0)
    total_bs_cr: Decimal = Decimal(0)

    def _to_html(self, title: str) -> str:
        headers = "<tr><th>รหัส</th><th>ชื่อบัญชี</th>"
        headers += "<th>Trial Dr</th><th>Trial Cr</th>"
        if self.columns >= 8:
            headers += "<th>Adjust Dr</th><th>Adjust Cr</th>"
        if self.columns >= 10:
            headers += "<th>P&L Dr</th><th>P&L Cr</th><th>BS Dr</th><th>BS Cr</th>"
        headers += "</tr>"

        rows = ""
        for ln in self.lines:
            rows += f"<tr><td>{ln.account_code}</td><td>{ln.account_name}</td>"
            rows += f"<td class='number'>{ln.trial_dr:,.2f}</td><td class='number'>{ln.trial_cr:,.2f}</td>"
            if self.columns >= 8:
                rows += f"<td class='number'>{ln.adjust_dr:,.2f}</td><td class='number'>{ln.adjust_cr:,.2f}</td>"
            if self.columns >= 10:
                rows += (f"<td class='number'>{ln.pl_dr:,.2f}</td><td class='number'>{ln.pl_cr:,.2f}</td>"
                         f"<td class='number'>{ln.bs_dr:,.2f}</td><td class='number'>{ln.bs_cr:,.2f}</td>")
            rows += "</tr>"

        return (f"<html><head><meta charset='utf-8'></head><body>"
                f"<h1>{title}</h1><p>งวด {self.period}</p>"
                f"<table>{headers}{rows}</table></body></html>")


async def generate(
    ctx: AppContext,
    db: AsyncSession,
    period_str: str,
    columns: int = 10,
) -> WorkingPaperReport:
    """สร้างกระดาษทำการ."""
    from app.reports import trial_balance as tb

    year, month = int(period_str[:4]), int(period_str[5:7])
    tb_report = await tb.generate(ctx, db, year, month)

    lines: list[WPLine] = []

    for tb_line in tb_report.lines:
        wp = WPLine(
            account_code=tb_line.account_code,
            account_name=tb_line.account_name,
            category=tb_line.category,
            trial_dr=tb_line.debit_balance,
            trial_cr=tb_line.credit_balance,
        )

        if columns >= 10:
            # Adjusted balance = trial (adjust_dr/cr are 0 since no adjusting service)
            adj_dr = wp.trial_dr + wp.adjust_dr - wp.adjust_cr
            adj_cr = wp.trial_cr + wp.adjust_cr - wp.adjust_dr
            # Normalize
            if adj_dr < 0:
                adj_cr = abs(adj_dr)
                adj_dr = Decimal(0)
            elif adj_cr < 0:
                adj_dr = abs(adj_cr)
                adj_cr = Decimal(0)

            cat = tb_line.category
            # category 4 (revenue) → P&L CR
            if cat == "4":
                wp.pl_cr = adj_cr - adj_dr if adj_cr >= adj_dr else Decimal(0)
                wp.pl_dr = adj_dr - adj_cr if adj_dr > adj_cr else Decimal(0)
            # category 5 (COGS), 6 (expenses) → P&L DR
            elif cat in ("5", "6"):
                wp.pl_dr = adj_dr - adj_cr if adj_dr >= adj_cr else Decimal(0)
                wp.pl_cr = adj_cr - adj_dr if adj_cr > adj_dr else Decimal(0)
            # category 7 (finance) — depends on normal_balance
            elif cat == "7":
                # finance items: positive amounts go to P&L
                wp.pl_dr = adj_dr
                wp.pl_cr = adj_cr
            # category 8 (other income) → P&L CR
            elif cat == "8":
                wp.pl_cr = adj_cr
                wp.pl_dr = adj_dr
            # category 1 (assets) → BS DR
            elif cat == "1":
                wp.bs_dr = adj_dr
                wp.bs_cr = adj_cr
            # category 2 (liabilities), 3 (equity) → BS CR
            elif cat in ("2", "3"):
                wp.bs_cr = adj_cr
                wp.bs_dr = adj_dr

        lines.append(wp)

    total_trial_dr = sum(ln.trial_dr for ln in lines)
    total_trial_cr = sum(ln.trial_cr for ln in lines)
    total_adjust_dr = sum(ln.adjust_dr for ln in lines)
    total_adjust_cr = sum(ln.adjust_cr for ln in lines)
    total_pl_dr = sum(ln.pl_dr for ln in lines)
    total_pl_cr = sum(ln.pl_cr for ln in lines)
    total_bs_dr = sum(ln.bs_dr for ln in lines)
    total_bs_cr = sum(ln.bs_cr for ln in lines)
    net_profit_loss = total_pl_cr - total_pl_dr

    # เพิ่ม summary line สำหรับ 10 ช่อง
    if columns >= 10 and net_profit_loss != 0:
        label = "กำไรสุทธิ" if net_profit_loss > 0 else "ขาดทุนสุทธิ"
        summary = WPLine(
            account_code="",
            account_name=label,
            category="",
            pl_dr=net_profit_loss if net_profit_loss > 0 else Decimal(0),
            pl_cr=abs(net_profit_loss) if net_profit_loss < 0 else Decimal(0),
            bs_cr=net_profit_loss if net_profit_loss > 0 else Decimal(0),
            bs_dr=abs(net_profit_loss) if net_profit_loss < 0 else Decimal(0),
        )
        lines.append(summary)

    return WorkingPaperReport(
        period=period_str,
        columns=columns,
        lines=lines,
        total_trial_dr=total_trial_dr,
        total_trial_cr=total_trial_cr,
        total_adjust_dr=total_adjust_dr,
        total_adjust_cr=total_adjust_cr,
        total_pl_dr=total_pl_dr,
        total_pl_cr=total_pl_cr,
        net_profit_loss=net_profit_loss,
        total_bs_dr=total_bs_dr,
        total_bs_cr=total_bs_cr,
    )
