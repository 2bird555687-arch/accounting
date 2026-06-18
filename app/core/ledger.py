"""LedgerService — query บัญชีแยกประเภท, ยอดคงเหลือ, รายการเดินบัญชี."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Optional

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.context import AppContext, DrCr
from app.core.models import (
    AccountBalance,
    ChartOfAccount,
    JournalEntry as JournalEntryORM,
    JournalLine as JournalLineORM,
    LedgerEntry,
    Period,
)


@dataclass(frozen=True)
class LedgerLine:
    """หนึ่งบรรทัดในรายการเดินบัญชี."""

    entry_date: date
    entry_no: str
    description: str
    reference: Optional[str]
    debit_amount: Decimal
    credit_amount: Decimal
    running_balance: Decimal
    journal_type: str
    branch_id: int
    line_description: Optional[str]


@dataclass(frozen=True)
class AccountStatement:
    """รายการเดินบัญชีพร้อม summary."""

    account_code: str
    account_name: str
    date_from: date
    date_to: date
    opening_balance: Decimal
    lines: list[LedgerLine]
    total_debit: Decimal
    total_credit: Decimal
    closing_balance: Decimal


class LedgerService:
    """
    บริการอ่านข้อมูลบัญชีแยกประเภท

    ไม่มี write method — การเขียนต้องผ่าน PostingEngine เท่านั้น
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ── Balance ───────────────────────────────────────────────────────────────

    async def get_balance(
        self,
        account_code: str,
        ctx: AppContext,
        as_of_date: Optional[date] = None,
        branch_id: Optional[int] = None,
    ) -> Decimal:
        """
        คืนยอดคงเหลือของบัญชี ณ วันที่กำหนด

        Args:
            account_code: รหัสบัญชี เช่น "1101"
            ctx: AppContext
            as_of_date: ถ้า None ใช้วันสุดท้ายใน period ปัจจุบัน
            branch_id: ถ้า None ดึงรวมทุกสาขา

        Returns:
            ยอดคงเหลือ (บวก = Dr สำหรับบัญชีประเภท DR, บวก = Cr สำหรับ CR)
        """
        acc = await self._get_account(account_code)

        # ยอดจาก account_balances (งวดก่อนหน้า)
        opening = await self._get_opening_balance(acc, ctx, as_of_date, branch_id)

        # บวก/ลบ transactions ในงวดปัจจุบันถึง as_of_date
        current_dr, current_cr = await self._get_period_movements(
            acc, ctx, as_of_date, branch_id
        )

        if acc.normal_balance == DrCr.DR:
            return opening + current_dr - current_cr
        else:
            return opening + current_cr - current_dr

    async def get_balance_by_period(
        self,
        account_code: str,
        fiscal_year: int,
        month: int,
        ctx: AppContext,
        branch_id: Optional[int] = None,
    ) -> Decimal:
        """คืนยอดปิดงวดของบัญชีใน period ที่กำหนด."""
        acc = await self._get_account(account_code)

        stmt = (
            select(AccountBalance)
            .join(Period, AccountBalance.period_id == Period.id)
            .where(
                AccountBalance.account_id == acc.id,
                Period.fiscal_year == fiscal_year,
                Period.month == month,
            )
        )
        if branch_id is not None:
            stmt = stmt.where(AccountBalance.branch_id == branch_id)

        result = await self._session.execute(stmt)
        balances = result.scalars().all()

        if not balances:
            return Decimal(0)

        # รวมทุกสาขา (ถ้าไม่ระบุ branch)
        return sum((b.closing_balance for b in balances), Decimal(0))

    # ── Account Statement ─────────────────────────────────────────────────────

    async def get_account_statement(
        self,
        account_code: str,
        ctx: AppContext,
        date_from: date,
        date_to: date,
        branch_id: Optional[int] = None,
    ) -> AccountStatement:
        """
        คืนรายการเดินบัญชีพร้อม opening/closing balance

        Args:
            account_code: รหัสบัญชี
            ctx: AppContext
            date_from: วันเริ่มต้น
            date_to: วันสิ้นสุด
            branch_id: None = ทุกสาขา
        """
        acc = await self._get_account(account_code)

        # Opening balance ณ วันก่อน date_from
        opening = await self._get_balance_before(acc, ctx, date_from, branch_id)

        # ดึง ledger lines ในช่วงวันที่
        lines = await self._fetch_ledger_lines(acc, ctx, date_from, date_to, branch_id)

        total_dr = sum(ln.debit_amount for ln in lines)
        total_cr = sum(ln.credit_amount for ln in lines)

        if acc.normal_balance == DrCr.DR:
            closing = opening + total_dr - total_cr
        else:
            closing = opening + total_cr - total_dr

        return AccountStatement(
            account_code=acc.code,
            account_name=acc.name,
            date_from=date_from,
            date_to=date_to,
            opening_balance=opening,
            lines=lines,
            total_debit=total_dr,
            total_credit=total_cr,
            closing_balance=closing,
        )

    # ── Trial Balance helper ──────────────────────────────────────────────────

    async def get_all_balances(
        self,
        ctx: AppContext,
        fiscal_year: int,
        month: int,
        branch_id: Optional[int] = None,
    ) -> dict[str, Decimal]:
        """
        คืน {account_code: closing_balance} สำหรับ trial balance

        เรียกใช้โดย reports layer.
        """
        stmt = (
            select(ChartOfAccount.code, AccountBalance.closing_balance)
            .join(AccountBalance, ChartOfAccount.id == AccountBalance.account_id)
            .join(Period, AccountBalance.period_id == Period.id)
            .where(
                Period.fiscal_year == fiscal_year,
                Period.month == month,
                ChartOfAccount.is_active == True,  # noqa: E712
            )
        )
        if branch_id is not None:
            stmt = stmt.where(AccountBalance.branch_id == branch_id)

        result = await self._session.execute(stmt)
        rows = result.all()

        # รวมค่าถ้ามีหลาย branch
        balances: dict[str, Decimal] = {}
        for code, bal in rows:
            balances[code] = balances.get(code, Decimal(0)) + bal

        return balances

    # ── Private helpers ───────────────────────────────────────────────────────

    async def _get_account(self, account_code: str) -> ChartOfAccount:
        stmt = select(ChartOfAccount).where(ChartOfAccount.code == account_code)
        result = await self._session.execute(stmt)
        acc = result.scalar_one_or_none()
        if acc is None:
            raise ValueError(f"ไม่พบรหัสบัญชี {account_code!r} ใน COA")
        return acc

    async def _get_opening_balance(
        self,
        acc: ChartOfAccount,
        ctx: AppContext,
        as_of_date: Optional[date],
        branch_id: Optional[int],
    ) -> Decimal:
        """ยอดยกมาจากงวดที่ผ่านมาจนถึงงวดก่อนหน้า as_of_date."""
        ref_date = as_of_date or ctx.period
        ref_period_month = ref_date.month
        ref_period_year = ref_date.year

        stmt = (
            select(AccountBalance.closing_balance)
            .join(Period, AccountBalance.period_id == Period.id)
            .where(
                AccountBalance.account_id == acc.id,
                and_(
                    Period.fiscal_year * 100 + Period.month
                    < ref_period_year * 100 + ref_period_month
                ),
            )
            .order_by((Period.fiscal_year * 100 + Period.month).desc())
            .limit(1)
        )
        if branch_id is not None:
            stmt = stmt.where(AccountBalance.branch_id == branch_id)

        result = await self._session.execute(stmt)
        val = result.scalar_one_or_none()
        return val or Decimal(0)

    async def _get_period_movements(
        self,
        acc: ChartOfAccount,
        ctx: AppContext,
        as_of_date: Optional[date],
        branch_id: Optional[int],
    ) -> tuple[Decimal, Decimal]:
        """คืน (total_dr, total_cr) ในงวดปัจจุบันถึง as_of_date."""
        ref_date = as_of_date or ctx.period
        period_start = ref_date.replace(day=1)

        stmt = (
            select(
                LedgerEntry.debit_amount,
                LedgerEntry.credit_amount,
            )
            .join(JournalEntryORM, LedgerEntry.entry_id == JournalEntryORM.id)
            .where(
                LedgerEntry.account_id == acc.id,
                LedgerEntry.entry_date >= period_start,
                LedgerEntry.entry_date <= ref_date,
                JournalEntryORM.status == "posted",
            )
        )
        if branch_id is not None:
            stmt = stmt.where(LedgerEntry.branch_id == branch_id)

        result = await self._session.execute(stmt)
        rows = result.all()

        total_dr = sum((r.debit_amount for r in rows), Decimal(0))
        total_cr = sum((r.credit_amount for r in rows), Decimal(0))
        return total_dr, total_cr

    async def _get_balance_before(
        self,
        acc: ChartOfAccount,
        ctx: AppContext,
        before_date: date,
        branch_id: Optional[int],
    ) -> Decimal:
        """ยอดคงเหลือของบัญชีก่อนถึง before_date (exclusive)."""
        stmt = (
            select(LedgerEntry.running_balance)
            .join(JournalEntryORM, LedgerEntry.entry_id == JournalEntryORM.id)
            .where(
                LedgerEntry.account_id == acc.id,
                LedgerEntry.entry_date < before_date,
                JournalEntryORM.status == "posted",
            )
            .order_by(LedgerEntry.id.desc())
            .limit(1)
        )
        if branch_id is not None:
            stmt = stmt.where(LedgerEntry.branch_id == branch_id)

        result = await self._session.execute(stmt)
        val = result.scalar_one_or_none()
        return val or Decimal(0)

    async def _fetch_ledger_lines(
        self,
        acc: ChartOfAccount,
        ctx: AppContext,
        date_from: date,
        date_to: date,
        branch_id: Optional[int],
    ) -> list[LedgerLine]:
        stmt = (
            select(
                LedgerEntry.entry_date,
                JournalEntryORM.entry_no,
                JournalEntryORM.description,
                JournalEntryORM.reference,
                LedgerEntry.debit_amount,
                LedgerEntry.credit_amount,
                LedgerEntry.running_balance,
                JournalEntryORM.journal_type,
                LedgerEntry.branch_id,
                JournalLineORM.description.label("line_description"),
            )
            .join(JournalEntryORM, LedgerEntry.entry_id == JournalEntryORM.id)
            .join(JournalLineORM, LedgerEntry.line_id == JournalLineORM.id)
            .where(
                LedgerEntry.account_id == acc.id,
                LedgerEntry.entry_date >= date_from,
                LedgerEntry.entry_date <= date_to,
                JournalEntryORM.status == "posted",
            )
            .order_by(LedgerEntry.entry_date, LedgerEntry.id)
        )
        if branch_id is not None:
            stmt = stmt.where(LedgerEntry.branch_id == branch_id)

        result = await self._session.execute(stmt)
        rows = result.all()

        return [
            LedgerLine(
                entry_date=row.entry_date,
                entry_no=row.entry_no,
                description=row.description,
                reference=row.reference,
                debit_amount=row.debit_amount,
                credit_amount=row.credit_amount,
                running_balance=row.running_balance,
                journal_type=row.journal_type,
                branch_id=row.branch_id,
                line_description=row.line_description,
            )
            for row in rows
        ]
