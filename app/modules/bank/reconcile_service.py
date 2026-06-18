"""Bank Reconciliation Service."""

from __future__ import annotations

import json
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.context import AppContext, DrCr, JournalType
from app.core.engine import PostingEngine, JournalEntryInput, JournalLineInput
from app.core.models import JournalLine, JournalEntry, ChartOfAccount
from app.modules.bank.models import BankReconciliation, BankReconLine
from app.modules.bank.schemas import (
    BankReconReport,
    MatchConfirm,
    ReconLineOut,
    ReconResult,
)
from app.ocr.bank_reader import BankStatementOCRResult


# ── Keyword → account_code สำหรับรายการธนาคารทั่วไป ──────────────────────────

_BANK_KEYWORDS: dict[str, str] = {
    "ดอกเบี้ย": "4201",      # ดอกเบี้ยรับ
    "interest": "4201",
    "ค่าธรรมเนียม": "7102",  # ค่าธรรมเนียมธนาคาร
    "fee": "7102",
    "service charge": "7102",
    "สาขา": "7102",
    "เบี้ยปรับ": "7102",
    "ภาษี": "2121",           # ภาษีหัก ณ ที่จ่าย
    "withold": "2121",
}


def classify_bank_transaction(description: str) -> str | None:
    """ระบุ account_code จาก description ของรายการธนาคาร."""
    desc = description.lower()
    for kw, code in _BANK_KEYWORDS.items():
        if kw.lower() in desc:
            return code
    return None


async def start_reconciliation(
    bank_account_code: str,
    statement: BankStatementOCRResult,
    ctx: AppContext,
    db: AsyncSession,
) -> int:
    """สร้าง BankReconciliation record และ lines จาก statement."""
    recon = BankReconciliation(
        company_id=ctx.company_id,
        branch_id=ctx.branch_id,
        bank_account_code=bank_account_code,
        bank_name=statement.bank_name,
        account_no=statement.account_no,
        account_name=statement.account_name,
        period_from=date.fromisoformat(statement.period_from) if statement.period_from else None,
        period_to=date.fromisoformat(statement.period_to) if statement.period_to else None,
        opening_balance=statement.opening_balance,
        closing_balance=statement.closing_balance,
        statement_json=json.dumps(statement.to_dict(), default=str),
        status="matching",
        created_by=ctx.user_id,
    )
    db.add(recon)
    await db.flush()

    # สร้าง STATEMENT_ONLY lines สำหรับทุกรายการใน statement
    for txn in statement.transactions:
        line = BankReconLine(
            recon_id=recon.id,
            company_id=ctx.company_id,
            stmt_date=date.fromisoformat(txn.date) if txn.date else None,
            stmt_description=txn.description,
            stmt_debit=txn.debit,
            stmt_credit=txn.credit,
            stmt_balance=txn.balance,
            stmt_ref_no=txn.ref_no,
            match_status="STATEMENT_ONLY",
        )
        db.add(line)

    await db.flush()
    return recon.id


