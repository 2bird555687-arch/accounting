"""TAX API Routes."""

from __future__ import annotations

from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import get_app_context, CTX, CompanyDB
from app.context import AppContext
from app.modules.tax.schemas import (
    PP30Data,
    PostWHTPaymentIn,
    VATSummaryItem,
    WHTCertificateOut,
    WHTPaymentResult,
    WHTRecordCreate,
    WHTRecordOut,
    WHTSummaryItem,
)
from app.modules.tax.vat_service import VATService
from app.modules.tax.wht_service import WHTService
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/tax", tags=["Tax"])

Ctx = Annotated[AppContext, Depends(get_app_context)]
DB = CompanyDB


# โ”€โ”€ VAT โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€

@router.get("/vat/summary", response_model=list[VATSummaryItem])
async def get_vat_summary(
    ctx: Ctx, db: DB,
    fiscal_year: int = Query(...),
    month: int = Query(..., ge=1, le=12),
):
    return await VATService.get_vat_summary(ctx, db, fiscal_year=fiscal_year, month=month)


@router.get("/vat/pp30", response_model=PP30Data)
async def generate_pp30(
    ctx: Ctx, db: DB,
    fiscal_year: int = Query(...),
    month: int = Query(..., ge=1, le=12),
):
    return await VATService.generate_pp30(ctx, db, fiscal_year=fiscal_year, month=month)


# โ”€โ”€ WHT โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€

@router.get("/wht/records", response_model=list[WHTRecordOut])
async def list_wht_records(
    ctx: Ctx, db: DB,
    direction: Optional[str] = None,
    fiscal_year: Optional[int] = None,
    month: Optional[int] = None,
    contact_id: Optional[int] = None,
):
    return await WHTService.list_wht_records(
        ctx, db, direction=direction, fiscal_year=fiscal_year, month=month, contact_id=contact_id
    )


@router.post("/wht/records", response_model=WHTRecordOut, status_code=201)
async def create_wht_record(data: WHTRecordCreate, ctx: Ctx, db: DB):
    try:
        return await WHTService.create_wht_record(data, ctx, db)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/wht/summary", response_model=list[WHTSummaryItem])
async def get_wht_summary(
    ctx: Ctx, db: DB,
    fiscal_year: int = Query(...),
    month: int = Query(..., ge=1, le=12),
    direction: str = Query("collected", pattern="^(collected|withheld)$"),
):
    return await WHTService.get_wht_summary(ctx, db, fiscal_year=fiscal_year, month=month, direction=direction)


@router.get("/wht/certificate", response_model=WHTCertificateOut)
async def generate_wht_certificate(
    ctx: Ctx, db: DB,
    contact_id: int = Query(...),
    fiscal_year: int = Query(...),
    month: int = Query(..., ge=1, le=12),
    direction: str = Query("collected"),
):
    try:
        return await WHTService.generate_certificate(ctx, db, contact_id, fiscal_year, month, direction)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/wht/payment", response_model=WHTPaymentResult, status_code=201)
async def post_wht_payment(data: PostWHTPaymentIn, ctx: Ctx, db: DB):
    try:
        return await WHTService.post_wht_payment(data, ctx, db)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


