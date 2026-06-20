"""Bank Statement OCR and Reconciliation API Routes."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, UploadFile, File
from pydantic import BaseModel, Field

from app.api.deps import CTX, CompanyDB
from app.api.responses import ok
from app.modules.bank import service as bank_service
from app.modules.bank.reconcile_service import (
    auto_match,
    auto_post_new_items,
    complete_reconciliation,
    confirm_match,
    start_reconciliation,
)
from app.modules.bank.schemas import (
    BankReconOut,
    BankReconReport,
    ConfirmRequest,
    ReconResult,
    StatementUploadResponse,
    BankStatementOut,
    BankTransactionOut,
)
from app.ocr.bank_reader import extract_statement
from app.ocr.reader import read_file

router = APIRouter(prefix="/bank", tags=["Bank"])


# ══════════════════════════════════════════════════════════════════════════════
# BANK ACCOUNTS & TRANSFERS
# ══════════════════════════════════════════════════════════════════════════════

class BankAccountCreate(BaseModel):
    bank_name: str = Field(..., max_length=100)
    account_number: Optional[str] = Field(None, max_length=30)
    account_name: Optional[str] = Field(None, max_length=200)
    account_type: str = "current"   # current | savings | cash
    coa_account_code: str = Field(..., max_length=10)


class BankTransferCreate(BaseModel):
    from_bank_account_id: int
    to_bank_account_id: int
    amount: Decimal
    transfer_date: date
    note: Optional[str] = None


def _account_dict(acc, balance=None) -> dict:
    d = {
        "id": acc.id,
        "bank_name": acc.bank_name,
        "account_number": acc.account_number,
        "account_name": acc.account_name,
        "account_type": acc.account_type,
        "coa_account_code": acc.coa_account_code,
        "is_active": acc.is_active,
    }
    if balance is not None:
        d["balance"] = float(balance)
    return d


@router.get("/accounts", summary="รายการบัญชีธนาคารพร้อมยอดคงเหลือ")
async def list_bank_accounts(ctx: CTX, db: CompanyDB) -> dict:
    accounts = await bank_service.get_bank_accounts(db, ctx.company_id)
    out = []
    for acc in accounts:
        bal = await bank_service.get_balance_by_code(db, acc.coa_account_code)
        out.append(_account_dict(acc, bal))
    return ok(out)


@router.post("/accounts", status_code=201, summary="สร้างบัญชีธนาคาร")
async def create_bank_account(data: BankAccountCreate, ctx: CTX, db: CompanyDB) -> dict:
    acc = await bank_service.create_bank_account(
        db,
        ctx.company_id,
        bank_name=data.bank_name,
        coa_account_code=data.coa_account_code,
        account_number=data.account_number,
        account_name=data.account_name,
        account_type=data.account_type,
    )
    await db.commit()
    return ok(_account_dict(acc), "สร้างบัญชีธนาคารสำเร็จ")


@router.get("/accounts/{account_id}", summary="รายละเอียดบัญชีธนาคาร")
async def get_bank_account(account_id: int, ctx: CTX, db: CompanyDB) -> dict:
    acc = await bank_service.get_bank_account(db, ctx.company_id, account_id)
    bal = await bank_service.get_balance_by_code(db, acc.coa_account_code)
    return ok(_account_dict(acc, bal))


@router.post("/transfers", status_code=201, summary="โอนเงินระหว่างบัญชี")
async def create_bank_transfer(data: BankTransferCreate, ctx: CTX, db: CompanyDB) -> dict:
    transfer = await bank_service.create_bank_transfer(
        db,
        ctx,
        from_id=data.from_bank_account_id,
        to_id=data.to_bank_account_id,
        amount=data.amount,
        transfer_date=data.transfer_date,
        note=data.note,
    )
    await db.commit()
    return ok(
        {
            "id": transfer.id,
            "journal_ref": transfer.journal_ref,
            "amount": float(transfer.amount),
        },
        "โอนเงินสำเร็จ",
    )


@router.get("/transfers", summary="ประวัติการโอนเงิน")
async def list_bank_transfers(ctx: CTX, db: CompanyDB) -> dict:
    transfers = await bank_service.get_bank_transfers(db, ctx.company_id)
    accounts = {a.id: a for a in await bank_service.get_bank_accounts(db, ctx.company_id, active_only=False)}
    out = []
    for t in transfers:
        fa = accounts.get(t.from_bank_account_id)
        ta = accounts.get(t.to_bank_account_id)
        out.append({
            "id": t.id,
            "transfer_date": t.transfer_date.isoformat(),
            "amount": float(t.amount),
            "from_name": fa.bank_name if fa else "-",
            "from_coa": fa.coa_account_code if fa else "-",
            "to_name": ta.bank_name if ta else "-",
            "to_coa": ta.coa_account_code if ta else "-",
            "journal_ref": t.journal_ref,
            "note": t.note,
        })
    return ok(out)


@router.post("/statement/upload", response_model=StatementUploadResponse, status_code=201)
async def upload_bank_statement(
    ctx: CTX,
    db: CompanyDB,
    file: UploadFile = File(...),
    bank_account_code: str = Query(..., description="รหัสบัญชีธนาคารใน COA เช่น 1102"),
    bank_name: Optional[str] = Query(None, description="กรุงไทย|กสิกร|SCB|กรุงเทพ|TTB"),
):
    """อัปโหลด bank statement → OCR → เริ่ม reconciliation."""
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="ไฟล์ว่างเปล่า")

    try:
        images = read_file(raw)
    except (ImportError, ValueError) as e:
        raise HTTPException(status_code=422, detail=str(e))

    try:
        statement = extract_statement(images, bank_name=bank_name, ctx=ctx)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"OCR failed: {e}")

    if not ctx.can_post:
        raise HTTPException(status_code=403, detail="ไม่มีสิทธิ์")

    recon_id = await start_reconciliation(bank_account_code, statement, ctx, db)

    # auto-match immediately
    await auto_match(recon_id, ctx, db)

    stmt_out = BankStatementOut(
        account_no=statement.account_no,
        account_name=statement.account_name,
        bank_name=statement.bank_name,
        period_from=statement.period_from,
        period_to=statement.period_to,
        opening_balance=statement.opening_balance,
        closing_balance=statement.closing_balance,
        total_debit=statement.total_debit,
        total_credit=statement.total_credit,
        transactions=[
            BankTransactionOut(
                date=t.date,
                description=t.description,
                debit=t.debit,
                credit=t.credit,
                balance=t.balance,
                ref_no=t.ref_no,
            )
            for t in statement.transactions
        ],
        confidence=statement.confidence,
        validation_ok=statement.validation_ok,
        validation_diff=statement.validation_diff,
    )

    return StatementUploadResponse(
        recon_id=recon_id,
        statement=stmt_out,
        message=f"อ่าน statement สำเร็จ {len(statement.transactions)} รายการ",
    )


@router.get("/reconciliation/{recon_id}", response_model=ReconResult)
async def get_reconciliation(recon_id: int, ctx: CTX, db: CompanyDB):
    """ดูผลการ auto-match."""
    try:
        return await auto_match(recon_id, ctx, db)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/reconciliation/{recon_id}/confirm")
async def confirm_reconciliation(
    recon_id: int,
    data: ConfirmRequest,
    ctx: CTX,
    db: CompanyDB,
):
    """ยืนยัน/ปฏิเสธ/post รายการที่จับคู่."""
    if not ctx.can_post:
        raise HTTPException(status_code=403, detail="ไม่มีสิทธิ์")
    try:
        await confirm_match(recon_id, data.matches, ctx, db)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"message": f"ยืนยัน {len(data.matches)} รายการสำเร็จ"}


@router.post("/reconciliation/{recon_id}/auto-post")
async def auto_post(recon_id: int, ctx: CTX, db: CompanyDB):
    """Auto-post รายการ STATEMENT_ONLY ที่ระบุ account_code ได้จาก keyword rules."""
    if not ctx.can_post:
        raise HTTPException(status_code=403, detail="ไม่มีสิทธิ์")
    try:
        count = await auto_post_new_items(recon_id, ctx, db)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"posted": count, "message": f"บันทึกอัตโนมัติ {count} รายการ"}


@router.get("/reconciliation/{recon_id}/report", response_model=BankReconReport)
async def get_report(recon_id: int, ctx: CTX, db: CompanyDB):
    """ปิดและดู reconciliation report."""
    try:
        return await complete_reconciliation(recon_id, ctx, db)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
