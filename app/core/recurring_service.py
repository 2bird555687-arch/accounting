"""Recurring Entry Service — จัดการรายการบัญชีที่เกิดซ้ำตามกำหนด."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Optional

from dateutil.relativedelta import relativedelta
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.context import AppContext, DrCr, JournalType
from app.core.engine import PostingEngine, JournalEntryInput, JournalLineInput
from app.core.models import ChartOfAccount, RecurringLine, RecurringTemplate


# ── Input / Output dataclasses ────────────────────────────────────────────────

@dataclass
class RecurringLineIn:
    account_code: str
    side: str  # DR | CR
    amount: Decimal
    description: Optional[str] = None


@dataclass
class RecurringTemplateIn:
    name: str
    journal_type: str  # GJ | CP | CR
    description: str
    frequency: str     # monthly | quarterly | yearly
    lines: list[RecurringLineIn]
    day_of_month: int = 1
    next_run_date: Optional[date] = None
    end_date: Optional[date] = None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _next_date(current: date, frequency: str, day: int) -> date:
    """คำนวณวันทำงานถัดไปตาม frequency."""
    if frequency == "monthly":
        nxt = current + relativedelta(months=1)
    elif frequency == "quarterly":
        nxt = current + relativedelta(months=3)
    else:  # yearly
        nxt = current + relativedelta(years=1)

    import calendar
    last_day = calendar.monthrange(nxt.year, nxt.month)[1]
    return nxt.replace(day=min(day, last_day))


# ── Service ───────────────────────────────────────────────────────────────────

async def create_template(
    data: RecurringTemplateIn,
    ctx: AppContext,
    db: AsyncSession,
) -> RecurringTemplate:
    """สร้าง recurring template พร้อม lines."""
    if not ctx.can_post:
        raise PermissionError("ไม่มีสิทธิ์สร้าง recurring template")

    import calendar
    first_run = data.next_run_date
    if first_run is None:
        today = ctx.period
        last_day = calendar.monthrange(today.year, today.month)[1]
        first_run = today.replace(day=min(data.day_of_month, last_day))

    tmpl = RecurringTemplate(
        name=data.name,
        journal_type=data.journal_type,
        description=data.description,
        frequency=data.frequency,
        day_of_month=data.day_of_month,
        branch_id=ctx.branch_id,
        company_id=ctx.company_id,
        created_by=ctx.user_id,
        is_active=True,
        next_run_date=first_run,
        end_date=data.end_date,
    )
    db.add(tmpl)
    await db.flush()

    for i, ln in enumerate(data.lines, start=1):
        coa = await db.scalar(
            select(ChartOfAccount).where(ChartOfAccount.code == ln.account_code)
        )
        if not coa:
            raise ValueError(f"ไม่พบบัญชี {ln.account_code}")
        dr = Decimal(str(ln.amount)) if ln.side.upper() == "DR" else Decimal(0)
        cr = Decimal(str(ln.amount)) if ln.side.upper() == "CR" else Decimal(0)
        db.add(RecurringLine(
            template_id=tmpl.id,
            line_no=i,
            account_id=coa.id,
            description=ln.description,
            debit_amount=dr,
            credit_amount=cr,
        ))

    return tmpl


async def list_templates(ctx: AppContext, db: AsyncSession) -> list[RecurringTemplate]:
    """ดู templates ทั้งหมดของบริษัท."""
    rows = await db.scalars(
        select(RecurringTemplate).where(
            RecurringTemplate.branch_id == ctx.branch_id,
            RecurringTemplate.is_active == True,
        ).order_by(RecurringTemplate.next_run_date)
    )
    return list(rows)


async def get_due_templates(
    ctx: AppContext,
    db: AsyncSession,
    as_of_date: date,
) -> list[RecurringTemplate]:
    """คืน templates ที่ถึงกำหนด run แล้ว."""
    rows = await db.scalars(
        select(RecurringTemplate).where(
            RecurringTemplate.branch_id == ctx.branch_id,
            RecurringTemplate.is_active == True,
            RecurringTemplate.next_run_date <= as_of_date,
        )
    )
    result = []
    for t in rows:
        if t.end_date and as_of_date > t.end_date:
            continue
        result.append(t)
    return result


async def execute_template(
    template_id: int,
    ctx: AppContext,
    db: AsyncSession,
) -> str:
    """Execute recurring template → post journal entry → อัปเดต next_run_date."""
    if not ctx.can_post:
        raise PermissionError("ไม่มีสิทธิ์")

    tmpl = await db.scalar(
        select(RecurringTemplate).where(RecurringTemplate.id == template_id)
    )
    if not tmpl:
        raise ValueError(f"ไม่พบ template id={template_id}")
    if not tmpl.is_active:
        raise ValueError("Template ถูกปิดใช้งานแล้ว")

    # โหลด lines พร้อม COA
    lines_orm = list(await db.scalars(
        select(RecurringLine).where(RecurringLine.template_id == template_id)
    ))

    entry_lines: list[JournalLineInput] = []
    for ln in sorted(lines_orm, key=lambda x: x.line_no):
        coa = await db.scalar(
            select(ChartOfAccount).where(ChartOfAccount.id == ln.account_id)
        )
        if not coa:
            raise ValueError(f"ไม่พบบัญชี account_id={ln.account_id}")
        if ln.debit_amount > 0:
            entry_lines.append(JournalLineInput(
                account_code=coa.code,
                side=DrCr.DR,
                amount=ln.debit_amount,
                description=ln.description,
            ))
        else:
            entry_lines.append(JournalLineInput(
                account_code=coa.code,
                side=DrCr.CR,
                amount=ln.credit_amount,
                description=ln.description,
            ))

    run_date = tmpl.next_run_date or ctx.period
    entry = JournalEntryInput(
        journal_type=JournalType(tmpl.journal_type),
        entry_date=run_date,
        description=f"[Recurring] {tmpl.description}",
        lines=entry_lines,
        source_module="recurring",
        source_id=tmpl.id,
    )
    journal_no = await PostingEngine(db).post(entry, ctx)

    # อัปเดต next_run_date
    tmpl.last_run_date = run_date
    tmpl.next_run_date = _next_date(run_date, tmpl.frequency, tmpl.day_of_month)
    if tmpl.end_date and tmpl.next_run_date > tmpl.end_date:
        tmpl.is_active = False

    return journal_no
