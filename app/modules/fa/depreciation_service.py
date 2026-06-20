"""FA — Depreciation Service (calculate / post / schedule)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.context import AppContext, DrCr, JournalType
from app.core.engine import (
    JournalEntryInput,
    JournalLineInput,
    PostingEngine,
    PostingError,
)
from app.modules.fa.models import AssetDepreciation, FixedAsset
from app.modules.fa.schemas import DeprScheduleItem, DepreciationRecordOut, PostDepreciationIn


class DepreciationService:

    @staticmethod
    async def get_schedule(
        ctx: AppContext,
        db: AsyncSession,
        fiscal_year: int,
        month: int,
        asset_ids: list[int] | None = None,
    ) -> list[DeprScheduleItem]:
        """คำนวณค่าเสื่อมราคาประจำเดือน (preview ก่อน post)."""
        q = select(FixedAsset).where(
            FixedAsset.company_id == ctx.company_id,
            FixedAsset.status == "active",
        )
        if asset_ids:
            q = q.where(FixedAsset.id.in_(asset_ids))
        assets = await db.scalars(q)

        schedule: list[DeprScheduleItem] = []
        for asset in assets:
            if not asset.depreciable:
                continue
            if asset.months_depreciated >= asset.useful_life_months:
                continue

            posted = await db.scalar(
                select(AssetDepreciation).where(
                    AssetDepreciation.asset_id == asset.id,
                    AssetDepreciation.fiscal_year == fiscal_year,
                    AssetDepreciation.month == month,
                )
            )

            if asset.depr_method == "straight_line":
                depr_amount = asset.monthly_depr_straight_line()
            else:
                depr_amount = asset.monthly_depr_declining()

            # อย่าให้เกิน book_value - salvage_value
            max_depr = asset.book_value - asset.salvage_value
            depr_amount = min(depr_amount, max_depr).quantize(Decimal("0.01"), ROUND_HALF_UP)

            if depr_amount <= 0:
                continue

            acc_after = asset.accumulated_depr + depr_amount
            bv_after = asset.book_value - depr_amount

            schedule.append(DeprScheduleItem(
                asset_id=asset.id,
                asset_code=asset.asset_code,
                asset_name=asset.asset_name,
                fiscal_year=fiscal_year,
                month=month,
                depr_amount=depr_amount,
                accumulated_depr_after=acc_after,
                book_value_after=bv_after,
                already_posted=posted is not None,
            ))

        return schedule

    @staticmethod
    async def post_depreciation(
        data: PostDepreciationIn, ctx: AppContext, db: AsyncSession
    ) -> list[DepreciationRecordOut]:
        """บันทึกค่าเสื่อมราคา — Dr 6504 | Cr acc_depr_account (GJ)."""
        if ctx.user_role not in ("firm_admin", "accountant"):
            raise PermissionError("ต้องการสิทธิ์ accountant ขึ้นไป")

        schedule = await DepreciationService.get_schedule(
            ctx=ctx,
            db=db,
            fiscal_year=data.fiscal_year,
            month=data.month,
            asset_ids=data.asset_ids,
        )

        # วันที่ลงบัญชี = สิ้นเดือนของงวด
        import calendar
        last_day = calendar.monthrange(data.fiscal_year, data.month)[1]
        entry_date = date(data.fiscal_year, data.month, last_day)

        records: list[DepreciationRecordOut] = []

        for item in schedule:
            if item.already_posted:
                continue

            asset = await db.scalar(select(FixedAsset).where(FixedAsset.id == item.asset_id))
            if not asset or not asset.acc_depr_account:
                continue

            entry = JournalEntryInput(
                journal_type=JournalType.GJ,
                entry_date=entry_date,
                description=f"ค่าเสื่อมราคา {asset.asset_code} {data.fiscal_year}/{data.month:02d}",
                reference="FA-DEPR",
                source_module="fa",
                source_id=asset.id,
                lines=[
                    JournalLineInput(
                        account_code=asset.depr_expense_account, side=DrCr.DR, amount=item.depr_amount
                    ),
                    JournalLineInput(
                        account_code=asset.acc_depr_account, side=DrCr.CR, amount=item.depr_amount
                    ),
                ],
            )
            try:
                entry_no = await PostingEngine(db).post(entry, ctx)
            except PostingError as e:
                raise ValueError(str(e))

            # อัปเดต asset
            asset.accumulated_depr = item.accumulated_depr_after
            asset.book_value = item.book_value_after
            asset.months_depreciated += 1

            if asset.months_depreciated >= asset.useful_life_months:
                asset.status = "fully_depreciated"

            rec = AssetDepreciation(
                asset_id=asset.id,
                fiscal_year=data.fiscal_year,
                month=data.month,
                depr_amount=item.depr_amount,
                accumulated_depr_after=item.accumulated_depr_after,
                book_value_after=item.book_value_after,
                journal_entry_no=entry_no,
            )
            db.add(rec)
            await db.flush()
            await db.refresh(rec)
            records.append(DepreciationRecordOut.model_validate(rec))

        return records

    @staticmethod
    async def list_records(
        ctx: AppContext,
        db: AsyncSession,
        asset_id: int | None = None,
        fiscal_year: int | None = None,
    ) -> list[DepreciationRecordOut]:
        q = select(AssetDepreciation).join(
            FixedAsset, AssetDepreciation.asset_id == FixedAsset.id
        ).where(FixedAsset.company_id == ctx.company_id)

        if asset_id:
            q = q.where(AssetDepreciation.asset_id == asset_id)
        if fiscal_year:
            q = q.where(AssetDepreciation.fiscal_year == fiscal_year)

        q = q.order_by(AssetDepreciation.asset_id, AssetDepreciation.fiscal_year, AssetDepreciation.month)
        rows = await db.scalars(q)
        return [DepreciationRecordOut.model_validate(r) for r in rows]
