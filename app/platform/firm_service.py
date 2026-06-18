"""FirmService — CRUD สำนักงานบัญชี (top-level tenant)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from fastapi import HTTPException, status
from pydantic import BaseModel, EmailStr, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.context import AppContext, UserRole
from app.platform.models import Firm


# ── Schemas ───────────────────────────────────────────────────────────────────

class FirmCreate(BaseModel):
    name: str
    tax_id: Optional[str] = None
    address: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None

    @field_validator("tax_id")
    @classmethod
    def validate_tax_id(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and len(v) != 13:
            raise ValueError("เลขประจำตัวผู้เสียภาษีต้อง 13 หลัก")
        return v


class FirmUpdate(BaseModel):
    name: Optional[str] = None
    tax_id: Optional[str] = None
    address: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    is_active: Optional[bool] = None


class FirmOut(BaseModel):
    id: int
    name: str
    tax_id: Optional[str]
    address: Optional[str]
    phone: Optional[str]
    email: Optional[str]
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Service ───────────────────────────────────────────────────────────────────

class FirmService:
    """CRUD สำหรับ Firm — ใช้ shared session."""

    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def create(self, data: FirmCreate) -> Firm:
        """
        สร้างสำนักงานบัญชีใหม่

        ไม่ต้องการ AppContext (เรียกโดย superuser/system)
        """
        if data.tax_id:
            existing = await self._s.execute(
                select(Firm).where(Firm.tax_id == data.tax_id)
            )
            if existing.scalar_one_or_none():
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"เลขประจำตัวผู้เสียภาษี {data.tax_id} ถูกใช้แล้ว",
                )

        firm = Firm(**data.model_dump())
        self._s.add(firm)
        await self._s.flush()
        return firm

    async def get(self, firm_id: int) -> Firm:
        """ดึงข้อมูล Firm ด้วย id."""
        result = await self._s.execute(
            select(Firm).where(Firm.id == firm_id)
        )
        firm = result.scalar_one_or_none()
        if firm is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"ไม่พบสำนักงานบัญชี id={firm_id}",
            )
        return firm

    async def list_all(self, active_only: bool = True) -> list[Firm]:
        """ดึงรายการ Firm ทั้งหมด (superuser เท่านั้น)."""
        stmt = select(Firm)
        if active_only:
            stmt = stmt.where(Firm.is_active == True)  # noqa: E712
        result = await self._s.execute(stmt.order_by(Firm.name))
        return list(result.scalars().all())

    async def update(self, firm_id: int, data: FirmUpdate, ctx: AppContext) -> Firm:
        """อัปเดตข้อมูล Firm — เฉพาะ firm_admin ของ firm นั้น."""
        self._check_admin(ctx, firm_id)
        firm = await self.get(firm_id)

        for field, val in data.model_dump(exclude_none=True).items():
            setattr(firm, field, val)

        await self._s.flush()
        return firm

    async def deactivate(self, firm_id: int, ctx: AppContext) -> None:
        """ปิดใช้งาน Firm (soft delete)."""
        self._check_admin(ctx, firm_id)
        firm = await self.get(firm_id)
        firm.is_active = False
        await self._s.flush()

    def _check_admin(self, ctx: AppContext, firm_id: int) -> None:
        is_correct_firm = ctx.firm_id == firm_id
        is_admin = ctx.user_role == UserRole.FIRM_ADMIN
        if not (is_correct_firm and is_admin):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="ต้องเป็น firm_admin ของสำนักงานบัญชีนั้น",
            )
