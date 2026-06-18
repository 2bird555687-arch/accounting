"""Database engine factory — จัดการ connection pool แยกต่อ company."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, MappedColumn, mapped_column
from sqlalchemy import DateTime, func

from app.config import settings


class Base(DeclarativeBase):
    """Base class สำหรับ SQLAlchemy models ทั้งหมด."""
    pass


# ── Engine registry (connection pool per company) ─────────────────────────────

_engines: dict[str, AsyncEngine] = {}
_session_factories: dict[str, async_sessionmaker[AsyncSession]] = {}


def _make_engine(db_url: str, echo: bool = False) -> AsyncEngine:
    """สร้าง AsyncEngine พร้อม pool settings ที่เหมาะสม."""
    connect_args: dict[str, Any] = {}
    if db_url.startswith("sqlite"):
        connect_args["check_same_thread"] = False

    return create_async_engine(
        db_url,
        echo=echo,
        connect_args=connect_args,
        pool_pre_ping=True,
    )


def get_engine(db_url: str) -> AsyncEngine:
    """คืน (หรือสร้าง) engine สำหรับ db_url นั้น."""
    if db_url not in _engines:
        _engines[db_url] = _make_engine(db_url, echo=settings.DB_ECHO)
        _session_factories[db_url] = async_sessionmaker(
            _engines[db_url],
            expire_on_commit=False,
            class_=AsyncSession,
        )
    return _engines[db_url]


def get_session_factory(db_url: str) -> async_sessionmaker[AsyncSession]:
    """คืน session factory สำหรับ db_url นั้น."""
    get_engine(db_url)  # ensure registered
    return _session_factories[db_url]


# ── Convenience: shared (platform) database ──────────────────────────────────

_shared_engine = _make_engine(settings.DATABASE_URL, echo=settings.DB_ECHO)
_shared_factory = async_sessionmaker(
    _shared_engine,
    expire_on_commit=False,
    class_=AsyncSession,
)


@asynccontextmanager
async def get_shared_session() -> AsyncGenerator[AsyncSession, None]:
    """Context manager คืน session สำหรับ shared database."""
    async with _shared_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


@asynccontextmanager
async def get_company_session(firm_id: int, company_id: int) -> AsyncGenerator[AsyncSession, None]:
    """Context manager คืน session สำหรับ company database."""
    db_url = settings.get_company_db_url(firm_id, company_id)
    factory = get_session_factory(db_url)
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


# ── FastAPI dependency ────────────────────────────────────────────────────────

async def shared_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI Dependency สำหรับ shared session."""
    async with _shared_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_shared_db() -> None:
    """สร้างตาราง shared database (ใช้ตอน startup)."""
    from app.platform.models import Base as PlatformBase
    from app.shared.models import Base as SharedBase

    async with _shared_engine.begin() as conn:
        await conn.run_sync(PlatformBase.metadata.create_all)
        await conn.run_sync(SharedBase.metadata.create_all)


async def init_company_db(firm_id: int, company_id: int) -> None:
    """สร้างตาราง company database (เรียกตอนสร้าง company ใหม่)."""
    from app.core.models import Base as CoreBase
    from app.modules.ap.models import Base as APBase
    from app.modules.ar.models import Base as ARBase
    from app.modules.inv.models import Base as INVBase
    from app.modules.fa.models import Base as FABase
    from app.modules.tax.models import Base as TAXBase

    db_url = settings.get_company_db_url(firm_id, company_id)
    engine = get_engine(db_url)
    async with engine.begin() as conn:
        await conn.run_sync(CoreBase.metadata.create_all)
        await conn.run_sync(ARBase.metadata.create_all)
        await conn.run_sync(APBase.metadata.create_all)
        await conn.run_sync(INVBase.metadata.create_all)
        await conn.run_sync(FABase.metadata.create_all)
        await conn.run_sync(TAXBase.metadata.create_all)
