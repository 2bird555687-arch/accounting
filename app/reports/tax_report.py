"""Tax Reports — ภพ.30, ภ.ง.ด.1, ภ.ง.ด.3."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.context import AppContext
from app.core.models import ChartOfAccount, LedgerEntry, Period
from app.modules.tax.models import WHTRecord
from app.reports._base import BaseReport
from app.reports._queries import get_period


# ── ภพ.30 VAT ─────────────────────────────────────────────────────────────────

class VATLine(BaseModel):
    tax_base: Decimal
    vat_amount: Decimal
    vat_type: str  # input | output


class PP30Report(BaseReport):
    period: str
    year_month: str
    output_vat_base: Decimal    # ภาษีขาย (ยอดขาย)
    output_vat: Decimal         # ภาษีขายที่ต้องนำส่ง
    input_vat: Decimal          # ภาษีซื้อ
    net_vat: Decimal            # output - input (ต้องนำส่ง/ขอคืน)
    must_pay: bool              # True = ต้องนำส่ง, False = ขอคืน

    def _to_html(self, title: str) -> str:
        color = "#c00000" if self.must_pay else "#006400"
        return (f"<html><head><meta charset='utf-8'></head><body>"
                f"<h1>{title}</h1><p>งวด: {self.period}</p>"
                f"<table>"
                f"<tr><th>รายการ</th><th>ฐานภาษี</th><th>ภาษี</th></tr>"
                f"<tr><td>ภาษีขาย (Output VAT)</td>"
                f"<td class='number'>{self.output_vat_base:,.2f}</td>"
                f"<td class='number'>{self.output_vat:,.2f}</td></tr>"
                f"<tr><td>ภาษีซื้อ (Input VAT)</td>"
                f"<td></td><td class='number'>{self.input_vat:,.2f}</td></tr>"
                f"<tr class='total'><td>ภาษีที่ต้องนำส่ง (ขอคืน)</td>"
                f"<td></td>"
                f"<td class='number' style='color:{color}'>{self.net_vat:,.2f}</td></tr>"
                f"</table></body></html>")


async def pp30(ctx: AppContext, db: AsyncSession, year: int, month: int) -> PP30Report:
    """สร้างสรุปสำหรับ ภพ.30."""
    period = await get_period(year, month, db)
    if not period:
        raise ValueError(f"ไม่พบงวด {year}/{month:02d}")

    # Output VAT: บัญชี 2120 (ภาษีขาย)
    output_cr = await db.scalar(
        select(func.sum(LedgerEntry.credit_amount) - func.sum(LedgerEntry.debit_amount))
        .join(ChartOfAccount, LedgerEntry.account_id == ChartOfAccount.id)
        .where(
            ChartOfAccount.code.in_(["2120", "2121"]),
            LedgerEntry.entry_date >= period.start_date,
            LedgerEntry.entry_date <= period.end_date,
        )
    )
    output_vat = Decimal(str(output_cr or 0))

    # Output tax base (ยอดขายก่อนภาษี) ≈ output_vat / 0.07
    output_base = (output_vat / Decimal("0.07")).quantize(Decimal("0.01")) if output_vat else Decimal(0)

    # Input VAT: บัญชี 1140, 1151 (ภาษีซื้อ)
    input_dr = await db.scalar(
        select(func.sum(LedgerEntry.debit_amount) - func.sum(LedgerEntry.credit_amount))
        .join(ChartOfAccount, LedgerEntry.account_id == ChartOfAccount.id)
        .where(
            ChartOfAccount.code.in_(["1140", "1151"]),
            LedgerEntry.entry_date >= period.start_date,
            LedgerEntry.entry_date <= period.end_date,
        )
    )
    input_vat = Decimal(str(input_dr or 0))

    net = output_vat - input_vat

    return PP30Report(
        period=f"{year}/{month:02d}",
        year_month=f"{year}{month:02d}",
        output_vat_base=output_base,
        output_vat=output_vat,
        input_vat=input_vat,
        net_vat=net,
        must_pay=net > 0,
    )


# ── WHT Reports ────────────────────────────────────────────────────────────────

class WHTLine(BaseModel):
    contact_id: int
    income_type: str
    wht_type: str
    base_amount: Decimal
    wht_rate: Decimal
    wht_amount: Decimal
    payment_date: str


class WHTReport(BaseReport):
    period: str
    form_type: str   # pnd1 | pnd3 | pnd53
    lines: list[WHTLine]
    total_base: Decimal
    total_wht: Decimal

    def _to_html(self, title: str) -> str:
        rows = "".join(
            f"<tr><td>{ln.contact_id}</td><td>{ln.income_type}</td>"
            f"<td class='number'>{ln.base_amount:,.2f}</td>"
            f"<td class='number'>{ln.wht_rate}%</td>"
            f"<td class='number'>{ln.wht_amount:,.2f}</td>"
            f"<td>{ln.payment_date}</td></tr>"
            for ln in self.lines
        )
        return (f"<html><head><meta charset='utf-8'></head><body>"
                f"<h1>{title}</h1><p>งวด: {self.period}</p>"
                f"<table>"
                f"<tr><th>Contact</th><th>ประเภทเงินได้</th>"
                f"<th>ฐานภาษี</th><th>อัตรา</th><th>ภาษีที่หัก</th><th>วันที่จ่าย</th></tr>"
                f"{rows}"
                f"<tr class='total'><td colspan='2'>รวม</td>"
                f"<td class='number'>{self.total_base:,.2f}</td>"
                f"<td></td>"
                f"<td class='number'>{self.total_wht:,.2f}</td>"
                f"<td></td></tr>"
                f"</table></body></html>")


async def _wht_report(
    ctx: AppContext, db: AsyncSession,
    year: int, month: int,
    form_type: str,
    income_types: list[str],
    direction: str = "collected",
) -> WHTReport:
    records = list(await db.scalars(
        select(WHTRecord).where(
            WHTRecord.company_id == ctx.company_id,
            WHTRecord.fiscal_year == year,
            WHTRecord.month == month,
            WHTRecord.direction == direction,
            WHTRecord.income_type.in_(income_types),
        ).order_by(WHTRecord.payment_date)
    ))

    lines = [
        WHTLine(
            contact_id=r.contact_id,
            income_type=r.income_type,
            wht_type=r.wht_type,
            base_amount=r.base_amount,
            wht_rate=r.wht_rate,
            wht_amount=r.wht_amount,
            payment_date=str(r.payment_date),
        )
        for r in records
    ]

    return WHTReport(
        period=f"{year}/{month:02d}",
        form_type=form_type,
        lines=lines,
        total_base=sum(ln.base_amount for ln in lines),
        total_wht=sum(ln.wht_amount for ln in lines),
    )


async def pnd1(ctx: AppContext, db: AsyncSession, year: int, month: int) -> WHTReport:
    """ภ.ง.ด.1 — WHT เงินเดือนและค่าจ้าง (income_type 1)."""
    return await _wht_report(ctx, db, year, month, "pnd1", ["1"])


async def pnd3(ctx: AppContext, db: AsyncSession, year: int, month: int) -> WHTReport:
    """ภ.ง.ด.3 — WHT ค่าบริการบุคคลธรรมดา (income_type 3, 5, 6)."""
    return await _wht_report(ctx, db, year, month, "pnd3", ["3", "5", "6"])


async def pnd53(ctx: AppContext, db: AsyncSession, year: int, month: int) -> WHTReport:
    """ภ.ง.ด.53 — WHT นิติบุคคล (income_type 3, 5, 6, collected)."""
    return await _wht_report(ctx, db, year, month, "pnd53", ["3", "5", "6", "2"])
