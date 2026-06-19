"""Web UI Routes — HTML pages served via Jinja2 templates (Starlette 1.x API)."""

from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.ui.deps import UIRedirectException, get_ui_context
from app.platform.auth import verify_access_token

router = APIRouter(tags=["UI"])
templates = Jinja2Templates(directory="templates")


def _ctx(ctx=None, user=None, **extra) -> dict:
    """Build template context dict — request is passed separately in Starlette 1.x."""
    return {"ctx": ctx, "user": user, "today": date.today(), **extra}


def _r(name: str, request: Request, context: dict) -> HTMLResponse:
    """Shorthand for TemplateResponse with Starlette 1.x signature."""
    return templates.TemplateResponse(request=request, name=name, context=context)


# ── Auth ──────────────────────────────────────────────────────────────────────

@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    token = request.cookies.get("access_token")
    if token:
        try:
            verify_access_token(token)
            return RedirectResponse(url="/", status_code=302)
        except Exception:
            pass
    return _r("auth/login.html", request, {})


@router.post("/login")
async def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    company_id: int = Form(1),
    branch_id: int = Form(1),
):
    import httpx
    base = str(request.base_url).rstrip("/")
    async with httpx.AsyncClient() as client:
        resp = await client.post(f"{base}/api/v1/auth/login", json={
            "username": username, "password": password,
            "company_id": company_id, "branch_id": branch_id,
        })
    if resp.status_code != 200:
        return templates.TemplateResponse(
            request=request,
            name="auth/login.html",
            context={"error": "ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง"},
            status_code=401,
        )
    data = resp.json()
    token = data.get("access_token") or data.get("data", {}).get("access_token", "")
    response = RedirectResponse(url="/", status_code=302)
    response.set_cookie("access_token", token, httponly=True, samesite="lax", max_age=86400)
    return response


@router.get("/logout")
async def logout():
    response = RedirectResponse(url="/login", status_code=302)
    response.delete_cookie("access_token")
    return response


# ── Dashboard ─────────────────────────────────────────────────────────────────

@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    try:
        ctx = await get_ui_context(request)
    except UIRedirectException as e:
        return RedirectResponse(url=e.url, status_code=302)
    return _r("dashboard.html", request, _ctx(ctx))


# ── Journals ─────────────────────────────────────────────────────────────────

@router.get("/journals", response_class=HTMLResponse)
async def journal_list(request: Request, jtype: str = ""):
    try:
        ctx = await get_ui_context(request)
    except UIRedirectException as e:
        return RedirectResponse(url=e.url, status_code=302)
    return _r("journals/list.html", request, _ctx(ctx, jtype=jtype))


@router.get("/journals/{entry_no}", response_class=HTMLResponse)
async def journal_detail(request: Request, entry_no: str):
    try:
        ctx = await get_ui_context(request)
    except UIRedirectException as e:
        return RedirectResponse(url=e.url, status_code=302)
    return _r("journals/detail.html", request, _ctx(ctx, entry_no=entry_no))


# ── AR ────────────────────────────────────────────────────────────────────────

@router.get("/ar/invoices", response_class=HTMLResponse)
async def ar_invoice_list(request: Request):
    try:
        ctx = await get_ui_context(request)
    except UIRedirectException as e:
        return RedirectResponse(url=e.url, status_code=302)
    return _r("ar/invoice_list.html", request, _ctx(ctx))


@router.get("/ar/invoices/new", response_class=HTMLResponse)
async def ar_invoice_new(request: Request):
    try:
        ctx = await get_ui_context(request)
    except UIRedirectException as e:
        return RedirectResponse(url=e.url, status_code=302)
    return _r("ar/invoice_form.html", request, _ctx(ctx, invoice=None))


@router.get("/ar/invoices/{invoice_id}", response_class=HTMLResponse)
async def ar_invoice_detail(request: Request, invoice_id: int):
    try:
        ctx = await get_ui_context(request)
    except UIRedirectException as e:
        return RedirectResponse(url=e.url, status_code=302)
    return _r("ar/invoice_detail.html", request, _ctx(ctx, invoice_id=invoice_id))


@router.get("/ar/receipts/new", response_class=HTMLResponse)
async def ar_receipt_new(request: Request, invoice_id: Optional[int] = None):
    try:
        ctx = await get_ui_context(request)
    except UIRedirectException as e:
        return RedirectResponse(url=e.url, status_code=302)
    return _r("ar/receipt_form.html", request, _ctx(ctx, invoice_id=invoice_id))


