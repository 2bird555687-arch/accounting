"""Payroll Service — คำนวณ / post / จ่ายเงินเดือน."""

from __future__ import annotations

from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.context import AppContext, JournalType, DrCr
from app.core.engine import PostingEngine, JournalEntryInput, JournalLineInput
from app.master.models import Employee, PayrollRecord
from app.master.schemas import PayrollCalculateIn, PayrollRecordOut, PayrollSummary


def _parse_period(period: str) -> date:
    """แปลง "202601" → date(2026,1,1)."""
    return date(int(period[:4]), int(period[4:]), 1)


def _calc_wht(gross: Decimal, annual_gross: Decimal) -> Decimal:
    """ประมาณการ WHT รายเดือน (simplified progressive rate สำหรับ demo).

    อัตราจริงต้องใช้ตาราง ภงด.1 แต่นี้ใช้สูตรประมาณ:
      0–150,000  → 0%
      150,001–300,000 → 5%
      300,001–500,000 → 10%
      500,001–750,000 → 15%
      750,001–1,000,000 → 20%
      > 1,000,000 → 25%
    """
    brackets = [
        (Decimal(150_000), Decimal(0)),
        (Decimal(150_000), Decimal("0.05")),
        (Decimal(200_000), Decimal("0.10")),
        (Decimal(250_000), Decimal("0.15")),
        (Decimal(250_000), Decimal("0.20")),
        (Decimal(0),       Decimal("0.25")),  # > 1,000,000
    ]
    annual_tax = Decimal(0)
    remaining = annual_gross - Decimal(60_000)  # หักค่าใช้จ่าย 50% ไม่เกิน 100,000 (simplified)
    if remaining < 0:
        remaining = Decimal(0)

    for band_size, rate in brackets:
        if remaining <= 0:
            break
        if band_size == 0:
            annual_tax += remaining * rate
            break
        taxable = min(remaining, band_size)
        annual_tax += taxable * rate
        remaining -= taxable

    monthly_wht = (annual_tax / 12).quantize(Decimal("0.01"), ROUND_HALF_UP)
    return monthly_wht


