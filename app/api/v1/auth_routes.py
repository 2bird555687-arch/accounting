"""Auth routes — login, logout, refresh, me."""

from __future__ import annotations

from datetime import date, timezone, datetime
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CTX, SharedDB
from app.api.responses import ok
from app.config import settings
from app.context import AppContext, UserRole
from app.platform.auth import (
    TokenPair,
    build_app_context,
    create_tokens,
    get_app_context,
    get_current_user,
    verify_access_token,
)
from app.platform.models import Company, FiscalYear, User, UserPermission
from app.platform.user_service import LoginOut, UserLogin, UserOut, UserService

router = APIRouter(prefix="/auth", tags=["Auth"])


# ── Schemas ───────────────────────────────────────────────────────────────────

class RefreshRequest(BaseModel):
    refresh_token: str


class SwitchPeriodRequest(BaseModel):
    period: date  # เปลี่ยน active period (YYYY-MM-01)


class SelectContextRequest(BaseModel):
    company_id: int
    fiscal_year_id: Optional[int] = None
    branch_id: Optional[int] = None  # None = ทุกสาขา


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post(
    "/login",
    response_model=LoginOut,
    summary="เข้าสู่ระบบ",
    responses={401: {"description": "username/password ไม่ถูกต้อง"}},
)
async def login(data: UserLogin, shared: SharedDB) -> LoginOut:
    """
    เข้าสู่ระบบด้วย username (หรือ email) + password

    - ถ้าระบุ `company_id` จะได้ token พร้อม context ทันที
    - ถ้าไม่ระบุ ให้เรียก `POST /companies/{id}/switch` ทีหลัง
    """
    svc = UserService(shared)
    return await svc.login(data)


@router.post(
    "/logout",
    summary="ออกจากระบบ",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def logout(ctx: CTX) -> None:
    """
    ออกจากระบบ (stateless JWT — client ต้องลบ token เอง)

    ใน production ควรเพิ่ม token blacklist ใน Redis
    """
    # JWT เป็น stateless — log action เท่านั้น
    # TODO: เพิ่ม revocation list ใน Redis
    return None


@router.post(
    "/refresh",
    response_model=dict,
    summary="ต่ออายุ access token",
    responses={401: {"description": "refresh token ไม่ถูกต้องหรือหมดอายุ"}},
)
async def refresh_token(body: RefreshRequest, shared: SharedDB) -> dict:
    """ใช้ refresh token แลกเป็น access token ใหม่."""
    try:
        payload = jwt.decode(
            body.refresh_token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM],
        )
        if payload.get("type") != "refresh":
            raise HTTPException(status_code=401, detail="ไม่ใช่ refresh token")

        user_id = int(payload["sub"])
        firm_id = int(payload["firm_id"])

    except (JWTError, KeyError, ValueError):
        raise HTTPException(status_code=401, detail="refresh token ไม่ถูกต้องหรือหมดอายุ")

    # โหลด user ตรวจ active
    result = await shared.execute(
        select(User).where(User.id == user_id, User.is_active == True)  # noqa: E712
    )
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=401, detail="ไม่พบผู้ใช้หรือถูกระงับ")

    # สร้าง access token ใหม่ — ใช้ claims เดิมจาก refresh payload
    # ดึง company context จาก token เดิม (refresh payload เก็บแค่ sub + firm_id)
    # client ต้องเรียก /companies/{id}/switch ถ้าต้องการ company context ใหม่
    from app.platform.auth import TokenClaims, create_access_token

    # กรณีไม่มี company context ใน refresh payload → ออก token แบบ no-company
    company_id = int(payload.get("company_id", 0))
    branch_id = int(payload.get("branch_id", 0))
    role = payload.get("role", user.default_role)
    period_str = payload.get("period", date.today().replace(day=1).isoformat())

    claims = TokenClaims(
        sub=str(user_id),
        firm_id=firm_id,
        company_id=company_id,
        branch_id=branch_id,
        role=role,
        period=period_str,
    )
    new_access = create_access_token(claims)

    return ok({
        "access_token": new_access,
        "token_type": "bearer",
        "expires_in": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    })


@router.get(
    "/me",
    response_model=dict,
    summary="ข้อมูลผู้ใช้ปัจจุบัน",
)
async def me(
    ctx: CTX,
    current_user: Annotated[User, Depends(get_current_user)],
) -> dict:
    """คืนข้อมูล user + AppContext ปัจจุบัน."""
    return ok({
        "user": UserOut.model_validate(current_user),
        "context": {
            "firm_id": ctx.firm_id,
            "company_id": ctx.company_id,
            "branch_id": ctx.branch_id,
            "user_role": str(ctx.user_role),
            "period": ctx.period.isoformat(),
            "fiscal_year": ctx.fiscal_year,
            "fiscal_month": ctx.fiscal_month,
            "permissions": {
                "can_post": ctx.can_post,
                "can_approve": ctx.can_approve,
                "can_close_period": ctx.can_close_period,
                "is_read_only": ctx.is_read_only,
            },
        },
    })


