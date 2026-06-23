"""Currency / Exchange Rate API endpoints."""
from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from app.api.deps import CTX, CompanyDB
from app.api.responses import ok
from app.modules.currency.service import (
    ExchangeRateIn,
    ExchangeRateOut,
    upsert_rate,
    get_rate,
    list_rates,
    convert,
)

router = APIRouter(prefix="/currency", tags=["Currency"])


@router.get("/rates", response_model=list[ExchangeRateOut])
async def get_rates(
    ctx: CTX,
    db: CompanyDB,
    currency_code: Optional[str] = Query(None),
    limit: int = Query(90, le=365),
):
    rows = await list_rates(ctx, db, currency_code, limit)
    return rows


@router.post("/rates", status_code=201, response_model=ExchangeRateOut)
async def create_rate(data: ExchangeRateIn, ctx: CTX, db: CompanyDB):
    er = await upsert_rate(ctx, db, data)
    await db.commit()
    await db.refresh(er)
    return er


@router.get("/rate/{currency_code}")
async def get_single_rate(
    currency_code: str,
    ctx: CTX,
    db: CompanyDB,
    as_of: Optional[date] = Query(None),
):
    as_of_date = as_of or date.today()
    try:
        rate = await get_rate(ctx, db, currency_code, as_of_date)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {
        "currency_code": currency_code.upper(),
        "rate": float(rate),
        "as_of_date": str(as_of_date),
    }


@router.get("/convert")
async def convert_currency(
    ctx: CTX,
    db: CompanyDB,
    amount: float = Query(...),
    from_currency: str = Query(...),
    to_currency: str = Query(...),
    as_of: Optional[date] = Query(None),
):
    as_of_date = as_of or date.today()
    try:
        result = await convert(ctx, db, amount, from_currency, to_currency, as_of_date)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return result
