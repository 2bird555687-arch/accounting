"""JournalService — ค้นหาและอ่านรายการสมุดรายวัน."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Optional

from sqlalchemy import select, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.context import AppContext, JournalType
from app.core.models import (
    ChartOfAccount,
    JournalEntry as JournalEntryORM,
    JournalLine as JournalLineORM,
    Period,
)


# ── Result dataclasses ────────────────────────────────────────────────────────

@dataclass(frozen=True)
class JournalLineResult:
    """ผลการค้นหา — หนึ่งบรรทัดใน journal."""

    line_no: int
    account_code: str
    account_name: str
    description: Optional[str]
    debit_amount: Decimal
    credit_amount: Decimal
    tax_rate: Optional[Decimal]
    tax_base_amount: Optional[Decimal]
    cost_center: Optional[str]


@dataclass(frozen=True)
class JournalEntryResult:
    """ผลการค้นหา — header + lines ของรายการบัญชี."""

    id: int
    entry_no: str
    journal_type: str
    entry_date: date
    description: str
    reference: Optional[str]
    status: str
    is_reversing: bool
    reversed_entry_id: Optional[int]
    source_module: Optional[str]
    source_id: Optional[int]
    branch_id: int
    user_id: int
    period_fiscal_year: int
    period_month: int
    lines: list[JournalLineResult] = field(default_factory=list)

    @property
    def total_debit(self) -> Decimal:
        return sum(ln.debit_amount for ln in self.lines)

    @property
    def total_credit(self) -> Decimal:
        return sum(ln.credit_amount for ln in self.lines)


# ── Filter ────────────────────────────────────────────────────────────────────

@dataclass
class JournalFilter:
    """ตัวกรองสำหรับค้นหารายการ."""

    date_from: Optional[date] = None
    date_to: Optional[date] = None
    journal_type: Optional[JournalType] = None
    status: Optional[str] = None            # draft | posted | reversed
    reference: Optional[str] = None
    account_code: Optional[str] = None      # กรองเฉพาะ entry ที่มีบัญชีนี้
    source_module: Optional[str] = None
    source_id: Optional[int] = None
    branch_id: Optional[int] = None
    description_contains: Optional[str] = None
    limit: int = 100
    offset: int = 0


# ── Service ───────────────────────────────────────────────────────────────────

class JournalService:
    """
    บริการอ่านข้อมูลสมุดรายวัน

    ไม่มี write method — เขียนผ่าน PostingEngine เท่านั้น
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_ref(
        self, entry_no: str, ctx: AppContext
    ) -> Optional[JournalEntryResult]:
        """
        ค้นหารายการด้วยเลขที่รายการ

        Args:
            entry_no: เช่น "GJ202601-0001"
            ctx: AppContext (ใช้ตรวจสิทธิ์ branch)

        Returns:
            JournalEntryResult หรือ None ถ้าไม่พบ
        """
        stmt = (
            select(JournalEntryORM)
            .options(
                selectinload(JournalEntryORM.lines).selectinload(JournalLineORM.account),
                selectinload(JournalEntryORM.period),
            )
            .where(JournalEntryORM.entry_no == entry_no)
        )
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()
        if orm is None:
            return None

        return self._to_result(orm)

    async def get_by_id(
        self, entry_id: int, ctx: AppContext
    ) -> Optional[JournalEntryResult]:
        """ค้นหารายการด้วย id."""
        stmt = (
            select(JournalEntryORM)
            .options(
                selectinload(JournalEntryORM.lines).selectinload(JournalLineORM.account),
                selectinload(JournalEntryORM.period),
            )
            .where(JournalEntryORM.id == entry_id)
        )
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()
        return self._to_result(orm) if orm else None

    async def search(
        self, ctx: AppContext, filters: JournalFilter
    ) -> list[JournalEntryResult]:
        """
        ค้นหารายการตาม filter

        Returns:
            list ของ JournalEntryResult เรียงตาม entry_date DESC, entry_no DESC
        """
        stmt = (
            select(JournalEntryORM)
            .options(
                selectinload(JournalEntryORM.lines).selectinload(JournalLineORM.account),
                selectinload(JournalEntryORM.period),
            )
            .join(Period, JournalEntryORM.period_id == Period.id)
        )

        conditions = []

        if filters.date_from:
            conditions.append(JournalEntryORM.entry_date >= filters.date_from)
        if filters.date_to:
            conditions.append(JournalEntryORM.entry_date <= filters.date_to)
        if filters.journal_type:
            conditions.append(
                JournalEntryORM.journal_type == str(filters.journal_type)
            )
        if filters.status:
            conditions.append(JournalEntryORM.status == filters.status)
        if filters.reference:
            conditions.append(
                JournalEntryORM.reference.ilike(f"%{filters.reference}%")
            )
        if filters.source_module:
            conditions.append(JournalEntryORM.source_module == filters.source_module)
        if filters.source_id is not None:
            conditions.append(JournalEntryORM.source_id == filters.source_id)
        if filters.branch_id is not None:
            conditions.append(JournalEntryORM.branch_id == filters.branch_id)
        if filters.description_contains:
            conditions.append(
                JournalEntryORM.description.ilike(f"%{filters.description_contains}%")
            )

        # กรองตาม account_code — ต้องมี subquery
        if filters.account_code:
            acc_stmt = select(ChartOfAccount.id).where(
                ChartOfAccount.code == filters.account_code
            )
            acc_result = await self._session.execute(acc_stmt)
            acc_id = acc_result.scalar_one_or_none()
            if acc_id:
                line_entry_ids = select(JournalLineORM.entry_id).where(
                    JournalLineORM.account_id == acc_id
                )
                conditions.append(JournalEntryORM.id.in_(line_entry_ids))
            else:
                return []  # ไม่มีบัญชีนี้ = ไม่มีผล

        if conditions:
            stmt = stmt.where(and_(*conditions))

        stmt = (
            stmt.order_by(
                JournalEntryORM.entry_date.desc(),
                JournalEntryORM.entry_no.desc(),
            )
            .offset(filters.offset)
            .limit(min(filters.limit, 500))  # hard cap
        )

        result = await self._session.execute(stmt)
        orms = result.scalars().unique().all()
        return [self._to_result(orm) for orm in orms]

    async def get_by_source(
        self,
        source_module: str,
        source_id: int,
        ctx: AppContext,
    ) -> list[JournalEntryResult]:
        """ดึงรายการบัญชีทั้งหมดที่สร้างจาก module record หนึ่ง."""
        f = JournalFilter(source_module=source_module, source_id=source_id, limit=200)
        return await self.search(ctx, f)

    async def count(self, ctx: AppContext, filters: JournalFilter) -> int:
        """นับจำนวนรายการตาม filter (สำหรับ pagination)."""
        stmt = (
            select(JournalEntryORM.id)
            .join(Period, JournalEntryORM.period_id == Period.id)
        )
        if filters.date_from:
            stmt = stmt.where(JournalEntryORM.entry_date >= filters.date_from)
        if filters.date_to:
            stmt = stmt.where(JournalEntryORM.entry_date <= filters.date_to)
        if filters.journal_type:
            stmt = stmt.where(
                JournalEntryORM.journal_type == str(filters.journal_type)
            )
        if filters.status:
            stmt = stmt.where(JournalEntryORM.status == filters.status)

        count_stmt = select(JournalEntryORM.id).where(
            JournalEntryORM.id.in_(stmt)
        )
        result = await self._session.execute(count_stmt)
        return len(result.scalars().all())

    # ── Converter ─────────────────────────────────────────────────────────────

    def _to_result(self, orm: JournalEntryORM) -> JournalEntryResult:
        lines = [
            JournalLineResult(
                line_no=ln.line_no,
                account_code=ln.account.code,
                account_name=ln.account.name,
                description=ln.description,
                debit_amount=ln.debit_amount,
                credit_amount=ln.credit_amount,
                tax_rate=ln.tax_rate,
                tax_base_amount=ln.tax_base_amount,
                cost_center=ln.cost_center,
            )
            for ln in sorted(orm.lines, key=lambda x: x.line_no)
        ]
        return JournalEntryResult(
            id=orm.id,
            entry_no=orm.entry_no,
            journal_type=orm.journal_type,
            entry_date=orm.entry_date,
            description=orm.description,
            reference=orm.reference,
            status=orm.status,
            is_reversing=orm.is_reversing,
            reversed_entry_id=orm.reversed_entry_id,
            source_module=orm.source_module,
            source_id=orm.source_id,
            branch_id=orm.branch_id,
            user_id=orm.user_id,
            period_fiscal_year=orm.period.fiscal_year,
            period_month=orm.period.month,
            lines=lines,
        )