@router.post(
    "/switch-period",
    response_model=dict,
    summary="เปลี่ยน active period",
)
async def switch_period(body: SwitchPeriodRequest, ctx: CTX) -> dict:
    """
    เปลี่ยน period ที่ active ใน token

    ออก access token ใหม่พร้อม period ที่เลือก (วันต้องเป็นวันที่ 1)
    """
    if body.period.day != 1:
        raise HTTPException(
            status_code=400,
            detail="period ต้องเป็นวันที่ 1 ของเดือน เช่น 2026-01-01",
        )

    from app.platform.auth import TokenClaims, create_access_token

    claims = TokenClaims(
        sub=str(ctx.user_id),
        firm_id=ctx.firm_id,
        company_id=ctx.company_id,
        branch_id=ctx.branch_id,
        role=str(ctx.user_role),
        period=body.period.isoformat(),
    )
    new_token = create_access_token(claims)

    return ok({
        "access_token": new_token,
        "token_type": "bearer",
        "expires_in": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        "period": body.period.isoformat(),
    })


@router.get("/my-companies", response_model=dict, summary="รายการบริษัทที่ user เข้าได้")
async def my_companies(ctx: CTX, shared: SharedDB) -> dict:
    """คืนรายการ company + fiscal_years + branches ที่ user มีสิทธิ์เข้าถึง."""
    perms = await shared.scalars(
        select(UserPermission).where(
            UserPermission.user_id == ctx.user_id,
            UserPermission.is_active == True,  # noqa: E712
        )
    )
    company_ids = list({p.company_id for p in perms.all()})

    result = []
    for cid in company_ids:
        company = await shared.scalar(select(Company).where(Company.id == cid, Company.is_active == True))  # noqa: E712
        if not company:
            continue
        fy_rows = await shared.scalars(
            select(FiscalYear).where(FiscalYear.company_id == cid).order_by(FiscalYear.year.desc())
        )
        fiscal_years = [
            {"id": f.id, "year": f.year, "start_date": str(f.start_date),
             "end_date": str(f.end_date), "status": f.status}
            for f in fy_rows.all()
        ]
        result.append({
            "id": company.id, "code": company.code, "name": company.name,
            "entity_type": company.entity_type, "fiscal_year_start": company.fiscal_year_start,
            "fiscal_years": fiscal_years,
        })
    return ok(result)


@router.post("/select-context", response_model=dict, summary="เลือก context หลัง login")
async def select_context(body: SelectContextRequest, ctx: CTX, shared: SharedDB) -> dict:
    """เลือก company + fiscal_year + branch แล้วออก JWT ใหม่."""
    company = await shared.scalar(
        select(Company).where(Company.id == body.company_id, Company.is_active == True)  # noqa: E712
    )
    if not company:
        raise HTTPException(404, "ไม่พบบริษัท")

    # ตรวจสิทธิ์
    perm = await shared.scalar(
        select(UserPermission).where(
            UserPermission.user_id == ctx.user_id,
            UserPermission.company_id == body.company_id,
            UserPermission.is_active == True,  # noqa: E712
        )
    )
    if not perm and ctx.user_role != UserRole.FIRM_ADMIN:
        raise HTTPException(403, "ไม่มีสิทธิ์เข้า company นี้")

    # กำหนด period = วันแรกของเดือนปัจจุบัน
    today = date.today()
    period = date(today.year, today.month, 1)

    from app.platform.auth import TokenClaims, create_access_token
    claims = TokenClaims(
        sub=str(ctx.user_id),
        firm_id=ctx.firm_id,
        company_id=body.company_id,
        branch_id=body.branch_id or 1,
        role=perm.role if perm else str(ctx.user_role),
        period=period.isoformat(),
    )
    new_token = create_access_token(claims)
    return ok({
        "access_token": new_token,
        "token_type": "bearer",
        "company_id": body.company_id,
        "period": period.isoformat(),
    })


@router.post("/switch-context", response_model=dict, summary="สลับ company/branch")
async def switch_context(body: SelectContextRequest, ctx: CTX, shared: SharedDB) -> dict:
    """สลับ company หรือ branch โดยไม่ต้อง logout."""
    return await select_context(body, ctx, shared)
