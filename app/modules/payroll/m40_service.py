"""M40 / SSO-1-10 Service — ภ.ง.ด.1ก และ สปส.1-10."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.master.models import Employee, PayrollRecord

# ── Thai month name tables ────────────────────────────────────────────────────

MONTHS_TH = [
    "", "มกราคม", "กุมภาพันธ์", "มีนาคม", "เมษายน",
    "พฤษภาคม", "มิถุนายน", "กรกฎาคม", "สิงหาคม",
    "กันยายน", "ตุลาคม", "พฤศจิกายน", "ธันวาคม",
]
MONTHS_SHORT_TH = [
    "", "ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.",
    "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค.",
]

SSO_MIN_BASE = Decimal("1650")
SSO_MAX_BASE = Decimal("15000")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _period_display(period_str: str) -> str:
    """'202601' → 'มกราคม 2569'"""
    y = int(period_str[:4])
    m = int(period_str[4:])
    return f"{MONTHS_TH[m]} {y + 543}"


def _round_sso(amount: Decimal) -> Decimal:
    """Round SSO: satang >= 50 → round up to next baht."""
    baht = int(amount)
    satang = (amount - Decimal(baht)) * 100
    if satang >= 50:
        return Decimal(baht + 1)
    return Decimal(baht)


# ── Dataclasses ───────────────────────────────────────────────────────────────

@dataclass
class M40Line:
    month: int
    period: str        # "202601"
    month_short: str   # "ม.ค."
    gross: Decimal
    wht: Decimal
    sso_employee: Decimal
    net: Decimal


@dataclass
class M40Certificate:
    employee_id: int
    emp_code: str
    full_name: str
    id_card: str
    position: str
    department: str
    year: int
    total_gross: Decimal
    total_wht: Decimal
    total_sso: Decimal
    total_net: Decimal
    lines: list


@dataclass
class SSO110Line:
    seq: int
    id_card: str
    full_name: str
    gross_actual: Decimal
    sso_base: Decimal
    sso_employee: Decimal


@dataclass
class SSO110Report:
    period: str
    period_display: str
    sso_rate: Decimal
    total_gross: Decimal
    total_sso_employee: Decimal
    total_sso_employer: Decimal
    total_sso_submit: Decimal
    total_insured_count: int
    lines: list


# ── Service Functions ─────────────────────────────────────────────────────────

async def get_pnd1k_summary(ctx, db: AsyncSession, year: int) -> list[dict]:
    """ภ.ง.ด.1ก — สรุปรายบุคคลทั้งปี."""
    year_prefix = str(year)  # "2026"

    records = (await db.execute(
        select(PayrollRecord).where(
            PayrollRecord.company_id == ctx.company_id,
            PayrollRecord.period.like(f"{year_prefix}%"),
        )
    )).scalars().all()

    # Group by employee_id
    emp_totals: dict[int, dict] = {}
    for r in records:
        if r.employee_id not in emp_totals:
            emp_totals[r.employee_id] = {
                "employee_id": r.employee_id,
                "total_gross": Decimal(0),
                "total_wht": Decimal(0),
                "total_sso": Decimal(0),
            }
        emp_totals[r.employee_id]["total_gross"] += r.gross
        emp_totals[r.employee_id]["total_wht"] += r.wht
        emp_totals[r.employee_id]["total_sso"] += r.sso_employee

    if not emp_totals:
        return []

    # Fetch employee details
    employees = (await db.execute(
        select(Employee).where(
            Employee.company_id == ctx.company_id,
            Employee.id.in_(list(emp_totals.keys())),
        )
    )).scalars().all()

    emp_map = {e.id: e for e in employees}

    result = []
    for emp_id, totals in emp_totals.items():
        emp = emp_map.get(emp_id)
        if emp is None:
            continue
        result.append({
            "employee_id": emp_id,
            "emp_code": emp.employee_code,
            "full_name": emp.name_th,
            "id_card": emp.tax_id or "",
            "position": emp.position or "",
            "department": emp.department or "",
            "total_gross": float(totals["total_gross"]),
            "total_wht": float(totals["total_wht"]),
            "total_sso": float(totals["total_sso"]),
        })

    result.sort(key=lambda x: x["emp_code"])
    return result


async def get_pnd1k_certificate(
    ctx, db: AsyncSession, year: int, employee_id: int
) -> M40Certificate:
    """ภ.ง.ด.1ก รายบุคคล — 12 เดือน."""
    emp = (await db.execute(
        select(Employee).where(
            Employee.id == employee_id,
            Employee.company_id == ctx.company_id,
        )
    )).scalar_one_or_none()

    if emp is None:
        raise ValueError(f"ไม่พบพนักงาน id={employee_id}")

    year_prefix = str(year)
    records = (await db.execute(
        select(PayrollRecord).where(
            PayrollRecord.company_id == ctx.company_id,
            PayrollRecord.employee_id == employee_id,
            PayrollRecord.period.like(f"{year_prefix}%"),
        )
    )).scalars().all()

    rec_map: dict[int, PayrollRecord] = {}
    for r in records:
        month = int(r.period[4:])
        rec_map[month] = r

    lines: list[M40Line] = []
    for m in range(1, 13):
        period_str = f"{year}{m:02d}"
        r = rec_map.get(m)
        if r:
            lines.append(M40Line(
                month=m,
                period=period_str,
                month_short=MONTHS_SHORT_TH[m],
                gross=r.gross,
                wht=r.wht,
                sso_employee=r.sso_employee,
                net=r.net,
            ))
        else:
            lines.append(M40Line(
                month=m,
                period=period_str,
                month_short=MONTHS_SHORT_TH[m],
                gross=Decimal(0),
                wht=Decimal(0),
                sso_employee=Decimal(0),
                net=Decimal(0),
            ))

    total_gross = sum(l.gross for l in lines)
    total_wht = sum(l.wht for l in lines)
    total_sso = sum(l.sso_employee for l in lines)
    total_net = sum(l.net for l in lines)

    return M40Certificate(
        employee_id=employee_id,
        emp_code=emp.employee_code,
        full_name=emp.name_th,
        id_card=emp.tax_id or "",
        position=emp.position or "",
        department=emp.department or "",
        year=year,
        total_gross=total_gross,
        total_wht=total_wht,
        total_sso=total_sso,
        total_net=total_net,
        lines=lines,
    )


async def get_sso110(ctx, db: AsyncSession, period_str: str) -> SSO110Report:
    """สปส.1-10 — รายงานนำส่งประกันสังคมรายเดือน.
    period_str: 'YYYYMM' เช่น '202601'
    """
    records = (await db.execute(
        select(PayrollRecord).where(
            PayrollRecord.company_id == ctx.company_id,
            PayrollRecord.period == period_str,
        )
    )).scalars().all()

    if not records:
        raise ValueError(f"ไม่มีข้อมูลเงินเดือนงวด {period_str}")

    emp_ids = [r.employee_id for r in records]
    employees = (await db.execute(
        select(Employee).where(
            Employee.company_id == ctx.company_id,
            Employee.id.in_(emp_ids),
        )
    )).scalars().all()
    emp_map = {e.id: e for e in employees}

    lines: list[SSO110Line] = []
    total_gross = Decimal(0)
    total_sso_employee = Decimal(0)
    total_sso_employer = Decimal(0)

    for seq, r in enumerate(records, start=1):
        emp = emp_map.get(r.employee_id)
        full_name = emp.name_th if emp else str(r.employee_id)
        id_card = (emp.tax_id or "") if emp else ""

        # sso_base: max(1650, min(gross, 15000))
        sso_base = max(SSO_MIN_BASE, min(r.gross, SSO_MAX_BASE))

        # sso_rate stored as decimal (0.05 = 5%)
        emp_sso_rate = emp.sso_rate if emp else Decimal("0.05")
        sso_employee = _round_sso(sso_base * emp_sso_rate)
        sso_employer = sso_employee  # same rate

        total_gross += r.gross
        total_sso_employee += sso_employee
        total_sso_employer += sso_employer

        lines.append(SSO110Line(
            seq=seq,
            id_card=id_card,
            full_name=full_name,
            gross_actual=r.gross,
            sso_base=sso_base,
            sso_employee=sso_employee,
        ))

    # Use first employee's sso_rate for display (5% is standard)
    display_rate = Decimal("0.05")
    if records and emp_map.get(records[0].employee_id):
        display_rate = emp_map[records[0].employee_id].sso_rate

    return SSO110Report(
        period=period_str,
        period_display=_period_display(period_str),
        sso_rate=display_rate * 100,  # display as percent e.g. 5.00
        total_gross=total_gross,
        total_sso_employee=total_sso_employee,
        total_sso_employer=total_sso_employer,
        total_sso_submit=total_sso_employee + total_sso_employer,
        total_insured_count=len(lines),
        lines=lines,
    )
