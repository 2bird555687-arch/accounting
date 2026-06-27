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


class CompanyBase(DeclarativeBase):
    """Shared Base สำหรับทุก model ใน company database.

    ทุก module (AR, AP, INV, FA, TAX, Master, OCR, Bank, Core) ต้องใช้ Base นี้
    เพื่อให้ metadata เดียวกัน — SQLAlchemy จะ resolve ForeignKey ข้าม-module ได้ถูกต้อง
    เมื่อ create_all ถูกเรียกครั้งเดียว.
    """
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

_shared_engine = _make_engine(settings.get_platform_db_url(), echo=settings.DB_ECHO)
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
    # Import all company-DB model modules so their Table objects register onto
    # CompanyBase.metadata before we call create_all once.  Order doesn't matter
    # because we resolve FKs in a single pass rather than module-by-module.
    import app.core.models  # noqa: F401
    import app.modules.ar.models  # noqa: F401
    import app.modules.ap.models  # noqa: F401
    import app.modules.inv.models  # noqa: F401
    import app.modules.fa.models  # noqa: F401
    import app.modules.tax.models  # noqa: F401
    import app.master.models  # noqa: F401
    import app.ocr.models  # noqa: F401
    import app.modules.bank.models  # noqa: F401

    db_url = settings.get_company_db_url(firm_id, company_id)
    engine = get_engine(db_url)
    async with engine.begin() as conn:
        await conn.run_sync(CompanyBase.metadata.create_all)
