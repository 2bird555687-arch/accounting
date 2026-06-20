"""FA Module Models — FixedAsset, AssetDepreciation."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    Boolean, Date, DateTime, ForeignKey, Integer,
    Numeric, String, Text, UniqueConstraint, func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import CompanyBase as Base


# ── บัญชีที่ใช้ตามประเภทสินทรัพย์ ─────────────────────────────────────────────
# (asset_account, acc_depr_account, depreciable)
# รหัสตรงกับ COA template จริง (app/platform/coa_template.py)
ASSET_CATEGORY_ACCOUNTS: dict[str, tuple[str, Optional[str], bool]] = {
    "land":       ("1220", None,   False),   # ที่ดิน — ไม่คิดค่าเสื่อม
    "building":   ("1230", "1231", True),    # อาคาร + ค่าเสื่อมราคาสะสม-อาคาร
    "equipment":  ("1240", "1241", True),    # เครื่องจักรและอุปกรณ์
    "vehicle":    ("1260", "1261", True),    # ยานพาหนะ
    "furniture":  ("1250", "1251", True),    # เครื่องใช้สำนักงาน
    "it":         ("1250", "1251", True),    # คอมพิวเตอร์/IT → เครื่องใช้สำนักงาน
    "other":      ("1240", "1241", True),
}

DEPR_EXPENSE_ACCOUNT = "6504"   # ค่าเสื่อมราคา (6505 = ค่าซ่อมแซม)


# ── Fixed Asset ───────────────────────────────────────────────────────────────

class FixedAsset(Base):
    """
    สินทรัพย์ถาวร (Fixed Asset).

    depr_method: "straight_line" | "declining_balance"
    status:      "active" | "fully_depreciated" | "disposed"
    """

    __tablename__ = "fa_assets"
    __table_args__ = (UniqueConstraint("company_id", "asset_code", name="uq_fa_asset_code"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    company_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    branch_id: Mapped[int] = mapped_column(Integer, nullable=False)

    asset_code: Mapped[str] = mapped_column(String(20), nullable=False)
    asset_name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    serial_no: Mapped[Optional[str]] = mapped_column(String(100))
    location: Mapped[Optional[str]] = mapped_column(String(200))

    # ประเภทสินทรัพย์ → กำหนดบัญชี
    category: Mapped[str] = mapped_column(String(20), nullable=False, default="equipment")
    # land/building/equipment/vehicle/furniture/it/other

    # บัญชีที่ใช้ (คำนวณอัตโนมัติจาก category หรือ override ได้)
    asset_account: Mapped[str] = mapped_column(String(10), nullable=False)
    acc_depr_account: Mapped[Optional[str]] = mapped_column(String(10))  # None สำหรับที่ดิน
    depr_expense_account: Mapped[str] = mapped_column(String(10), nullable=False, default=DEPR_EXPENSE_ACCOUNT)

    # ราคาและค่าเสื่อม
    purchase_date: Mapped[date] = mapped_column(Date, nullable=False)
    cost: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)         # ราคาทุน
    salvage_value: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=Decimal(0))
    useful_life_months: Mapped[int] = mapped_column(Integer, nullable=False)       # อายุการใช้งาน (เดือน)

    depr_method: Mapped[str] = mapped_column(String(20), nullable=False, default="straight_line")
    # "straight_line" | "declining_balance"
    declining_rate: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 4))
    # สำหรับ declining_balance เช่น 0.4 = 40%/ปี (ถ้า None ใช้ 2x straight-line)

    # ยอดสะสม (denormalized — อัปเดตทุกครั้งที่ post depr)
    accumulated_depr: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=Decimal(0))
    book_value: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=Decimal(0))
    months_depreciated: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    # "active" | "fully_depreciated" | "disposed"

    # Journal references
    purchase_journal_no: Mapped[Optional[str]] = mapped_column(String(20))   # GJ/CP ตอนซื้อ
    disposal_journal_no: Mapped[Optional[str]] = mapped_column(String(20))   # GJ ตอนขาย/ตัดจำหน่าย
    disposed_at: Mapped[Optional[date]] = mapped_column(Date)
    disposal_proceeds: Mapped[Optional[Decimal]] = mapped_column(Numeric(15, 2))

    created_by: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    depreciation_records: Mapped[list[AssetDepreciation]] = relationship(
        "AssetDepreciation", back_populates="asset", order_by="AssetDepreciation.fiscal_year, AssetDepreciation.month"
    )

    @property
    def depreciable(self) -> bool:
        return self.acc_depr_account is not None

    @property
    def depreciable_amount(self) -> Decimal:
        return self.cost - self.salvage_value

    def monthly_depr_straight_line(self) -> Decimal:
        from decimal import ROUND_HALF_UP
        return (self.depreciable_amount / self.useful_life_months).quantize(
            Decimal("0.01"), ROUND_HALF_UP
        )

    def monthly_depr_declining(self) -> Decimal:
        """ค่าเสื่อมสำหรับเดือนถัดไปโดยวิธี declining balance."""
        from decimal import ROUND_HALF_UP
        rate = self.declining_rate or (Decimal(2) / self.useful_life_months * Decimal(12) / 12)
        return (self.book_value * rate).quantize(Decimal("0.01"), ROUND_HALF_UP)


# ── Asset Depreciation Record ─────────────────────────────────────────────────

class AssetDepreciation(Base):
    """บันทึกค่าเสื่อมราคารายเดือน (posted)."""

    __tablename__ = "fa_depreciation_records"
    __table_args__ = (
        UniqueConstraint("asset_id", "fiscal_year", "month", name="uq_fa_depr_period"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    asset_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("fa_assets.id"), nullable=False, index=True
    )
    fiscal_year: Mapped[int] = mapped_column(Integer, nullable=False)
    month: Mapped[int] = mapped_column(Integer, nullable=False)    # 1-12

    depr_amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    accumulated_depr_after: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    book_value_after: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)

    journal_entry_no: Mapped[Optional[str]] = mapped_column(String(20))
    posted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    asset: Mapped[FixedAsset] = relationship("FixedAsset", back_populates="depreciation_records")
