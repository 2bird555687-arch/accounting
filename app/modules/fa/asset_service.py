"""FA — Fixed Asset Service (create / update / dispose)."""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import func as sqlfunc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.context import AppContext, DrCr, JournalType
from app.core.engine import (
    JournalEntryInput,
    JournalLineInput,
    PostingEngine,
    PostingError,
)
from app.modules.fa.models import ASSET_CATEGORY_ACCOUNTS, FixedAsset
from app.modules.fa.schemas import AssetCreate, AssetOut, AssetUpdate, DisposeAssetIn


async def _next_asset_code(company_id: int, db: AsyncSession) -> str:
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
            raise PermissionError("ต้องการสิทธิ์ accountant ขึ้นไป")

        existing = await db.scalar(
            select(FixedAsset).where(
                FixedAsset.company_id == ctx.company_id,
                FixedAsset.asset_code == data.asset_code,
            )
        )
        if existing:
            raise ValueError(f"รหัสสินทรัพย์ '{data.asset_code}' มีอยู่แล้ว")

        # กำหนดบัญชีตาม category (override ได้)
        cat = ASSET_CATEGORY_ACCOUNTS.get(data.category, ASSET_CATEGORY_ACCOUNTS["other"])
        asset_account = data.asset_account or cat[0]
        acc_depr_account = data.acc_depr_account or cat[1]
        depr_expense_account = data.depr_expense_account or "6504"

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

        # Journal ตอนซื้อ: Dr asset_account | Cr credit_account (เจ้าหนี้/เงินสด)
        entry = JournalEntryInput(
            journal_type=JournalType.GJ,
            entry_date=data.purchase_date,
            description=f"ซื้อสินทรัพย์ {data.asset_code} {data.asset_name}",
            reference=data.payment_reference or "FA-PURCHASE",
            source_module="fa",
            source_id=asset.id,
            lines=[
                JournalLineInput(account_code=asset_account, side=DrCr.DR, amount=data.cost),
                JournalLineInput(account_code=data.credit_account, side=DrCr.CR, amount=data.cost),
            ],
        )
        try:
            entry_no = await PostingEngine(db).post(entry, ctx)
        except PostingError as e:
            raise ValueError(str(e))
        asset.purchase_journal_no = entry_no

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
            raise ValueError(f"ไม่พบสินทรัพย์ {asset_id}")
        return AssetOut.model_validate(a)

    @staticmethod
    async def update_asset(
        asset_id: int, data: AssetUpdate, ctx: AppContext, db: AsyncSession
    ) -> AssetOut:
        if ctx.user_role not in ("firm_admin", "accountant"):
            raise PermissionError("ต้องการสิทธิ์ accountant ขึ้นไป")

        a = await db.scalar(
            select(FixedAsset).where(
                FixedAsset.id == asset_id,
                FixedAsset.company_id == ctx.company_id,
            )
        )
        if not a:
            raise ValueError(f"ไม่พบสินทรัพย์ {asset_id}")
        if a.status == "disposed":
            raise ValueError("ไม่สามารถแก้ไขสินทรัพย์ที่ตัดจำหน่ายแล้ว")

        for field, val in data.model_dump(exclude_none=True).items():
            setattr(a, field, val)

        await db.flush()
        await db.refresh(a)
        return AssetOut.model_validate(a)

    @staticmethod
    async def dispose_asset(
        asset_id: int, data: DisposeAssetIn, ctx: AppContext, db: AsyncSession
    ) -> AssetOut:
        """ตัดจำหน่ายสินทรัพย์ (Disposal).

        Journal:
            Dr acc_depr_account (ค่าเสื่อมสะสม)
            Dr proceeds_account (เงินสด ถ้ามี proceeds)
            Dr 7104 (ขาดทุนจากการขายสินทรัพย์ ถ้า proceeds < book_value)
          Cr asset_account (ราคาทุน)
          Cr 4202 (กำไรจากการขายสินทรัพย์ ถ้า proceeds > book_value)
        """
        if ctx.user_role not in ("firm_admin", "accountant"):
            raise PermissionError("ต้องการสิทธิ์ accountant ขึ้นไป")

        a = await db.scalar(
            select(FixedAsset).where(
                FixedAsset.id == asset_id,
                FixedAsset.company_id == ctx.company_id,
            )
        )
        if not a:
            raise ValueError(f"ไม่พบสินทรัพย์ {asset_id}")
        if a.status == "disposed":
            raise ValueError("สินทรัพย์นี้ถูกตัดจำหน่ายแล้ว")

        book_value = a.book_value
        proceeds = data.proceeds
        gain_loss = proceeds - book_value  # บวก = กำไร, ลบ = ขาดทุน

        lines: list[JournalLineInput] = []

        # Dr ค่าเสื่อมสะสม (ล้างออก)
        if a.accumulated_depr > 0 and a.acc_depr_account:
            lines.append(JournalLineInput(
                account_code=a.acc_depr_account, side=DrCr.DR,
                amount=a.accumulated_depr,
            ))

        # Dr เงินสด (ถ้าได้รับ)
        if proceeds > 0:
            lines.append(JournalLineInput(
                account_code=data.proceeds_account, side=DrCr.DR, amount=proceeds,
            ))

        # Dr ขาดทุน (ถ้า proceeds < book_value)
        if gain_loss < 0:
            lines.append(JournalLineInput(
                account_code="7104", side=DrCr.DR,
                amount=abs(gain_loss).quantize(Decimal("0.01"), ROUND_HALF_UP),
            ))

        # Cr ราคาทุนสินทรัพย์ (ล้างออก)
        lines.append(JournalLineInput(account_code=a.asset_account, side=DrCr.CR, amount=a.cost))

        # Cr กำไรจากการขายสินทรัพย์
        if gain_loss > 0:
            lines.append(JournalLineInput(
                account_code="4202", side=DrCr.CR,
                amount=gain_loss.quantize(Decimal("0.01"), ROUND_HALF_UP),
            ))

        entry = JournalEntryInput(
            journal_type=JournalType.GJ,
            entry_date=data.disposal_date,
            description=f"ตัดจำหน่ายสินทรัพย์ {a.asset_code} {a.asset_name}",
            reference="FA-DISPOSAL",
            source_module="fa",
            source_id=a.id,
            lines=lines,
        )
        try:
            entry_no = await PostingEngine(db).post(entry, ctx)
        except PostingError as e:
            raise ValueError(str(e))

        a.status = "disposed"
        a.disposed_at = data.disposal_date
        a.disposal_proceeds = proceeds
        a.disposal_journal_no = entry_no
        a.book_value = Decimal(0)

        await db.flush()
        await db.refresh(a)
        return AssetOut.model_validate(a)
