"""
Shared FastAPI dependencies — inject session + AppContext ทุก route

Usage::
    @router.get("/")
    async def endpoint(
        ctx: CTX,
        shared: SharedDB,
        company: CompanyDB,
    ): ...
"""

from __future__ import annotations

from typing import Annotated, AsyncGenerator

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.context import AppContext
from app.database import _shared_factory, get_session_factory
from app.platform.auth import get_app_context


# ── Session dependencies ──────────────────────────────────────────────────────

async def _shared_session() -> AsyncGenerator[AsyncSession, None]:
    async with _shared_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def _company_session(
    ctx: Annotated[AppContext, Depends(get_app_context)],
) -> AsyncGenerator[AsyncSession, None]:
    """Company-specific DB session — ใช้ company_id จาก AppContext."""
    db_url = settings.get_company_db_url(ctx.firm_id, ctx.company_id)
    factory = get_session_factory(db_url)
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


# ── Type aliases ──────────────────────────────────────────────────────────────

SharedDB = Annotated[AsyncSession, Depends(_shared_session)]
CompanyDB = Annotated[AsyncSession, Depends(_company_session)]
CTX = Annotated[AppContext, Depends(get_app_context)]
