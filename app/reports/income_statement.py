"""Income Statement Report."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.context import AppContext
from app.reports._base import BaseReport
from app.reports._queries import sum_ledger_by_account


class ISLine(BaseModel):
    account_code: str
    account_name: str
    current_amount: Decimal
    prior_year_amount: Decimal = Decimal(0)


class ISSection(BaseModel):
    label: str
    lines: list[ISLine]
    total: Decimal
    prior_year_total: Decimal = Decimal(0)


class IncomeStatementReport(BaseReport):
    date_from: str
    date_to: str
    format: str = "by_nature"
    revenue: ISSection
    cost_of_sales: ISSection
    gross_profit: Decimal
    gross_profit_prior: Decimal = Decimal(0)
    operating_profit: Optional[Decimal] = None
    expenses: ISSection
    finance_costs: ISSection
    other_income: ISSection
    net_profit: Decimal
    net_profit_prior: Decimal = Decimal(0)
    ytd_net_profit: Decimal = Decimal(0)

    def _to_html(self, title: str) -> str:
        def sec_html(sec: ISSection) -> str:
            rows = "".join(
                f"<tr><td>{ln.account_code} {ln.account_name}</td>"
                f"<td class='number'>{ln.current_amount:,.2f}</td>"
                f"<td class='number'>{ln.prior_year_amount:,.2f}</td></tr>"
                for ln in sec.lines
            )
            return (f"<h3>{sec.label}</h3><table>"
                    f"<tr><th>บัญชี</th><th>ปัจจุบัน</th><th>ปีก่อน</th></tr>{rows}"
                    f"<tr class='total'><td>รวม</td>"
                    f"<td class='number'>{sec.total:,.2f}</td>"
                    f"<td class='number'>{sec.prior_year_total:,.2f}</td></tr></table>")

        profit_cls = "" if self.net_profit >= 0 else "class='negative'"
        return (f"<html><head><meta charset='utf-8'></head><body>"
                f"<h1>{title}</h1><p>{self.date_from} ถึง {self.date_to}</p>"
                f"{sec_html(self.revenue)}"
                f"{sec_html(self.cost_of_sales)}"
                f"<p><strong>กำไรขั้นต้น: {self.gross_profit:,.2f}</strong></p>"
                f"{sec_html(self.expenses)}"
                f"{sec_html(self.finance_costs)}"
                f"{sec_html(self.other_income)}"
                f"<p {profit_cls}><strong>กำไร(ขาดทุน)สุทธิ: {self.net_profit:,.2f}</strong></p>"
                f"<p>กำไรสะสม YTD: {self.ytd_net_profit:,.2f}</p>"
                f"</body></html>")


async def _sum_section(
    rows: list, categories: list[str], label: str, is_cr_normal: bool
) -> ISSection:
    lines = []
    for coa, dr, cr in rows:
        if coa.category not in categories:
            continue
        amount = cr - dr if is_cr_normal else dr - cr
        lines.append(ISLine(
            account_code=coa.code,
            account_name=coa.name,
            current_amount=amount,
        ))
    total = sum(ln.current_amount for ln in lines)
    return ISSection(label=label, lines=lines, total=total)


async def generate(
    ctx: AppContext,
    db: AsyncSession,
    date_from: date,
    date_to: date,
    branch_ids: Optional[list[int]] = None,
    compare_prior_year: bool = False,
    fmt: str = "by_nature",
) -> IncomeStatementReport:
    """สร้างงบกำไรขาดทุน."""
    branches = branch_ids or [ctx.branch_id]
    rows = await sum_ledger_by_account(date_from, date_to, branches, db,
                                        category_filter=["4", "5", "6", "7", "8"])

    revenue = await _sum_section(rows, ["4"], "รายได้จากการขาย/บริการ", is_cr_normal=True)
    cogs = await _sum_section(rows, ["5"], "ต้นทุนขาย", is_cr_normal=False)
    finance = await _sum_section(rows, ["7"], "รายได้(ค่าใช้จ่าย)ทางการเงิน", is_cr_normal=True)
    other = await _sum_section(rows, ["8"], "รายได้อื่น", is_cr_normal=True)

    gross = revenue.total - cogs.total

    # Build expenses section — split by account_type for by_function formats
    if fmt in ("by_function_single", "by_function_multi"):
        selling_lines = []
        admin_lines = []
        other_exp_lines = []
        for coa, dr, cr in rows:
            if coa.category != "6":
                continue
            amount = dr - cr
            line = ISLine(account_code=coa.code, account_name=coa.name, current_amount=amount)
            acct_type = (coa.account_type or "").lower()
            if "selling" in acct_type or "sale" in acct_type:
                selling_lines.append(line)
            elif "admin" in acct_type or "general" in acct_type:
                admin_lines.append(line)
            else:
                other_exp_lines.append(line)

        selling = ISSection(
            label="ค่าใช้จ่ายในการขาย",
            lines=selling_lines,
            total=sum(ln.current_amount for ln in selling_lines),
        )
        admin = ISSection(
            label="ค่าใช้จ่ายในการบริหาร",
            lines=admin_lines,
            total=sum(ln.current_amount for ln in admin_lines),
        )
        # For compatibility, store all expenses in the expenses field
        all_exp_lines = selling_lines + admin_lines + other_exp_lines
        expenses = ISSection(
            label="ค่าใช้จ่ายในการดำเนินงาน",
            lines=all_exp_lines,
            total=sum(ln.current_amount for ln in all_exp_lines),
        )
        operating_profit = gross - selling.total - admin.total
    else:
        expenses = await _sum_section(rows, ["6"], "ค่าใช้จ่ายในการดำเนินงาน", is_cr_normal=False)
        operating_profit = None

    net = gross - expenses.total + finance.total + other.total

    # Prior year comparison
    prior_net = Decimal(0)
    if compare_prior_year:
        from dateutil.relativedelta import relativedelta
        py_from = date_from - relativedelta(years=1)
        py_to = date_to - relativedelta(years=1)
        py_rows = await sum_ledger_by_account(py_from, py_to, branches, db,
                                               category_filter=["4", "5", "6", "7", "8"])
        py_rev = await _sum_section(py_rows, ["4"], "", is_cr_normal=True)
        py_cogs = await _sum_section(py_rows, ["5"], "", is_cr_normal=False)
        py_exp = await _sum_section(py_rows, ["6"], "", is_cr_normal=False)
        py_fin = await _sum_section(py_rows, ["7"], "", is_cr_normal=True)
        py_oth = await _sum_section(py_rows, ["8"], "", is_cr_normal=True)
        prior_net = py_rev.total - py_cogs.total - py_exp.total + py_fin.total + py_oth.total

    return IncomeStatementReport(
        date_from=str(date_from),
        date_to=str(date_to),
        format=fmt,
        revenue=revenue,
        cost_of_sales=cogs,
        gross_profit=gross,
        operating_profit=operating_profit,
        expenses=expenses,
        finance_costs=finance,
        other_income=other,
        net_profit=net,
        net_profit_prior=prior_net,
        ytd_net_profit=net,
    )
