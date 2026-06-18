"""Bank Reconciliation Pydantic schemas."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel


class BankTransactionOut(BaseModel):
    date: str
    description: str
    debit: Decimal
    credit: Decimal
    balance: Decimal
    ref_no: str | None = None


class BankStatementOut(BaseModel):
    account_no: str
    account_name: str
    bank_name: str
    period_from: str
    period_to: str
    opening_balance: Decimal
    closing_balance: Decimal
    total_debit: Decimal
    total_credit: Decimal
    transactions: list[BankTransactionOut]
    confidence: float
    validation_ok: bool
    validation_diff: Decimal


class StatementUploadResponse(BaseModel):
    recon_id: int
    statement: BankStatementOut
    message: str = "อ่าน statement สำเร็จ"


MatchStatus = Literal["MATCHED", "NEAR_MATCH", "STATEMENT_ONLY", "BOOK_ONLY", "MISMATCH", "CONFIRMED"]


class ReconLineOut(BaseModel):
    id: int
    stmt_date: date | None
    stmt_description: str | None
    stmt_debit: Decimal
    stmt_credit: Decimal
    stmt_ref_no: str | None
    journal_entry_no: str | None
    journal_date: date | None
    journal_debit: Decimal
    journal_credit: Decimal
    journal_description: str | None
    match_status: str
    match_confidence: int | None
    is_confirmed: bool
    posted_journal_no: str | None
    note: str | None

    model_config = {"from_attributes": True}


class ReconResult(BaseModel):
    recon_id: int
    total_lines: int
    matched: int
    near_match: int
    statement_only: int
    book_only: int
    mismatch: int
    lines: list[ReconLineOut]


class MatchConfirm(BaseModel):
    line_id: int
    action: Literal["confirm", "reject", "post_new"]
    account_code: str | None = None
    note: str | None = None


class ConfirmRequest(BaseModel):
    matches: list[MatchConfirm]


class BankReconReport(BaseModel):
    recon_id: int
    bank_account_code: str
    bank_name: str | None
    account_no: str | None
    period_from: date | None
    period_to: date | None
    opening_balance: Decimal
    closing_balance: Decimal
    book_balance: Decimal | None
    adjusted_balance: Decimal | None
    status: str
    total_matched: int
    total_statement_only: int
    total_book_only: int
    unreconciled_statement: Decimal
    unreconciled_book: Decimal
    lines: list[ReconLineOut]


class BankReconOut(BaseModel):
    id: int
    bank_account_code: str
    bank_name: str | None
    account_no: str | None
    period_from: date | None
    period_to: date | None
    opening_balance: Decimal
    closing_balance: Decimal
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}
