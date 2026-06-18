"""FA API Routes."""

from __future__ import annotations

from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import get_app_context, CTX, CompanyDB
from app.context import AppContext
from app.modules.fa.schemas import (
    AssetCreate,
    AssetOut,
    AssetUpdate,
    DeprScheduleItem,
    DepreciationRecordOut,
    DisposeAssetIn,
    PostDepreciationIn,
)
from app.modules.fa.asset_service import AssetService
from app.modules.fa.depreciation_service import DepreciationService
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/fa", tags=["Fixed Assets"])

Ctx = Annotated[AppContext, Depends(get_app_context)]
DB = CompanyDB


# โ”€โ”€ Assets โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€

@router.get("/assets", response_model=list[AssetOut])
async def list_assets(
    ctx: Ctx, db: DB,
    status: Optional[str] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, le=500),
):
    return await AssetService.list_assets(ctx, db, status=status, skip=skip, limit=limit)


@router.post("/assets", response_model=AssetOut, status_code=201)
async def create_asset(data: AssetCreate, ctx: Ctx, db: DB):
    try:
        return await AssetService.create_asset(data, ctx, db)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/assets/{asset_id}", response_model=AssetOut)
async def get_asset(asset_id: int, ctx: Ctx, db: DB):
    try:
        return await AssetService.get_asset(asset_id, ctx, db)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.put("/assets/{asset_id}", response_model=AssetOut)
async def update_asset(asset_id: int, data: AssetUpdate, ctx: Ctx, db: DB):
    try:
        return await AssetService.update_asset(asset_id, data, ctx, db)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/assets/{asset_id}/dispose", response_model=AssetOut)
async def dispose_asset(asset_id: int, data: DisposeAssetIn, ctx: Ctx, db: DB):
    try:
        return await AssetService.dispose_asset(asset_id, data, ctx, db)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# โ”€โ”€ Depreciation โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€

@router.get("/depreciation/schedule", response_model=list[DeprScheduleItem])
async def get_depr_schedule(
    ctx: Ctx, db: DB,
    fiscal_year: int = Query(...),
    month: int = Query(..., ge=1, le=12),
):
    return await DepreciationService.get_schedule(ctx, db, fiscal_year=fiscal_year, month=month)


@router.post("/depreciation/post", response_model=list[DepreciationRecordOut], status_code=201)
async def post_depreciation(data: PostDepreciationIn, ctx: Ctx, db: DB):
    try:
        return await DepreciationService.post_depreciation(data, ctx, db)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/depreciation/records", response_model=list[DepreciationRecordOut])
async def list_depr_records(
    ctx: Ctx, db: DB,
    asset_id: Optional[int] = None,
    fiscal_year: Optional[int] = None,
):
    return await DepreciationService.list_records(ctx, db, asset_id=asset_id, fiscal_year=fiscal_year)