# ── AP ────────────────────────────────────────────────────────────────────────

@router.get("/ap/purchases", response_class=HTMLResponse)
async def ap_purchase_list(request: Request):
    try:
        ctx = await get_ui_context(request)
    except UIRedirectException as e:
        return RedirectResponse(url=e.url, status_code=302)
    return _r("ap/purchase_list.html", request, _ctx(ctx))


@router.get("/ap/purchases/new", response_class=HTMLResponse)
async def ap_purchase_new(request: Request):
    try:
        ctx = await get_ui_context(request)
    except UIRedirectException as e:
        return RedirectResponse(url=e.url, status_code=302)
    return _r("ap/purchase_form.html", request, _ctx(ctx, purchase=None))


@router.get("/ap/payments/new", response_class=HTMLResponse)
async def ap_payment_new(request: Request, purchase_id: Optional[int] = None):
    try:
        ctx = await get_ui_context(request)
    except UIRedirectException as e:
        return RedirectResponse(url=e.url, status_code=302)
    return _r("ap/payment_form.html", request, _ctx(ctx, purchase_id=purchase_id))


@router.get("/ap/po", response_class=HTMLResponse)
async def ap_po_list(request: Request):
    try:
        ctx = await get_ui_context(request)
    except UIRedirectException as e:
        return RedirectResponse(url=e.url, status_code=302)
    return _r("ap/po_list.html", request, _ctx(ctx))


# ── OCR ───────────────────────────────────────────────────────────────────────

@router.get("/ocr", response_class=HTMLResponse)
async def ocr_upload(request: Request):
    try:
        ctx = await get_ui_context(request)
    except UIRedirectException as e:
        return RedirectResponse(url=e.url, status_code=302)
    return _r("ocr/upload.html", request, _ctx(ctx))


@router.get("/ocr/review/{history_id}", response_class=HTMLResponse)
async def ocr_review(request: Request, history_id: int):
    try:
        ctx = await get_ui_context(request)
    except UIRedirectException as e:
        return RedirectResponse(url=e.url, status_code=302)
    return _r("ocr/review.html", request, _ctx(ctx, history_id=history_id))


# ── Reports ───────────────────────────────────────────────────────────────────

@router.get("/reports/trial-balance", response_class=HTMLResponse)
async def report_trial_balance(request: Request):
    try:
        ctx = await get_ui_context(request)
    except UIRedirectException as e:
        return RedirectResponse(url=e.url, status_code=302)
    today = date.today()
    return _r("reports/trial_balance.html", request,
              _ctx(ctx, default_year=today.year, default_month=today.month))


@router.get("/reports/balance-sheet", response_class=HTMLResponse)
async def report_balance_sheet(request: Request):
    try:
        ctx = await get_ui_context(request)
    except UIRedirectException as e:
        return RedirectResponse(url=e.url, status_code=302)
    return _r("reports/balance_sheet.html", request,
              _ctx(ctx, default_date=str(date.today())))


@router.get("/reports/income", response_class=HTMLResponse)
async def report_income(request: Request):
    try:
        ctx = await get_ui_context(request)
    except UIRedirectException as e:
        return RedirectResponse(url=e.url, status_code=302)
    today = date.today()
    return _r("reports/income.html", request,
              _ctx(ctx, default_from=str(today.replace(day=1)), default_to=str(today)))


@router.get("/reports/aging/ar", response_class=HTMLResponse)
async def report_aging_ar(request: Request):
    try:
        ctx = await get_ui_context(request)
    except UIRedirectException as e:
        return RedirectResponse(url=e.url, status_code=302)
    return _r("reports/aging_ar.html", request,
              _ctx(ctx, default_date=str(date.today())))


@router.get("/reports/aging/ap", response_class=HTMLResponse)
async def report_aging_ap(request: Request):
    try:
        ctx = await get_ui_context(request)
    except UIRedirectException as e:
        return RedirectResponse(url=e.url, status_code=302)
    return _r("reports/aging_ap.html", request,
              _ctx(ctx, default_date=str(date.today())))


# ── Firm Dashboard ────────────────────────────────────────────────────────────

@router.get("/firm", response_class=HTMLResponse)
async def firm_dashboard(request: Request):
    try:
        ctx = await get_ui_context(request)
    except UIRedirectException as e:
        return RedirectResponse(url=e.url, status_code=302)
    return _r("firm_dashboard.html", request, _ctx(ctx))
