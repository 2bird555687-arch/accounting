"""
Auth Layer — JWT, bcrypt, AppContext middleware

Flow:
  Login → create_tokens() → access_token + refresh_token
  Request → bearer token → verify_access_token() → build_app_context() → AppContext
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Annotated, Optional

import bcrypt as _bcrypt
from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import ExpiredSignatureError, JWTError, jwt
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.context import AppContext, UserRole
from app.database import shared_db
from app.platform.models import Company, User, UserPermission


# ── Password hashing ──────────────────────────────────────────────────────────

def hash_password(plain: str) -> str:
    """Hash รหัสผ่านด้วย bcrypt."""
    return _bcrypt.hashpw(plain.encode(), _bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    """ตรวจรหัสผ่าน — คืน True ถ้าตรง."""
    try:
        return _bcrypt.checkpw(plain.encode(), hashed.encode())
    except Exception:
        return False


# ── Token schemas ─────────────────────────────────────────────────────────────

class TokenPair(BaseModel):
    """คู่ access_token + refresh_token."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int  # วินาที


class TokenClaims(BaseModel):
    """Claims ใน JWT payload."""

    sub: str                    # user_id (str)
    firm_id: int
    company_id: int
    branch_id: int
    role: str
    period: str                 # YYYY-MM-DD
    jti: Optional[str] = None  # JWT ID สำหรับ revocation


# ── Token operations ──────────────────────────────────────────────────────────

def create_access_token(claims: TokenClaims) -> str:
    """สร้าง JWT access token — อายุตามค่า ACCESS_TOKEN_EXPIRE_MINUTES."""
    expire = datetime.now(tz=timezone.utc) + timedelta(
        minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
    )
    payload = claims.model_dump(exclude={"jti"})  # jti=None ทำให้ jose reject
    payload["exp"] = expire
    payload["type"] = "access"
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def create_refresh_token(claims: TokenClaims) -> str:
    """สร้าง JWT refresh token — อายุตามค่า REFRESH_TOKEN_EXPIRE_DAYS."""
    expire = datetime.now(tz=timezone.utc) + timedelta(
        days=settings.REFRESH_TOKEN_EXPIRE_DAYS
    )
    payload = {
        "sub": claims.sub,
        "firm_id": claims.firm_id,
        "exp": expire,
        "type": "refresh",
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def create_tokens(
    user_id: int,
    firm_id: int,
    company_id: int,
    branch_id: int,
    role: UserRole,
    period: date,
) -> TokenPair:
    """สร้าง access + refresh token พร้อมกัน."""
    claims = TokenClaims(
        sub=str(user_id),
        firm_id=firm_id,
        company_id=company_id,
        branch_id=branch_id,
        role=str(role),
        period=period.isoformat(),
    )
    return TokenPair(
        access_token=create_access_token(claims),
        refresh_token=create_refresh_token(claims),
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


def verify_access_token(token: str) -> TokenClaims:
    """
    Decode และตรวจ access token

    Raises:
        HTTPException 401: token ไม่ถูกต้องหรือหมดอายุ
    """
    try:
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
        )
        if payload.get("type") != "access":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="token type ไม่ถูกต้อง ต้องเป็น access token",
            )
        return TokenClaims(**payload)
    except ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="token หมดอายุ กรุณาเข้าสู่ระบบใหม่",
        )
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="token ไม่ถูกต้อง",
        )


def build_app_context(claims: TokenClaims) -> AppContext:
    """แปลง TokenClaims → AppContext."""
    period_date = date.fromisoformat(claims.period)
    return AppContext(
        firm_id=claims.firm_id,
        company_id=claims.company_id,
        branch_id=claims.branch_id,
        user_id=int(claims.sub),
        user_role=UserRole(claims.role),
        period=period_date,
    )


# ── FastAPI dependencies ──────────────────────────────────────────────────────

_bearer = HTTPBearer(auto_error=False)


async def get_current_claims(
    request: Request,
    credentials: Annotated[
        Optional[HTTPAuthorizationCredentials], Depends(_bearer)
    ] = None,
) -> TokenClaims:
    """FastAPI Dependency: ดึง TokenClaims จาก Bearer token หรือ cookie.

    ลำดับ:
      1. Authorization: Bearer <token>  (API clients / HTMX hx-headers)
      2. Cookie: access_token            (fallback สำหรับ browser session)
    """
    token: Optional[str] = None

    if credentials is not None:
        token = credentials.credentials
    else:
        # fallback: อ่านจาก httpOnly cookie (HTMX requests จาก browser)
        token = request.cookies.get("access_token")

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="กรุณาเข้าสู่ระบบก่อน",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return verify_access_token(token)


async def get_app_context(
    claims: Annotated[TokenClaims, Depends(get_current_claims)],
) -> AppContext:
    """
    FastAPI Dependency: คืน AppContext สำหรับทุก request

    Usage::
        @router.get("/")
        async def endpoint(ctx: Annotated[AppContext, Depends(get_app_context)]):
            ...
    """
    return build_app_context(claims)


async def get_current_user(
    claims: Annotated[TokenClaims, Depends(get_current_claims)],
    session: Annotated[AsyncSession, Depends(shared_db)],
) -> User:
    """FastAPI Dependency: คืน User ORM object ปัจจุบัน."""
    stmt = select(User).where(
        User.id == int(claims.sub),
        User.is_active == True,  # noqa: E712
    )
    result = await session.execute(stmt)
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="ไม่พบผู้ใช้หรือถูกระงับการใช้งาน",
        )
    return user


# ── Role guards ────────────────────────────────────────────────────────────────

def require_role(*roles: UserRole):
    """
    Dependency factory ตรวจ role

    Usage::
        @router.post("/", dependencies=[Depends(require_role(UserRole.FIRM_ADMIN))])
        async def admin_only(): ...
    """
    async def _check(ctx: Annotated[AppContext, Depends(get_app_context)]) -> AppContext:
        if ctx.user_role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"ต้องการสิทธิ์: {', '.join(str(r) for r in roles)} "
                    f"(ปัจจุบัน: {ctx.user_role})"
                ),
            )
        return ctx
    return _check


def require_can_post(ctx: Annotated[AppContext, Depends(get_app_context)]) -> AppContext:
    """Dependency: ต้องมีสิทธิ์บันทึกรายการบัญชี."""
    if not ctx.can_post:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="ไม่มีสิทธิ์บันทึกรายการบัญชี",
        )
    return ctx
