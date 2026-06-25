"""Report API Routes — งบการเงินครบชุด."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select

from app.api.deps import CTX, CompanyDB
from decimal import Decimal

router = APIRouter(prefix="/reports", tags=["Reports"])


def _export(report, fmt: str, title: str) -> Response:
    if fmt == "pdf":
        try:
            data = report.to_pdf(title=title)
            return Response(content=data, media_type="application/pdf",
                            headers={"Content-Disposition": f'attachment; filename="{title}.pdf"'})
        except ImportError as e:
            raise HTTPException(status_code=501, detail=str(e))
    if fmt == "excel":
        try:
            data = report.to_excel(sheet_name=title)
            return Response(
                content=data,
                media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                headers={"Content-Disposition": f'attachment; filename="{title}.xlsx"'},
            )
        except ImportError as e:
            raise HTTPException(status_code=501, detail=str(e))
    raise HTTPException(status_code=400, detail="format ต้องเป็น pdf หรือ excel")


# ── Trial Balance ─────────────────────────────────────────────────────────────

@router.get("/trial-balance/{year}/{month}")
async def trial_balance(
    year: int, month: int,
    ctx: CTX, db: CompanyDB,
    branch_ids: Optional[str] = Query(None),
    fmt: Optional[str] = Query(None, description="pdf | excel"),
):
    from app.reports import trial_balance as tb
    branches = [int(x) for x in branch_ids.split(",")] if branch_ids else None
    try:
        report = await tb.generate(ctx, db, year, month, branch_ids=branches)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    if fmt:
        return _export(report, fmt, f"TrialBalance_{year}_{month:02d}")
    return report.model_dump()


# ── Balance Sheet ─────────────────────────────────────────────────────────────

@router.get("/balance-sheet")
async def balance_sheet(
    ctx: CTX, db: CompanyDB,
    as_of: date = Query(default_factory=date.today),
    branch_ids: Optional[str] = Query(None),
    fmt: Optional[str] = Query(None),
):
    from app.reports import balance_sheet as bs
    branches = [int(x) for x in branch_ids.split(",")] if branch_ids else None
    try:
        report = await bs.generate(ctx, db, as_of, branch_ids=branches)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    if fmt:
        return _export(report, fmt, f"BalanceSheet_{as_of}")
    return report.model_dump()


# ── Income Statement ──────────────────────────────────────────────────────────

@router.get("/income-statement")
async def income_statement(
    ctx: CTX, db: CompanyDB,
    date_from: date = Query(...),
    date_to: date = Query(...),
    branch_ids: Optional[str] = Query(None),
    compare_prior_year: bool = Query(False),
    fmt: Optional[str] = Query(None),
):
    from app.reports import income_statement as ist
    branches = [int(x) for x in branch_ids.split(",")] if branch_ids else None
    try:
        report = await ist.generate(ctx, db, date_from, date_to,
                                     branch_ids=branches, compare_prior_year=compare_prior_year)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    if fmt:
        return _export(report, fmt, f"P&L_{date_from}_{date_to}")
    return report.model_dump()


# ── Cash Flow ─────────────────────────────────────────────────────────────────

@router.get("/cashflow")
async def cashflow(
    ctx: CTX, db: CompanyDB,
    date_from: date = Query(...),
    date_to: date = Query(...),
    branch_ids: Optional[str] = Query(None),
    fmt: Optional[str] = Query(None),
):
    from app.reports import cashflow as cf
    branches = [int(x) for x in branch_ids.split(",")] if branch_ids else None
    try:
        report = await cf.generate(ctx, db, date_from, date_to, branch_ids=branches)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    if fmt:
        return _export(report, fmt, f"CashFlow_{date_from}_{date_to}")
    return report.model_dump()


# ── Aging ─────────────────────────────────────────────────────────────────────

@router.get("/aging/ar")
async def ar_aging(
    ctx: CTX, db: CompanyDB,
    as_of: date = Query(default_factory=date.today),
    branch_ids: Optional[str] = Query(None),
    fmt: Optional[str] = Query(None),
):
    from app.reports import aging
    branches = [int(x) for x in branch_ids.split(",")] if branch_ids else None
    report = await aging.ar_aging(ctx, db, as_of, branch_ids=branches)
    if fmt:
        return _export(report, fmt, f"AR_Aging_{as_of}")
    return report.model_dump()


@router.get("/aging/ap")
async def ap_aging(
    ctx: CTX, db: CompanyDB,
    as_of: date = Query(default_factory=date.today),
    branch_ids: Optional[str] = Query(None),
    fmt: Optional[str] = Query(None),
):
    from app.reports import aging
    branches = [int(x) for x in branch_ids.split(",")] if branch_ids else None
    report = await aging.ap_aging(ctx, db, as_of, branch_ids=branches)
    if fmt:
        return _export(report, fmt, f"AP_Aging_{as_of}")
    return report.model_dump()


# ── Budget vs Actual ──────────────────────────────────────────────────────────

class BudgetSetReq(BaseModel):
    account_code: str
    amount: Decimal


@router.get("/budget-actual/{year}/{month}")
async def budget_actual(
    year: int, month: int,
    ctx: CTX, db: CompanyDB,
    branch_ids: Optional[str] = Query(None),
    fmt: Optional[str] = Query(None),
):
    from app.reports import budget_actual as ba
    branches = [int(x) for x in branch_ids.split(",")] if branch_ids else None
    try:
        report = await ba.generate(ctx, db, year, month, branch_ids=branches)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    if fmt:
        return _export(report, fmt, f"Budget_{year}_{month:02d}")
    return report.model_dump()


@router.post("/budget/{year}/{month}", status_code=201)
async def set_budget(
    year: int, month: int,
    data: BudgetSetReq,
    ctx: CTX, db: CompanyDB,
):
    from app.reports import budget_actual as ba
    try:
        bi = await ba.set_budget(ctx, db, year, month, data.account_code, data.amount)
        return {"account_code": data.account_code, "amount": float(data.amount), "year": year, "month": month}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ── Tax Reports ───────────────────────────────────────────────────────────────

@router.get("/tax/pp30/{year}/{month}")
async def tax_pp30(
    year: int, month: int,
    ctx: CTX, db: CompanyDB,
    fmt: Optional[str] = Query(None),
):
    from app.reports import tax_report
    try:
        report = await tax_report.pp30(ctx, db, year, month)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    if fmt:
        return _export(report, fmt, f"PP30_{year}_{month:02d}")
    return report.model_dump()


@router.get("/tax/pnd1/{year}/{month}")
async def tax_pnd1(
    year: int, month: int,
    ctx: CTX, db: CompanyDB,
    fmt: Optional[str] = Query(None),
):
    from app.reports import tax_report
    try:
        report = await tax_report.pnd1(ctx, db, year, month)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    if fmt:
        return _export(report, fmt, f"PND1_{year}_{month:02d}")
    return report.model_dump()


@router.get("/tax/pnd3/{year}/{month}")
async def tax_pnd3(
    year: int, month: int,
    ctx: CTX, db: CompanyDB,
    fmt: Optional[str] = Query(None),
):
    from app.reports import tax_report
    try:
        report = await tax_report.pnd3(ctx, db, year, month)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    if fmt:
        return _export(report, fmt, f"PND3_{year}_{month:02d}")
    return report.model_dump()


@router.get("/tax/pnd53/{year}/{month}")
async def tax_pnd53(
    year: int, month: int,
    ctx: CTX, db: CompanyDB,
    fmt: Optional[str] = Query(None),
):
    from app.reports import tax_report
    try:
        report = await tax_report.pnd53(ctx, db, year, month)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    if fmt:
        return _export(report, fmt, f"PND53_{year}_{month:02d}")
    return report.model_dump()


# ── Cost Center ───────────────────────────────────────────────────────────────

@router.get("/cost-center/list")
async def list_cost_centers(ctx: CTX, db: CompanyDB):
    from sqlalchemy import select, distinct
    from app.core.models import JournalLine
    rows = await db.scalars(
        select(distinct(JournalLine.cost_center))
        .where(JournalLine.cost_center.isnot(None))
        .order_by(JournalLine.cost_center)
    )
    return {"data": [r for r in rows if r]}


@router.get("/cost-center")
async def cost_center_report(
    ctx: CTX,
    db: CompanyDB,
    date_from: date = Query(...),
    date_to: date = Query(...),
    cost_centers: Optional[str] = Query(None),
    branch_ids: Optional[str] = Query(None),
    fmt: Optional[str] = Query(None),
):
    from app.reports import cost_center as cc_module
    ccs = [x.strip() for x in cost_centers.split(",")] if cost_centers else None
    branches = [int(x) for x in branch_ids.split(",")] if branch_ids else None
    try:
        report = await cc_module.generate(ctx, db, date_from, date_to, ccs, branches)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    if fmt:
        return _export(report, fmt, f"CostCenter_{date_from}_{date_to}")
    return report.model_dump()


# ── Equity Changes ───────────────────────────────────────────────────────────

class EquityChangeIn(BaseModel):
    change_type: str
    account_code: str
    partner_name: Optional[str] = None
    amount: Decimal
    description: str = ""
    period: str


@router.get("/equity")
async def equity_report(
    ctx: CTX,
    db: CompanyDB,
    period: str = Query(..., description="YYYY-MM"),
    fmt: Optional[str] = Query(None),
):
    from app.reports import equity_changes as eq
    report = await eq.generate(ctx, db, period)
    if fmt:
        return _export(report, fmt, f"Equity_{period}")
    return report.model_dump()


@router.post("/equity/manual-entry", status_code=201)
async def equity_manual_entry(
    data: EquityChangeIn,
    ctx: CTX,
    db: CompanyDB,
):
    from app.core.models import EquityChange
    entry = EquityChange(
        company_id=ctx.company_id,
        period=data.period,
        change_type=data.change_type,
        account_code=data.account_code,
        partner_name=data.partner_name,
        amount=data.amount,
        description=data.description,
        source="manual",
    )
    db.add(entry)
    await db.commit()
    return {"ok": True, "id": entry.id}


# ── Notes ─────────────────────────────────────────────────────────────────────

class NoteTemplateIn(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    enabled: Optional[bool] = None
    display_order: Optional[int] = None


@router.get("/notes")
async def notes_report(
    ctx: CTX,
    db: CompanyDB,
    period: str = Query(..., description="YYYY-MM"),
    fmt: Optional[str] = Query(None),
):
    from app.reports import notes as nt
    report = await nt.generate(ctx, db, period)
    if fmt:
        return _export(report, fmt, f"Notes_{period}")
    return report.model_dump()


@router.get("/notes/templates")
async def list_note_templates(
    ctx: CTX,
    db: CompanyDB,
):
    from app.core.models import NoteTemplate
    from app.reports.notes import NOTE_DEFAULTS
    templates_result = await db.execute(
        select(NoteTemplate).where(
            NoteTemplate.company_id == ctx.company_id,
            NoteTemplate.period.is_(None),
        ).order_by(NoteTemplate.display_order)
    )
    templates = list(templates_result.scalars().all())
    result = []
    for note_id, defaults in NOTE_DEFAULTS.items():
        tmpl = next((t for t in templates if t.note_id == note_id), None)
        result.append({
            "note_id": note_id,
            "title": tmpl.title if tmpl else defaults["title"],
            "enabled": tmpl.enabled if tmpl else True,
            "display_order": tmpl.display_order if tmpl else defaults["display_order"],
            "note_required": defaults.get("note_required", False),
        })
    result.sort(key=lambda x: x["display_order"])
    return result


@router.put("/notes/templates/{note_id}")
async def update_note_template(
    note_id: str,
    data: NoteTemplateIn,
    ctx: CTX,
    db: CompanyDB,
):
    from app.core.models import NoteTemplate
    from app.reports.notes import NOTE_DEFAULTS
    tmpl_result = await db.execute(
        select(NoteTemplate).where(
            NoteTemplate.company_id == ctx.company_id,
            NoteTemplate.note_id == note_id,
            NoteTemplate.period.is_(None),
        )
    )
    tmpl = tmpl_result.scalar_one_or_none()
    if not tmpl:
        defaults = NOTE_DEFAULTS.get(note_id, {})
        tmpl = NoteTemplate(
            company_id=ctx.company_id,
            note_id=note_id,
            period=None,
            title=data.title or defaults.get("title", note_id),
            content=data.content,
            enabled=data.enabled if data.enabled is not None else True,
            display_order=data.display_order if data.display_order is not None else defaults.get("display_order", 99),
        )
        db.add(tmpl)
    else:
        if data.title is not None:
            tmpl.title = data.title
        if data.content is not None:
            tmpl.content = data.content
        if data.enabled is not None:
            tmpl.enabled = data.enabled
        if data.display_order is not None:
            tmpl.display_order = data.display_order
    await db.commit()
    return {"ok": True}


# ── Consolidation ─────────────────────────────────────────────────────────────

@router.get("/consolidation/{year}/{month}")
async def consolidation(
    year: int, month: int,
    ctx: CTX, db: CompanyDB,
    branch_ids: str = Query(..., description="comma-separated branch IDs"),
    fmt: Optional[str] = Query(None),
):
    from app.reports import consolidation as cons
    try:
        ids = [int(x.strip()) for x in branch_ids.split(",")]
        report = await cons.consolidate(ctx, db, ids, year, month)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if fmt:
        return _export(report, fmt, f"Consolidation_{year}_{month:02d}")
    return report.model_dump()
