"""AP Module Models — PurchaseOrder, GRN, APPurchase, APPayment."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import CompanyBase as Base


# ── Purchase Order ────────────────────────────────────────────────────────────

class PurchaseOrder(Base):
    """
    ใบสั่งซื้อ (Purchase Order).

    status flow: draft → approved → goods_received → invoiced → cancelled
    """

    __tablename__ = "ap_purchase_orders"
    __table_args__ = (
        UniqueConstraint("company_id", "po_no", name="uq_ap_po_no"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    company_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    branch_id: Mapped[int] = mapped_column(Integer, nullable=False)

    po_no: Mapped[str] = mapped_column(String(20), nullable=False)
    po_date: Mapped[date] = mapped_column(Date, nullable=False)
    expected_date: Mapped[Optional[date]] = mapped_column(Date)  # วันที่คาดรับสินค้า

    contact_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("contacts.id"), nullable=False
    )

    subtotal: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=Decimal(0))
    vat_amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=Decimal(0))
    total_amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=Decimal(0))

    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    # draft / approved / goods_received / invoiced / cancelled

    purchase_type: Mapped[str] = mapped_column(String(20), nullable=False, default="goods")
    # goods → Dr 1130, service → Dr [service expense], expense → Dr [expense account]

    notes: Mapped[Optional[str]] = mapped_column(Text)
    approved_by: Mapped[Optional[int]] = mapped_column(Integer)
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    created_by: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # Relationships
    lines: Mapped[list[PurchaseOrderLine]] = relationship(
        "PurchaseOrderLine", back_populates="po",
        order_by="PurchaseOrderLine.line_no",
        cascade="all, delete-orphan",
    )
    grns: Mapped[list[GoodsReceivedNote]] = relationship("GoodsReceivedNote", back_populates="po")
    purchases: Mapped[list[APPurchase]] = relationship("APPurchase", back_populates="po")


class PurchaseOrderLine(Base):
    """บรรทัดรายการใน PO."""

    __tablename__ = "ap_po_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    po_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("ap_purchase_orders.id", ondelete="CASCADE"), nullable=False
    )
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)

    description: Mapped[str] = mapped_column(String(500), nullable=False)
    account_code: Mapped[str] = mapped_column(String(10), nullable=False)
    # 1130 สินค้า / 5102 ต้นทุนบริการ / 6xxx ค่าใช้จ่าย
    unit: Mapped[Optional[str]] = mapped_column(String(20))
    quantity: Mapped[Decimal] = mapped_column(Numeric(15, 4), nullable=False, default=Decimal(1))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(15, 4), nullable=False, default=Decimal(0))
    amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=Decimal(0))
    vat_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, default=Decimal("7"))
    vat_amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=Decimal(0))
    received_qty: Mapped[Decimal] = mapped_column(Numeric(15, 4), nullable=False, default=Decimal(0))

    po: Mapped[PurchaseOrder] = relationship("PurchaseOrder", back_populates="lines")
    grn_lines: Mapped[list[GRNLine]] = relationship("GRNLine", back_populates="po_line")


# ── Goods Received Note ───────────────────────────────────────────────────────

class GoodsReceivedNote(Base):
    """
    ใบรับสินค้า (Goods Received Note / GRN).

    ใช้ใน 3-way match: PO ↔ GRN ↔ Invoice
    """

    __tablename__ = "ap_grns"
    __table_args__ = (UniqueConstraint("company_id", "grn_no", name="uq_ap_grn_no"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    company_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    branch_id: Mapped[int] = mapped_column(Integer, nullable=False)

    grn_no: Mapped[str] = mapped_column(String(20), nullable=False)
    grn_date: Mapped[date] = mapped_column(Date, nullable=False)
    po_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("ap_purchase_orders.id"), nullable=False
    )

    notes: Mapped[Optional[str]] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="posted")

    received_by: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    po: Mapped[PurchaseOrder] = relationship("PurchaseOrder", back_populates="grns")
    lines: Mapped[list[GRNLine]] = relationship(
        "GRNLine", back_populates="grn", cascade="all, delete-orphan"
    )


class GRNLine(Base):
    """บรรทัดรายการรับสินค้าใน GRN."""

    __tablename__ = "ap_grn_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    grn_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("ap_grns.id", ondelete="CASCADE"), nullable=False
    )
    po_line_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("ap_po_lines.id"), nullable=False
    )

    description: Mapped[str] = mapped_column(String(500), nullable=False)
    ordered_qty: Mapped[Decimal] = mapped_column(Numeric(15, 4), nullable=False)
    received_qty: Mapped[Decimal] = mapped_column(Numeric(15, 4), nullable=False)
    unit: Mapped[Optional[str]] = mapped_column(String(20))

    grn: Mapped[GoodsReceivedNote] = relationship("GoodsReceivedNote", back_populates="lines")
    po_line: Mapped[PurchaseOrderLine] = relationship("PurchaseOrderLine", back_populates="grn_lines")


# ── AP Purchase (Supplier Invoice) ────────────────────────────────────────────

class APPurchase(Base):
    """
    ใบแจ้งหนี้เจ้าหนี้ (Supplier Invoice / AP Purchase).

    Journal (PJ):
        Dr [inventory/expense accounts]  subtotal
        Dr 1140 ภาษีซื้อ                 vat_amount
          Cr 2101 เจ้าหนี้               subtotal + vat_amount

    status: draft / posted / partially_paid / paid / cancelled
    """

    __tablename__ = "ap_purchases"
    __table_args__ = (
        UniqueConstraint("company_id", "purchase_no", name="uq_ap_purchase_no"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    company_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    branch_id: Mapped[int] = mapped_column(Integer, nullable=False)

    purchase_no: Mapped[str] = mapped_column(String(20), nullable=False)       # เลขที่ภายใน
    supplier_invoice_no: Mapped[Optional[str]] = mapped_column(String(100))    # เลขที่ใบแจ้งหนี้ supplier
    purchase_date: Mapped[date] = mapped_column(Date, nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)

    contact_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("contacts.id"), nullable=True
    )

    payment_mode: Mapped[str] = mapped_column(String(10), nullable=False, default="credit")
    # "cash" | "credit"
    payment_account_code: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    # account code เงินสด/ธนาคาร — ใช้เฉพาะ payment_mode="cash"

    po_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("ap_purchase_orders.id")
    )
    grn_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("ap_grns.id")
    )

    purchase_type: Mapped[str] = mapped_column(String(20), nullable=False, default="goods")

    subtotal: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=Decimal(0))
    vat_amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=Decimal(0))
    wht_amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=Decimal(0))
    total_amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=Decimal(0))
    paid_amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=Decimal(0))
    balance: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=Decimal(0))

    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    description: Mapped[Optional[str]] = mapped_column(Text)
    journal_entry_no: Mapped[Optional[str]] = mapped_column(String(20))

    created_by: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # Relationships
    lines: Mapped[list[APPurchaseLine]] = relationship(
        "APPurchaseLine", back_populates="purchase",
        order_by="APPurchaseLine.line_no",
        cascade="all, delete-orphan",
    )
    po: Mapped[Optional[PurchaseOrder]] = relationship("PurchaseOrder", back_populates="purchases")
    allocations: Mapped[list[APPaymentAllocation]] = relationship(
        "APPaymentAllocation", back_populates="purchase"
    )

    @property
    def is_overdue(self) -> bool:
        return self.status not in ("paid", "cancelled") and date.today() > self.due_date


class APPurchaseLine(Base):
    """บรรทัดรายการใน AP Purchase."""

    __tablename__ = "ap_purchase_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    purchase_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("ap_purchases.id", ondelete="CASCADE"), nullable=False
    )
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)

    product_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("inv_products.id"), nullable=True
    )
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    account_code: Mapped[str] = mapped_column(String(10), nullable=False)
    unit: Mapped[Optional[str]] = mapped_column(String(20))
    quantity: Mapped[Decimal] = mapped_column(Numeric(15, 4), nullable=False, default=Decimal(1))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(15, 4), nullable=False, default=Decimal(0))
    amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=Decimal(0))
    vat_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, default=Decimal("7"))
    vat_amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=Decimal(0))

    purchase: Mapped[APPurchase] = relationship("APPurchase", back_populates="lines")


# ── AP Payment ────────────────────────────────────────────────────────────────

class APPayment(Base):
    """
    ใบสำคัญจ่าย (Payment Voucher).

    Journal (CP):
        Dr 2101 เจ้าหนี้        total_applied
          Cr 1102 ธนาคาร        total_paid (= total_applied - wht_amount)
          Cr 2121 WHT ค้างนำส่ง  wht_amount (ถ้ามี)
    """

    __tablename__ = "ap_payments"
    __table_args__ = (UniqueConstraint("company_id", "payment_no", name="uq_ap_payment_no"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    company_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    branch_id: Mapped[int] = mapped_column(Integer, nullable=False)

    payment_no: Mapped[str] = mapped_column(String(20), nullable=False)
    payment_date: Mapped[date] = mapped_column(Date, nullable=False)

    contact_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("contacts.id"), nullable=False
    )

    bank_account_code: Mapped[str] = mapped_column(String(10), nullable=False, default="1102")
    total_paid: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    # เงินที่จ่ายออกจริง
    wht_amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=Decimal(0))
    # WHT ที่เราหักณที่จ่าย → Cr 2121
    total_applied: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=Decimal(0))
    # รวมยอดที่ match กับ AP = total_paid + wht_amount

    status: Mapped[str] = mapped_column(String(20), nullable=False, default="posted")
    description: Mapped[Optional[str]] = mapped_column(Text)
    reference: Mapped[Optional[str]] = mapped_column(String(100))
    journal_entry_no: Mapped[Optional[str]] = mapped_column(String(20))

    created_by: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    allocations: Mapped[list[APPaymentAllocation]] = relationship(
        "APPaymentAllocation", back_populates="payment", cascade="all, delete-orphan"
    )


class APPaymentAllocation(Base):
    """การ match ใบสำคัญจ่ายกับ AP Purchase."""

    __tablename__ = "ap_payment_allocations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    payment_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("ap_payments.id", ondelete="CASCADE"), nullable=False
    )
    purchase_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("ap_purchases.id"), nullable=False
    )
    allocated_amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)

    payment: Mapped[APPayment] = relationship("APPayment", back_populates="allocations")
    purchase: Mapped[APPurchase] = relationship("APPurchase", back_populates="allocations")
