"""Bank Statement OCR and Reconciliation API Routes."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query, UploadFile, File

from app.api.deps import CTX, CompanyDB
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
