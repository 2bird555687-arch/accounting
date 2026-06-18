"""FA โ€” Fixed Asset Service (create / update / dispose)."""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.fa.models import ASSET_CATEGORY_ACCOUNTS, FixedAsset
from app.modules.fa.schemas import AssetCreate, AssetOut, AssetUpdate, DisposeAssetIn
from app.context import AppContext
from app.core.engine import PostingEngine, JournalLineInput as JournalLineIn


async def _next_asset_code(company_id: int, db: AsyncSession) -> str:
    from sqlalchemy import func as sqlfunc
    count = await db.scalar(
        select(sqlfunc.count()).select_from(FixedAsset).where(
            FixedAsset.company_id == company_id,
        )
    )
    return f"FA-{(count or 0) + 1:04d}"


class AssetService:

    @staticmethod
    async def create_asset(data: AssetCreate, ctx: AppContext, db: AsyncSession) -> AssetOut:
        if ctx.user_role not in ("firm_admin", "accountant"):
            raise PermissionError("เธ•เนเธญเธเธเธฒเธฃเธชเธดเธ—เธเธดเน accountant เธเธถเนเธเนเธ")

        # เธ•เธฃเธงเธ asset_code เธเนเธณ
        existing = await db.scalar(
            select(FixedAsset).where(
                FixedAsset.company_id == ctx.company_id,
                FixedAsset.asset_code == data.asset_code,
            )
        )
        if existing:
            raise ValueError(f"เธฃเธซเธฑเธชเธชเธดเธเธ—เธฃเธฑเธเธขเน '{data.asset_code}' เธกเธตเธญเธขเธนเนเนเธฅเนเธง")

        # เธเธณเธซเธเธ”เธเธฑเธเธเธตเธเธฒเธ category
        cat = ASSET_CATEGORY_ACCOUNTS.get(data.category, ASSET_CATEGORY_ACCOUNTS["other"])
        asset_account = data.asset_account or cat[0]
        acc_depr_account = data.acc_depr_account or cat[1]
        depr_expense_account = data.depr_expense_account or "6505"

        asset = FixedAsset(
            company_id=ctx.company_id,
            branch_id=ctx.branch_id,
            asset_code=data.asset_code,
            asset_name=data.asset_name,
            description=data.description,
            serial_no=data.serial_no,
            location=data.location,
            category=data.category,
            asset_account=asset_account,
            acc_depr_account=acc_depr_account,
            depr_expense_account=depr_expense_account,
            purchase_date=data.purchase_date,
            cost=data.cost,
            salvage_value=data.salvage_value,
            useful_life_months=data.useful_life_months,
            depr_method=data.depr_method,
            declining_rate=data.declining_rate,
            accumulated_depr=Decimal(0),
            book_value=data.cost,
            months_depreciated=0,
            status="active",
            created_by=ctx.user_id,
        )
        db.add(asset)
        await db.flush()

        # Journal เธเธทเนเธญเธชเธดเธเธ—เธฃเธฑเธเธขเน: Dr asset_account | Cr credit_account (เน€เธเนเธฒเธซเธเธตเน/เน€เธเธดเธเธชเธ”)
        lines = [
            JournalLineIn(account_code=asset_account, dr_cr="DR", amount=data.cost),
            JournalLineIn(account_code=data.credit_account, dr_cr="CR", amount=data.cost),
        ]
        je = await PostingEngine(db).post(
            ctx=ctx,
            journal_type="GJ",
            lines=lines,
            description=f"เธเธทเนเธญเธชเธดเธเธ—เธฃเธฑเธเธขเน {data.asset_code} {data.asset_name}",
            source_module="FA",
            source_id=asset.id,
        )
        asset.purchase_journal_no = je.entry_no

        await db.flush()
        await db.refresh(asset)
        return AssetOut.model_validate(asset)

    @staticmethod
    async def list_assets(
        ctx: AppContext,
        db: AsyncSession,
        status: str | None = None,
        skip: int = 0,
        limit: int = 100,
    ) -> list[AssetOut]:
        q = select(FixedAsset).where(FixedAsset.company_id == ctx.company_id)
        if status:
            q = q.where(FixedAsset.status == status)
        q = q.order_by(FixedAsset.asset_code).offset(skip).limit(limit)
        rows = await db.scalars(q)
        return [AssetOut.model_validate(r) for r in rows]

    @staticmethod
    async def get_asset(asset_id: int, ctx: AppContext, db: AsyncSession) -> AssetOut:
        a = await db.scalar(
            select(FixedAsset).where(
                FixedAsset.id == asset_id,
                FixedAsset.company_id == ctx.company_id,
            )
        )
        if not a:
            raise ValueError(f"เนเธกเนเธเธเธชเธดเธเธ—เธฃเธฑเธเธขเน {asset_id}")
        return AssetOut.model_validate(a)

    @staticmethod
    async def update_asset(
        asset_id: int, data: AssetUpdate, ctx: AppContext, db: AsyncSession
    ) -> AssetOut:
        if ctx.user_role not in ("firm_admin", "accountant"):
            raise PermissionError("เธ•เนเธญเธเธเธฒเธฃเธชเธดเธ—เธเธดเน accountant เธเธถเนเธเนเธ")

        a = await db.scalar(
            select(FixedAsset).where(
                FixedAsset.id == asset_id,
                FixedAsset.company_id == ctx.company_id,
            )
        )
        if not a:
            raise ValueError(f"เนเธกเนเธเธเธชเธดเธเธ—เธฃเธฑเธเธขเน {asset_id}")
        if a.status == "disposed":
            raise ValueError("เนเธกเนเธชเธฒเธกเธฒเธฃเธ–เนเธเนเนเธเธชเธดเธเธ—เธฃเธฑเธเธขเนเธ—เธตเนเธ•เธฑเธ”เธเธณเธซเธเนเธฒเธขเนเธฅเนเธง")

        for field, val in data.model_dump(exclude_none=True).items():
            setattr(a, field, val)

        await db.flush()
        await db.refresh(a)
        return AssetOut.model_validate(a)

    @staticmethod
    async def dispose_asset(
        asset_id: int, data: DisposeAssetIn, ctx: AppContext, db: AsyncSession
    ) -> AssetOut:
        """เธ•เธฑเธ”เธเธณเธซเธเนเธฒเธขเธชเธดเธเธ—เธฃเธฑเธเธขเน (Disposal).

        Journal:
            Dr acc_depr_account (เธเนเธฒเน€เธชเธทเนเธญเธกเธชเธฐเธชเธก)
            Dr proceeds_account (เน€เธเธดเธเธชเธ” เธ–เนเธฒเธกเธต proceeds)
            Dr 6506 (เธเธฒเธ”เธ—เธธเธเธเธฒเธเธเธฒเธฃเธเธณเธซเธเนเธฒเธข เธ–เนเธฒ proceeds < book_value)
          Cr asset_account (เธฃเธฒเธเธฒเธ—เธธเธ)
          Cr 7401 (เธเธณเนเธฃเธเธฒเธเธเธฒเธฃเธเธณเธซเธเนเธฒเธข เธ–เนเธฒ proceeds > book_value)
        """
        if ctx.user_role not in ("firm_admin", "accountant"):
            raise PermissionError("เธ•เนเธญเธเธเธฒเธฃเธชเธดเธ—เธเธดเน accountant เธเธถเนเธเนเธ")

        a = await db.scalar(
            select(FixedAsset).where(
                FixedAsset.id == asset_id,
                FixedAsset.company_id == ctx.company_id,
            )
        )
        if not a:
            raise ValueError(f"เนเธกเนเธเธเธชเธดเธเธ—เธฃเธฑเธเธขเน {asset_id}")
        if a.status == "disposed":
            raise ValueError("เธชเธดเธเธ—เธฃเธฑเธเธขเนเธเธตเนเธ–เธนเธเธ•เธฑเธ”เธเธณเธซเธเนเธฒเธขเนเธฅเนเธง")

        book_value = a.book_value
        proceeds = data.proceeds
        gain_loss = proceeds - book_value  # เธเธงเธ = เธเธณเนเธฃ, เธฅเธ = เธเธฒเธ”เธ—เธธเธ

        lines: list[JournalLineIn] = []

        # Dr เธเนเธฒเน€เธชเธทเนเธญเธกเธชเธฐเธชเธก (เธฅเนเธฒเธเธญเธญเธ)
        if a.accumulated_depr > 0 and a.acc_depr_account:
            lines.append(JournalLineIn(
                account_code=a.acc_depr_account, dr_cr="DR",
                amount=a.accumulated_depr,
            ))

        # Dr เน€เธเธดเธเธชเธ” (เธ–เนเธฒเนเธ”เนเธฃเธฑเธ)
        if proceeds > 0:
            lines.append(JournalLineIn(
                account_code=data.proceeds_account, dr_cr="DR", amount=proceeds,
            ))

        # Dr เธเธฒเธ”เธ—เธธเธ (เธ–เนเธฒ proceeds < book_value)
        if gain_loss < 0:
            lines.append(JournalLineIn(
                account_code="6506", dr_cr="DR",
                amount=abs(gain_loss).quantize(Decimal("0.01"), ROUND_HALF_UP),
            ))

        # Cr เธฃเธฒเธเธฒเธ—เธธเธเธชเธดเธเธ—เธฃเธฑเธเธขเน (เธฅเนเธฒเธเธญเธญเธ)
        lines.append(JournalLineIn(account_code=a.asset_account, dr_cr="CR", amount=a.cost))

        # Cr เธเธณเนเธฃเธเธฒเธเธเธฒเธฃเธเธณเธซเธเนเธฒเธข
        if gain_loss > 0:
            lines.append(JournalLineIn(
                account_code="7401", dr_cr="CR",
                amount=gain_loss.quantize(Decimal("0.01"), ROUND_HALF_UP),
            ))

        je = await PostingEngine(db).post(
            ctx=ctx,
            journal_type="GJ",
            lines=lines,
            description=f"เธ•เธฑเธ”เธเธณเธซเธเนเธฒเธขเธชเธดเธเธ—เธฃเธฑเธเธขเน {a.asset_code} {a.asset_name}",
            source_module="FA",
            source_id=a.id,
        )

        a.status = "disposed"
        a.disposed_at = data.disposal_date
        a.disposal_proceeds = proceeds
        a.disposal_journal_no = je.entry_no
        a.book_value = Decimal(0)

        await db.flush()
        await db.refresh(a)
        return AssetOut.model_validate(a)