async def auto_match(recon_id: int, ctx: AppContext, db: AsyncSession) -> ReconResult:
    """จับคู่รายการ statement กับรายการในสมุดบัญชี."""
    recon = await db.scalar(
        select(BankReconciliation).where(
            BankReconciliation.id == recon_id,
            BankReconciliation.company_id == ctx.company_id,
        )
    )
    if not recon:
        raise ValueError(f"ไม่พบ reconciliation id={recon_id}")

    # โหลด recon lines ทั้งหมด
    stmt_lines = list(await db.scalars(
        select(BankReconLine).where(BankReconLine.recon_id == recon_id)
    ))

    # โหลด journal lines สำหรับ bank account ในช่วงเวลา
    coa = await db.scalar(
        select(ChartOfAccount).where(
            ChartOfAccount.code == recon.bank_account_code
        )
    )
    if not coa:
        raise ValueError(f"ไม่พบบัญชี {recon.bank_account_code} ใน COA")

    journal_lines_q = (
        select(JournalLine, JournalEntry)
        .join(JournalEntry, JournalLine.entry_id == JournalEntry.id)
        .where(
            JournalLine.account_id == coa.id,
            JournalEntry.status == "posted",
        )
    )
    if recon.period_from:
        journal_lines_q = journal_lines_q.where(JournalEntry.entry_date >= recon.period_from)
    if recon.period_to:
        journal_lines_q = journal_lines_q.where(JournalEntry.entry_date <= recon.period_to)

    rows = await db.execute(journal_lines_q)
    book_entries: list[tuple[JournalLine, JournalEntry]] = list(rows.all())
    used_book_ids: set[int] = set()

    # จับคู่แต่ละ statement line
    for sl in stmt_lines:
        if sl.stmt_date is None:
            continue
        stmt_amount = sl.stmt_credit if sl.stmt_credit > 0 else sl.stmt_debit
        # statement credit → journal debit (เงินเข้าธนาคาร = Dr ธนาคาร)
        # statement debit  → journal credit (เงินออกธนาคาร = Cr ธนาคาร)
        is_credit_txn = sl.stmt_credit > Decimal(0)

        best_line: JournalLine | None = None
        best_entry: JournalEntry | None = None
        best_status = "STATEMENT_ONLY"
        best_conf = 0

        for jl, je in book_entries:
            if jl.id in used_book_ids:
                continue

            book_amount = jl.debit_amount if is_credit_txn else jl.credit_amount
            if book_amount == 0:
                continue

            amount_match = abs(book_amount - stmt_amount) < Decimal("0.01")
            date_diff = abs((je.entry_date - sl.stmt_date).days)

            if amount_match and date_diff == 0:
                best_line = jl
                best_entry = je
                best_status = "MATCHED"
                best_conf = 100
                break
            elif amount_match and date_diff <= 3 and best_conf < 85:
                best_line = jl
                best_entry = je
                best_status = "NEAR_MATCH"
                best_conf = max(85, 100 - date_diff * 5)
            elif amount_match and best_conf < 60:
                best_line = jl
                best_entry = je
                best_status = "NEAR_MATCH"
                best_conf = 60

        if best_line and best_entry:
            used_book_ids.add(best_line.id)
            sl.journal_line_id = best_line.id
            sl.journal_entry_no = best_entry.entry_no
            sl.journal_date = best_entry.entry_date
            sl.journal_debit = best_line.debit_amount
            sl.journal_credit = best_line.credit_amount
            sl.journal_description = best_entry.description
            sl.match_status = best_status
            sl.match_confidence = best_conf

    # รายการในสมุดที่ไม่มีใน statement → BOOK_ONLY
    for jl, je in book_entries:
        if jl.id not in used_book_ids:
            book_only = BankReconLine(
                recon_id=recon_id,
                company_id=ctx.company_id,
                journal_line_id=jl.id,
                journal_entry_no=je.entry_no,
                journal_date=je.entry_date,
                journal_debit=jl.debit_amount,
                journal_credit=jl.credit_amount,
                journal_description=je.description,
                match_status="BOOK_ONLY",
            )
            db.add(book_only)

    await db.flush()

    # รวม stats
    all_lines = list(await db.scalars(
        select(BankReconLine).where(BankReconLine.recon_id == recon_id)
    ))
    counts = {"MATCHED": 0, "NEAR_MATCH": 0, "STATEMENT_ONLY": 0, "BOOK_ONLY": 0, "MISMATCH": 0}
    for ln in all_lines:
        counts[ln.match_status] = counts.get(ln.match_status, 0) + 1

    return ReconResult(
        recon_id=recon_id,
        total_lines=len(all_lines),
        matched=counts["MATCHED"],
        near_match=counts["NEAR_MATCH"],
        statement_only=counts["STATEMENT_ONLY"],
        book_only=counts["BOOK_ONLY"],
        mismatch=counts["MISMATCH"],
        lines=[ReconLineOut.model_validate(ln) for ln in all_lines],
    )


async def confirm_match(
    recon_id: int,
    matches: list[MatchConfirm],
    ctx: AppContext,
    db: AsyncSession,
) -> None:
    """ยืนยันหรือปฏิเสธการจับคู่ และ post รายการใหม่ถ้าเลือก post_new."""
    for m in matches:
        line = await db.scalar(
            select(BankReconLine).where(
                BankReconLine.id == m.line_id,
                BankReconLine.recon_id == recon_id,
            )
        )
        if not line:
            continue

        if m.action == "confirm":
            line.is_confirmed = True
            line.match_status = "CONFIRMED"
            if m.note:
                line.note = m.note

        elif m.action == "reject":
            line.match_status = "STATEMENT_ONLY"
            line.journal_line_id = None
            line.journal_entry_no = None
            line.is_confirmed = False

        elif m.action == "post_new":
            account_code = m.account_code or classify_bank_transaction(line.stmt_description or "") or "7102"
            await _post_bank_transaction(line, account_code, ctx, db)


