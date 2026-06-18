"""Ledger routes — บัญชีแยกประเภท, ยอดคงเหลือ, trial balance."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.api.deps import CTX, CompanyDB
from app.api.responses import ok
from app.core.ledger import AccountStatement, LedgerLine, LedgerService

router = APIRouter(prefix="/ledger", tags=["Ledger"])


# ── Response schemas ──────────────────────────────────────────────────────────

class LedgerLineOut(BaseModel):
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


class AccountStatementOut(BaseModel):
    account_code: str
    account_name: str
    date_from: date
    date_to: date
    opening_balance: Decimal
    lines: list[LedgerLineOut]
    total_debit: Decimal
    total_credit: Decimal
    closing_balance: Decimal


class BalanceItem(BaseModel):
    account_code: str
    account_name: str
    category: str
    account_type: str
    normal_balance: str
    debit_balance: Decimal
    credit_balance: Decimal
    net_balance: Decimal


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/{account_code}", response_model=dict, summary="รายการเดินบัญชี")
async def get_account_statement(
    account_code: str,
    ctx: CTX,
    company_db: CompanyDB,
    date_from: Optional[date] = Query(None, description="วันเริ่มต้น (ค่าเริ่มต้น: ต้นงวด)"),
    date_to: Optional[date] = Query(None, description="วันสิ้นสุด (ค่าเริ่มต้น: วันนี้)"),
    branch_id: Optional[int] = Query(None, description="None = รวมทุกสาขา"),
) -> dict:
    """
    รายการเดินบัญชี (Account Statement) พร้อม opening/closing balance

    - ถ้าไม่ระบุ `date_from` ใช้วันที่ 1 ของ period ปัจจุบัน
    - ถ้าไม่ระบุ `date_to` ใช้วันนี้
    """
    effective_from = date_from or ctx.period
    effective_to = date_to or date.today()

    if effective_from > effective_to:
        raise HTTPException(400, "date_from ต้องไม่มากกว่า date_to")

    svc = LedgerService(company_db)
    try:
        stmt = await svc.get_account_statement(
            account_code, ctx,
            date_from=effective_from,
            date_to=effective_to,
            branch_id=branch_id,
        )
    except ValueError as e:
        raise HTTPException(404, str(e))

    out = AccountStatementOut(
        account_code=stmt.account_code,
        account_name=stmt.account_name,
        date_from=stmt.date_from,
        date_to=stmt.date_to,
        opening_balance=stmt.opening_balance,
        lines=[LedgerLineOut(**ln.__dict__) for ln in stmt.lines],
        total_debit=stmt.total_debit,
        total_credit=stmt.total_credit,
        closing_balance=stmt.closing_balance,
    )
    return ok(out)


@router.get("/balances/current", response_model=dict, summary="ยอดคงเหลือทุกบัญชี ณ วันที่")
async def get_all_balances(
    ctx: CTX,
    company_db: CompanyDB,
    fiscal_year: Optional[int] = Query(None, description="ค่าเริ่มต้น: ปีงบปัจจุบัน"),
    month: Optional[int] = Query(None, ge=1, le=12, description="ค่าเริ่มต้น: เดือนปัจจุบัน"),
    branch_id: Optional[int] = Query(None, description="None = รวมทุกสาขา"),
    category: Optional[str] = Query(None, description="กรองตามหมวด 1-8"),
    nonzero_only: bool = Query(False, description="แสดงเฉพาะยอดที่ไม่เป็น 0"),
) -> dict:
    """
    ยอดคงเหลือของทุกบัญชี (สำหรับ Trial Balance)

    คืน list พร้อม debit_balance, credit_balance, net_balance
    """
    fy = fiscal_year or ctx.fiscal_year
    m = month or ctx.fiscal_month

    svc = LedgerService(company_db)
    balances = await svc.get_all_balances(ctx, fiscal_year=fy, month=m, branch_id=branch_id)

    if not balances:
        return ok([], "ไม่มีข้อมูลยอดคงเหลือ")

    # โหลด COA info
    from sqlalchemy import select
    from app.core.models import ChartOfAccount

    codes = list(balances.keys())
    coa_result = await company_db.execute(
        select(ChartOfAccount).where(
            ChartOfAccount.code.in_(codes),
            ChartOfAccount.is_active == True,  # noqa: E712
        )
    )
    coa_map = {a.code: a for a in coa_result.scalars().all()}

    items: list[BalanceItem] = []
    for code, net_bal in balances.items():
        acc = coa_map.get(code)
        if acc is None:
            continue
        if category and acc.category != category:
            continue
        if nonzero_only and net_bal == 0:
            continue

        # แยก debit / credit ตาม normal_balance
        if acc.normal_balance == "DR":
            dr_bal = max(net_bal, Decimal(0))
            cr_bal = max(-net_bal, Decimal(0))
        else:
            cr_bal = max(net_bal, Decimal(0))
            dr_bal = max(-net_bal, Decimal(0))

        items.append(BalanceItem(
            account_code=code,
            account_name=acc.name,
            category=acc.category,
            account_type=acc.account_type,
            normal_balance=acc.normal_balance,
            debit_balance=dr_bal,
            credit_balance=cr_bal,
            net_balance=net_bal,
        ))

    items.sort(key=lambda x: x.account_code)

    # summary
    total_dr = sum(i.debit_balance for i in items)
    total_cr = sum(i.credit_balance for i in items)

    return ok({
        "fiscal_year": fy,
        "month": m,
        "items": items,
        "summary": {
            "total_debit": total_dr,
            "total_credit": total_cr,
            "balanced": total_dr == total_cr,
        },
    })


@router.get("/balance/{account_code}", response_model=dict, summary="ยอดคงเหลือบัญชีเดียว")
async def get_single_balance(
    account_code: str,
    ctx: CTX,
    company_db: CompanyDB,
    as_of_date: Optional[date] = Query(None, description="ยอด ณ วันที่นี้"),
    branch_id: Optional[int] = Query(None),
) -> dict:
    """ยอดคงเหลือของบัญชีเดียว ณ วันที่ที่ระบุ."""
    svc = LedgerService(company_db)
    try:
        balance = await svc.get_balance(
            account_code, ctx,
            as_of_date=as_of_date,
            branch_id=branch_id,
        )
    except ValueError as e:
        raise HTTPException(404, str(e))

    return ok({
        "account_code": account_code,
        "as_of_date": (as_of_date or date.today()).isoformat(),
        "balance": balance,
    })
