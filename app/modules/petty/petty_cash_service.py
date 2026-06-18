"""Petty Cash Service — ตั้งกองทุน / บันทึกค่าใช้จ่าย / เบิกคืน."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import select, func as sqlfunc
from sqlalchemy.ext.asyncio import AsyncSession

from app.context import AppContext, JournalType, DrCr
from app.core.engine import PostingEngine, JournalEntryInput, JournalLineInput
from app.master.models import PettyCashExpense, PettyCashFund
from app.master.schemas import (
    PettyCashExpenseOut,
    PettyCashFundOut,
    RecordExpenseIn,
    ReplenishResult,
    SetupFundIn,
)


async def _next_fund_no(company_id: int, db: AsyncSession) -> str:
    count = await db.scalar(
        select(sqlfunc.count()).select_from(PettyCashFund).where(
            PettyCashFund.company_id == company_id
        )
    )
    return f"PCF-{(count or 0) + 1:04d}"


class PettyCashService:

    @staticmethod
    async def setup_fund(data: SetupFundIn, ctx: AppContext, db: AsyncSession) -> PettyCashFundOut:
        """ตั้งกองทุนเงินสดย่อย:
        Dr 1103 (เงินสดย่อย) | Cr 1102 (ธนาคาร) → GJ
        """
        if ctx.user_role not in ("firm_admin", "accountant"):
            raise PermissionError("ต้องการสิทธิ์ accountant ขึ้นไป")

        fund_no = await _next_fund_no(ctx.company_id, db)

        fund = PettyCashFund(
            company_id=ctx.company_id,
            branch_id=ctx.branch_id,
            fund_no=fund_no,
            description=data.description,
            petty_cash_account=data.petty_cash_account,
            bank_account=data.bank_account,
            initial_amount=data.amount,
            current_balance=data.amount,
            status="active",
            created_by=ctx.user_id,
        )
        db.add(fund)
        await db.flush()

        lines = [
            JournalLineInput(account_code=data.petty_cash_account, side=DrCr.DR, amount=data.amount,
                             description="ตั้งกองทุนเงินสดย่อย"),
            JournalLineInput(account_code=data.bank_account, side=DrCr.CR, amount=data.amount,
                             description="โอนจากธนาคาร"),
        ]
        entry = JournalEntryInput(
            journal_type=JournalType.GJ,
            entry_date=date.today(),
            description=f"ตั้งกองทุนเงินสดย่อย {fund_no}",
            lines=lines,
            source_module="PETTY",
            source_id=fund.id,
        )
        engine = PostingEngine(db)
        entry_no = await engine.post(entry, ctx)
        fund.setup_journal_no = entry_no

        await db.flush()
        await db.refresh(fund)
        return PettyCashFundOut.model_validate(fund)

    @staticmethod
    async def record_expense(data: RecordExpenseIn, ctx: AppContext, db: AsyncSession) -> PettyCashExpenseOut:
        """บันทึกค่าใช้จ่ายเงินสดย่อย:
        Dr ค่าใช้จ่าย (account_code) | Cr 1103 (เงินสดย่อย) → GJ
        """
        if ctx.user_role not in ("firm_admin", "accountant", "junior"):
            raise PermissionError("ไม่มีสิทธิ์บันทึกค่าใช้จ่าย")

        fund = await db.scalar(
            select(PettyCashFund).where(
                PettyCashFund.id == data.fund_id,
                PettyCashFund.company_id == ctx.company_id,
                PettyCashFund.status == "active",
            )
        )
        if not fund:
            raise ValueError("ไม่พบกองทุนเงินสดย่อย หรือกองทุนปิดแล้ว")

        if fund.current_balance < data.amount:
            raise ValueError(
                f"ยอดเงินสดย่อยไม่พอ (คงเหลือ {fund.current_balance} / ต้องการ {data.amount})"
            )

        fund.current_balance -= data.amount

        expense = PettyCashExpense(
            fund_id=fund.id,
            company_id=ctx.company_id,
            branch_id=ctx.branch_id,
            expense_date=data.expense_date,
            description=data.description,
            account_code=data.account_code,
            amount=data.amount,
            receipt_no=data.receipt_no,
            is_replenished=False,
            created_by=ctx.user_id,
        )
        db.add(expense)
        await db.flush()

        lines = [
            JournalLineInput(account_code=data.account_code, side=DrCr.DR, amount=data.amount,
                             description=data.description),
            JournalLineInput(account_code=fund.petty_cash_account, side=DrCr.CR, amount=data.amount,
                             description="เงินสดย่อย"),
        ]
        entry = JournalEntryInput(
            journal_type=JournalType.GJ,
            entry_date=data.expense_date,
            description=f"ค่าใช้จ่ายเงินสดย่อย {fund.fund_no}: {data.description}",
            lines=lines,
            source_module="PETTY",
            source_id=expense.id,
        )
        engine = PostingEngine(db)
        entry_no = await engine.post(entry, ctx)
        expense.expense_journal_no = entry_no

        await db.flush()
        await db.refresh(expense)
        return PettyCashExpenseOut.model_validate(expense)

    @staticmethod
    async def replenish(
        fund_id: int, ctx: AppContext, db: AsyncSession
    ) -> ReplenishResult:
        """เบิกเงินเพิ่มกองทุน — รวมค่าใช้จ่ายที่ยังไม่ได้เบิก:
        Dr ค่าใช้จ่าย (แยกบัญชี) | Cr 1102 (ธนาคาร) → GJ
        (ไม่ผ่านบัญชี 1103 อีก เพราะ record_expense หักออกไปแล้ว)
        """
        if ctx.user_role not in ("firm_admin", "accountant"):
            raise PermissionError("ต้องการสิทธิ์ accountant ขึ้นไป")

        fund = await db.scalar(
            select(PettyCashFund).where(
                PettyCashFund.id == fund_id,
                PettyCashFund.company_id == ctx.company_id,
                PettyCashFund.status == "active",
            )
        )
        if not fund:
            raise ValueError("ไม่พบกองทุนเงินสดย่อย")

        expenses = await db.scalars(
            select(PettyCashExpense).where(
                PettyCashExpense.fund_id == fund_id,
                PettyCashExpense.is_replenished.is_(False),
            ).order_by(PettyCashExpense.expense_date)
        )
        expenses = list(expenses)
        if not expenses:
            raise ValueError("ไม่มีรายการค่าใช้จ่ายที่รอเบิกคืน")

        # รวมตามบัญชี
        account_totals: dict[str, Decimal] = {}
        for exp in expenses:
            account_totals[exp.account_code] = account_totals.get(exp.account_code, Decimal(0)) + exp.amount

        total = sum(account_totals.values())

        lines: list[JournalLineInput] = [
            JournalLineInput(account_code=acc, side=DrCr.DR, amount=amt, description="เบิกคืนเงินสดย่อย")
            for acc, amt in account_totals.items()
        ]
        lines.append(
            JournalLineInput(account_code=fund.bank_account, side=DrCr.CR, amount=total,
                             description=f"เบิกคืน {fund.fund_no}")
        )

        entry = JournalEntryInput(
            journal_type=JournalType.GJ,
            entry_date=date.today(),
            description=f"เบิกคืนเงินสดย่อย {fund.fund_no} ({len(expenses)} รายการ)",
            lines=lines,
            source_module="PETTY",
            source_id=fund.id,
        )
        engine = PostingEngine(db)
        entry_no = await engine.post(entry, ctx)

        fund.current_balance += total

        for exp in expenses:
            exp.is_replenished = True
            exp.replenish_journal_no = entry_no

        await db.flush()

        return ReplenishResult(
            journal_entry_no=entry_no,
            total_replenished=total,
            expense_count=len(expenses),
            new_balance=fund.current_balance,
        )

    @staticmethod
    async def list_funds(ctx: AppContext, db: AsyncSession) -> list[PettyCashFundOut]:
        rows = await db.scalars(
            select(PettyCashFund).where(PettyCashFund.company_id == ctx.company_id)
            .order_by(PettyCashFund.fund_no)
        )
        return [PettyCashFundOut.model_validate(r) for r in rows]

    @staticmethod
    async def get_fund(fund_id: int, ctx: AppContext, db: AsyncSession) -> PettyCashFundOut:
        fund = await db.scalar(
            select(PettyCashFund).where(
                PettyCashFund.id == fund_id,
                PettyCashFund.company_id == ctx.company_id,
            )
        )
        if not fund:
            raise ValueError("ไม่พบกองทุนเงินสดย่อย")
        return PettyCashFundOut.model_validate(fund)

    @staticmethod
    async def list_expenses(
        fund_id: int, ctx: AppContext, db: AsyncSession, replenished: bool | None = None
    ) -> list[PettyCashExpenseOut]:
        q = select(PettyCashExpense).where(
            PettyCashExpense.fund_id == fund_id,
            PettyCashExpense.company_id == ctx.company_id,
        )
        if replenished is not None:
            q = q.where(PettyCashExpense.is_replenished.is_(replenished))
        q = q.order_by(PettyCashExpense.expense_date.desc())
        rows = await db.scalars(q)
        return [PettyCashExpenseOut.model_validate(r) for r in rows]
