"""Payroll + Employee API Routes."""

from __future__ import annotations

from datetime import date
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import CTX, CompanyDB
from app.context import AppContext
from app.master.schemas import (
    EmployeeCreate,
    EmployeeOut,
    EmployeeUpdate,
    PayrollCalculateIn,
    PayrollRecordOut,
    PayrollSummary,
)
from app.master.employee_service import EmployeeService
from app.modules.payroll.payroll_service import PayrollService

router = APIRouter(tags=["Payroll"])


# ── Employees ─────────────────────────────────────────────────────────────────

@router.get("/employees", response_model=list[EmployeeOut])
async def list_employees(
    ctx: CTX, db: CompanyDB,
    active_only: bool = Query(True),
    skip: int = Query(0, ge=0),
    limit: int = Query(200, le=1000),
):
    return await EmployeeService.list_employees(ctx, db, active_only=active_only, skip=skip, limit=limit)


@router.post("/employees", response_model=EmployeeOut, status_code=201)
async def create_employee(data: EmployeeCreate, ctx: CTX, db: CompanyDB):
    try:
        return await EmployeeService.create_employee(data, ctx, db)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/employees/{emp_id}", response_model=EmployeeOut)
async def get_employee(emp_id: int, ctx: CTX, db: CompanyDB):
    try:
        return await EmployeeService.get_employee(emp_id, ctx, db)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.put("/employees/{emp_id}", response_model=EmployeeOut)
async def update_employee(emp_id: int, data: EmployeeUpdate, ctx: CTX, db: CompanyDB):
    try:
        return await EmployeeService.update_employee(emp_id, data, ctx, db)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/employees/{emp_id}/terminate", response_model=EmployeeOut)
async def terminate_employee(
    emp_id: int, ctx: CTX, db: CompanyDB,
    end_date: date = Query(...),
):
    try:
        return await EmployeeService.terminate_employee(emp_id, end_date, ctx, db)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ── Payroll ───────────────────────────────────────────────────────────────────

@router.get("/payroll/{period}/summary", response_model=PayrollSummary)
async def get_payroll_summary(period: str, ctx: CTX, db: CompanyDB):
    try:
        return await PayrollService.get_summary(period, ctx, db)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/payroll/{period}/records", response_model=list[PayrollRecordOut])
async def list_payroll_records(period: str, ctx: CTX, db: CompanyDB):
    try:
        from sqlalchemy import select
        from app.master.models import PayrollRecord, Employee
        rows = await db.scalars(
            select(PayrollRecord).where(
                PayrollRecord.company_id == ctx.company_id,
                PayrollRecord.period == period,
            )
        )
        results = []
        for r in rows:
            emp = await db.scalar(
                select(Employee).where(Employee.id == r.employee_id)
            )
            from app.modules.payroll.payroll_service import _payroll_out_dict
            results.append(PayrollRecordOut(**_payroll_out_dict(r, emp)))
        return results
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/payroll/calculate", response_model=list[PayrollRecordOut], status_code=201)
async def calculate_payroll(data: PayrollCalculateIn, ctx: CTX, db: CompanyDB):
    try:
        return await PayrollService.calculate_payroll(data, ctx, db)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/payroll/{period}/post", response_model=PayrollSummary)
async def post_payroll(period: str, ctx: CTX, db: CompanyDB):
    try:
        return await PayrollService.post_payroll(period, ctx, db)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/payroll/{period}/pay", response_model=PayrollSummary)
async def pay_payroll(
    period: str, ctx: CTX, db: CompanyDB,
    bank_account_code: str = Query("1102"),
):
    try:
        return await PayrollService.post_payroll_payment(period, bank_account_code, ctx, db)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ── Tax Forms (ภ.ง.ด.1ก / สปส.1-10) ─────────────────────────────────────────

@router.get("/payroll/pnd1k/{year}/summary")
async def pnd1k_summary(year: int, ctx: CTX, db: CompanyDB):
    from app.modules.payroll.m40_service import get_pnd1k_summary
    data = await get_pnd1k_summary(ctx, db, year)
    return {"data": data, "year": year}


@router.get("/payroll/pnd1k/{year}/{employee_id}")
async def pnd1k_certificate(year: int, employee_id: int, ctx: CTX, db: CompanyDB):
    from app.modules.payroll.m40_service import get_pnd1k_certificate
    from dataclasses import asdict
    try:
        cert = await get_pnd1k_certificate(ctx, db, year, employee_id)
        return asdict(cert)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/payroll/sso110/{period}")
async def sso_110(period: str, ctx: CTX, db: CompanyDB):
    from app.modules.payroll.m40_service import get_sso110
    from dataclasses import asdict
    try:
        report = await get_sso110(ctx, db, period)
        return asdict(report)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
