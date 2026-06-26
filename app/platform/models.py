"""Platform Layer Models — Firm, Company, Branch, User, UserPermission."""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base สำหรับ platform models (shared database)."""
    pass


# ── Firm ──────────────────────────────────────────────────────────────────────

class Firm(Base):
    """สำนักงานบัญชี — top-level tenant."""

    __tablename__ = "firms"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    tax_id: Mapped[Optional[str]] = mapped_column(String(13), unique=True)
    address: Mapped[Optional[str]] = mapped_column(Text)
    phone: Mapped[Optional[str]] = mapped_column(String(20))
    email: Mapped[Optional[str]] = mapped_column(String(200))
    logo_path: Mapped[Optional[str]] = mapped_column(String(500))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    companies: Mapped[list[Company]] = relationship("Company", back_populates="firm")
    users: Mapped[list[User]] = relationship("User", back_populates="firm")

    def __repr__(self) -> str:
        return f"<Firm id={self.id} name={self.name!r}>"


# ── Company ───────────────────────────────────────────────────────────────────

class Company(Base):
    """กิจการลูกค้า — สังกัด Firm."""

    __tablename__ = "companies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    firm_id: Mapped[int] = mapped_column(Integer, ForeignKey("firms.id"), nullable=False)
    code: Mapped[str] = mapped_column(String(20), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    name_en: Mapped[Optional[str]] = mapped_column(String(200))
    tax_id: Mapped[Optional[str]] = mapped_column(String(13))
    business_type: Mapped[Optional[str]] = mapped_column(String(100))
    address: Mapped[Optional[str]] = mapped_column(Text)
    phone: Mapped[Optional[str]] = mapped_column(String(20))
    email: Mapped[Optional[str]] = mapped_column(String(200))
    fiscal_year_start: Mapped[int] = mapped_column(Integer, default=1, nullable=False)  # เดือน
    vat_registered: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    vat_id: Mapped[Optional[str]] = mapped_column(String(13))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    entity_type: Mapped[str] = mapped_column(
        String(20), default="company", nullable=False
    )
    income_statement_format: Mapped[str] = mapped_column(
        String(30), default="by_nature", nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (UniqueConstraint("firm_id", "code", name="uq_company_code"),)

    firm: Mapped[Firm] = relationship("Firm", back_populates="companies")
    branches: Mapped[list[Branch]] = relationship("Branch", back_populates="company")
    permissions: Mapped[list[UserPermission]] = relationship(
        "UserPermission", back_populates="company"
    )

    def __repr__(self) -> str:
        return f"<Company id={self.id} code={self.code!r} name={self.name!r}>"


# ── Branch ────────────────────────────────────────────────────────────────────

class Branch(Base):
    """สาขา — สังกัด Company. branch_code='00000' คือ HQ."""

    __tablename__ = "branches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    company_id: Mapped[int] = mapped_column(Integer, ForeignKey("companies.id"), nullable=False)
    branch_code: Mapped[str] = mapped_column(String(5), nullable=False)  # 00000 = HQ
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    address: Mapped[Optional[str]] = mapped_column(Text)
    phone: Mapped[Optional[str]] = mapped_column(String(20))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (UniqueConstraint("company_id", "branch_code", name="uq_branch_code"),)

    company: Mapped[Company] = relationship("Company", back_populates="branches")

    @property
    def is_hq(self) -> bool:
        """สาขาใหญ่ (HQ) หรือไม่."""
        return self.branch_code == "00000"

    def __repr__(self) -> str:
        return f"<Branch id={self.id} code={self.branch_code!r} name={self.name!r}>"


# ── User ──────────────────────────────────────────────────────────────────────

class User(Base):
    """ผู้ใช้งานระบบ — สังกัด Firm."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    firm_id: Mapped[int] = mapped_column(Integer, ForeignKey("firms.id"), nullable=False)
    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    email: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(200), nullable=False)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    phone: Mapped[Optional[str]] = mapped_column(String(20))
    default_role: Mapped[str] = mapped_column(String(30), nullable=False, default="junior")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_superuser: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_login: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    firm: Mapped[Firm] = relationship("Firm", back_populates="users")
    permissions: Mapped[list[UserPermission]] = relationship(
        "UserPermission",
        back_populates="user",
        foreign_keys="[UserPermission.user_id]",
    )

    def __repr__(self) -> str:
        return f"<User id={self.id} username={self.username!r}>"


# ── UserPermission ────────────────────────────────────────────────────────────

class UserPermission(Base):
    """
    สิทธิ์ผู้ใช้ต่อ Company — กำหนด role ที่ user มีใน company นั้น.

    User คน 1 มีได้หลาย company แต่ละ company role อาจต่างกัน.
    """

    __tablename__ = "user_permissions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    company_id: Mapped[int] = mapped_column(Integer, ForeignKey("companies.id"), nullable=False)
    role: Mapped[str] = mapped_column(String(30), nullable=False)
    # branch_id=None หมายความว่ามีสิทธิ์ทุกสาขา
    branch_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("branches.id"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    granted_by: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("users.id"))
    granted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("user_id", "company_id", "branch_id", name="uq_user_company_branch"),
    )

    user: Mapped[User] = relationship("User", foreign_keys=[user_id], back_populates="permissions")
    company: Mapped[Company] = relationship("Company", back_populates="permissions")
    branch: Mapped[Optional[Branch]] = relationship("Branch")
    granter: Mapped[Optional[User]] = relationship("User", foreign_keys=[granted_by])

    def __repr__(self) -> str:
        return (
            f"<UserPermission user={self.user_id} company={self.company_id} role={self.role!r}>"
        )


# ── FiscalYear ────────────────────────────────────────────────────────────────

class FiscalYear(Base):
    """ปีงบการเงินของ Company (เก็บใน platform DB)."""

    __tablename__ = "fiscal_years"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    company_id: Mapped[int] = mapped_column(Integer, ForeignKey("companies.id"), nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    # "active" | "closing" | "closed"
    is_locked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("company_id", "year", name="uq_fiscal_year"),
    )

    company: Mapped[Company] = relationship("Company")

    def __repr__(self) -> str:
        return f"<FiscalYear company={self.company_id} year={self.year} status={self.status!r}>"
