"""BranchService — CRUD สาขา พร้อม branch_code validation."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Optional

from fastapi import HTTPException, status
from pydantic import BaseModel, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.context import AppContext, UserRole
from app.platform.models import Branch, UserPermission


# ── Schemas ───────────────────────────────────────────────────────────────────

class BranchCreate(BaseModel):
    branch_code: str
    name: str
    address: Optional[str] = None
    phone: Optional[str] = None

    @field_validator("branch_code")
    @classmethod
    def validate_branch_code(cls, v: str) -> str:
        """branch_code ต้องเป็นตัวเลข 5 หลักเท่านั้น (00000 = HQ)."""
        v = v.strip()
        if not re.fullmatch(r"\d{5}", v):
            raise ValueError("branch_code ต้องเป็นตัวเลข 5 หลัก เช่น '00000' หรือ '00001'")
        return v

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("ชื่อสาขาต้องไม่ว่างเปล่า")
        return v


class BranchUpdate(BaseModel):
    name: Optional[str] = None
    address: Optional[str] = None
    phone: Optional[str] = None
    is_active: Optional[bool] = None


class BranchOut(BaseModel):
    id: int
    company_id: int
    branch_code: str
    name: str
    address: Optional[str]
    phone: Optional[str]
    is_active: bool
    is_hq: bool
    created_at: datetime

    model_config = {"from_attributes": True}

    @classmethod
    def from_orm_branch(cls, branch: Branch) -> "BranchOut":
        return cls(
            id=branch.id,
            company_id=branch.company_id,
            branch_code=branch.branch_code,
            name=branch.name,
            address=branch.address,
            phone=branch.phone,
            is_active=branch.is_active,
            is_hq=branch.is_hq,
            created_at=branch.created_at,
        )


# ── Service ───────────────────────────────────────────────────────────────────

class BranchService:
    """CRUD สาขา ใน shared database."""

    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def create(
        self,
        company_id: int,
        data: BranchCreate,
        ctx: AppContext,
    ) -> Branch:
        """
        สร้างสาขาใหม่

        กฎ:
          - ต้องเป็น firm_admin หรือ accountant
          - branch_code ต้องไม่ซ้ำในบริษัทเดียวกัน
          - ห้ามสร้าง 00000 ซ้ำ (HQ มีแล้วตอน create_company)
        """
        self._require_can_manage(ctx)
        self._check_company_access(company_id, ctx)

        # ตรวจซ้ำ
        existing = await self._s.execute(
            select(Branch).where(
                Branch.company_id == company_id,
                Branch.branch_code == data.branch_code,
            )
        )
        if existing.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"branch_code {data.branch_code!r} มีอยู่แล้วในบริษัทนี้",
            )

        if data.branch_code == "00000":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="branch_code 00000 (HQ) ถูกสร้างอัตโนมัติตอนสร้างบริษัท ไม่ต้องสร้างเอง",
            )

        branch = Branch(company_id=company_id, **data.model_dump())
        self._s.add(branch)
        await self._s.flush()
        return branch

    async def get(self, branch_id: int, ctx: AppContext) -> Branch:
        """ดึงข้อมูลสาขาด้วย id."""
        result = await self._s.execute(
            select(Branch).where(Branch.id == branch_id)
        )
        branch = result.scalar_one_or_none()
        if branch is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"ไม่พบสาขา id={branch_id}",
            )
        self._check_company_access(branch.company_id, ctx)
        return branch

    async def get_by_code(
        self, company_id: int, branch_code: str, ctx: AppContext
    ) -> Branch:
        """ดึงสาขาด้วย branch_code."""
        self._check_company_access(company_id, ctx)
        result = await self._s.execute(
            select(Branch).where(
                Branch.company_id == company_id,
                Branch.branch_code == branch_code,
            )
        )
        branch = result.scalar_one_or_none()
        if branch is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"ไม่พบสาขารหัส {branch_code!r}",
            )
        return branch

    async def list_branches(
        self,
        company_id: int,
        ctx: AppContext,
        active_only: bool = True,
    ) -> list[Branch]:
        """ดึงรายการสาขาทั้งหมดของบริษัท."""
        self._check_company_access(company_id, ctx)

        # ถ้า user มีสิทธิ์แค่บางสาขา — กรองตาม UserPermission
        if ctx.user_role not in (UserRole.FIRM_ADMIN, UserRole.ACCOUNTANT):
            permitted = await self._get_permitted_branch_ids(ctx.user_id, company_id)
            stmt = select(Branch).where(
                Branch.company_id == company_id,
                Branch.id.in_(permitted),
            )
        else:
            stmt = select(Branch).where(Branch.company_id == company_id)

        if active_only:
            stmt = stmt.where(Branch.is_active == True)  # noqa: E712

        result = await self._s.execute(stmt.order_by(Branch.branch_code))
        return list(result.scalars().all())

    async def update(
        self,
        branch_id: int,
        data: BranchUpdate,
        ctx: AppContext,
    ) -> Branch:
        """อัปเดตข้อมูลสาขา."""
        self._require_can_manage(ctx)
        branch = await self.get(branch_id, ctx)

        for field, val in data.model_dump(exclude_none=True).items():
            setattr(branch, field, val)

        await self._s.flush()
        return branch

    async def deactivate(self, branch_id: int, ctx: AppContext) -> None:
        """ปิดใช้งานสาขา (soft delete)."""
        self._require_can_manage(ctx)
        branch = await self.get(branch_id, ctx)

        if branch.is_hq:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="ไม่สามารถปิด HQ branch (00000) ได้ ต้องปิดบริษัทแทน",
            )

        branch.is_active = False
        await self._s.flush()

    async def validate_branch_belongs_to_company(
        self, branch_id: int, company_id: int
    ) -> bool:
        """ตรวจว่า branch_id สังกัด company_id ที่ระบุ."""
        result = await self._s.execute(
            select(Branch.id).where(
                Branch.id == branch_id,
                Branch.company_id == company_id,
                Branch.is_active == True,  # noqa: E712
            )
        )
        return result.scalar_one_or_none() is not None

    # ── Helpers ───────────────────────────────────────────────────────────────

    async def _get_permitted_branch_ids(
        self, user_id: int, company_id: int
    ) -> list[int]:
        """ดึง branch_ids ที่ user มีสิทธิ์ใน company นี้."""
        result = await self._s.execute(
            select(UserPermission.branch_id).where(
                UserPermission.user_id == user_id,
                UserPermission.company_id == company_id,
                UserPermission.is_active == True,  # noqa: E712
                UserPermission.branch_id.is_not(None),
            )
        )
        ids = [row[0] for row in result.all() if row[0] is not None]

        # ถ้า permission มี branch_id=None = ทุกสาขา — ดึงทั้งหมด
        all_perm = await self._s.execute(
            select(UserPermission.branch_id).where(
                UserPermission.user_id == user_id,
                UserPermission.company_id == company_id,
                UserPermission.is_active == True,  # noqa: E712
                UserPermission.branch_id.is_(None),
            )
        )
        if all_perm.scalar_one_or_none() is not None:
            all_branches = await self._s.execute(
                select(Branch.id).where(
                    Branch.company_id == company_id,
                    Branch.is_active == True,  # noqa: E712
                )
            )
            return [r[0] for r in all_branches.all()]

        return ids

    def _check_company_access(self, company_id: int, ctx: AppContext) -> None:
        """ตรวจว่า ctx.company_id ตรงกับที่ขอ (หรือเป็น firm_admin)."""
        if ctx.user_role == UserRole.FIRM_ADMIN:
            return
        if ctx.company_id != company_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="ไม่มีสิทธิ์เข้าถึงบริษัทนี้",
            )

    def _require_can_manage(self, ctx: AppContext) -> None:
        if ctx.user_role not in (UserRole.FIRM_ADMIN, UserRole.ACCOUNTANT):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="ต้องเป็น firm_admin หรือ accountant เท่านั้น",
            )
