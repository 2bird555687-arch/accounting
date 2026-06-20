"""FA — Fixed Asset Service (create / update / dispose)."""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from dateutil.relativedelta import relativedelta
from sqlalchemy import func as sqlfunc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.context import AppContext, DrCr, JournalType
from app.core.engine import (
    JournalEntryInput,
    JournalLineInput,
    PostingEngine,
    PostingError,
)
from app.modules.bank.models import BankAccount
from app.modules.fa.asset_defaults import ASSET_TYPE_DEFAULTS
from app.modules.fa.models import (
    ASSET_CATEGORY_ACCOUNTS,
    FixedAsset,
    FundingType,
    HirePurchaseInstallment,
)
from app.modules.fa.schemas import AssetCreate, AssetOut, AssetUpdate, DisposeAssetIn


# ── COA codes used for asset funding (ตรงกับ coa_template.py) ───────────────────
OWNER_EQUITY_CODE = "3101"       # ทุนชำระแล้ว
OTHER_PAYABLE_CODE = "2102"      # เจ้าหนี้อื่น
HP_PAYABLE_CODE = "2103"         # เจ้าหนี้เช่าซื้อ
INTEREST_DEFERRED_CODE = "2104"  # ดอกเบี้ยรอตัดบัญชี (contra-liability, DR-normal)
INTEREST_EXPENSE_CODE = "7101"   # ดอกเบี้ยจ่าย


def _q(v: Decimal) -> Decimal:
    return v.quantize(Decimal("0.01"), ROUND_HALF_UP)


