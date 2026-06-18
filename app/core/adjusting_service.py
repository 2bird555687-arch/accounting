"""Adjusting Entry Service — รายการปรับปรุงสิ้นงวด."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.context import AppContext, DrCr, JournalType
from app.core.engine import PostingEngine, JournalEntryInput, JournalLineInput
from app.core.models import AdjustingEntry, Period


# ── Schemas ───────────────────────────────────────────────────────────────────

@dataclass
class AdjustingItem:
    item_type: str
    description: str
    amount: Decimal
    status: str  # pending | posted | skipped
    source_id: Optional[int] = None
    journal_no: Optional[str] = None
    adjusting_entry_id: Optional[int] = None


@dataclass
class AdjustmentIn:
    item_type: str
    description: str
    amount: Decimal
    debit_account: str   # account_code
    credit_account: str  # account_code
    source_id: Optional[int] = None


# ── Preset account_code ต่อประเภท ────────────────────────────────────────────

_ADJUSTING_ACCOUNTS: dict[str, tuple[str, str]] = {
    "depreciation":       ("6601", "1601"),  # Dr ค่าเสื่อมราคา | Cr สะสมค่าเสื่อมราคา
    "accrual":            ("6999", "2199"),  # Dr ค่าใช้จ่าย | Cr ค้างจ่าย
    "prepaid":            ("2199", "1301"),  # Dr ค้างจ่าย | Cr ค่าใช้จ่ายจ่ายล่วงหน้า
    "deferred_revenue":   ("2301", "4101"),  # Dr รายได้รับล่วงหน้า | Cr รายได้
    "allowance":          ("6701", "1102"),  # Dr หนี้สงสัยจะสูญ | Cr ค่าเผื่อหนี้สงสัย
}


# ── Service ───────────────────────────────────────────────────────────────────

async def _get_period(period: date, db: AsyncSession) -> Period:
    p = await db.scalar(
        select(Period).where(
            Period.fiscal_year == period.year,
            Period.month == period.month,
        )
    )
    if not p:
        raise ValueError(f"ไม่พบงวด {period.year}/{period.month:02d}")
    return p


async def get_checklist(
    ctx: AppContext,
    db: AsyncSession,
    period: date,
) -> list[AdjustingItem]:
    """สร้าง checklist รายการปรับปรุงที่ต้องทำในงวดนี้."""
    p = await _get_period(period, db)
    items: list[AdjustingItem] = []

    # ── 1. ค่าเสื่อมราคา (FA) ─────────────────────────────────────────────────
    try:
        from app.modules.fa.models import FixedAsset, AssetDepreciation
        assets = list(await db.scalars(
            select(FixedAsset).where(
                FixedAsset.status == "active",
            )
        ))
        for asset in assets:
            already = await db.scalar(
                select(AssetDepreciation).where(
                    AssetDepreciation.asset_id == asset.id,
                    AssetDepreciation.period_id == p.id,
                )
            )
            status = "posted" if already else "pending"
            journal_no = already.journal_no if already else None
            items.append(AdjustingItem(
                item_type="depreciation",
                description=f"ค่าเสื่อมราคา: {asset.name}",
                amount=getattr(asset, "depreciation_per_period", Decimal(0)),
                status=status,
                source_id=asset.id,
                journal_no=journal_no,
            ))
    except ImportError:
        pass

    # ── 2–5. ดึงจาก adjusting_entries ที่ track ไว้ ──────────────────────────
    stored = list(await db.scalars(
        select(AdjustingEntry).where(AdjustingEntry.period_id == p.id)
    ))
    for ae in stored:
        if ae.item_type == "depreciation":
            continue  # ดึงจาก FA แล้ว
        items.append(AdjustingItem(
            item_type=ae.item_type,
            description=ae.description,
            amount=ae.amount,
            status=ae.status,
            source_id=ae.source_id,
            journal_no=ae.journal_no,
            adjusting_entry_id=ae.id,
        ))

    # ── Placeholder checklist ถ้าไม่มีข้อมูล ─────────────────────────────────
    existing_types = {i.item_type for i in items}
    for t in ("accrual", "prepaid", "deferred_revenue", "allowance"):
        if t not in existing_types:
            items.append(AdjustingItem(
                item_type=t,
                description={
                    "accrual": "ค่าใช้จ่ายค้างจ่าย (Accruals)",
                    "prepaid": "ค่าใช้จ่ายจ่ายล่วงหน้า (Prepaid)",
                    "deferred_revenue": "รายได้รับล่วงหน้า (Deferred Revenue)",
                    "allowance": "ค่าเผื่อหนี้สงสัยจะสูญ (Allowance for Doubtful Accounts)",
                }[t],
                amount=Decimal(0),
                status="pending",
            ))

    return items


async def post_adjustment(
    data: AdjustmentIn,
    ctx: AppContext,
    db: AsyncSession,
) -> str:
    """บันทึก adjusting entry."""
    if not ctx.can_post:
        raise PermissionError("ไม่มีสิทธิ์")

    # ใช้ preset accounts ถ้าไม่ระบุ
    preset = _ADJUSTING_ACCOUNTS.get(data.item_type)
    dr_code = data.debit_account or (preset[0] if preset else "6999")
    cr_code = data.credit_account or (preset[1] if preset else "2199")

    lines = [
        JournalLineInput(account_code=dr_code, side=DrCr.DR, amount=data.amount,
                         description=data.description),
        JournalLineInput(account_code=cr_code, side=DrCr.CR, amount=data.amount,
                         description=data.description),
    ]
    entry = JournalEntryInput(
        journal_type=JournalType.GJ,
        entry_date=ctx.period,
        description=f"[Adjusting] {data.description}",
        lines=lines,
        source_module="adjusting",
        source_id=data.source_id,
    )
    journal_no = await PostingEngine(db).post(entry, ctx)

    # บันทึกใน AdjustingEntry
    p = await _get_period(ctx.period, db)
    ae = AdjustingEntry(
        period_id=p.id,
        item_type=data.item_type,
        description=data.description,
        amount=data.amount,
        status="posted",
        journal_no=journal_no,
        source_id=data.source_id,
        created_by=ctx.user_id,
    )
    db.add(ae)
    return journal_no
