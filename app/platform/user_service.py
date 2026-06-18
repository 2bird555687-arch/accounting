"""
UserService — register, login, permission management

รองรับ role: firm_admin, accountant, junior, client_viewer, auditor
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Optional

from fastapi import HTTPException, status
from pydantic import BaseModel, EmailStr, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.context import AppContext, UserRole
from app.platform.auth import (
    TokenPair,
    create_tokens,
    hash_password,
    verify_password,
)
from app.platform.models import Branch, Company, User, UserPermission


# ── Schemas ───────────────────────────────────────────────────────────────────

class UserRegister(BaseModel):
    username: str
    email: str
    password: str
    full_name: str
    phone: Optional[str] = None
    default_role: UserRole = UserRole.JUNIOR

    @field_validator("username")
    @classmethod
    def validate_username(cls, v: str) -> str:
        v = v.strip().lower()
        if not v or len(v) < 3 or len(v) > 50:
            raise ValueError("username ต้อง 3-50 ตัวอักษร")
        if not v.replace("_", "").replace("-", "").isalnum():
            raise ValueError("username ใช้ได้เฉพาะ a-z, 0-9, _ และ -")
        return v

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("รหัสผ่านต้องมีอย่างน้อย 8 ตัวอักษร")
        return v


class UserLogin(BaseModel):
    username: str           # รับทั้ง username หรือ email
    password: str
    company_id: Optional[int] = None
    branch_id: Optional[int] = None


class ChangePassword(BaseModel):
    current_password: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def validate_new_password(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("รหัสผ่านใหม่ต้องมีอย่างน้อย 8 ตัวอักษร")
        return v


class AssignCompany(BaseModel):
    user_id: int
    company_id: int
    role: UserRole
    branch_id: Optional[int] = None   # None = ทุกสาขา


class UserOut(BaseModel):
    id: int
    firm_id: int
    username: str
    email: str
    full_name: str
    phone: Optional[str]
    default_role: str
    is_active: bool
    last_login: Optional[datetime]
    created_at: datetime

    model_config = {"from_attributes": True}


class PermissionOut(BaseModel):
    id: int
    user_id: int
    company_id: int
    role: str
    branch_id: Optional[int]
    is_active: bool
    granted_at: datetime

    model_config = {"from_attributes": True}


class LoginOut(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str
    expires_in: int
    user: UserOut
    company_id: Optional[int]
    branch_id: Optional[int]
    role: Optional[str]


# ── Service ───────────────────────────────────────────────────────────────────

class UserService:
    """จัดการ User ใน shared database."""

    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def register(
        self,
        firm_id: int,
        data: UserRegister,
        ctx: Optional[AppContext] = None,
    ) -> User:
        """
        สร้าง user ใหม่ใน firm

        ถ้ามี ctx ต้องเป็น firm_admin
        ถ้าไม่มี ctx เป็นการสร้าง superuser แรก (bootstrap)
        """
        if ctx is not None and ctx.user_role != UserRole.FIRM_ADMIN:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="ต้องเป็น firm_admin เพื่อสร้างผู้ใช้ใหม่",
            )

        # ตรวจ username ซ้ำ
        dup_user = await self._s.execute(
            select(User).where(User.username == data.username)
        )
        if dup_user.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"username {data.username!r} ถูกใช้แล้ว",
            )

        # ตรวจ email ซ้ำ
        dup_email = await self._s.execute(
            select(User).where(User.email == data.email)
        )
        if dup_email.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"email {data.email!r} ถูกใช้แล้ว",
            )

        user = User(
            firm_id=firm_id,
            username=data.username,
            email=data.email,
            hashed_password=hash_password(data.password),
            full_name=data.full_name,
            phone=data.phone,
            default_role=str(data.default_role),
        )
        self._s.add(user)
        await self._s.flush()
        return user

    async def login(self, data: UserLogin) -> LoginOut:
        """
        เข้าสู่ระบบ — คืน JWT tokens

        ถ้าระบุ company_id จะสร้าง token สำหรับ company นั้นทันที
        ถ้าไม่ระบุ สร้าง token ด้วย company_id=0 (เลือก company หลัง login)
        """
        # ค้นหา user ด้วย username หรือ email
        result = await self._s.execute(
            select(User).where(
                (User.username == data.username) | (User.email == data.username)
            )
        )
        user = result.scalar_one_or_none()

        if user is None or not verify_password(data.password, user.hashed_password):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="username หรือรหัสผ่านไม่ถูกต้อง",
            )

        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="บัญชีผู้ใช้ถูกระงับ กรุณาติดต่อผู้ดูแลระบบ",
            )

        # อัปเดต last_login
        user.last_login = datetime.now(tz=timezone.utc)

        company_id = data.company_id
        branch_id = data.branch_id
        role_str: Optional[str] = None
        period = date.today().replace(day=1)

        if company_id:
            role_str, branch_id = await self._resolve_company_access(
                user.id, company_id, branch_id
            )
        else:
            # ถ้าไม่ระบุ company — ใช้ company แรกที่มีสิทธิ์
            first_perm = await self._get_first_permission(user.id)
            if first_perm:
                company_id = first_perm.company_id
                branch_id = first_perm.branch_id
                role_str = first_perm.role
                # ถ้า branch_id=None ดึง HQ
                if branch_id is None:
                    hq = await self._get_hq_branch(company_id)
                    branch_id = hq.id if hq else 1

        # สร้าง token
        effective_company = company_id or 0
        effective_branch = branch_id or 0
        effective_role = UserRole(role_str) if role_str else UserRole(user.default_role)

        token_pair = create_tokens(
            user_id=user.id,
            firm_id=user.firm_id,
            company_id=effective_company,
            branch_id=effective_branch,
            role=effective_role,
            period=period,
        )

        await self._s.flush()

        return LoginOut(
            access_token=token_pair.access_token,
            refresh_token=token_pair.refresh_token,
            token_type=token_pair.token_type,
            expires_in=token_pair.expires_in,
            user=UserOut.model_validate(user),
            company_id=effective_company or None,
            branch_id=effective_branch or None,
            role=str(effective_role),
        )

    async def change_password(
        self,
        user_id: int,
        data: ChangePassword,
        ctx: AppContext,
    ) -> None:
        """เปลี่ยนรหัสผ่าน — user เปลี่ยนของตัวเอง หรือ firm_admin เปลี่ยนให้ได้."""
        if ctx.user_id != user_id and ctx.user_role != UserRole.FIRM_ADMIN:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="สามารถเปลี่ยนรหัสผ่านได้เฉพาะของตัวเอง",
            )

        user = await self._get_user(user_id)

        # superuser เปลี่ยนให้ไม่ต้องใส่รหัสเดิม
        if ctx.user_id == user_id:
            if not verify_password(data.current_password, user.hashed_password):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="รหัสผ่านปัจจุบันไม่ถูกต้อง",
                )

        user.hashed_password = hash_password(data.new_password)
        await self._s.flush()

    async def assign_company(
        self,
        data: AssignCompany,
        ctx: AppContext,
    ) -> UserPermission:
        """
        กำหนดสิทธิ์ user เข้า company

        เฉพาะ firm_admin เท่านั้น
        ถ้ามี permission อยู่แล้วจะ update role
        """
        if ctx.user_role != UserRole.FIRM_ADMIN:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="ต้องเป็น firm_admin เพื่อกำหนดสิทธิ์",
            )

        # ตรวจ user อยู่ใน firm เดียวกัน
        target_user = await self._get_user(data.user_id)
        if target_user.firm_id != ctx.firm_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="ไม่สามารถกำหนดสิทธิ์ข้าม firm",
            )

        # หา permission ที่มีอยู่
        stmt = select(UserPermission).where(
            UserPermission.user_id == data.user_id,
            UserPermission.company_id == data.company_id,
        )
        if data.branch_id is not None:
            stmt = stmt.where(UserPermission.branch_id == data.branch_id)
        else:
            stmt = stmt.where(UserPermission.branch_id.is_(None))

        result = await self._s.execute(stmt)
        perm = result.scalar_one_or_none()

        if perm:
            # update role
            perm.role = str(data.role)
            perm.is_active = True
            perm.granted_by = ctx.user_id
        else:
            perm = UserPermission(
                user_id=data.user_id,
                company_id=data.company_id,
                role=str(data.role),
                branch_id=data.branch_id,
                granted_by=ctx.user_id,
            )
            self._s.add(perm)

        await self._s.flush()
        return perm

    async def revoke_company(
        self,
        user_id: int,
        company_id: int,
        ctx: AppContext,
        branch_id: Optional[int] = None,
    ) -> None:
        """ยกเลิกสิทธิ์ user ใน company."""
        if ctx.user_role != UserRole.FIRM_ADMIN:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="ต้องเป็น firm_admin เพื่อยกเลิกสิทธิ์",
            )

        stmt = select(UserPermission).where(
            UserPermission.user_id == user_id,
            UserPermission.company_id == company_id,
        )
        if branch_id is not None:
            stmt = stmt.where(UserPermission.branch_id == branch_id)

        result = await self._s.execute(stmt)
        perms = result.scalars().all()

        for p in perms:
            p.is_active = False

        await self._s.flush()

    async def check_permission(
        self,
        user_id: int,
        action: str,
        ctx: AppContext,
    ) -> bool:
        """
        ตรวจสิทธิ์ตาม action string

        Actions: "post", "approve", "close_period", "view", "manage_users"
        """
        perm = await self._s.execute(
            select(UserPermission).where(
                UserPermission.user_id == user_id,
                UserPermission.company_id == ctx.company_id,
                UserPermission.is_active == True,  # noqa: E712
            )
        )
        p = perm.scalars().first()
        if p is None:
            return False

        role = UserRole(p.role)
        match action:
            case "post":
                return role in (UserRole.FIRM_ADMIN, UserRole.ACCOUNTANT, UserRole.JUNIOR)
            case "approve":
                return role in (UserRole.FIRM_ADMIN, UserRole.ACCOUNTANT)
            case "close_period":
                return role == UserRole.FIRM_ADMIN
            case "view":
                return True  # ทุก role ดูได้
            case "manage_users":
                return role == UserRole.FIRM_ADMIN
            case _:
                return False

    async def list_users(
        self,
        ctx: AppContext,
        company_id: Optional[int] = None,
    ) -> list[User]:
        """ดึงรายการ user ใน firm."""
        if ctx.user_role not in (UserRole.FIRM_ADMIN, UserRole.ACCOUNTANT):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="ไม่มีสิทธิ์ดูรายการผู้ใช้",
            )

        stmt = select(User).where(
            User.firm_id == ctx.firm_id,
            User.is_active == True,  # noqa: E712
        )

        if company_id:
            user_ids = select(UserPermission.user_id).where(
                UserPermission.company_id == company_id,
                UserPermission.is_active == True,  # noqa: E712
            )
            stmt = stmt.where(User.id.in_(user_ids))

        result = await self._s.execute(stmt.order_by(User.full_name))
        return list(result.scalars().all())

    async def list_permissions(
        self,
        company_id: int,
        ctx: AppContext,
    ) -> list[UserPermission]:
        """ดึงสิทธิ์ทั้งหมดของ company."""
        if ctx.user_role != UserRole.FIRM_ADMIN:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="ต้องเป็น firm_admin",
            )

        result = await self._s.execute(
            select(UserPermission)
            .options(selectinload(UserPermission.user))
            .where(
                UserPermission.company_id == company_id,
                UserPermission.is_active == True,  # noqa: E712
            )
            .order_by(UserPermission.role, UserPermission.user_id)
        )
        return list(result.scalars().all())

    # ── Private helpers ───────────────────────────────────────────────────────

    async def _get_user(self, user_id: int) -> User:
        result = await self._s.execute(
            select(User).where(User.id == user_id)
        )
        user = result.scalar_one_or_none()
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"ไม่พบผู้ใช้ id={user_id}",
            )
        return user

    async def _resolve_company_access(
        self,
        user_id: int,
        company_id: int,
        preferred_branch_id: Optional[int],
    ) -> tuple[str, int]:
        """คืน (role, branch_id) ที่ user มีสิทธิ์."""
        stmt = select(UserPermission).where(
            UserPermission.user_id == user_id,
            UserPermission.company_id == company_id,
            UserPermission.is_active == True,  # noqa: E712
        )
        result = await self._s.execute(stmt)
        perms = result.scalars().all()

        if not perms:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"ไม่มีสิทธิ์เข้าถึงกิจการ id={company_id}",
            )

        # เลือก perm ที่ตรงกับ branch หรือ perm ที่ไม่จำกัด branch
        matching = next(
            (p for p in perms if p.branch_id == preferred_branch_id), None
        ) or next(
            (p for p in perms if p.branch_id is None), None
        ) or perms[0]

        # resolve branch_id
        if preferred_branch_id:
            branch_id = preferred_branch_id
        elif matching.branch_id:
            branch_id = matching.branch_id
        else:
            hq = await self._get_hq_branch(company_id)
            branch_id = hq.id if hq else 1

        return matching.role, branch_id

    async def _get_first_permission(self, user_id: int) -> Optional[UserPermission]:
        result = await self._s.execute(
            select(UserPermission)
            .where(
                UserPermission.user_id == user_id,
                UserPermission.is_active == True,  # noqa: E712
            )
            .order_by(UserPermission.id)
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def _get_hq_branch(self, company_id: int) -> Optional[Branch]:
        result = await self._s.execute(
            select(Branch).where(
                Branch.company_id == company_id,
                Branch.branch_code == "00000",
            )
        )
        return result.scalar_one_or_none()