async def _bank_coa_code(db: AsyncSession, ctx: AppContext, bank_account_id: int) -> str:
    ba = await db.scalar(
        select(BankAccount).where(
            BankAccount.id == bank_account_id,
            BankAccount.company_id == ctx.company_id,
        )
    )
    if not ba:
        raise ValueError(f"ไม่พบบัญชีธนาคาร {bank_account_id}")
    return ba.coa_account_code


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

        funding = data.funding_type
        cost = data.cost

        # ── ค่าเสื่อมทางบัญชี vs ทางภาษี (book vs tax) ─────────────────────────
        cfg = ASSET_TYPE_DEFAULTS.get(data.asset_type) if data.asset_type else None

        book_life_years = data.book_useful_life_years
        tax_life_years = data.tax_useful_life_years
        if book_life_years is None and cfg and cfg.depreciable:
            book_life_years = cfg.default_life_years
        if tax_life_years is None and cfg and cfg.depreciable:
            tax_life_years = cfg.tax_min_life_years

        # เพดานราคาทุนทางภาษีสำหรับรถยนต์นั่งส่วนบุคคล
        tax_depreciable_cost = cost
        tax_warning = None
        if cfg and cfg.has_cost_cap and cfg.cost_cap_amount and cost > cfg.cost_cap_amount:
            tax_depreciable_cost = Decimal(cfg.cost_cap_amount)
            tax_warning = (
                f"ค่าเสื่อมทางภาษีคำนวณได้เฉพาะ 1,000,000 บาทแรกตาม มาตรา 5 "
                f"พ.ร.ฎ. 145/2527 ส่วนต่าง {cost - tax_depreciable_cost:,.2f} บาท "
                f"ไม่สามารถหักเป็นรายจ่ายทางภาษีได้"
            )

        salvage = data.salvage_value
        book_monthly = (
            _q((cost - salvage) / (book_life_years * 12))
            if book_life_years else Decimal(0)
        )
        tax_monthly = (
            _q((tax_depreciable_cost - salvage) / (tax_life_years * 12))
            if tax_life_years else Decimal(0)
        )

        # ── คำนวณค่าเช่าซื้อ (ถ้า hire_purchase) ──────────────────────────────
        hp_total_price = hp_down_payment = hp_monthly_payment = hp_interest_total = None
        hp_installments = None
        if funding == FundingType.HIRE_PURCHASE.value:
            if not data.hp_total_price or not data.hp_installments or data.hp_installments < 1:
                raise ValueError("เช่าซื้อต้องระบุ hp_total_price และ hp_installments (>=1)")
            hp_total_price = data.hp_total_price
            hp_down_payment = data.hp_down_payment or Decimal(0)
            hp_installments = data.hp_installments
            financed = hp_total_price - hp_down_payment   # ยอดผ่อน (เงินต้น+ดอกเบี้ย)
            if financed <= 0:
                raise ValueError("ยอดผ่อนต้องมากกว่า 0 (hp_total_price ต้องมากกว่าเงินดาวน์)")
            # ดอกเบี้ยรวมตลอดสัญญา = ราคารวมที่จ่ายจริง − ราคาเงินสด (cost)
            hp_interest_total = _q(hp_total_price - cost)
            if hp_interest_total < 0:
                raise ValueError("ดอกเบี้ยติดลบ: hp_total_price ต้อง >= cost")
            hp_monthly_payment = _q(financed / hp_installments)

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
            cost=cost,
            salvage_value=data.salvage_value,
            useful_life_months=data.useful_life_months,
            depr_method=data.depr_method,
            declining_rate=data.declining_rate,
            accumulated_depr=Decimal(0),
            book_value=cost,
            months_depreciated=0,
            status="active",
            asset_type=data.asset_type,
            book_useful_life_years=book_life_years,
            book_monthly_depreciation=book_monthly,
            tax_useful_life_years=tax_life_years,
            tax_depreciable_cost=tax_depreciable_cost,
            tax_monthly_depreciation=tax_monthly,
            depreciation_basis=data.depreciation_basis,
            funding_type=funding,
            bank_account_id=data.bank_account_id,
            hp_total_price=hp_total_price,
            hp_down_payment=hp_down_payment,
            hp_installments=hp_installments,
            hp_monthly_payment=hp_monthly_payment,
            hp_interest_total=hp_interest_total,
            created_by=ctx.user_id,
        )
        db.add(asset)
        await db.flush()

        # ── สร้าง JE ตามแหล่งเงินทุน ──────────────────────────────────────────
        lines: list[JournalLineInput] = [
            JournalLineInput(account_code=asset_account, side=DrCr.DR, amount=cost),
        ]

        if funding == FundingType.CASH_BANK.value:
            if not data.bank_account_id:
                raise ValueError("เงินสด/ธนาคารต้องเลือกบัญชีธนาคาร")
            bank_code = await _bank_coa_code(db, ctx, data.bank_account_id)
            lines.append(JournalLineInput(account_code=bank_code, side=DrCr.CR, amount=cost))

        elif funding == FundingType.OWNER_CONTRIBUTION.value:
            lines.append(JournalLineInput(account_code=OWNER_EQUITY_CODE, side=DrCr.CR, amount=cost))

        elif funding == FundingType.OTHER_PAYABLE.value:
            lines.append(JournalLineInput(account_code=OTHER_PAYABLE_CODE, side=DrCr.CR, amount=cost))

        elif funding == FundingType.HIRE_PURCHASE.value:
            financed = hp_total_price - hp_down_payment
            if hp_interest_total > 0:
                lines.append(JournalLineInput(
                    account_code=INTEREST_DEFERRED_CODE, side=DrCr.DR, amount=hp_interest_total,
                ))
            # เจ้าหนี้เช่าซื้อ = ยอดที่ยังต้องผ่อน (รวมดอกเบี้ย)
            lines.append(JournalLineInput(
                account_code=HP_PAYABLE_CODE, side=DrCr.CR, amount=financed,
            ))
            if hp_down_payment > 0:
                if not data.bank_account_id:
                    raise ValueError("เงินดาวน์ > 0 ต้องเลือกบัญชีธนาคารที่จ่ายดาวน์")
                bank_code = await _bank_coa_code(db, ctx, data.bank_account_id)
                lines.append(JournalLineInput(
                    account_code=bank_code, side=DrCr.CR, amount=hp_down_payment,
                ))
        else:
            raise ValueError(f"funding_type ไม่ถูกต้อง: {funding}")

        entry = JournalEntryInput(
            journal_type=JournalType.GJ,
            entry_date=data.purchase_date,
            description=f"ซื้อสินทรัพย์ {data.asset_code} {data.asset_name}",
            reference=data.payment_reference or "FA-PURCHASE",
            source_module="fa",
            source_id=asset.id,
            lines=lines,
        )
        try:
            entry_no = await PostingEngine(db).post(entry, ctx)
        except PostingError as e:
            raise ValueError(str(e))
        asset.purchase_journal_no = entry_no

        # ── สร้างตารางงวดผ่อน (hire_purchase) ─────────────────────────────────
        if funding == FundingType.HIRE_PURCHASE.value:
            interest_each = _q(hp_interest_total / hp_installments)
            financed = hp_total_price - hp_down_payment
            principal_acc = Decimal(0)
            interest_acc = Decimal(0)
            for i in range(1, hp_installments + 1):
                last = i == hp_installments
                if last:
                    # งวดสุดท้าย: ปัดเศษให้ผลรวมตรงพอดี
                    payment = _q(financed - (hp_monthly_payment * (hp_installments - 1)))
                    interest_p = _q(hp_interest_total - interest_acc)
                    principal_p = _q(payment - interest_p)
                else:
                    payment = hp_monthly_payment
                    interest_p = interest_each
                    principal_p = _q(payment - interest_p)
                principal_acc += principal_p
                interest_acc += interest_p
                db.add(HirePurchaseInstallment(
                    asset_id=asset.id,
                    installment_no=i,
                    due_date=data.purchase_date + relativedelta(months=i),
                    payment_amount=payment,
                    principal_portion=principal_p,
                    interest_portion=interest_p,
                    status="PENDING",
                ))

        await db.flush()
        await db.refresh(asset)
        out = AssetOut.model_validate(asset)
        out.tax_warning = tax_warning
        return out

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

    # ── Hire Purchase Installments ──────────────────────────────────────────────

    @staticmethod
    async def list_installments(
        asset_id: int, ctx: AppContext, db: AsyncSession
    ) -> list[HirePurchaseInstallment]:
        asset = await db.scalar(
            select(FixedAsset).where(
                FixedAsset.id == asset_id,
                FixedAsset.company_id == ctx.company_id,
            )
        )
        if not asset:
            raise ValueError(f"ไม่พบสินทรัพย์ {asset_id}")
        rows = await db.scalars(
            select(HirePurchaseInstallment)
            .where(HirePurchaseInstallment.asset_id == asset_id)
            .order_by(HirePurchaseInstallment.installment_no)
        )
        return list(rows)

    @staticmethod
    async def pay_hire_purchase_installment(
        asset_id: int,
        installment_no: int,
        payment_date,
        bank_account_id: int,
        ctx: AppContext,
        db: AsyncSession,
    ) -> HirePurchaseInstallment:
        if ctx.user_role not in ("firm_admin", "accountant"):
            raise PermissionError("ต้องการสิทธิ์ accountant ขึ้นไป")

        asset = await db.scalar(
            select(FixedAsset).where(
                FixedAsset.id == asset_id,
                FixedAsset.company_id == ctx.company_id,
            )
        )
        if not asset:
            raise ValueError(f"ไม่พบสินทรัพย์ {asset_id}")

        inst = await db.scalar(
            select(HirePurchaseInstallment).where(
                HirePurchaseInstallment.asset_id == asset_id,
                HirePurchaseInstallment.installment_no == installment_no,
            )
        )
        if not inst:
            raise ValueError(f"ไม่พบงวดที่ {installment_no}")
        if inst.status == "PAID":
            raise ValueError(f"งวดที่ {installment_no} ชำระแล้ว")

        bank_code = await _bank_coa_code(db, ctx, bank_account_id)

        lines: list[JournalLineInput] = [
            JournalLineInput(account_code=HP_PAYABLE_CODE, side=DrCr.DR, amount=inst.payment_amount),
        ]
        if inst.interest_portion > 0:
            lines.append(JournalLineInput(
                account_code=INTEREST_EXPENSE_CODE, side=DrCr.DR, amount=inst.interest_portion,
            ))
            lines.append(JournalLineInput(
                account_code=INTEREST_DEFERRED_CODE, side=DrCr.CR, amount=inst.interest_portion,
            ))
        lines.append(JournalLineInput(
            account_code=bank_code, side=DrCr.CR, amount=inst.payment_amount,
        ))

        entry = JournalEntryInput(
            journal_type=JournalType.GJ,
            entry_date=payment_date,
            description=f"ชำระค่างวดเช่าซื้อ {asset.asset_code} งวดที่ {installment_no}",
            reference="FA-HP-PAY",
            source_module="fa",
            source_id=asset.id,
            lines=lines,
        )
        try:
            entry_no = await PostingEngine(db).post(entry, ctx)
        except PostingError as e:
            raise ValueError(str(e))

        inst.status = "PAID"
        inst.paid_date = payment_date
        inst.journal_ref = entry_no

        await db.flush()
        await db.refresh(inst)
        return inst
