"""FA Module Pydantic Schemas."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field


# ── Fixed Asset ───────────────────────────────────────────────────────────────

class AssetCreate(BaseModel):
    asset_code: str = Field(min_length=1, max_length=20)
    asset_name: str = Field(min_length=1, max_length=200)
    description: Optional[str] = None
    serial_no: Optional[str] = None
    location: Optional[str] = None
    category: str = Field("equipment", pattern="^(land|building|equipment|vehicle|furniture|it|other)$")
    # ถ้า override บัญชีจาก category default
    asset_account: Optional[str] = None
    acc_depr_account: Optional[str] = None
    depr_expense_account: Optional[str] = None

    purchase_date: date
    cost: Decimal = Field(gt=0)
    salvage_value: Decimal = Decimal(0)
    useful_life_months: int = Field(gt=0)

    depr_method: str = Field("straight_line", pattern="^(straight_line|declining_balance)$")
    declining_rate: Optional[Decimal] = None

    # แหล่งเงินทุน
    funding_type: str = Field(
        "cash_bank",
        pattern="^(cash_bank|owner_contribution|other_payable|hire_purchase)$",
    )
    bank_account_id: Optional[int] = None   # ใช้กับ cash_bank และ hire_purchase (เงินดาวน์)

    # เช่าซื้อ (hire_purchase)
    hp_total_price: Optional[Decimal] = None
    hp_down_payment: Optional[Decimal] = Decimal(0)
    hp_installments: Optional[int] = None

    # สำหรับบันทึกการซื้อ (journal)
    payment_reference: Optional[str] = None


class PayInstallmentIn(BaseModel):
    payment_date: date
    bank_account_id: int


class HirePurchaseInstallmentOut(BaseModel):
    id: int
    asset_id: int
    installment_no: int
    due_date: date
    payment_amount: Decimal
    principal_portion: Decimal
    interest_portion: Decimal
    status: str
    paid_date: Optional[date]
    journal_ref: Optional[str]

    class Config:
        from_attributes = True


class AssetUpdate(BaseModel):
    asset_name: Optional[str] = None
    description: Optional[str] = None
    serial_no: Optional[str] = None
    location: Optional[str] = None
    salvage_value: Optional[Decimal] = None
    useful_life_months: Optional[int] = None


class AssetOut(BaseModel):
    id: int
    asset_code: str
    asset_name: str
    description: Optional[str]
    serial_no: Optional[str]
    location: Optional[str]
    category: str
    asset_account: str
    acc_depr_account: Optional[str]
    depr_expense_account: str
    purchase_date: date
    cost: Decimal
    salvage_value: Decimal
    useful_life_months: int
    depr_method: str
    declining_rate: Optional[Decimal]
    accumulated_depr: Decimal
    book_value: Decimal
    months_depreciated: int
    status: str
    funding_type: str
    bank_account_id: Optional[int]
    hp_total_price: Optional[Decimal]
    hp_down_payment: Optional[Decimal]
    hp_installments: Optional[int]
    hp_monthly_payment: Optional[Decimal]
    hp_interest_total: Optional[Decimal]
    purchase_journal_no: Optional[str]
    disposal_journal_no: Optional[str]
    disposed_at: Optional[date]
    disposal_proceeds: Optional[Decimal]
    created_at: datetime

    class Config:
        from_attributes = True


class DisposeAssetIn(BaseModel):
    disposal_date: date
    proceeds: Decimal = Field(ge=0, description="เงินที่ได้รับจากการขาย (0 = ทิ้ง/ตัดจำหน่าย)")
    proceeds_account: str = "1102"   # Dr: เงินสด/ธนาคาร (ถ้ามี proceeds)
    reason: Optional[str] = None


# ── Depreciation ──────────────────────────────────────────────────────────────

class DeprScheduleItem(BaseModel):
    asset_id: int
    asset_code: str
    asset_name: str
    fiscal_year: int
    month: int
    depr_amount: Decimal
    accumulated_depr_after: Decimal
    book_value_after: Decimal
    already_posted: bool


class DepreciationRecordOut(BaseModel):
    id: int
    asset_id: int
    fiscal_year: int
    month: int
    depr_amount: Decimal
    accumulated_depr_after: Decimal
    book_value_after: Decimal
    journal_entry_no: Optional[str]
    posted_at: datetime

    class Config:
        from_attributes = True


class PostDepreciationIn(BaseModel):
    fiscal_year: int
    month: int = Field(ge=1, le=12)
    asset_ids: Optional[list[int]] = None  # None = post ทุกสินทรัพย์ที่ active