async def _post_bank_transaction(
    line: BankReconLine,
    account_code: str,
    ctx: AppContext,
    db: AsyncSession,
) -> None:
    """บันทึก journal entry สำหรับรายการที่ไม่มีในสมุดบัญชี."""
    recon = await db.scalar(
        select(BankReconciliation).where(BankReconciliation.id == line.recon_id)
    )
    bank_code = recon.bank_account_code if recon else "1102"

    if line.stmt_credit > 0:
        # เงินเข้า: Dr ธนาคาร | Cr รายได้/ดอกเบี้ย
        lines = [
            JournalLineInput(account_code=bank_code, side=DrCr.DR, amount=line.stmt_credit),
            JournalLineInput(account_code=account_code, side=DrCr.CR, amount=line.stmt_credit),
        ]
    else:
        # เงินออก: Dr ค่าธรรมเนียม | Cr ธนาคาร
        lines = [
            JournalLineInput(account_code=account_code, side=DrCr.DR, amount=line.stmt_debit),
            JournalLineInput(account_code=bank_code, side=DrCr.CR, amount=line.stmt_debit),
        ]

    entry = JournalEntryInput(
        journal_type=JournalType.GJ,
        entry_date=line.stmt_date or ctx.period,
        description=f"Bank recon: {line.stmt_description or ''}",
        lines=lines,
        source_module="bank",
        source_id=line.recon_id,
    )
    journal_no = await PostingEngine(db).post(entry, ctx)
    line.posted_journal_no = journal_no
    line.is_confirmed = True
    line.match_status = "CONFIRMED"


async def auto_post_new_items(recon_id: int, ctx: AppContext, db: AsyncSession) -> int:
    """Auto-post รายการ STATEMENT_ONLY ที่ระบุ account_code ได้จาก keyword rules."""
    lines = list(await db.scalars(
        select(BankReconLine).where(
            BankReconLine.recon_id == recon_id,
            BankReconLine.match_status == "STATEMENT_ONLY",
        )
    ))
    posted = 0
    for line in lines:
        code = classify_bank_transaction(line.stmt_description or "")
        if code:
            await _post_bank_transaction(line, code, ctx, db)
            posted += 1
    return posted


async def complete_reconciliation(
    recon_id: int,
    ctx: AppContext,
    db: AsyncSession,
) -> BankReconReport:
    """ปิด reconciliation และสร้าง report."""
    recon = await db.scalar(
        select(BankReconciliation).where(
            BankReconciliation.id == recon_id,
            BankReconciliation.company_id == ctx.company_id,
        )
    )
    if not recon:
        raise ValueError(f"ไม่พบ reconciliation id={recon_id}")

    all_lines = list(await db.scalars(
        select(BankReconLine).where(BankReconLine.recon_id == recon_id)
    ))

    matched_count = sum(1 for ln in all_lines if ln.match_status == "CONFIRMED")
    stmt_only = [ln for ln in all_lines if ln.match_status == "STATEMENT_ONLY"]
    book_only = [ln for ln in all_lines if ln.match_status == "BOOK_ONLY"]

    unreconciled_stmt = sum(
        (ln.stmt_credit - ln.stmt_debit) for ln in stmt_only
    )
    unreconciled_book = sum(
        (ln.journal_debit - ln.journal_credit) for ln in book_only
    )

    adjusted = recon.closing_balance - unreconciled_stmt
    recon.adjusted_balance = adjusted
    recon.status = "completed"

    return BankReconReport(
        recon_id=recon_id,
        bank_account_code=recon.bank_account_code,
        bank_name=recon.bank_name,
        account_no=recon.account_no,
        period_from=recon.period_from,
        period_to=recon.period_to,
        opening_balance=recon.opening_balance,
        closing_balance=recon.closing_balance,
        book_balance=recon.book_balance,
        adjusted_balance=adjusted,
        status="completed",
        total_matched=matched_count,
        total_statement_only=len(stmt_only),
        total_book_only=len(book_only),
        unreconciled_statement=unreconciled_stmt,
        unreconciled_book=unreconciled_book,
        lines=[ReconLineOut.model_validate(ln) for ln in all_lines],
    )
