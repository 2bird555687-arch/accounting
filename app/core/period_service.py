"""Period Close/Reopen Service — ควบคุมการปิด/เปิดงวดบัญชี."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.context import AppContext, UserRole
from app.core.models import (
    AdjustingEntry,
    JournalEntry,
    Period,
    PeriodCloseLog,
    RecurringTemplate,
)
from app.modules.bank.models import BankReconciliation


@dataclass
class ChecklistItem:
    key: str
    label: str
    status: str       # ok | warning | blocking
    count: int = 0
    detail: str = ""


@dataclass
class CloseResult:
    success: bool
    period: str
    message: str
    blockers: list[ChecklistItem]


async def _get_period(period: date, db: AsyncSession) -> Period:
    p = await db.scalar(
        select(Period).where(
            Period.fiscal_year == period.year,
            Period.month == period.month,
        )
    )
    if not p:
        raise ValueError(f"ไม่พบงวด {period.year}/{period.month:02d}")
    return p


async def get_close_checklist(
    ctx: AppContext,
    db: AsyncSession,
    period: date,
) -> list[ChecklistItem]:
    """สร้าง checklist ก่อนปิดงวด."""
    p = await _get_period(period, db)
    items: list[ChecklistItem] = []

    # ── 1. Journal entries ที่ยังเป็น draft ──────────────────────────────────
    draft_count = await db.scalar(
        select(func.count()).select_from(JournalEntry).where(
            JournalEntry.period_id == p.id,
            JournalEntry.status == "draft",
        )
    ) or 0
    items.append(ChecklistItem(
        key="draft_entries",
        label="Journal entries ค้าง draft",
        status="blocking" if draft_count > 0 else "ok",
        count=draft_count,
        detail=f"มี {draft_count} รายการที่ยังไม่ post" if draft_count else "ไม่มีรายการค้าง",
    ))

    # ── 2. Recurring templates ที่ยังไม่ execute ──────────────────────────────
    due_recurring = list(await db.scalars(
        select(RecurringTemplate).where(
            RecurringTemplate.branch_id == ctx.branch_id,
            RecurringTemplate.is_active == True,
            RecurringTemplate.next_run_date <= p.end_date,
        )
    ))
    rec_count = len(due_recurring)
    items.append(ChecklistItem(
        key="recurring",
        label="Recurring entries ที่ยังไม่ execute",
        status="warning" if rec_count > 0 else "ok",
        count=rec_count,
        detail=f"มี {rec_count} template ที่ถึงกำหนด" if rec_count else "ครบทุกรายการ",
    ))

    # ── 3. Bank reconciliation ที่ยังค้าง ────────────────────────────────────
    unrecon = await db.scalar(
        select(func.count()).select_from(BankReconciliation).where(
            BankReconciliation.company_id == ctx.company_id,
            BankReconciliation.status != "completed",
            BankReconciliation.period_from >= p.start_date,
            BankReconciliation.period_to <= p.end_date,
        )
    ) or 0
    items.append(ChecklistItem(
        key="bank_recon",
        label="Bank reconciliation ที่ยังไม่เสร็จ",
        status="warning" if unrecon > 0 else "ok",
        count=unrecon,
        detail=f"มี {unrecon} recon ค้างอยู่" if unrecon else "Bank recon ครบแล้ว",
    ))

    # ── 4. Adjusting entries ที่ยังเป็น pending ──────────────────────────────
    pending_adj = await db.scalar(
        select(func.count()).select_from(AdjustingEntry).where(
            AdjustingEntry.period_id == p.id,
            AdjustingEntry.status == "pending",
        )
    ) or 0
    items.append(ChecklistItem(
        key="adjusting",
        label="Adjusting entries ที่ยังไม่ทำ",
        status="warning" if pending_adj > 0 else "ok",
        count=pending_adj,
        detail=f"มี {pending_adj} รายการปรับปรุงค้าง" if pending_adj else "ครบทุกรายการ",
    ))

    # ── 5. ลูกหนี้/เจ้าหนี้ที่เกินกำหนด ──────────────────────────────────────
    try:
        from app.modules.ar.models import ARInvoice
        from app.modules.ap.models import APInvoice as APBill
        overdue_ar = await db.scalar(
            select(func.count()).select_from(ARInvoice).where(
                ARInvoice.due_date < p.end_date,
                ARInvoice.status.in_(["posted", "partial"]),
            )
        ) or 0
        overdue_ap = await db.scalar(
            select(func.count()).select_from(APBill).where(
                APBill.due_date < p.end_date,
                APBill.status.in_(["posted", "partial"]),
            )
        ) or 0
        total_overdue = overdue_ar + overdue_ap
        items.append(ChecklistItem(
            key="overdue",
            label="ลูกหนี้/เจ้าหนี้เกินกำหนด",
            status="warning" if total_overdue > 0 else "ok",
            count=total_overdue,
            detail=f"AR {overdue_ar} / AP {overdue_ap} รายการ",
        ))
    except Exception:
        pass

    return items


async def close_period(
    ctx: AppContext,
    db: AsyncSession,
    period: date,
) -> CloseResult:
    """ปิดงวดบัญชี — ต้อง checklist ผ่านก่อน (blocking items = 0)."""
    if not ctx.can_approve:
        raise PermissionError("ต้องเป็น Accountant หรือ Firm Admin")

    p = await _get_period(period, db)
    if p.status != "open":
        raise ValueError(f"งวด {period.year}/{period.month:02d} สถานะ {p.status!r} แล้ว")

    checklist = await get_close_checklist(ctx, db, period)
    blockers = [c for c in checklist if c.status == "blocking"]

    if blockers:
        return CloseResult(
            success=False,
            period=f"{period.year}/{period.month:02d}",
            message="ไม่สามารถปิดงวดได้ มีรายการค้างอยู่",
            blockers=blockers,
        )

    p.status = "closed"
    p.closed_by = ctx.user_id
    from datetime import datetime, timezone
    p.closed_at = datetime.now(timezone.utc)
    p.notes = f"ปิดโดย user_id={ctx.user_id}"

    db.add(PeriodCloseLog(
        period_id=p.id,
        action="closed",
        user_id=ctx.user_id,
        user_role=str(ctx.user_role),
    ))

    return CloseResult(
        success=True,
        period=f"{period.year}/{period.month:02d}",
        message="ปิดงวดสำเร็จ",
        blockers=[],
    )


async def reopen_period(
    ctx: AppContext,
    db: AsyncSession,
    period: date,
    reason: str,
) -> bool:
    """เปิดงวดที่ปิดแล้ว — เฉพาะ FIRM_ADMIN เท่านั้น."""
    if ctx.user_role != UserRole.FIRM_ADMIN:
        raise PermissionError("เฉพาะ Firm Admin เท่านั้นที่สามารถเปิดงวดได้")

    p = await _get_period(period, db)
    if p.status == "locked":
        raise ValueError("งวดถูก lock แล้ว ไม่สามารถเปิดได้")
    if p.status == "open":
        raise ValueError("งวดยังเปิดอยู่")

    p.status = "open"
    p.notes = f"เปิดซ้ำโดย user_id={ctx.user_id}: {reason}"

    db.add(PeriodCloseLog(
        period_id=p.id,
        action="reopened",
        user_id=ctx.user_id,
        user_role=str(ctx.user_role),
        reason=reason,
    ))
    return True
