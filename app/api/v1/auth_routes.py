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
from app.platform.models import User
from app.platform.user_service import LoginOut, UserLogin, UserOut, UserService

router = APIRouter(prefix="/auth", tags=["Auth"])


# ── Schemas ───────────────────────────────────────────────────────────────────

class RefreshRequest(BaseModel):
    refresh_token: str


class SwitchPeriodRequest(BaseModel):
    period: date  # เปลี่ยน active period (YYYY-MM-01)


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
