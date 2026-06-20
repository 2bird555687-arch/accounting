"""Bank Account service — accounts, balances, transfers."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.context import AppContext, DrCr, JournalType
from app.core.engine import (
    JournalEntryInput,
    JournalLineInput,
    PostingEngine,
    PostingError,
)
from app.core.models import ChartOfAccount, LedgerEntry
from app.modules.bank.models import BankAccount, BankTransfer


async def get_bank_accounts(
    db: AsyncSession, company_id: int, active_only: bool = True
) -> list[BankAccount]:
    """คืนรายการบัญชีธนาคารของ company."""
    stmt = select(BankAccount).where(BankAccount.company_id == company_id)
    if active_only:
        stmt = stmt.where(BankAccount.is_active == True)  # noqa: E712
    stmt = stmt.order_by(BankAccount.id)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_bank_account(
    db: AsyncSession, company_id: int, bank_account_id: int
) -> BankAccount:
    acc = await db.scalar(
        select(BankAccount).where(
            BankAccount.id == bank_account_id,
            BankAccount.company_id == company_id,
        )
    )
    if acc is None:
        raise HTTPException(404, "ไม่พบบัญชีธนาคาร")
    return acc


async def create_bank_account(
    db: AsyncSession,
    company_id: int,
    *,
    bank_name: str,
    coa_account_code: str,
    account_number: Optional[str] = None,
    account_name: Optional[str] = None,
    account_type: str = "current",
) -> BankAccount:
    """สร้างบัญชีธนาคารใหม่ — ตรวจว่ารหัส COA มีจริง."""
    coa = await db.scalar(
        select(ChartOfAccount).where(ChartOfAccount.code == coa_account_code)
    )
    if coa is None:
        raise HTTPException(400, f"ไม่พบรหัสบัญชี COA {coa_account_code}")
    if coa.is_header:
        raise HTTPException(400, f"รหัส {coa_account_code} เป็นบัญชีหมวด (header)")

    acc = BankAccount(
        company_id=company_id,
        bank_name=bank_name,
        account_number=account_number,
        account_name=account_name,
        account_type=account_type,
        coa_account_code=coa_account_code,
    )
    db.add(acc)
    await db.flush()
    return acc


async def get_bank_balance(
    db: AsyncSession, ctx: AppContext, bank_account_id: int
) -> Decimal:
    """ยอดคงเหลือ = sum(debit) - sum(credit) ของ ledger สำหรับ coa_account_code."""
    acc = await get_bank_account(db, ctx.company_id, bank_account_id)
    return await get_balance_by_code(db, acc.coa_account_code)


async def get_balance_by_code(db: AsyncSession, coa_account_code: str) -> Decimal:
    coa = await db.scalar(
        select(ChartOfAccount).where(ChartOfAccount.code == coa_account_code)
    )
    if coa is None:
        return Decimal(0)
    total = await db.scalar(
        select(
            func.coalesce(func.sum(LedgerEntry.debit_amount), 0)
            - func.coalesce(func.sum(LedgerEntry.credit_amount), 0)
        ).where(LedgerEntry.account_id == coa.id)
    )
    return Decimal(str(total or 0))


async def create_bank_transfer(
    db: AsyncSession,
    ctx: AppContext,
    *,
    from_id: int,
    to_id: int,
    amount: Decimal,
    transfer_date: date,
    note: Optional[str] = None,
) -> BankTransfer:
    """โอนเงินระหว่างบัญชี — post JE (Dr to | Cr from) ผ่าน PostingEngine."""
    if not ctx.can_post:
        raise HTTPException(403, "ไม่มีสิทธิ์บันทึกรายการ")
    if from_id == to_id:
        raise HTTPException(400, "บัญชีต้นทางและปลายทางต้องไม่ใช่บัญชีเดียวกัน")

    amount = Decimal(str(amount))
    if amount <= 0:
        raise HTTPException(400, "จำนวนเงินต้องมากกว่า 0")

    from_acc = await get_bank_account(db, ctx.company_id, from_id)
    to_acc = await get_bank_account(db, ctx.company_id, to_id)

    desc = f"โอนเงิน {from_acc.bank_name} → {to_acc.bank_name}"
    entry = JournalEntryInput(
        journal_type=JournalType.GJ,
        entry_date=transfer_date,
        description=note or desc,
        reference="BANK-TRANSFER",
        source_module="bank",
        lines=[
            JournalLineInput(
                account_code=to_acc.coa_account_code,
                side=DrCr.DR,
                amount=amount,
                description=f"รับโอนเข้า {to_acc.bank_name}",
            ),
            JournalLineInput(
                account_code=from_acc.coa_account_code,
                side=DrCr.CR,
                amount=amount,
                description=f"โอนออกจาก {from_acc.bank_name}",
            ),
        ],
    )

    engine = PostingEngine(db)
    try:
        journal_ref = await engine.post(entry, ctx)
    except PostingError as e:
        raise HTTPException(400, str(e))

    transfer = BankTransfer(
        company_id=ctx.company_id,
        from_bank_account_id=from_id,
        to_bank_account_id=to_id,
        amount=amount,
        transfer_date=transfer_date,
        journal_ref=journal_ref,
        note=note,
        created_by=ctx.user_id,
    )
    db.add(transfer)
    await db.flush()
    return transfer


async def get_bank_transfers(
    db: AsyncSession, company_id: int, limit: int = 100
) -> list[BankTransfer]:
    stmt = (
        select(BankTransfer)
        .where(BankTransfer.company_id == company_id)
        .order_by(BankTransfer.id.desc())
        .limit(limit)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())
