"""Deadline Tracker Service — ติดตามกำหนดการยื่นภาษีและปิดงวดรายบริษัท."""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.models import TaxDeadline


@dataclass
class DeadlineInfo:
    company_id: int
    year_month: str
    deadline_type: str
    due_date: date
    filed_date: date | None
    status: str
    notes: str | None
    deadline_id: int | None = None


_TYPE_LABELS = {
    "pp30": "ภพ.30 (VAT)",
    "pnd1": "ภ.ง.ด.1 (เงินเดือน)",
    "pnd3": "ภ.ง.ด.3 (บุคคลธรรมดา)",
    "pnd53": "ภ.ง.ด.53 (นิติบุคคล)",
    "sso": "ประกันสังคม",
    "period_close": "ปิดงวดบัญชี",
}


def _compute_standard_due(year_month: str, deadline_type: str) -> date:
    """คำนวณวันครบกำหนดมาตรฐาน."""
    year, month = int(year_month[:4]), int(year_month[5:7])
    # ยื่นเดือนถัดไป
    next_month = month + 1 if month < 12 else 1
    next_year = year if month < 12 else year + 1

    if deadline_type in ("pp30", "sso"):
        day = 15
    elif deadline_type in ("pnd1", "pnd3", "pnd53"):
        day = 7
    elif deadline_type == "period_close":
        # วันสุดท้ายของเดือนถัดไป
        day = calendar.monthrange(next_year, next_month)[1]
    else:
        day = 15

    last_day = calendar.monthrange(next_year, next_month)[1]
    return date(next_year, next_month, min(day, last_day))


async def _ensure_deadlines(
    firm_id: int,
    company_id: int,
    year_month: str,
    db: AsyncSession,
) -> list[TaxDeadline]:
    """สร้าง deadline records ถ้ายังไม่มี."""
    existing = list(await db.scalars(
        select(TaxDeadline).where(
            TaxDeadline.firm_id == firm_id,
            TaxDeadline.company_id == company_id,
            TaxDeadline.year_month == year_month,
        )
    ))
    existing_types = {d.deadline_type for d in existing}

    for dtype in ("pp30", "pnd1", "pnd3", "pnd53", "sso", "period_close"):
        if dtype not in existing_types:
            due = _compute_standard_due(year_month, dtype)
            dl = TaxDeadline(
                firm_id=firm_id,
                company_id=company_id,
                year_month=year_month,
                deadline_type=dtype,
                due_date=due,
                status="pending",
            )
            db.add(dl)
            existing.append(dl)

    await db.flush()
    return existing


async def get_deadlines(
    firm_id: int,
    year_month: str,
    db: AsyncSession,
    company_ids: list[int] | None = None,
) -> list[DeadlineInfo]:
    """ดูกำหนดการของ firm ทุก company หรือ company ที่ระบุ."""
    stmt = select(TaxDeadline).where(
        TaxDeadline.firm_id == firm_id,
        TaxDeadline.year_month == year_month,
    )
    if company_ids:
        stmt = stmt.where(TaxDeadline.company_id.in_(company_ids))

    rows = list(await db.scalars(stmt))

    # ถ้าไม่มีข้อมูล ให้ generate สำหรับแต่ละ company
    if not rows and company_ids:
        for cid in company_ids:
            rows.extend(await _ensure_deadlines(firm_id, cid, year_month, db))

    result = []
    today = date.today()
    for dl in rows:
        # อัปเดต status อัตโนมัติ
        if dl.status == "pending" and dl.due_date < today:
            dl.status = "overdue"

        result.append(DeadlineInfo(
            company_id=dl.company_id,
            year_month=dl.year_month,
            deadline_type=dl.deadline_type,
            due_date=dl.due_date,
            filed_date=dl.filed_date,
            status=dl.status,
            notes=dl.notes,
            deadline_id=dl.id,
        ))

    return sorted(result, key=lambda x: (x.company_id, x.due_date))


async def get_overdue(
    firm_id: int,
    db: AsyncSession,
) -> list[DeadlineInfo]:
    """คืนรายการที่เลยกำหนดแล้วทั้งหมด."""
    today = date.today()
    rows = list(await db.scalars(
        select(TaxDeadline).where(
            TaxDeadline.firm_id == firm_id,
            TaxDeadline.due_date < today,
            TaxDeadline.status.in_(["pending", "overdue"]),
        ).order_by(TaxDeadline.due_date)
    ))
    result = []
    for dl in rows:
        dl.status = "overdue"
        result.append(DeadlineInfo(
            company_id=dl.company_id,
            year_month=dl.year_month,
            deadline_type=dl.deadline_type,
            due_date=dl.due_date,
            filed_date=dl.filed_date,
            status="overdue",
            notes=dl.notes,
            deadline_id=dl.id,
        ))
    return result


async def mark_filed(
    deadline_id: int,
    filed_date: date,
    db: AsyncSession,
) -> TaxDeadline:
    """บันทึกว่ายื่นแล้ว."""
    dl = await db.scalar(select(TaxDeadline).where(TaxDeadline.id == deadline_id))
    if not dl:
        raise ValueError(f"ไม่พบ deadline id={deadline_id}")
    dl.filed_date = filed_date
    dl.status = "filed"
    return dl
