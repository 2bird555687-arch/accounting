"""Notes Engine — หมายเหตุประกอบงบการเงิน."""

from __future__ import annotations

import calendar
from datetime import date
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.context import AppContext
from app.core.models import AccountBalance, ChartOfAccount, NoteTemplate, Period
from app.reports._base import BaseReport
from app.reports._queries import get_account_balances, get_period


NOTE_DEFAULTS: dict[str, dict] = {
    "NOTE_POLICY":     {"title": "นโยบายการบัญชี", "display_order": 0, "note_required": True},
    "NOTE_CASH":       {"title": "เงินสดและรายการเทียบเท่าเงินสด", "display_order": 1},
    "NOTE_RECEIVABLE": {"title": "ลูกหนี้การค้าและลูกหนี้อื่น", "display_order": 2},
    "NOTE_INVENTORY":  {"title": "สินค้าคงเหลือ", "display_order": 3},
    "NOTE_PPE":        {"title": "ที่ดิน อาคารและอุปกรณ์", "display_order": 5},
    "NOTE_PAYABLE":    {"title": "เจ้าหนี้การค้าและเจ้าหนี้อื่น", "display_order": 6},
    "NOTE_LOAN":       {"title": "เงินกู้ยืม", "display_order": 7},
    "NOTE_ACCRUED":    {"title": "ค่าใช้จ่ายค้างจ่าย", "display_order": 8},
    "NOTE_TAX":        {"title": "ภาษีเงินได้", "display_order": 9},
    "NOTE_CAPITAL":    {"title": "ทุนและกำไรสะสม", "display_order": 10},
    "NOTE_RELATED":    {"title": "รายการกับบุคคลหรือกิจการที่เกี่ยวข้องกัน", "display_order": 11},
    "NOTE_COMMITMENT": {"title": "ภาระผูกพันและหนี้สินที่อาจเกิดขึ้น", "display_order": 12},
    "NOTE_SEGMENT":    {"title": "ข้อมูลจำแนกตามส่วนงาน", "display_order": 13},
}

DEFAULT_POLICY_TEXT = """นโยบายการบัญชีที่สำคัญ
1. เกณฑ์การจัดทำงบการเงิน: จัดทำตามมาตรฐานการรายงานทางการเงินสำหรับกิจการที่ไม่มีส่วนได้เสียสาธารณะ (TFRS for NPAEs)
2. เกณฑ์การรับรู้รายได้: รับรู้รายได้เมื่อมีการส่งมอบสินค้าหรือให้บริการแล้ว
3. สินทรัพย์ถาวร: บันทึกด้วยราคาทุนหักค่าเสื่อมราคาสะสม คำนวณค่าเสื่อมราคาด้วยวิธีเส้นตรง"""


class NoteSection(BaseModel):
    note_number: int
    note_id: str
    title: str
    content: Optional[str] = None
    data: Optional[dict] = None
    enabled: bool


class NotesReport(BaseReport):
    period: str
    entity_type: str = "company"
    sections: list[NoteSection]
    total_notes: int

    def _to_html(self, title: str) -> str:
        parts = [f"<html><head><meta charset='utf-8'></head><body><h1>{title}</h1>"]
        for sec in self.sections:
            if not sec.enabled:
                continue
            parts.append(f"<h2>หมายเหตุที่ {sec.note_number} — {sec.title}</h2>")
            if sec.content:
                parts.append(f"<pre>{sec.content}</pre>")
            if sec.data:
                parts.append("<table><tr>")
                for k in sec.data.keys():
                    parts.append(f"<th>{k}</th>")
                parts.append("</tr><tr>")
                for v in sec.data.values():
                    parts.append(f"<td>{v}</td>")
                parts.append("</tr></table>")
        parts.append("</body></html>")
        return "".join(parts)


async def _sum_note_balance(
    db: AsyncSession,
    period_ids: list[int],
    branch_ids: list[int],
    note_id: str,
) -> Decimal:
    """รวมยอดบัญชีที่มี note_id ตรงกัน."""
    stmt = (
        select(func.sum(AccountBalance.closing_balance))
        .join(ChartOfAccount, ChartOfAccount.id == AccountBalance.account_id)
        .where(
            AccountBalance.period_id.in_(period_ids),
            AccountBalance.branch_id.in_(branch_ids),
            ChartOfAccount.note_id == note_id,
            ChartOfAccount.is_header == False,
        )
    )
    result = await db.scalar(stmt)
    return Decimal(str(result or 0))


