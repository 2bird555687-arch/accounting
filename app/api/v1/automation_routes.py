"""Automation API Routes — Recurring, Adjusting, Period Close."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Annotated, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.api.deps import CTX, CompanyDB
from app.core import adjusting_service, recurring_service, period_service

router = APIRouter(tags=["Automation"])


# ── Recurring Templates ───────────────────────────────────────────────────────

class RecurringLineReq(BaseModel):
    account_code: str
    side: str  # DR | CR
    amount: Decimal
    description: Optional[str] = None


class RecurringTemplateReq(BaseModel):
    name: str
    journal_type: str = "GJ"
    description: str
    frequency: str  # monthly | quarterly | yearly
    lines: list[RecurringLineReq]
    day_of_month: int = 1
    next_run_date: Optional[date] = None
    end_date: Optional[date] = None


class RecurringTemplateOut(BaseModel):
    id: int
    name: str
    journal_type: str
    description: str
    frequency: str
    day_of_month: int
    is_active: bool
    last_run_date: Optional[date]
    next_run_date: Optional[date]
    end_date: Optional[date]

    model_config = {"from_attributes": True}


@router.get("/recurring", response_model=list[RecurringTemplateOut])
async def list_recurring(ctx: CTX, db: CompanyDB):
    rows = await recurring_service.list_templates(ctx, db)
    return [RecurringTemplateOut.model_validate(r) for r in rows]


@router.post("/recurring", response_model=RecurringTemplateOut, status_code=201)
async def create_recurring(data: RecurringTemplateReq, ctx: CTX, db: CompanyDB):
    try:
        tmpl = await recurring_service.create_template(
            recurring_service.RecurringTemplateIn(
                name=data.name,
                journal_type=data.journal_type,
                description=data.description,
                frequency=data.frequency,
                lines=[
                    recurring_service.RecurringLineIn(
                        account_code=ln.account_code,
                        side=ln.side,
                        amount=ln.amount,
                        description=ln.description,
                    )
                    for ln in data.lines
                ],
                day_of_month=data.day_of_month,
                next_run_date=data.next_run_date,
                end_date=data.end_date,
            ),
            ctx, db,
        )
        return RecurringTemplateOut.model_validate(tmpl)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/recurring/due", response_model=list[RecurringTemplateOut])
async def get_due_recurring(
    ctx: CTX, db: CompanyDB,
    as_of: date = Query(default_factory=date.today),
):
    rows = await recurring_service.get_due_templates(ctx, db, as_of)
    return [RecurringTemplateOut.model_validate(r) for r in rows]


@router.post("/recurring/{template_id}/execute")
async def execute_recurring(template_id: int, ctx: CTX, db: CompanyDB):
    try:
        journal_no = await recurring_service.execute_template(template_id, ctx, db)
        return {"journal_no": journal_no, "message": "Execute สำเร็จ"}
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ── Adjusting Entries ─────────────────────────────────────────────────────────

class AdjustingItemOut(BaseModel):
    item_type: str
    description: str
    amount: Decimal
    status: str
    source_id: Optional[int] = None
    journal_no: Optional[str] = None


class AdjustmentReq(BaseModel):
    item_type: str
    description: str
    amount: Decimal
    debit_account: str
    credit_account: str
    source_id: Optional[int] = None


@router.get("/adjusting", response_model=list[AdjustingItemOut])
async def get_adjusting_checklist(
    ctx: CTX, db: CompanyDB,
    period: Optional[date] = None,
):
    p = period or ctx.period
    items = await adjusting_service.get_checklist(ctx, db, p)
    return [
        AdjustingItemOut(
            item_type=i.item_type,
            description=i.description,
            amount=i.amount,
            status=i.status,
            source_id=i.source_id,
            journal_no=i.journal_no,
        )
        for i in items
    ]


@router.post("/adjusting", status_code=201)
async def post_adjusting(data: AdjustmentReq, ctx: CTX, db: CompanyDB):
    try:
        journal_no = await adjusting_service.post_adjustment(
            adjusting_service.AdjustmentIn(
                item_type=data.item_type,
                description=data.description,
                amount=data.amount,
                debit_account=data.debit_account,
                credit_account=data.credit_account,
                source_id=data.source_id,
            ),
            ctx, db,
        )
        return {"journal_no": journal_no, "message": "บันทึก adjusting entry สำเร็จ"}
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ── Period Close ──────────────────────────────────────────────────────────────

class ChecklistItemOut(BaseModel):
    key: str
    label: str
    status: str
    count: int
    detail: str


class ReopenReq(BaseModel):
    reason: str


@router.get("/period/{year}/{month}/checklist", response_model=list[ChecklistItemOut])
async def period_close_checklist(year: int, month: int, ctx: CTX, db: CompanyDB):
    try:
        p = date(year, month, 1)
        items = await period_service.get_close_checklist(ctx, db, p)
        return [ChecklistItemOut(**vars(i)) for i in items]
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/period/{year}/{month}/close")
async def close_period(year: int, month: int, ctx: CTX, db: CompanyDB):
    try:
        result = await period_service.close_period(ctx, db, date(year, month, 1))
        if not result.success:
            raise HTTPException(status_code=400, detail={
                "message": result.message,
                "blockers": [vars(b) for b in result.blockers],
            })
        return {"success": True, "period": result.period, "message": result.message}
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/period/{year}/{month}/reopen")
async def reopen_period(year: int, month: int, data: ReopenReq, ctx: CTX, db: CompanyDB):
    try:
        await period_service.reopen_period(ctx, db, date(year, month, 1), data.reason)
        return {"success": True, "message": f"เปิดงวด {year}/{month:02d} สำเร็จ"}
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
