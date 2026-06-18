"""Employee Service — CRUD พนักงาน."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.context import AppContext
from app.master.models import Employee
from app.master.schemas import EmployeeCreate, EmployeeOut, EmployeeUpdate


class EmployeeService:

    @staticmethod
    async def create_employee(data: EmployeeCreate, ctx: AppContext, db: AsyncSession) -> EmployeeOut:
        if ctx.user_role not in ("firm_admin", "accountant"):
            raise PermissionError("ต้องการสิทธิ์ accountant ขึ้นไป")

        existing = await db.scalar(
            select(Employee).where(
                Employee.company_id == ctx.company_id,
                Employee.employee_code == data.employee_code,
            )
        )
        if existing:
            raise ValueError(f"รหัสพนักงาน '{data.employee_code}' มีอยู่แล้ว")

        emp = Employee(
            company_id=ctx.company_id,
            branch_id=ctx.branch_id,
            **data.model_dump(),
        )
        db.add(emp)
        await db.flush()
        await db.refresh(emp)
        return EmployeeOut.model_validate(emp)

    @staticmethod
    async def list_employees(
        ctx: AppContext,
        db: AsyncSession,
        active_only: bool = True,
        skip: int = 0,
        limit: int = 200,
    ) -> list[EmployeeOut]:
        q = select(Employee).where(Employee.company_id == ctx.company_id)
        if active_only:
            q = q.where(Employee.is_active.is_(True))
        q = q.order_by(Employee.employee_code).offset(skip).limit(limit)
        rows = await db.scalars(q)
        return [EmployeeOut.model_validate(r) for r in rows]

    @staticmethod
    async def get_employee(emp_id: int, ctx: AppContext, db: AsyncSession) -> EmployeeOut:
        emp = await db.scalar(
            select(Employee).where(
                Employee.id == emp_id,
                Employee.company_id == ctx.company_id,
            )
        )
        if not emp:
            raise ValueError(f"ไม่พบพนักงาน {emp_id}")
        return EmployeeOut.model_validate(emp)

    @staticmethod
    async def update_employee(
        emp_id: int, data: EmployeeUpdate, ctx: AppContext, db: AsyncSession
    ) -> EmployeeOut:
        if ctx.user_role not in ("firm_admin", "accountant"):
            raise PermissionError("ต้องการสิทธิ์ accountant ขึ้นไป")

        emp = await db.scalar(
            select(Employee).where(
                Employee.id == emp_id,
                Employee.company_id == ctx.company_id,
            )
        )
        if not emp:
            raise ValueError(f"ไม่พบพนักงาน {emp_id}")

        for field, val in data.model_dump(exclude_none=True).items():
            setattr(emp, field, val)

        await db.flush()
        await db.refresh(emp)
        return EmployeeOut.model_validate(emp)

    @staticmethod
    async def terminate_employee(
        emp_id: int, end_date: "date", ctx: AppContext, db: AsyncSession
    ) -> EmployeeOut:
        if ctx.user_role not in ("firm_admin", "accountant"):
            raise PermissionError("ต้องการสิทธิ์ accountant ขึ้นไป")

        emp = await db.scalar(
            select(Employee).where(
                Employee.id == emp_id,
                Employee.company_id == ctx.company_id,
            )
        )
        if not emp:
            raise ValueError(f"ไม่พบพนักงาน {emp_id}")

        emp.end_date = end_date
        emp.is_active = False
        await db.flush()
        await db.refresh(emp)
        return EmployeeOut.model_validate(emp)