async def _get_note_accounts(
    db: AsyncSession,
    period_ids: list[int],
    branch_ids: list[int],
    note_id: str,
) -> list[dict]:
    """ดึงรายการบัญชีพร้อมยอดที่มี note_id ตรงกัน."""
    stmt = (
        select(ChartOfAccount, func.sum(AccountBalance.closing_balance))
        .join(AccountBalance, AccountBalance.account_id == ChartOfAccount.id)
        .where(
            AccountBalance.period_id.in_(period_ids),
            AccountBalance.branch_id.in_(branch_ids),
            ChartOfAccount.note_id == note_id,
            ChartOfAccount.is_header == False,
        )
        .group_by(ChartOfAccount.id)
        .order_by(ChartOfAccount.code)
    )
    rows = await db.execute(stmt)
    result = []
    for coa, balance in rows.all():
        result.append({
            "code": coa.code,
            "name": coa.name,
            "balance": float(Decimal(str(balance or 0))),
        })
    return result


async def generate(
    ctx: AppContext,
    db: AsyncSession,
    period_str: str,
) -> NotesReport:
    """สร้างหมายเหตุประกอบงบการเงิน."""
    entity_type = "company"
    try:
        from app.database import get_shared_session
        from app.platform.models import Company as PlatformCompany
        async with get_shared_session() as shared_db:
            company_obj = await shared_db.scalar(
                select(PlatformCompany).where(PlatformCompany.id == ctx.company_id)
            )
            if company_obj:
                entity_type = company_obj.entity_type or "company"
    except Exception:
        pass

    year, month = int(period_str[:4]), int(period_str[5:7])
    period = await get_period(year, month, db)
    branches = [ctx.branch_id]
    period_ids = [period.id] if period else []

    # โหลด templates จาก DB
    templates_result = await db.execute(
        select(NoteTemplate).where(
            NoteTemplate.company_id == ctx.company_id,
            NoteTemplate.period.is_(None),
        ).order_by(NoteTemplate.display_order)
    )
    db_templates = {t.note_id: t for t in templates_result.scalars().all()}

    # รวม defaults + templates
    merged: list[dict] = []
    for note_id, defaults in NOTE_DEFAULTS.items():
        tmpl = db_templates.get(note_id)
        merged.append({
            "note_id": note_id,
            "title": tmpl.title if tmpl else defaults["title"],
            "content": tmpl.content if tmpl else None,
            "enabled": tmpl.enabled if tmpl else True,
            "display_order": tmpl.display_order if tmpl else defaults["display_order"],
            "note_required": defaults.get("note_required", False),
        })
    merged.sort(key=lambda x: x["display_order"])

    # สร้าง sections พร้อมข้อมูล
    sections: list[NoteSection] = []
    note_number = 0

    for item in merged:
        note_id = item["note_id"]
        enabled = item["enabled"]
        content = item["content"]
        data: Optional[dict] = None

        if period_ids:
            if note_id == "NOTE_POLICY":
                if not content:
                    content = DEFAULT_POLICY_TEXT
            elif note_id == "NOTE_RECEIVABLE":
                # ลองเรียก AR aging ก่อน ถ้าไม่มีให้ใช้ยอดบัญชี
                try:
                    from app.reports import aging
                    last_day = calendar.monthrange(year, month)[1]
                    as_of = date(year, month, last_day)
                    ar_report = await aging.ar_aging(ctx, db, as_of, branch_ids=branches)
                    total = sum(b.total for b in ar_report.buckets) if hasattr(ar_report, "buckets") else Decimal(0)
                    data = {"ยอดรวมลูกหนี้": float(total)}
                except Exception:
                    balance = await _sum_note_balance(db, period_ids, branches, note_id)
                    if balance != 0:
                        accts = await _get_note_accounts(db, period_ids, branches, note_id)
                        data = {"รายการ": accts, "รวม": float(balance)}
            elif note_id == "NOTE_PPE":
                # ลองเรียก FA depreciation service
                try:
                    from app.modules.fa import depreciation_service as dep_svc
                    fa_data = await dep_svc.get_ppe_note(ctx, db, period_str)
                    data = fa_data
                except Exception:
                    balance = await _sum_note_balance(db, period_ids, branches, note_id)
                    if balance != 0:
                        accts = await _get_note_accounts(db, period_ids, branches, note_id)
                        data = {"รายการ": accts, "รวม": float(balance)}
            else:
                # บัญชีทั่วไป: sum ยอด
                balance = await _sum_note_balance(db, period_ids, branches, note_id)
                if balance != 0:
                    accts = await _get_note_accounts(db, period_ids, branches, note_id)
                    data = {"รายการ": accts, "รวม": float(balance)}
                elif not item["note_required"]:
                    enabled = False

        if enabled:
            note_number += 1

        sections.append(NoteSection(
            note_number=note_number if enabled else 0,
            note_id=note_id,
            title=item["title"],
            content=content,
            data=data,
            enabled=enabled,
        ))

    return NotesReport(
        period=period_str,
        entity_type=entity_type,
        sections=sections,
        total_notes=note_number,
    )
