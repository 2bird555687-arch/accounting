"""
CompanyService — Multi-Company management

หน้าที่หลัก:
  - create_company: สร้าง directory + init DB + copy COA template
  - list_companies: เฉพาะบริษัทที่ user มีสิทธิ์
  - switch_company: validate สิทธิ์ → return AppContext ใหม่
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from fastapi import HTTPException, status
from pydantic import BaseModel, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.context import AppContext, UserRole
from app.database import init_company_db
from app.platform.auth import TokenClaims, build_app_context, create_tokens
from app.platform.models import Branch, Company, Firm, User, UserPermission


# ── Schemas ───────────────────────────────────────────────────────────────────

class CompanyCreate(BaseModel):
    code: str
    name: str
    name_en: Optional[str] = None
    tax_id: Optional[str] = None
    business_type: Optional[str] = None
    address: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    fiscal_year_start: int = 1
    vat_registered: bool = False
    vat_id: Optional[str] = None
    entity_type: str = "company"
    income_statement_format: str = "by_nature"
    coa_template: str = "trading"   # trading | service | mixed

    @field_validator("code")
    @classmethod
    def validate_code(cls, v: str) -> str:
        v = v.strip().upper()
        if not v or len(v) > 20:
            raise ValueError("code ต้องมีความยาว 1-20 ตัวอักษร")
        return v

    @field_validator("fiscal_year_start")
    @classmethod
    def validate_fiscal(cls, v: int) -> int:
        if not 1 <= v <= 12:
            raise ValueError("fiscal_year_start ต้องเป็น 1-12")
        return v

    @field_validator("coa_template")
    @classmethod
    def validate_template(cls, v: str) -> str:
        if v not in ("trading", "service", "mixed"):
            raise ValueError("coa_template ต้องเป็น trading, service หรือ mixed")
        return v


class CompanyUpdate(BaseModel):
    name: Optional[str] = None
    name_en: Optional[str] = None
    tax_id: Optional[str] = None
    business_type: Optional[str] = None
    address: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    vat_registered: Optional[bool] = None
    vat_id: Optional[str] = None
    is_active: Optional[bool] = None
    entity_type: Optional[str] = None
    income_statement_format: Optional[str] = None


class CompanyOut(BaseModel):
    id: int
    firm_id: int
    code: str
    name: str
    name_en: Optional[str]
    tax_id: Optional[str]
    business_type: Optional[str]
    vat_registered: bool
    fiscal_year_start: int
    is_active: bool
    entity_type: str
    income_statement_format: str
    created_at: datetime

    model_config = {"from_attributes": True}


class SwitchCompanyOut(BaseModel):
    """ผลลัพธ์ของ switch_company — token ใหม่พร้อม context ใหม่."""

    access_token: str
    refresh_token: str
    token_type: str
    expires_in: int
    company: CompanyOut
    branch_id: int
    role: str


# ── Service ───────────────────────────────────────────────────────────────────

class CompanyService:
    """จัดการ Company ใน shared database."""

    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def create_company(
        self,
        data: CompanyCreate,
        ctx: AppContext,
    ) -> Company:
        """
        สร้าง Company ใหม่

        Flow:
          1. ตรวจสิทธิ์ firm_admin
          2. ตรวจ code ซ้ำใน firm
          3. บันทึก Company + Branch HQ ใน shared DB
          4. init company database (SQLite file แยก)
          5. apply COA template
        """
        self._require_firm_admin(ctx)

        # ตรวจ code ซ้ำ
        dup = await self._s.execute(
            select(Company).where(
                Company.firm_id == ctx.firm_id,
                Company.code == data.code,
            )
        )
        if dup.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"รหัสกิจการ {data.code!r} ถูกใช้แล้วใน firm นี้",
            )

        # บันทึก Company
        coa_template = data.coa_template
        company_data = data.model_dump(exclude={"coa_template"})
        company = Company(firm_id=ctx.firm_id, **company_data)
        self._s.add(company)
        await self._s.flush()  # ได้ company.id

        # สร้าง HQ Branch (branch_code=00000) อัตโนมัติ
        hq = Branch(
            company_id=company.id,
            branch_code="00000",
            name="สำนักงานใหญ่",
        )
        self._s.add(hq)
        await self._s.flush()

        # init company database + COA
        await init_company_db(ctx.firm_id, company.id)
        await self._apply_coa_template(ctx.firm_id, company.id, coa_template)

        return company

    async def list_companies(
        self,
        ctx: AppContext,
        active_only: bool = True,
    ) -> list[Company]:
        """
        ดึงรายการ Company ที่ user มีสิทธิ์เข้าถึง

        firm_admin เห็นทุก company ใน firm
        role อื่นเห็นเฉพาะที่มี UserPermission
        """
        if ctx.user_role == UserRole.FIRM_ADMIN:
            stmt = select(Company).where(Company.firm_id == ctx.firm_id)
        else:
            permitted_ids = select(UserPermission.company_id).where(
                UserPermission.user_id == ctx.user_id,
                UserPermission.is_active == True,  # noqa: E712
            )
            stmt = select(Company).where(
                Company.firm_id == ctx.firm_id,
                Company.id.in_(permitted_ids),
            )

        if active_only:
            stmt = stmt.where(Company.is_active == True)  # noqa: E712

        result = await self._s.execute(stmt.order_by(Company.code))
        return list(result.scalars().all())

    async def get(self, company_id: int, ctx: AppContext) -> Company:
        """ดึง Company — ตรวจสิทธิ์ด้วย."""
        await self._check_access(company_id, ctx)
        result = await self._s.execute(
            select(Company).where(Company.id == company_id)
        )
        company = result.scalar_one_or_none()
        if company is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"ไม่พบกิจการ id={company_id}",
            )
        return company

    async def update(
        self,
        company_id: int,
        data: CompanyUpdate,
        ctx: AppContext,
    ) -> Company:
        """อัปเดตข้อมูล Company."""
        self._require_firm_admin(ctx)
        company = await self.get(company_id, ctx)
        for field, val in data.model_dump(exclude_none=True).items():
            setattr(company, field, val)
        await self._s.flush()
        return company

    async def switch_company(
        self,
        company_id: int,
        ctx: AppContext,
        branch_id: Optional[int] = None,
    ) -> SwitchCompanyOut:
        """
        เปลี่ยน context ไปยัง company อื่น

        ตรวจว่า user มีสิทธิ์เข้า company นั้น
        คืน token ใหม่พร้อม company + branch context

        Args:
            company_id: company ที่ต้องการ switch ไป
            ctx: context ปัจจุบัน
            branch_id: ถ้า None ใช้ HQ branch อัตโนมัติ
        """
        # ตรวจสิทธิ์
        role, effective_branch_id = await self._get_user_access(
            ctx.user_id, company_id, branch_id
        )

        company = await self._s.execute(
            select(Company).where(Company.id == company_id, Company.is_active == True)  # noqa: E712
        )
        company_obj = company.scalar_one_or_none()
        if company_obj is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"ไม่พบกิจการ id={company_id} หรือถูกปิดการใช้งาน",
            )

        # period = วันที่ 1 ของเดือนปัจจุบัน
        today = date.today()
        period = today.replace(day=1)

        token_pair = create_tokens(
            user_id=ctx.user_id,
            firm_id=ctx.firm_id,
            company_id=company_id,
            branch_id=effective_branch_id,
            role=UserRole(role),
            period=period,
        )

        return SwitchCompanyOut(
            access_token=token_pair.access_token,
            refresh_token=token_pair.refresh_token,
            token_type=token_pair.token_type,
            expires_in=token_pair.expires_in,
            company=CompanyOut.model_validate(company_obj),
            branch_id=effective_branch_id,
            role=role,
        )

    # ── Helpers ───────────────────────────────────────────────────────────────

    async def _get_user_access(
        self,
        user_id: int,
        company_id: int,
        preferred_branch_id: Optional[int],
    ) -> tuple[str, int]:
        """
        ตรวจสิทธิ์ user → company → branch

        Returns:
            (role, branch_id) ที่ได้รับอนุญาต
        """
        stmt = select(UserPermission).where(
            UserPermission.user_id == user_id,
            UserPermission.company_id == company_id,
            UserPermission.is_active == True,  # noqa: E712
        )
        if preferred_branch_id is not None:
            stmt = stmt.where(
                (UserPermission.branch_id == preferred_branch_id)
                | (UserPermission.branch_id.is_(None))
            )

        result = await self._s.execute(stmt.order_by(UserPermission.branch_id.nulls_first()))
        perm = result.scalars().first()

        if perm is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"ไม่มีสิทธิ์เข้าถึงกิจการ id={company_id}",
            )

        # ถ้า preferred_branch_id กำหนดมา ใช้ตาม; ถ้าไม่มี ใช้ HQ
        if preferred_branch_id and (perm.branch_id is None or perm.branch_id == preferred_branch_id):
            branch_id = preferred_branch_id
        else:
            hq = await self._s.execute(
                select(Branch).where(
                    Branch.company_id == company_id,
                    Branch.branch_code == "00000",
                )
            )
            hq_branch = hq.scalar_one_or_none()
            branch_id = hq_branch.id if hq_branch else (perm.branch_id or 1)

        return perm.role, branch_id

    async def _check_access(self, company_id: int, ctx: AppContext) -> None:
        """ตรวจว่า user มีสิทธิ์ดู company นี้."""
        if ctx.user_role == UserRole.FIRM_ADMIN:
            return  # firm_admin ดูได้ทุก company ใน firm

        result = await self._s.execute(
            select(UserPermission).where(
                UserPermission.user_id == ctx.user_id,
                UserPermission.company_id == company_id,
                UserPermission.is_active == True,  # noqa: E712
            )
        )
        if result.scalar_one_or_none() is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="ไม่มีสิทธิ์เข้าถึงกิจการนี้",
            )

    async def _apply_coa_template(
        self,
        firm_id: int,
        company_id: int,
        template_type: str,
    ) -> None:
        """Apply COA template ลง company database ใหม่."""
        from app.platform.coa_template import COATemplateService
        from app.database import get_session_factory
        from app.config import settings

        db_url = settings.get_company_db_url(firm_id, company_id)
        factory = get_session_factory(db_url)
        async with factory() as company_session:
            svc = COATemplateService(company_session)
            await svc.apply_template(template_type)
            await company_session.commit()

    def _require_firm_admin(self, ctx: AppContext) -> None:
        if ctx.user_role != UserRole.FIRM_ADMIN:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="ต้องเป็น firm_admin เท่านั้น",
            )
