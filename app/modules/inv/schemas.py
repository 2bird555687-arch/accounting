"""INV Module Pydantic Schemas."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field


# ── Product ───────────────────────────────────────────────────────────────────

class ProductCreate(BaseModel):
    sku: str = Field(min_length=1, max_length=50)
    name: str = Field(min_length=1, max_length=200)
    name_en: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    unit: str = "ชิ้น"
    cost_method: str = Field("average", pattern="^(fifo|average)$")
    inventory_account: str = "1130"
    cogs_account: str = "5101"
    standard_cost: Decimal = Decimal(0)
    reorder_point: Decimal = Decimal(0)
    min_stock: Decimal = Decimal(0)


class ProductUpdate(BaseModel):
    name: Optional[str] = None
    name_en: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    unit: Optional[str] = None
    inventory_account: Optional[str] = None
    cogs_account: Optional[str] = None
    standard_cost: Optional[Decimal] = None
    reorder_point: Optional[Decimal] = None
    min_stock: Optional[Decimal] = None
    is_active: Optional[bool] = None


class ProductOut(BaseModel):
    id: int
    sku: str
    name: str
    name_en: Optional[str]
    category: Optional[str]
    unit: str
    cost_method: str
    inventory_account: str
    cogs_account: str
    current_cost: Decimal
    standard_cost: Decimal
    quantity_on_hand: Decimal
    total_value: Decimal
    reorder_point: Decimal
    min_stock: Decimal
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


# ── Stock Operations ──────────────────────────────────────────────────────────

class ReceiveStockIn(BaseModel):
    product_id: int
    movement_date: date
    quantity: Decimal = Field(gt=0)
    unit_cost: Decimal = Field(ge=0)
    lot_no: Optional[str] = None          # ถ้าไม่ระบุ จะ auto-generate
    source: str = "purchase"              # "purchase" | "adjustment" | "opening"
    source_ref: Optional[str] = None
    reference: Optional[str] = None
    reason: Optional[str] = None
    # ถ้ามาจาก AP purchase แล้วต้องการ link journal
    ap_purchase_id: Optional[int] = None
    # False = ไม่ post JE (กรณี AP post Dr 1130 ให้แล้ว — แค่อัปเดต lot/cost/qty)
    post_journal: bool = True


class IssueStockIn(BaseModel):
    product_id: int
    movement_date: date
    quantity: Decimal = Field(gt=0)
    reference: Optional[str] = None
    reason: Optional[str] = None
    source_module: Optional[str] = None
    source_id: Optional[int] = None


class AdjustStockIn(BaseModel):
    product_id: int
    movement_date: date
    new_quantity: Decimal = Field(ge=0)   # ปริมาณที่ต้องการหลัง adjust
    new_unit_cost: Optional[Decimal] = None
    reason: str


class StockMovementOut(BaseModel):
    id: int
    product_id: int
    movement_no: str
    movement_date: date
    movement_type: str
    quantity: Decimal
    unit_cost: Decimal
    total_cost: Decimal
    qty_after: Decimal
    value_after: Decimal
    journal_entry_no: Optional[str]
    reference: Optional[str]
    reason: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


class StockBalance(BaseModel):
    product_id: int
    sku: str
    name: str
    unit: str
    cost_method: str
    quantity_on_hand: Decimal
    current_cost: Decimal
    total_value: Decimal
    reorder_point: Decimal
    below_reorder: bool


class ProductLotOut(BaseModel):
    id: int
    lot_no: str
    received_date: date
    quantity: Decimal
    remaining_qty: Decimal
    unit_cost: Decimal
    source: str

    class Config:
        from_attributes = True
