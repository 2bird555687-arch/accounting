"""Cash Flow Statement (Indirect Method)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.context import AppContext
from app.core.models import AccountBalance, LedgerEntry, Period
from app.reports._base import BaseReport
from app.reports._queries import get_periods_in_range, sum_ledger_by_account


class CFLine(BaseModel):
    label: str
    amount: Decimal


class CFSection(BaseModel):
    label: str
    lines: list[CFLine]
    total: Decimal


class CashFlowReport(BaseReport):
    date_from: str
    date_to: str
    operating: CFSection
    investing: CFSection
    financing: CFSection
    net_change: Decimal
    opening_cash: Decimal
    closing_cash: Decimal

    def _to_html(self, title: str) -> str:
        def sec_html(sec: CFSection) -> str:
            rows = "".join(
                f"<tr><td>{ln.label}</td><td class='number'>{ln.amount:,.2f}</td></tr>"
                for ln in sec.lines
            )
            return (f"<h3>{sec.label}</h3><table>"
                    f"<tr><th>รายการ</th><th>จำนวนเงิน</th></tr>{rows}"
                    f"<tr class='total'><td>กระแสเงินสดสุทธิ - {sec.label}</td>"
                    f"<td class='number'>{sec.total:,.2f}</td></tr></table>")

        return (f"<html><head><meta charset='utf-8'></head><body>"
                f"<h1>{title}</h1><p>{self.date_from} ถึง {self.date_to}</p>"
                f"{sec_html(self.operating)}"
                f"{sec_html(self.investing)}"
                f"{sec_html(self.financing)}"
                f"<p><strong>เงินสดเพิ่มขึ้น(ลดลง): {self.net_change:,.2f}</strong></p>"
                f"<p>เงินสดต้นงวด: {self.opening_cash:,.2f}</p>"
                f"<p><strong>เงินสดปลายงวด: {self.closing_cash:,.2f}</strong></p>"
                f"</body></html>")


async def _get_account_net(account_codes: list[str], date_from: date, date_to: date,
                            branch_ids: list[int], db: AsyncSession) -> Decimal:
    """ผลต่างระหว่าง debit กับ credit สำหรับบัญชีที่ระบุในช่วงวัน."""
    from sqlalchemy import select, func
    from app.core.models import LedgerEntry, ChartOfAccount
    stmt = (
        select(
            func.sum(LedgerEntry.debit_amount) - func.sum(LedgerEntry.credit_amount)
        )
        .join(ChartOfAccount, LedgerEntry.account_id == ChartOfAccount.id)
        .where(
            ChartOfAccount.code.in_(account_codes),
            LedgerEntry.entry_date >= date_from,
            LedgerEntry.entry_date <= date_to,
            LedgerEntry.branch_id.in_(branch_ids),
        )
    )
    result = await db.scalar(stmt)
    return Decimal(str(result or 0))


async def generate(
    ctx: AppContext,
    db: AsyncSession,
    date_from: date,
    date_to: date,
    branch_ids: Optional[list[int]] = None,
) -> CashFlowReport:
    """สร้างงบกระแสเงินสด (Indirect Method)."""
    from app.reports.income_statement import generate as gen_is

    branches = branch_ids or [ctx.branch_id]

    # ── กำไรสุทธิ (จาก income statement) ─────────────────────────────────────
    is_report = await gen_is(ctx, db, date_from, date_to, branch_ids=branches)
    net_profit = is_report.net_profit

    # ── ค่าเสื่อมราคา (add back) ──────────────────────────────────────────────
    depreciation = await _get_account_net(["6601", "6602"], date_from, date_to, branches, db)

    # ── การเปลี่ยนแปลงใน Working Capital ──────────────────────────────────────
    # ลูกหนี้เพิ่ม = ใช้เงินสด (ลบ), ลูกหนี้ลด = ได้เงินสด (บวก)
    ar_change = -(await _get_account_net(["1110", "1111"], date_from, date_to, branches, db))
    inv_change = -(await _get_account_net(["1300", "1301", "1302"], date_from, date_to, branches, db))
    # เจ้าหนี้เพิ่ม = ได้เงินสด (บวก), เจ้าหนี้ลด = ใช้เงินสด (ลบ)
    ap_change = await _get_account_net(["2101", "2102"], date_from, date_to, branches, db)
    ap_change = -ap_change  # CR normal: increase = positive cash

    operating_lines = [
        CFLine(label="กำไร(ขาดทุน)สุทธิ", amount=net_profit),
        CFLine(label="ค่าเสื่อมราคาและค่าตัดจำหน่าย", amount=depreciation),
        CFLine(label="การเปลี่ยนแปลงลูกหนี้การค้า", amount=ar_change),
        CFLine(label="การเปลี่ยนแปลงสินค้าคงเหลือ", amount=inv_change),
        CFLine(label="การเปลี่ยนแปลงเจ้าหนี้การค้า", amount=ap_change),
    ]
    operating_total = sum(ln.amount for ln in operating_lines)

    # ── Investing ─────────────────────────────────────────────────────────────
    # เงินจ่ายซื้อสินทรัพย์ถาวร (Dr ในหมวด 16xx)
    fa_purchase = -(await _get_account_net(
        [str(c) for c in range(1600, 1700)], date_from, date_to, branches, db
    ))
    investing_lines = [
        CFLine(label="ซื้อสินทรัพย์ถาวร", amount=fa_purchase),
    ]
    investing_total = sum(ln.amount for ln in investing_lines)

    # ── Financing ─────────────────────────────────────────────────────────────
    # เงินกู้ระยะยาว (2200s), เงินทุน (3xxx)
    loan_change = -(await _get_account_net(
        [str(c) for c in range(2200, 2300)], date_from, date_to, branches, db
    ))
    equity_change = -(await _get_account_net(["3101", "3102"], date_from, date_to, branches, db))
    financing_lines = [
        CFLine(label="เงินกู้ระยะยาวรับ(คืน)", amount=loan_change),
        CFLine(label="เงินทุนรับเพิ่ม(จ่ายคืน)", amount=equity_change),
    ]
    financing_total = sum(ln.amount for ln in financing_lines)

    # ── เงินสดต้นงวด / ปลายงวด ───────────────────────────────────────────────
    # บัญชีเงินสดและธนาคาร: 1101, 1102, 1103
    cash_codes = ["1101", "1102", "1103"]
    net_change = operating_total + investing_total + financing_total

    # Opening cash = ยอดต้นงวดของบัญชีเงินสด
    from app.core.models import ChartOfAccount, AccountBalance
    opening_period = await db.scalar(
        select(Period).where(
            Period.start_date <= date_from,
            Period.end_date >= date_from,
        )
    )
    opening_cash = Decimal(0)
    if opening_period:
        from sqlalchemy import func as safunc
        result = await db.scalar(
            select(safunc.sum(AccountBalance.opening_balance))
            .join(ChartOfAccount, AccountBalance.account_id == ChartOfAccount.id)
            .where(
                ChartOfAccount.code.in_(cash_codes),
                AccountBalance.period_id == opening_period.id,
                AccountBalance.branch_id.in_(branches),
            )
        )
        opening_cash = Decimal(str(result or 0))

    closing_cash = opening_cash + net_change

    return CashFlowReport(
        date_from=str(date_from),
        date_to=str(date_to),
        operating=CFSection(label="กิจกรรมดำเนินงาน", lines=operating_lines, total=operating_total),
        investing=CFSection(label="กิจกรรมลงทุน", lines=investing_lines, total=investing_total),
        financing=CFSection(label="กิจกรรมจัดหาเงิน", lines=financing_lines, total=financing_total),
        net_change=net_change,
        opening_cash=opening_cash,
        closing_cash=closing_cash,
    )
