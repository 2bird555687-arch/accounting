"""Shared query helpers สำหรับ reports layer."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.context import AppContext
from app.core.models import (
    AccountBalance,
    ChartOfAccount,
    LedgerEntry,
    Period,
)


async def get_period(year: int, month: int, db: AsyncSession) -> Period | None:
    return await db.scalar(
        select(Period).where(Period.fiscal_year == year, Period.month == month)
    )


async def get_periods_in_range(date_from: date, date_to: date, db: AsyncSession) -> list[Period]:
    rows = await db.scalars(
        select(Period).where(
            Period.start_date <= date_to,
            Period.end_date >= date_from,
        ).order_by(Period.start_date)
    )
    return list(rows)


async def get_account_balances(
    period_ids: list[int],
    branch_ids: list[int],
    db: AsyncSession,
    category_filter: list[str] | None = None,
) -> list[tuple[ChartOfAccount, Decimal, Decimal, Decimal, Decimal]]:
    """(COA, opening, debit, credit, closing) — รวมทุก branch ที่ระบุ."""
    stmt = (
        select(
            ChartOfAccount,
            func.sum(AccountBalance.opening_balance),
            func.sum(AccountBalance.total_debit),
            func.sum(AccountBalance.total_credit),
            func.sum(AccountBalance.closing_balance),
        )
        .join(AccountBalance, AccountBalance.account_id == ChartOfAccount.id)
        .where(
            AccountBalance.period_id.in_(period_ids),
            AccountBalance.branch_id.in_(branch_ids),
            ChartOfAccount.is_header == False,
        )
        .group_by(ChartOfAccount.id)
        .order_by(ChartOfAccount.code)
    )
    if category_filter:
        stmt = stmt.where(ChartOfAccount.category.in_(category_filter))

    rows = await db.execute(stmt)
    return [
        (r[0], Decimal(str(r[1] or 0)), Decimal(str(r[2] or 0)),
         Decimal(str(r[3] or 0)), Decimal(str(r[4] or 0)))
        for r in rows.all()
    ]


async def sum_ledger_by_account(
    date_from: date,
    date_to: date,
    branch_ids: list[int],
    db: AsyncSession,
    category_filter: list[str] | None = None,
) -> list[tuple[ChartOfAccount, Decimal, Decimal]]:
    """(COA, total_debit, total_credit) จาก LedgerEntry ในช่วงวันที่."""
    stmt = (
        select(
            ChartOfAccount,
            func.sum(LedgerEntry.debit_amount),
            func.sum(LedgerEntry.credit_amount),
        )
        .join(LedgerEntry, LedgerEntry.account_id == ChartOfAccount.id)
        .where(
            LedgerEntry.entry_date >= date_from,
            LedgerEntry.entry_date <= date_to,
            LedgerEntry.branch_id.in_(branch_ids),
            ChartOfAccount.is_header == False,
        )
        .group_by(ChartOfAccount.id)
        .order_by(ChartOfAccount.code)
    )
    if category_filter:
        stmt = stmt.where(ChartOfAccount.category.in_(category_filter))

    rows = await db.execute(stmt)
    return [
        (r[0], Decimal(str(r[1] or 0)), Decimal(str(r[2] or 0)))
        for r in rows.all()
    ]


def normal_balance(coa: ChartOfAccount) -> Decimal:
    """คำนวณยอดคงเหลือตามด้านปกติของบัญชี."""
    # ส่งคืนเป็น positive สำหรับยอดปกติ, negative สำหรับยอดผิดด้าน
    # DR normal: asset, expense, cost
    # CR normal: liability, equity, revenue
    return Decimal(1) if coa.normal_balance == "DR" else Decimal(-1)
