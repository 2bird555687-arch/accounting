"""INV Module Models — Product, ProductLot, StockMovement."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    Boolean, Date, DateTime, ForeignKey, Integer,
    Numeric, String, Text, UniqueConstraint, func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base สำหรับ INV module models (company database)."""
    pass


# ── Product ───────────────────────────────────────────────────────────────────

class Product(Base):
    """
    สินค้า / วัตถุดิบ (Product Master).

    cost_method: "fifo" → ราคาทุน FIFO ตาม lot
                 "average" → ราคาทุนถัวเฉลี่ยถ่วงน้ำหนัก
    """

    __tablename__ = "inv_products"
    __table_args__ = (UniqueConstraint("company_id", "sku", name="uq_inv_product_sku"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    company_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)

    sku: Mapped[str] = mapped_column(String(50), nullable=False)       # รหัสสินค้า
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    name_en: Mapped[Optional[str]] = mapped_column(String(200))
    description: Mapped[Optional[str]] = mapped_column(Text)
    category: Mapped[Optional[str]] = mapped_column(String(100))
    unit: Mapped[str] = mapped_column(String(20), nullable=False, default="ชิ้น")

    cost_method: Mapped[str] = mapped_column(String(10), nullable=False, default="average")
    # "fifo" | "average"

    # บัญชีที่ใช้
    inventory_account: Mapped[str] = mapped_column(String(10), nullable=False, default="1130")
    cogs_account: Mapped[str] = mapped_column(String(10), nullable=False, default="5101")

    # ราคาทุนปัจจุบัน (average cost หรือ standard)
    current_cost: Mapped[Decimal] = mapped_column(Numeric(15, 4), nullable=False, default=Decimal(0))
    standard_cost: Mapped[Decimal] = mapped_column(Numeric(15, 4), nullable=False, default=Decimal(0))

    # ยอดสต็อกปัจจุบัน (denormalized — อัปเดตทุกครั้งที่มี movement)
    quantity_on_hand: Mapped[Decimal] = mapped_column(Numeric(15, 4), nullable=False, default=Decimal(0))
    total_value: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=Decimal(0))

    # จุดสั่งซื้อ / สต็อกขั้นต่ำ
    reorder_point: Mapped[Decimal] = mapped_column(Numeric(15, 4), nullable=False, default=Decimal(0))
    min_stock: Mapped[Decimal] = mapped_column(Numeric(15, 4), nullable=False, default=Decimal(0))

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    lots: Mapped[list[ProductLot]] = relationship(
        "ProductLot", back_populates="product", order_by="ProductLot.received_date"
    )
    movements: Mapped[list[StockMovement]] = relationship(
        "StockMovement", back_populates="product", order_by="StockMovement.movement_date"
    )


# ── Product Lot (FIFO) ────────────────────────────────────────────────────────

class ProductLot(Base):
    """
    Lot สินค้าสำหรับคำนวณ FIFO.

    แต่ละครั้งที่รับสินค้า จะสร้าง lot ใหม่
    ตัดสต็อกตามลำดับ received_date (เก่าก่อน)
    """

    __tablename__ = "inv_product_lots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("inv_products.id"), nullable=False, index=True
    )
    lot_no: Mapped[str] = mapped_column(String(30), nullable=False)
    received_date: Mapped[date] = mapped_column(Date, nullable=False)

    quantity: Mapped[Decimal] = mapped_column(Numeric(15, 4), nullable=False)      # ปริมาณเข้า
    remaining_qty: Mapped[Decimal] = mapped_column(Numeric(15, 4), nullable=False)  # คงเหลือใน lot
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(15, 4), nullable=False)      # ต้นทุน/หน่วย

    source: Mapped[str] = mapped_column(String(20), nullable=False, default="purchase")
    # "purchase" | "adjustment" | "opening"
    source_ref: Mapped[Optional[str]] = mapped_column(String(50))  # purchase_no / entry_no

    product: Mapped[Product] = relationship("Product", back_populates="lots")


# ── Stock Movement ────────────────────────────────────────────────────────────

class StockMovement(Base):
    """
    รายการเคลื่อนไหวสินค้า (Stock Movement).

    movement_type:
        receive      — รับเข้าคลัง (Dr 1130)
        issue        — จ่ายออก / ขาย (Cr 1130 + Dr 5101)
        adjust_in    — ปรับเพิ่ม (Dr 1130)
        adjust_out   — ปรับลด (Cr 1130)
        transfer_in  — รับโอน
        transfer_out — จ่ายโอน
    """

    __tablename__ = "inv_stock_movements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    company_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    branch_id: Mapped[int] = mapped_column(Integer, nullable=False)
    product_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("inv_products.id"), nullable=False, index=True
    )

    movement_no: Mapped[str] = mapped_column(String(20), nullable=False)
    movement_date: Mapped[date] = mapped_column(Date, nullable=False)
    movement_type: Mapped[str] = mapped_column(String(20), nullable=False)

    quantity: Mapped[Decimal] = mapped_column(Numeric(15, 4), nullable=False)
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(15, 4), nullable=False, default=Decimal(0))
    total_cost: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=Decimal(0))

    # ยอดคงเหลือหลัง movement นี้
    qty_after: Mapped[Decimal] = mapped_column(Numeric(15, 4), nullable=False, default=Decimal(0))
    value_after: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=Decimal(0))

    lot_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("inv_product_lots.id"))
    # สำหรับ FIFO: lot ที่ตัดออก

    journal_entry_no: Mapped[Optional[str]] = mapped_column(String(20))
    reference: Mapped[Optional[str]] = mapped_column(String(100))
    reason: Mapped[Optional[str]] = mapped_column(Text)           # สำหรับ adjust

    # linked AR/AP
    source_module: Mapped[Optional[str]] = mapped_column(String(20))
    source_id: Mapped[Optional[int]] = mapped_column(Integer)

    created_by: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    product: Mapped[Product] = relationship("Product", back_populates="movements")
