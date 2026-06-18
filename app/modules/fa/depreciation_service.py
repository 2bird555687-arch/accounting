"""FA โ€” Depreciation Service (calculate / post / schedule)."""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.fa.models import AssetDepreciation, FixedAsset
from app.modules.fa.schemas import DeprScheduleItem, DepreciationRecordOut, PostDepreciationIn
from app.context import AppContext
from app.core.engine import PostingEngine, JournalLineInput as JournalLineIn


class DepreciationService:

    @staticmethod
    async def get_schedule(
        ctx: AppContext,
        db: AsyncSession,
        fiscal_year: int,
        month: int,
        asset_ids: list[int] | None = None,
    ) -> list[DeprScheduleItem]:
        """เธเธณเธเธงเธ“เธเนเธฒเน€เธชเธทเนเธญเธกเธฃเธฒเธเธฒเธเธฃเธฐเธเธณเน€เธ”เธทเธญเธ (preview เธเนเธญเธ post)."""
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

            # เธ•เธฃเธงเธเธงเนเธฒ period เธเธตเน posted เนเธฅเนเธงเธซเธฃเธทเธญเธขเธฑเธ
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

            # เธญเธขเนเธฒเนเธซเนเน€เธเธดเธ book_value - salvage_value
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
        """เธเธฑเธเธ—เธถเธเธเนเธฒเน€เธชเธทเนเธญเธกเธฃเธฒเธเธฒ โ€” Dr 6505 | Cr acc_depr_account (GJ)."""
        if ctx.user_role not in ("firm_admin", "accountant"):
            raise PermissionError("เธ•เนเธญเธเธเธฒเธฃเธชเธดเธ—เธเธดเน accountant เธเธถเนเธเนเธ")

        schedule = await DepreciationService.get_schedule(
            ctx=ctx,
            db=db,
            fiscal_year=data.fiscal_year,
            month=data.month,
            asset_ids=data.asset_ids,
        )

        records: list[DepreciationRecordOut] = []

        for item in schedule:
            if item.already_posted:
                continue

            asset = await db.scalar(select(FixedAsset).where(FixedAsset.id == item.asset_id))
            if not asset or not asset.acc_depr_account:
                continue

            # Journal: Dr 6505 | Cr acc_depr_account
            lines = [
                JournalLineIn(account_code=asset.depr_expense_account, dr_cr="DR", amount=item.depr_amount),
                JournalLineIn(account_code=asset.acc_depr_account, dr_cr="CR", amount=item.depr_amount),
            ]
            je = await PostingEngine(db).post(
                ctx=ctx,
                journal_type="GJ",
                lines=lines,
                description=f"เธเนเธฒเน€เธชเธทเนเธญเธกเธฃเธฒเธเธฒ {asset.asset_code} {data.fiscal_year}/{data.month:02d}",
                source_module="FA",
                source_id=asset.id,
            )

            # เธญเธฑเธเน€เธ”เธ• asset
            asset.accumulated_depr = item.accumulated_depr_after
            asset.book_value = item.book_value_after
            asset.months_depreciated += 1

            if asset.months_depreciated >= asset.useful_life_months:
                asset.status = "fully_depreciated"

            # เธเธฑเธเธ—เธถเธ AssetDepreciation
            rec = AssetDepreciation(
                asset_id=asset.id,
                fiscal_year=data.fiscal_year,
                month=data.month,
                depr_amount=item.depr_amount,
                accumulated_depr_after=item.accumulated_depr_after,
                book_value_after=item.book_value_after,
                journal_entry_no=je.entry_no,
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


