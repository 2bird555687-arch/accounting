"""TAX — VAT Service (get_vat_summary / generate_pp30)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import select, func as sqlfunc
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.tax.schemas import PP30Data, VATSummaryItem
from app.core.context import AppContext
from app.core.models import LedgerEntry  # ledger_entries table


class VATService:

    @staticmethod
    async def get_vat_summary(
        ctx: AppContext,
        db: AsyncSession,
        fiscal_year: int,
        month: int,
    ) -> list[VATSummaryItem]:
        """สรุป VAT input (1140) และ output (2120) สำหรับงวด."""
        period_str = f"{fiscal_year}{month:02d}"

        results: list[VATSummaryItem] = []

        for account_code, direction in [("1140", "input"), ("2120", "output")]:
            row = await db.execute(
                select(
                    sqlfunc.sum(LedgerEntry.amount).label("total_vat"),
                    sqlfunc.count(LedgerEntry.id).label("tx_count"),
                ).where(
                    LedgerEntry.company_id == ctx.company_id,
                    LedgerEntry.account_code == account_code,
                    LedgerEntry.period == period_str,
                )
            )
            r = row.one()
            vat = r.total_vat or Decimal(0)
            base = (vat / Decimal("0.07")).quantize(Decimal("0.01")) if vat else Decimal(0)

            results.append(VATSummaryItem(
                account_code=account_code,
                direction=direction,
                period=period_str,
                total_base=base,
                total_vat=vat,
                transaction_count=r.tx_count or 0,
            ))

        return results

    @staticmethod
    async def generate_pp30(
        ctx: AppContext,
        db: AsyncSession,
        fiscal_year: int,
        month: int,
    ) -> PP30Data:
        """สร้างข้อมูล ภ.พ.30."""
        summary = await VATService.get_vat_summary(ctx, db, fiscal_year, month)

        input_item = next((s for s in summary if s.direction == "input"), None)
        output_item = next((s for s in summary if s.direction == "output"), None)

        input_vat = input_item.total_vat if input_item else Decimal(0)
        output_vat = output_item.total_vat if output_item else Decimal(0)
        input_base = input_item.total_base if input_item else Decimal(0)
        output_base = output_item.total_base if output_item else Decimal(0)
        net_vat = output_vat - input_vat

        # กำหนดส่ง: วันที่ 15 ของเดือนถัดไป
        if month == 12:
            due_year, due_month = fiscal_year + 1, 1
        else:
            due_year, due_month = fiscal_year, month + 1
        due_date = date(due_year, due_month, 15)

        return PP30Data(
            period=f"{fiscal_year}{month:02d}",
            output_vat=output_vat,
            input_vat=input_vat,
            net_vat=net_vat,
            due_date=due_date,
            output_base=output_base,
            input_base=input_base,
        )
