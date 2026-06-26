"""Platform routes — firms, companies, branches, users."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from app.api.deps import CTX, SharedDB
from app.api.responses import ok, paginated
from app.context import UserRole
from app.platform.auth import require_role
from app.platform.branch_service import BranchCreate, BranchOut, BranchService, BranchUpdate
from app.platform.company_service import (
    CompanyCreate,
    CompanyOut,
    CompanyService,
    CompanyUpdate,
    SwitchCompanyOut,
)
from app.platform.firm_service import FirmCreate, FirmOut, FirmService, FirmUpdate
from app.platform.user_service import (
    AssignCompany,
    ChangePassword,
    PermissionOut,
    UserOut,
    UserRegister,
    UserService,
)

router = APIRouter(tags=["Platform"])


# ══════════════════════════════════════════════════════════════════════════════
# FIRMS
# ══════════════════════════════════════════════════════════════════════════════

firms = APIRouter(prefix="/firms")


@firms.get("", response_model=dict, summary="รายการสำนักงานบัญชี")
async def list_firms(
    ctx: CTX,
    shared: SharedDB,
    active_only: bool = Query(True, description="แสดงเฉพาะที่ active"),
) -> dict:
    """ดึงรายการ Firm ทั้งหมด (superuser เท่านั้น)."""
    svc = FirmService(shared)
    firms_list = await svc.list_all(active_only=active_only)
    return ok([FirmOut.model_validate(f) for f in firms_list])


@firms.post(
    "",
    response_model=dict,
    status_code=status.HTTP_201_CREATED,
    summary="สร้างสำนักงานบัญชี",
)
async def create_firm(data: FirmCreate, shared: SharedDB) -> dict:
    """สร้าง Firm ใหม่ (superuser/system bootstrap)."""
    svc = FirmService(shared)
    firm = await svc.create(data)
    return ok(FirmOut.model_validate(firm), "สร้างสำนักงานบัญชีสำเร็จ")


@firms.get("/{firm_id}", response_model=dict, summary="ข้อมูลสำนักงานบัญชี")
async def get_firm(firm_id: int, ctx: CTX, shared: SharedDB) -> dict:
    svc = FirmService(shared)
    firm = await svc.get(firm_id)
    return ok(FirmOut.model_validate(firm))


@firms.put("/{firm_id}", response_model=dict, summary="แก้ไขสำนักงานบัญชี")
async def update_firm(
    firm_id: int,
    data: FirmUpdate,
    ctx: CTX,
    shared: SharedDB,
) -> dict:
    svc = FirmService(shared)
    firm = await svc.update(firm_id, data, ctx)
    return ok(FirmOut.model_validate(firm), "แก้ไขสำเร็จ")


# ══════════════════════════════════════════════════════════════════════════════
# COMPANIES
# ══════════════════════════════════════════════════════════════════════════════

companies = APIRouter(prefix="/companies")


@companies.get("", response_model=dict, summary="รายการกิจการที่มีสิทธิ์")
async def list_companies(
    ctx: CTX,
    shared: SharedDB,
    active_only: bool = Query(True),
) -> dict:
    """ดึงเฉพาะกิจการที่ user มีสิทธิ์เข้าถึง."""
    svc = CompanyService(shared)
    companies_list = await svc.list_companies(ctx, active_only=active_only)
    return ok([CompanyOut.model_validate(c) for c in companies_list])


@companies.post(
    "",
    response_model=dict,
    status_code=status.HTTP_201_CREATED,
    summary="สร้างกิจการใหม่",
    dependencies=[Depends(require_role(UserRole.FIRM_ADMIN))],
)
async def create_company(data: CompanyCreate, ctx: CTX, shared: SharedDB) -> dict:
    """
    สร้างกิจการใหม่ — firm_admin เท่านั้น

    - สร้าง HQ branch อัตโนมัติ
    - init company database
    - apply COA template ที่เลือก
    """
    svc = CompanyService(shared)
    company = await svc.create_company(data, ctx)
    return ok(CompanyOut.model_validate(company), "สร้างกิจการสำเร็จ")


@companies.get("/{company_id}", response_model=dict, summary="ข้อมูลกิจการ")
async def get_company(company_id: int, ctx: CTX, shared: SharedDB) -> dict:
    svc = CompanyService(shared)
    company = await svc.get(company_id, ctx)
    return ok(CompanyOut.model_validate(company))


@companies.put(
    "/{company_id}",
    response_model=dict,
    summary="แก้ไขข้อมูลกิจการ",
    dependencies=[Depends(require_role(UserRole.FIRM_ADMIN))],
)
async def update_company(
    company_id: int,
    data: CompanyUpdate,
    ctx: CTX,
    shared: SharedDB,
) -> dict:
    svc = CompanyService(shared)
    company = await svc.update(company_id, data, ctx)
    return ok(CompanyOut.model_validate(company), "แก้ไขสำเร็จ")


@companies.post(
    "/{company_id}/switch",
    response_model=SwitchCompanyOut,
    summary="สลับไปทำงานกับกิจการนี้",
)
async def switch_company(
    company_id: int,
    ctx: CTX,
    shared: SharedDB,
    branch_id: Optional[int] = Query(None, description="ระบุ branch_id หรือใช้ HQ"),
) -> SwitchCompanyOut:
    """
    เปลี่ยน context ไปยัง company ที่เลือก

    คืน token ใหม่พร้อม company_id + branch_id + role
    Client ต้องเก็บ token ใหม่นี้แทนอันเดิม
    """
    svc = CompanyService(shared)
    return await svc.switch_company(company_id, ctx, branch_id=branch_id)


# ══════════════════════════════════════════════════════════════════════════════
# BRANCHES
# ══════════════════════════════════════════════════════════════════════════════

branches = APIRouter(prefix="/companies/{company_id}/branches")


@branches.get("", response_model=dict, summary="รายการสาขา")
async def list_branches(
    company_id: int,
    ctx: CTX,
    shared: SharedDB,
    active_only: bool = Query(True),
) -> dict:
    svc = BranchService(shared)
    branch_list = await svc.list_branches(company_id, ctx, active_only=active_only)
    return ok([BranchOut.from_orm_branch(b) for b in branch_list])


@branches.post(
    "",
    response_model=dict,
    status_code=status.HTTP_201_CREATED,
    summary="สร้างสาขาใหม่",
)
async def create_branch(
    company_id: int,
    data: BranchCreate,
    ctx: CTX,
    shared: SharedDB,
) -> dict:
    svc = BranchService(shared)
    branch = await svc.create(company_id, data, ctx)
    return ok(BranchOut.from_orm_branch(branch), "สร้างสาขาสำเร็จ")


@branches.get("/{branch_id}", response_model=dict, summary="ข้อมูลสาขา")
async def get_branch(branch_id: int, company_id: int, ctx: CTX, shared: SharedDB) -> dict:
    svc = BranchService(shared)
    branch = await svc.get(branch_id, ctx)
    return ok(BranchOut.from_orm_branch(branch))


@branches.put("/{branch_id}", response_model=dict, summary="แก้ไขสาขา")
async def update_branch(
    branch_id: int,
    company_id: int,
    data: BranchUpdate,
    ctx: CTX,
    shared: SharedDB,
) -> dict:
    svc = BranchService(shared)
    branch = await svc.update(branch_id, data, ctx)
    return ok(BranchOut.from_orm_branch(branch), "แก้ไขสำเร็จ")


@branches.delete(
    "/{branch_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="ปิดใช้งานสาขา",
)
async def deactivate_branch(
    branch_id: int,
    company_id: int,
    ctx: CTX,
    shared: SharedDB,
) -> None:
    svc = BranchService(shared)
    await svc.deactivate(branch_id, ctx)


# ══════════════════════════════════════════════════════════════════════════════
# USERS
# ══════════════════════════════════════════════════════════════════════════════

users = APIRouter(prefix="/users")


@users.get("", response_model=dict, summary="รายการผู้ใช้")
async def list_users(
    ctx: CTX,
    shared: SharedDB,
    company_id: Optional[int] = Query(None, description="กรองตาม company"),
) -> dict:
    svc = UserService(shared)
    user_list = await svc.list_users(ctx, company_id=company_id)
    return ok([UserOut.model_validate(u) for u in user_list])


@users.post(
    "",
    response_model=dict,
    status_code=status.HTTP_201_CREATED,
    summary="สร้างผู้ใช้ใหม่",
    dependencies=[Depends(require_role(UserRole.FIRM_ADMIN))],
)
async def register_user(data: UserRegister, ctx: CTX, shared: SharedDB) -> dict:
    svc = UserService(shared)
    user = await svc.register(ctx.firm_id, data, ctx)
    return ok(UserOut.model_validate(user), "สร้างผู้ใช้สำเร็จ")


@users.get("/{user_id}", response_model=dict, summary="ข้อมูลผู้ใช้")
async def get_user(user_id: int, ctx: CTX, shared: SharedDB) -> dict:
    from sqlalchemy import select
    from app.platform.models import User

    result = await shared.execute(
        select(User).where(User.id == user_id, User.firm_id == ctx.firm_id)
    )
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(404, "ไม่พบผู้ใช้")
    return ok(UserOut.model_validate(user))


@users.post(
    "/{user_id}/assign",
    response_model=dict,
    summary="กำหนดสิทธิ์ user เข้า company",
    dependencies=[Depends(require_role(UserRole.FIRM_ADMIN))],
)
async def assign_company(
    user_id: int,
    data: AssignCompany,
    ctx: CTX,
    shared: SharedDB,
) -> dict:
    """กำหนด role ของ user ใน company (สร้างหรืออัปเดต)."""
    if data.user_id != user_id:
        raise HTTPException(400, "user_id ใน path และ body ต้องตรงกัน")
    svc = UserService(shared)
    perm = await svc.assign_company(data, ctx)
    return ok(PermissionOut.model_validate(perm), "กำหนดสิทธิ์สำเร็จ")


@users.post(
    "/{user_id}/revoke",
    response_model=dict,
    summary="ยกเลิกสิทธิ์ user",
    dependencies=[Depends(require_role(UserRole.FIRM_ADMIN))],
)
async def revoke_company(
    user_id: int,
    company_id: int,
    ctx: CTX,
    shared: SharedDB,
    branch_id: Optional[int] = Query(None),
) -> dict:
    svc = UserService(shared)
    await svc.revoke_company(user_id, company_id, ctx, branch_id=branch_id)
    return ok(None, "ยกเลิกสิทธิ์สำเร็จ")


@users.post("/{user_id}/change-password", response_model=dict, summary="เปลี่ยนรหัสผ่าน")
async def change_password(
    user_id: int,
    data: ChangePassword,
    ctx: CTX,
    shared: SharedDB,
) -> dict:
    svc = UserService(shared)
    await svc.change_password(user_id, data, ctx)
    return ok(None, "เปลี่ยนรหัสผ่านสำเร็จ")


@users.get(
    "/{user_id}/permissions",
    response_model=dict,
    summary="รายการสิทธิ์ของ user",
)
async def list_user_permissions(
    user_id: int,
    ctx: CTX,
    shared: SharedDB,
    company_id: Optional[int] = Query(None),
) -> dict:
    from sqlalchemy import select
    from app.platform.models import UserPermission

    stmt = select(UserPermission).where(
        UserPermission.user_id == user_id,
        UserPermission.is_active == True,  # noqa: E712
    )
    if company_id:
        stmt = stmt.where(UserPermission.company_id == company_id)

    result = await shared.execute(stmt)
    perms = result.scalars().all()
    return ok([PermissionOut.model_validate(p) for p in perms])


# ══════════════════════════════════════════════════════════════════════════════
# FISCAL YEARS
# ══════════════════════════════════════════════════════════════════════════════

from datetime import date as _date

fiscal_years = APIRouter(prefix="/companies/{company_id}/fiscal-years")


@fiscal_years.get("", response_model=dict, summary="รายการปีงบการเงิน")
async def list_fiscal_years(company_id: int, ctx: CTX, shared: SharedDB) -> dict:
    from sqlalchemy import select
    from app.platform.models import FiscalYear

    rows = await shared.scalars(
        select(FiscalYear).where(FiscalYear.company_id == company_id).order_by(FiscalYear.year.desc())
    )
    result = [
        {
            "id": r.id, "company_id": r.company_id, "year": r.year,
            "start_date": str(r.start_date), "end_date": str(r.end_date),
            "status": r.status, "is_locked": r.is_locked,
        }
        for r in rows.all()
    ]
    return ok(result)


class FiscalYearCreate(BaseModel):
    year: int
    start_date: str
    end_date: str


@fiscal_years.post("", response_model=dict, status_code=201, summary="สร้างปีงบการเงิน")
async def create_fiscal_year(company_id: int, data: FiscalYearCreate, ctx: CTX, shared: SharedDB) -> dict:
    from sqlalchemy import select
    from app.platform.models import FiscalYear

    existing = await shared.scalar(
        select(FiscalYear).where(FiscalYear.company_id == company_id, FiscalYear.year == data.year)
    )
    if existing:
        raise HTTPException(400, f"ปีงบ {data.year} มีอยู่แล้ว")

    fy = FiscalYear(
        company_id=company_id,
        year=data.year,
        start_date=_date.fromisoformat(data.start_date),
        end_date=_date.fromisoformat(data.end_date),
        status="active",
    )
    shared.add(fy)
    await shared.flush()
    return ok({"id": fy.id, "year": fy.year, "status": fy.status}, "สร้างปีงบสำเร็จ")


# ── Register all sub-routers ──────────────────────────────────────────────────

router.include_router(firms)
router.include_router(companies)
router.include_router(branches)
router.include_router(users)
router.include_router(fiscal_years)
