"""Contact Master API Routes."""

from __future__ import annotations

from datetime import date
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import CTX, CompanyDB
from app.context import AppContext
from app.master.schemas import AgingBucket, ContactCreate, ContactOut, ContactUpdate
from app.master.contact_service import ContactService
from app.master.balance_tracker_service import BalanceTrackerService

router = APIRouter(prefix="/contacts", tags=["Contacts"])


@router.get("", response_model=list[ContactOut])
async def list_contacts(
    ctx: CTX, db: CompanyDB,
    contact_type: Optional[str] = None,
    active_only: bool = Query(True),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, le=500),
):
    return await ContactService.list_contacts(
        ctx, db, contact_type=contact_type, active_only=active_only, skip=skip, limit=limit
    )


@router.post("", response_model=ContactOut, status_code=201)
async def create_contact(data: ContactCreate, ctx: CTX, db: CompanyDB):
    try:
        return await ContactService.create_contact(data, ctx, db)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{contact_id}", response_model=ContactOut)
async def get_contact(contact_id: int, ctx: CTX, db: CompanyDB):
    try:
        return await ContactService.get_contact(contact_id, ctx, db)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.put("/{contact_id}", response_model=ContactOut)
async def update_contact(contact_id: int, data: ContactUpdate, ctx: CTX, db: CompanyDB):
    try:
        return await ContactService.update_contact(contact_id, data, ctx, db)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{contact_id}", status_code=204)
async def deactivate_contact(contact_id: int, ctx: CTX, db: CompanyDB):
    try:
        await ContactService.deactivate_contact(contact_id, ctx, db)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ── Aging ─────────────────────────────────────────────────────────────────────

@router.get("/aging/ar", response_model=list[AgingBucket])
async def aging_ar(
    ctx: CTX, db: CompanyDB,
    as_of_date: Optional[date] = None,
):
    return await BalanceTrackerService.get_aging_ar(ctx, db, as_of_date=as_of_date)


@router.get("/aging/ap", response_model=list[AgingBucket])
async def aging_ap(
    ctx: CTX, db: CompanyDB,
    as_of_date: Optional[date] = None,
):
    return await BalanceTrackerService.get_aging_ap(ctx, db, as_of_date=as_of_date)
