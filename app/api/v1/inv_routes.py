"""INV API Routes."""

from __future__ import annotations

from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import get_app_context, get_company_db
from app.core.context import AppContext
from app.modules.inv.schemas import (
    AdjustStockIn,
    IssueStockIn,
    ProductCreate,
    ProductLotOut,
    ProductOut,
    ProductUpdate,
    ReceiveStockIn,
    StockBalance,
    StockMovementOut,
)
from app.modules.inv.product_service import ProductService
from app.modules.inv.inventory_service import InventoryService
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/inv", tags=["Inventory"])

Ctx = Annotated[AppContext, Depends(get_app_context)]
DB = Annotated[AsyncSession, Depends(get_company_db)]


# ── Products ──────────────────────────────────────────────────────────────────

@router.get("/products", response_model=list[ProductOut])
async def list_products(
    ctx: Ctx, db: DB,
    active_only: bool = Query(True),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, le=500),
):
    return await ProductService.list_products(ctx, db, active_only=active_only, skip=skip, limit=limit)


@router.post("/products", response_model=ProductOut, status_code=201)
async def create_product(data: ProductCreate, ctx: Ctx, db: DB):
    try:
        return await ProductService.create_product(data, ctx, db)
    except (ValueError, PermissionError) as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/products/{product_id}", response_model=ProductOut)
async def get_product(product_id: int, ctx: Ctx, db: DB):
    try:
        return await ProductService.get_product(product_id, ctx, db)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.put("/products/{product_id}", response_model=ProductOut)
async def update_product(product_id: int, data: ProductUpdate, ctx: Ctx, db: DB):
    try:
        return await ProductService.update_product(product_id, data, ctx, db)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/products/{product_id}", status_code=204)
async def deactivate_product(product_id: int, ctx: Ctx, db: DB):
    try:
        await ProductService.deactivate_product(product_id, ctx, db)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ── Stock Balance ─────────────────────────────────────────────────────────────

@router.get("/stock/balance", response_model=list[StockBalance])
async def get_stock_balance(ctx: Ctx, db: DB, product_id: Optional[int] = None):
    return await InventoryService.get_stock_balance(ctx, db, product_id=product_id)


@router.get("/stock/lots/{product_id}", response_model=list[ProductLotOut])
async def get_lots(product_id: int, ctx: Ctx, db: DB):
    return await InventoryService.get_lots(product_id, ctx, db)


# ── Stock Movements ───────────────────────────────────────────────────────────

@router.get("/movements", response_model=list[StockMovementOut])
async def list_movements(
    ctx: Ctx, db: DB,
    product_id: Optional[int] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, le=500),
):
    return await InventoryService.list_movements(ctx, db, product_id=product_id, skip=skip, limit=limit)


@router.post("/movements/receive", response_model=StockMovementOut, status_code=201)
async def receive_stock(data: ReceiveStockIn, ctx: Ctx, db: DB):
    try:
        return await InventoryService.receive(data, ctx, db)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/movements/issue", response_model=list[StockMovementOut], status_code=201)
async def issue_stock(data: IssueStockIn, ctx: Ctx, db: DB):
    try:
        return await InventoryService.issue(data, ctx, db)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/movements/adjust", response_model=StockMovementOut, status_code=201)
async def adjust_stock(data: AdjustStockIn, ctx: Ctx, db: DB):
    try:
        return await InventoryService.adjust(data, ctx, db)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