class PayrollService:

    @staticmethod
    async def calculate_payroll(
        data: PayrollCalculateIn, ctx: AppContext, db: AsyncSession
    ) -> list[PayrollRecordOut]:
        """คำนวณเงินเดือนสำหรับงวด — ยังไม่ post journal."""
        if ctx.user_role not in ("firm_admin", "accountant"):
            raise PermissionError("ต้องการสิทธิ์ accountant ขึ้นไป")

        # ตรวจว่างวดนี้คำนวณไปแล้วหรือยัง
        existing = await db.scalars(
            select(PayrollRecord).where(
                PayrollRecord.company_id == ctx.company_id,
                PayrollRecord.period == data.period,
            )
        )
        existing_list = list(existing)
        if existing_list:
            # return ที่มีอยู่แทน
            return [
                PayrollRecordOut(
                    **_payroll_out_dict(r, await db.scalar(select(Employee).where(Employee.id == r.employee_id)))
                )
                for r in existing_list
            ]

        employees = await db.scalars(
            select(Employee).where(
                Employee.company_id == ctx.company_id,
                Employee.is_active.is_(True),
            )
        )

        overrides = data.overrides or {}
        records: list[PayrollRecord] = []

        for emp in employees:
            ov = overrides.get(emp.id, {})
            ot_hours = Decimal(str(ov.get("ot_hours", 0)))
            bonus = Decimal(str(ov.get("bonus", 0)))

            ot_amount = (ot_hours * emp.ot_rate).quantize(Decimal("0.01"), ROUND_HALF_UP)
            gross = emp.salary + ot_amount + bonus

            # SSO employee 5% ของ min(gross, sso_ceiling)
            sso_base = min(gross, emp.sso_ceiling)
            sso_employee = (sso_base * emp.sso_rate).quantize(Decimal("0.01"), ROUND_HALF_UP)
            sso_employer = sso_employee   # อัตราเท่ากัน

            # WHT (ประมาณ)
            annual_gross = gross * 12
            wht = _calc_wht(gross, annual_gross)

            net = gross - sso_employee - wht

            rec = PayrollRecord(
                company_id=ctx.company_id,
                branch_id=ctx.branch_id,
                period=data.period,
                employee_id=emp.id,
                gross=gross,
                sso_employee=sso_employee,
                sso_employer=sso_employer,
                wht=wht,
                net=net,
                ot_hours=ot_hours,
                ot_amount=ot_amount,
                bonus=bonus,
                status="calculated",
            )
            db.add(rec)
            records.append((rec, emp))

        await db.flush()

        return [
            PayrollRecordOut(**_payroll_out_dict(r, emp))
            for r, emp in records
        ]

    @staticmethod
    async def post_payroll(period: str, ctx: AppContext, db: AsyncSession) -> PayrollSummary:
        """Post journal เงินเดือน:
        Dr 6501 (เงินเดือน=gross) + Dr 6502 (SSO นายจ้าง)
        | Cr 2130 (เงินเดือนค้างจ่าย=net) + Cr 2131 (SSO ค้างจ่าย) + Cr 2121 (WHT)
        """
        if ctx.user_role not in ("firm_admin", "accountant"):
            raise PermissionError("ต้องการสิทธิ์ accountant ขึ้นไป")

        records = await db.scalars(
            select(PayrollRecord).where(
                PayrollRecord.company_id == ctx.company_id,
                PayrollRecord.period == period,
                PayrollRecord.status == "calculated",
            )
        )
        records = list(records)
        if not records:
            raise ValueError(f"ไม่มีรายการเงินเดือนงวด {period} ที่รอ post (คำนวณก่อน)")

        total_gross = sum(r.gross for r in records)
        total_sso_emp = sum(r.sso_employee for r in records)
        total_sso_er = sum(r.sso_employer for r in records)
        total_wht = sum(r.wht for r in records)
        total_net = sum(r.net for r in records)

        period_date = _parse_period(period)

        lines = [
            JournalLineInput(account_code="6501", side=DrCr.DR, amount=total_gross,
                             description="เงินเดือนพนักงาน"),
            JournalLineInput(account_code="6502", side=DrCr.DR, amount=total_sso_er,
                             description="SSO ส่วนนายจ้าง"),
            JournalLineInput(account_code="2130", side=DrCr.CR, amount=total_net,
                             description="เงินเดือนค้างจ่าย"),
            JournalLineInput(account_code="2131", side=DrCr.CR,
                             amount=total_sso_emp + total_sso_er,
                             description="SSO ค้างจ่าย"),
            JournalLineInput(account_code="2121", side=DrCr.CR, amount=total_wht,
                             description="WHT ค้างนำส่ง"),
        ]

        entry = JournalEntryInput(
            journal_type=JournalType.GJ,
            entry_date=period_date,
            description=f"บันทึกเงินเดือนงวด {period}",
            lines=lines,
            source_module="PAYROLL",
        )
        engine = PostingEngine(db)
        entry_no = await engine.post(entry, ctx)

        for r in records:
            r.status = "posted"
            r.posted_journal_no = entry_no

        await db.flush()

        return PayrollSummary(
            period=period,
            employee_count=len(records),
            total_gross=total_gross,
            total_sso_employee=total_sso_emp,
            total_sso_employer=total_sso_er,
            total_wht=total_wht,
            total_net=total_net,
            status="posted",
            posted_journal_no=entry_no,
            payment_journal_no=None,
        )

    @staticmethod
    async def post_payroll_payment(
        period: str, bank_account_code: str, ctx: AppContext, db: AsyncSession
    ) -> PayrollSummary:
        """จ่ายเงินเดือน:
        Dr 2130 (เงินเดือนค้างจ่าย) | Cr 1102 (ธนาคาร) → CP
        """
        if ctx.user_role not in ("firm_admin", "accountant"):
            raise PermissionError("ต้องการสิทธิ์ accountant ขึ้นไป")

        records = await db.scalars(
            select(PayrollRecord).where(
                PayrollRecord.company_id == ctx.company_id,
                PayrollRecord.period == period,
                PayrollRecord.status == "posted",
            )
        )
        records = list(records)
        if not records:
            raise ValueError(f"ไม่มีรายการเงินเดือนงวด {period} ที่ post แล้วรอจ่าย")

        total_net = sum(r.net for r in records)
        period_date = _parse_period(period)

        lines = [
            JournalLineInput(account_code="2130", side=DrCr.DR, amount=total_net,
                             description="จ่ายเงินเดือน"),
            JournalLineInput(account_code=bank_account_code, side=DrCr.CR, amount=total_net,
                             description="จ่ายผ่านธนาคาร"),
        ]
        entry = JournalEntryInput(
            journal_type=JournalType.CP,
            entry_date=period_date,
            description=f"จ่ายเงินเดือนงวด {period}",
            lines=lines,
            source_module="PAYROLL",
        )
        engine = PostingEngine(db)
        entry_no = await engine.post(entry, ctx)

        for r in records:
            r.status = "paid"
            r.payment_journal_no = entry_no

        await db.flush()

        total_gross = sum(r.gross for r in records)
        total_sso_emp = sum(r.sso_employee for r in records)
        total_sso_er = sum(r.sso_employer for r in records)
        total_wht = sum(r.wht for r in records)

        return PayrollSummary(
            period=period,
            employee_count=len(records),
            total_gross=total_gross,
            total_sso_employee=total_sso_emp,
            total_sso_employer=total_sso_er,
            total_wht=total_wht,
            total_net=total_net,
            status="paid",
            posted_journal_no=records[0].posted_journal_no if records else None,
            payment_journal_no=entry_no,
        )

    @staticmethod
    async def get_summary(period: str, ctx: AppContext, db: AsyncSession) -> PayrollSummary:
        records = await db.scalars(
            select(PayrollRecord).where(
                PayrollRecord.company_id == ctx.company_id,
                PayrollRecord.period == period,
            )
        )
        records = list(records)
        if not records:
            raise ValueError(f"ไม่มีข้อมูลเงินเดือนงวด {period}")

        status = records[0].status if len({r.status for r in records}) == 1 else "mixed"
        return PayrollSummary(
            period=period,
            employee_count=len(records),
            total_gross=sum(r.gross for r in records),
            total_sso_employee=sum(r.sso_employee for r in records),
            total_sso_employer=sum(r.sso_employer for r in records),
            total_wht=sum(r.wht for r in records),
            total_net=sum(r.net for r in records),
            status=status,
            posted_journal_no=records[0].posted_journal_no,
            payment_journal_no=records[0].payment_journal_no,
        )


def _payroll_out_dict(r: PayrollRecord, emp: Employee | None) -> dict:
    return {
        "id": r.id,
        "period": r.period,
        "employee_id": r.employee_id,
        "employee_name": emp.name_th if emp else str(r.employee_id),
        "gross": r.gross,
        "sso_employee": r.sso_employee,
        "sso_employer": r.sso_employer,
        "wht": r.wht,
        "net": r.net,
        "ot_hours": r.ot_hours,
        "ot_amount": r.ot_amount,
        "bonus": r.bonus,
        "status": r.status,
        "posted_journal_no": r.posted_journal_no,
        "payment_journal_no": r.payment_journal_no,
        "created_at": r.created_at,
    }
