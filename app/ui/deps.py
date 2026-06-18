"""UI-specific dependencies — JWT from cookie instead of Bearer header."""

from __future__ import annotations

from typing import Annotated, Optional

from fastapi import Cookie, Depends, Request
from fastapi.responses import RedirectResponse
from starlette.exceptions import HTTPException

from app.context import AppContext
from app.platform.auth import build_app_context, verify_access_token
from app.platform.models import User
from app.database import shared_db
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


class UIRedirectException(Exception):
    def __init__(self, url: str):
        self.url = url


def _get_token_from_request(request: Request) -> Optional[str]:
    token = request.cookies.get("access_token")
    if not token:
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            token = auth[7:]
    return token


async def get_ui_context(request: Request) -> AppContext:
    token = _get_token_from_request(request)
    if not token:
        raise UIRedirectException("/login")
    try:
        claims = verify_access_token(token)
        return build_app_context(claims)
    except HTTPException:
        raise UIRedirectException("/login")


async def get_ui_user(
    request: Request,
    session: Annotated[AsyncSession, Depends(shared_db)],
) -> tuple[AppContext, User]:
    ctx = await get_ui_context(request)
    user = await session.scalar(
        select(User).where(User.id == ctx.user_id, User.is_active.is_(True))
    )
    if not user:
        raise UIRedirectException("/login")
    return ctx, user


UICtx = Annotated[AppContext, Depends(get_ui_context)]
