"""Petty Cash API Routes."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from app.api.deps import CTX, CompanyDB
from app.master.schemas import (
    PettyCashExpenseOut,
    PettyCashFundOut,
    RecordExpenseIn,
    ReplenishResult,
    SetupFundIn,
)
from app.modules.petty.petty_cash_service import PettyCashService

router = APIRouter(prefix="/petty-cash", tags=["Petty Cash"])


@router.get("/funds", response_model=list[PettyCashFundOut])
async def list_funds(ctx: CTX, db: CompanyDB):
    return await PettyCashService.list_funds(ctx, db)


@router.post("/funds", response_model=PettyCashFundOut, status_code=201)
async def setup_fund(data: SetupFundIn, ctx: CTX, db: CompanyDB):
    try:
        return await PettyCashService.setup_fund(data, ctx, db)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/funds/{fund_id}", response_model=PettyCashFundOut)
async def get_fund(fund_id: int, ctx: CTX, db: CompanyDB):
    try:
        return await PettyCashService.get_fund(fund_id, ctx, db)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/funds/{fund_id}/expenses", response_model=list[PettyCashExpenseOut])
async def list_expenses(
    fund_id: int, ctx: CTX, db: CompanyDB,
    replenished: Optional[bool] = None,
):
    return await PettyCashService.list_expenses(fund_id, ctx, db, replenished=replenished)


@router.post("/expenses", response_model=PettyCashExpenseOut, status_code=201)
async def record_expense(data: RecordExpenseIn, ctx: CTX, db: CompanyDB):
    try:
        return await PettyCashService.record_expense(data, ctx, db)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/funds/{fund_id}/replenish", response_model=ReplenishResult)
async def replenish(fund_id: int, ctx: CTX, db: CompanyDB):
    try:
        return await PettyCashService.replenish(fund_id, ctx, db)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
