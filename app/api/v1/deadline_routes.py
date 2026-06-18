"""Deadline Tracker API Routes — กำหนดการยื่นภาษีและปิดงวด."""

from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.api.deps import CTX, SharedDB
from app.platform.deadline_tracker_service import (
    DeadlineInfo,
    get_deadlines,
    get_overdue,
    mark_filed,
)

router = APIRouter(prefix="/deadlines", tags=["Deadlines"])


class DeadlineOut(BaseModel):
    company_id: int
    year_month: str
    deadline_type: str
    due_date: date
    filed_date: Optional[date] = None
    status: str
    notes: Optional[str] = None
    deadline_id: Optional[int] = None
    days_remaining: Optional[int] = None

    model_config = {"from_attributes": True}


class MarkFiledReq(BaseModel):
    filed_date: date


def _to_out(d: DeadlineInfo) -> DeadlineOut:
    days = (d.due_date - date.today()).days if d.status not in ("filed", "waived") else None
    return DeadlineOut(
        company_id=d.company_id,
        year_month=d.year_month,
        deadline_type=d.deadline_type,
        due_date=d.due_date,
        filed_date=d.filed_date,
        status=d.status,
        notes=d.notes,
        deadline_id=d.deadline_id,
        days_remaining=days,
    )


@router.get("/{year_month}", response_model=list[DeadlineOut])
async def list_deadlines(
    year_month: str,
    ctx: CTX,
    shared: SharedDB,
    company_ids: Optional[str] = Query(None, description="comma-separated company IDs"),
):
    """ดูกำหนดการของ firm ในเดือนนั้น — รูปแบบ year_month: YYYY-MM."""
    ids: list[int] | None = None
    if company_ids:
        try:
            ids = [int(x.strip()) for x in company_ids.split(",")]
        except ValueError:
            raise HTTPException(status_code=400, detail="company_ids ต้องเป็นตัวเลขคั่นด้วย comma")

    deadlines = await get_deadlines(ctx.firm_id, year_month, shared, company_ids=ids)
    return [_to_out(d) for d in deadlines]


@router.get("/overdue/all", response_model=list[DeadlineOut])
async def list_overdue(ctx: CTX, shared: SharedDB):
    """ดูรายการที่เลยกำหนดทั้งหมดของ firm."""
    deadlines = await get_overdue(ctx.firm_id, shared)
    return [_to_out(d) for d in deadlines]


@router.post("/{deadline_id}/filed", response_model=DeadlineOut)
async def file_deadline(
    deadline_id: int,
    data: MarkFiledReq,
    ctx: CTX,
    shared: SharedDB,
):
    """บันทึกว่ายื่นแล้ว."""
    if not ctx.can_post:
        raise HTTPException(status_code=403, detail="ไม่มีสิทธิ์")
    try:
        dl = await mark_filed(deadline_id, data.filed_date, shared)
        return DeadlineOut(
            company_id=dl.company_id,
            year_month=dl.year_month,
            deadline_type=dl.deadline_type,
            due_date=dl.due_date,
            filed_date=dl.filed_date,
            status=dl.status,
            notes=dl.notes,
            deadline_id=dl.id,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
