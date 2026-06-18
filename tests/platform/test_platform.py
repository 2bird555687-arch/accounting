"""Tests สำหรับ Platform Layer — auth, firm, company, branch, user, COA template."""

from __future__ import annotations

import pytest
from datetime import date
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy import select

from app.context import AppContext, UserRole
from app.core.models import Base as CoreBase, ChartOfAccount
from app.platform.models import Base as PlatformBase, Firm, Company, Branch, User, UserPermission
from app.shared.models import Base as SharedBase


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
async def session() -> AsyncGenerator[AsyncSession, None]:
    """In-memory SQLite พร้อมตาราง platform + shared."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(PlatformBase.metadata.create_all)
        await conn.run_sync(SharedBase.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


@pytest.fixture
async def company_session() -> AsyncGenerator[AsyncSession, None]:
    """In-memory SQLite สำหรับ company DB (COA)."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(CoreBase.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


@pytest.fixture
async def seeded(session: AsyncSession):
    """Seed firm + company + branch + admin user."""
    firm = Firm(name="สำนักงานบัญชีทดสอบ", tax_id="1234567890123")
    session.add(firm)
    await session.flush()

    company = Company(
        firm_id=firm.id,
        code="TEST001",
        name="บริษัท ทดสอบ จำกัด",
        fiscal_year_start=1,
        vat_registered=True,
    )
    session.add(company)
    await session.flush()

    hq = Branch(company_id=company.id, branch_code="00000", name="สำนักงานใหญ่")
    session.add(hq)
    await session.flush()

    from app.platform.auth import hash_password
    admin = User(
        firm_id=firm.id,
        username="admin",
        email="admin@test.com",
        hashed_password=hash_password("Password123"),
        full_name="ผู้ดูแลระบบ",
        default_role="firm_admin",
        is_superuser=True,
    )
    session.add(admin)
    await session.flush()

    perm = UserPermission(
        user_id=admin.id,
        company_id=company.id,
        role="firm_admin",
        granted_by=admin.id,
    )
    session.add(perm)
    await session.commit()

    return {"firm": firm, "company": company, "hq": hq, "admin": admin}


def make_ctx(
    firm_id: int = 1,
    company_id: int = 1,
    branch_id: int = 1,
    user_id: int = 1,
    role: UserRole = UserRole.FIRM_ADMIN,
) -> AppContext:
    return AppContext(
        firm_id=firm_id,
        company_id=company_id,
        branch_id=branch_id,
        user_id=user_id,
        user_role=role,
        period=date(2026, 1, 1),
    )


# ── Tests: Auth ───────────────────────────────────────────────────────────────

class TestAuth:
    def test_hash_and_verify(self):
        from app.platform.auth import hash_password, verify_password
        hashed = hash_password("MySecret99")
        assert verify_password("MySecret99", hashed)
        assert not verify_password("WrongPass", hashed)

    def test_create_and_verify_token(self):
        from app.platform.auth import create_tokens, verify_access_token
        pair = create_tokens(
            user_id=1, firm_id=1, company_id=1, branch_id=1,
            role=UserRole.ACCOUNTANT, period=date(2026, 1, 1),
        )
        claims = verify_access_token(pair.access_token)
        assert claims.sub == "1"
        assert claims.firm_id == 1
        assert claims.role == "accountant"

    def test_invalid_token_raises(self):
        from app.platform.auth import verify_access_token
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            verify_access_token("not.a.valid.token")
        assert exc.value.status_code == 401

    def test_build_app_context(self):
        from app.platform.auth import create_tokens, verify_access_token, build_app_context
        pair = create_tokens(
            user_id=5, firm_id=2, company_id=3, branch_id=4,
            role=UserRole.JUNIOR, period=date(2026, 6, 1),
        )
        ctx = build_app_context(verify_access_token(pair.access_token))
        assert ctx.user_id == 5
        assert ctx.firm_id == 2
        assert ctx.company_id == 3
        assert ctx.branch_id == 4
        assert ctx.user_role == UserRole.JUNIOR
        assert ctx.period == date(2026, 6, 1)

    def test_refresh_token_not_usable_as_access(self):
        from app.platform.auth import create_tokens, verify_access_token
        from fastapi import HTTPException
        pair = create_tokens(
            user_id=1, firm_id=1, company_id=1, branch_id=1,
            role=UserRole.ACCOUNTANT, period=date(2026, 1, 1),
        )
        with pytest.raises(HTTPException) as exc:
            verify_access_token(pair.refresh_token)
        assert exc.value.status_code == 401


# ── Tests: FirmService ────────────────────────────────────────────────────────

class TestFirmService:
    @pytest.mark.asyncio
    async def test_create_firm(self, session: AsyncSession):
        from app.platform.firm_service import FirmCreate, FirmService
        svc = FirmService(session)
        firm = await svc.create(FirmCreate(name="ทดสอบ", tax_id="9999999999999"))
        assert firm.id is not None
        assert firm.name == "ทดสอบ"

    @pytest.mark.asyncio
    async def test_duplicate_tax_id_raises(self, session: AsyncSession, seeded):
        from app.platform.firm_service import FirmCreate, FirmService
        from fastapi import HTTPException
        svc = FirmService(session)
        with pytest.raises(HTTPException) as exc:
            await svc.create(FirmCreate(name="ซ้ำ", tax_id="1234567890123"))
        assert exc.value.status_code == 409

    @pytest.mark.asyncio
    async def test_update_firm(self, session: AsyncSession, seeded):
        from app.platform.firm_service import FirmUpdate, FirmService
        svc = FirmService(session)
        firm = seeded["firm"]
        ctx = make_ctx(firm_id=firm.id, user_id=seeded["admin"].id)
        updated = await svc.update(firm.id, FirmUpdate(phone="0812345678"), ctx)
        assert updated.phone == "0812345678"

    @pytest.mark.asyncio
    async def test_non_admin_cannot_update(self, session: AsyncSession, seeded):
        from app.platform.firm_service import FirmUpdate, FirmService
        from fastapi import HTTPException
        svc = FirmService(session)
        firm = seeded["firm"]
        ctx = make_ctx(firm_id=firm.id, role=UserRole.ACCOUNTANT)
        with pytest.raises(HTTPException) as exc:
            await svc.update(firm.id, FirmUpdate(phone="xxx"), ctx)
        assert exc.value.status_code == 403


# ── Tests: BranchService ──────────────────────────────────────────────────────

class TestBranchService:
    @pytest.mark.asyncio
    async def test_create_branch(self, session: AsyncSession, seeded):
        from app.platform.branch_service import BranchCreate, BranchService
        svc = BranchService(session)
        company = seeded["company"]
        ctx = make_ctx(firm_id=seeded["firm"].id, company_id=company.id)
        branch = await svc.create(company.id, BranchCreate(branch_code="00001", name="สาขา 1"), ctx)
        assert branch.branch_code == "00001"
        assert not branch.is_hq

    @pytest.mark.asyncio
    async def test_hq_already_exists_raises(self, session: AsyncSession, seeded):
        from app.platform.branch_service import BranchCreate, BranchService
        from fastapi import HTTPException
        svc = BranchService(session)
        company = seeded["company"]
        ctx = make_ctx(firm_id=seeded["firm"].id, company_id=company.id)
        with pytest.raises(HTTPException) as exc:
            await svc.create(company.id, BranchCreate(branch_code="00000", name="HQ ซ้ำ"), ctx)
        assert exc.value.status_code in (400, 409)  # 400=กฎ HQ, 409=ซ้ำ

    @pytest.mark.asyncio
    async def test_invalid_branch_code(self):
        from app.platform.branch_service import BranchCreate
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            BranchCreate(branch_code="ABC", name="ผิด")

    @pytest.mark.asyncio
    async def test_list_branches(self, session: AsyncSession, seeded):
        from app.platform.branch_service import BranchService
        svc = BranchService(session)
        company = seeded["company"]
        ctx = make_ctx(firm_id=seeded["firm"].id, company_id=company.id)
        branches = await svc.list_branches(company.id, ctx)
        assert len(branches) == 1
        assert branches[0].branch_code == "00000"

    @pytest.mark.asyncio
    async def test_cannot_deactivate_hq(self, session: AsyncSession, seeded):
        from app.platform.branch_service import BranchService
        from fastapi import HTTPException
        svc = BranchService(session)
        hq = seeded["hq"]
        ctx = make_ctx(
            firm_id=seeded["firm"].id,
            company_id=seeded["company"].id,
            branch_id=hq.id,
        )
        with pytest.raises(HTTPException) as exc:
            await svc.deactivate(hq.id, ctx)
        assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_junior_cannot_create_branch(self, session: AsyncSession, seeded):
        from app.platform.branch_service import BranchCreate, BranchService
        from fastapi import HTTPException
        svc = BranchService(session)
        company = seeded["company"]
        ctx = make_ctx(firm_id=seeded["firm"].id, company_id=company.id, role=UserRole.JUNIOR)
        with pytest.raises(HTTPException) as exc:
            await svc.create(company.id, BranchCreate(branch_code="00002", name="สาขา"), ctx)
        assert exc.value.status_code == 403


# ── Tests: UserService ────────────────────────────────────────────────────────

class TestUserService:
    @pytest.mark.asyncio
    async def test_register_user(self, session: AsyncSession, seeded):
        from app.platform.user_service import UserRegister, UserService
        svc = UserService(session)
        firm = seeded["firm"]
        admin = seeded["admin"]
        ctx = make_ctx(firm_id=firm.id, user_id=admin.id)
        user = await svc.register(
            firm.id,
            UserRegister(
                username="accountant1",
                email="acc@test.com",
                password="SecurePass1",
                full_name="นักบัญชี",
                default_role=UserRole.ACCOUNTANT,
            ),
            ctx,
        )
        assert user.username == "accountant1"
        assert user.default_role == "accountant"

    @pytest.mark.asyncio
    async def test_duplicate_username_raises(self, session: AsyncSession, seeded):
        from app.platform.user_service import UserRegister, UserService
        from fastapi import HTTPException
        svc = UserService(session)
        firm = seeded["firm"]
        ctx = make_ctx(firm_id=firm.id, user_id=seeded["admin"].id)
        with pytest.raises(HTTPException) as exc:
            await svc.register(firm.id, UserRegister(
                username="admin", email="other@test.com",
                password="Password123", full_name="ซ้ำ",
            ), ctx)
        assert exc.value.status_code == 409

    @pytest.mark.asyncio
    async def test_login_success(self, session: AsyncSession, seeded):
        from app.platform.user_service import UserLogin, UserService
        svc = UserService(session)
        out = await svc.login(UserLogin(
            username="admin",
            password="Password123",
            company_id=seeded["company"].id,
        ))
        assert out.access_token
        assert out.user.username == "admin"
        assert out.role == "firm_admin"

    @pytest.mark.asyncio
    async def test_login_wrong_password(self, session: AsyncSession, seeded):
        from app.platform.user_service import UserLogin, UserService
        from fastapi import HTTPException
        svc = UserService(session)
        with pytest.raises(HTTPException) as exc:
            await svc.login(UserLogin(username="admin", password="wrongpass"))
        assert exc.value.status_code == 401

    @pytest.mark.asyncio
    async def test_change_password(self, session: AsyncSession, seeded):
        from app.platform.user_service import ChangePassword, UserService
        from app.platform.auth import verify_password
        svc = UserService(session)
        admin = seeded["admin"]
        ctx = make_ctx(firm_id=seeded["firm"].id, user_id=admin.id)
        await svc.change_password(admin.id, ChangePassword(
            current_password="Password123",
            new_password="NewPass456",
        ), ctx)
        result = await session.get(User, admin.id)
        assert verify_password("NewPass456", result.hashed_password)

    @pytest.mark.asyncio
    async def test_assign_company(self, session: AsyncSession, seeded):
        from app.platform.user_service import AssignCompany, UserRegister, UserService
        svc = UserService(session)
        firm = seeded["firm"]
        admin = seeded["admin"]
        ctx = make_ctx(firm_id=firm.id, user_id=admin.id)

        # สร้าง junior user
        junior = await svc.register(firm.id, UserRegister(
            username="junior1", email="junior@test.com",
            password="Password123", full_name="ผู้ช่วย",
        ), ctx)

        # assign
        perm = await svc.assign_company(AssignCompany(
            user_id=junior.id,
            company_id=seeded["company"].id,
            role=UserRole.JUNIOR,
        ), ctx)
        assert perm.role == "junior"

    @pytest.mark.asyncio
    async def test_check_permission_post(self, session: AsyncSession, seeded):
        from app.platform.user_service import UserService
        svc = UserService(session)
        admin = seeded["admin"]
        ctx = make_ctx(
            firm_id=seeded["firm"].id,
            company_id=seeded["company"].id,
            user_id=admin.id,
        )
        can_post = await svc.check_permission(admin.id, "post", ctx)
        assert can_post is True

        can_close = await svc.check_permission(admin.id, "close_period", ctx)
        assert can_close is True


# ── Tests: COATemplateService ─────────────────────────────────────────────────

class TestCOATemplate:
    @pytest.mark.asyncio
    async def test_trading_template(self, company_session: AsyncSession):
        from app.platform.coa_template import COATemplateService
        svc = COATemplateService(company_session)
        count = await svc.apply_template("trading")
        assert count > 50  # trading มีบัญชีมากกว่า 50

        result = await company_session.execute(
            select(ChartOfAccount).where(ChartOfAccount.code == "1130")
        )
        inv = result.scalar_one_or_none()
        assert inv is not None
        assert inv.name == "สินค้าคงเหลือ"

    @pytest.mark.asyncio
    async def test_service_template_no_inventory(self, company_session: AsyncSession):
        from app.platform.coa_template import COATemplateService
        svc = COATemplateService(company_session)
        await svc.apply_template("service")

        result = await company_session.execute(
            select(ChartOfAccount).where(ChartOfAccount.code == "1130")
        )
        inv = result.scalar_one_or_none()
        assert inv is None  # service ไม่มีสินค้าคงเหลือ

    @pytest.mark.asyncio
    async def test_service_has_cost_of_service(self, company_session: AsyncSession):
        from app.platform.coa_template import COATemplateService
        svc = COATemplateService(company_session)
        await svc.apply_template("service")

        result = await company_session.execute(
            select(ChartOfAccount).where(ChartOfAccount.code == "5102")
        )
        cos = result.scalar_one_or_none()
        assert cos is not None
        assert cos.normal_balance == "DR"

    @pytest.mark.asyncio
    async def test_mixed_template_has_both(self, company_session: AsyncSession):
        from app.platform.coa_template import COATemplateService
        svc = COATemplateService(company_session)
        count = await svc.apply_template("mixed")

        result = await company_session.execute(select(ChartOfAccount))
        accs = result.scalars().all()
        codes = {a.code for a in accs}

        assert "1130" in codes   # สินค้าคงเหลือ (trading)
        assert "5102" in codes   # ต้นทุนบริการ (service)
        assert "5101" in codes   # ต้นทุนสินค้าขาย (trading)

    @pytest.mark.asyncio
    async def test_idempotent_apply(self, company_session: AsyncSession):
        """Apply ซ้ำต้องไม่เพิ่มข้อมูลซ้ำ."""
        from app.platform.coa_template import COATemplateService
        svc = COATemplateService(company_session)
        count1 = await svc.apply_template("trading")
        await company_session.commit()
        count2 = await svc.apply_template("trading")
        assert count2 == 0  # ไม่มีอะไรเพิ่ม

    @pytest.mark.asyncio
    async def test_all_accounts_are_valid(self, company_session: AsyncSession):
        """ทุก account ต้องมี normal_balance = DR หรือ CR เท่านั้น."""
        from app.platform.coa_template import COATemplateService
        svc = COATemplateService(company_session)
        await svc.apply_template("mixed")
        result = await company_session.execute(select(ChartOfAccount))
        accs = result.scalars().all()
        for acc in accs:
            assert acc.normal_balance in ("DR", "CR"), f"{acc.code} มี normal_balance ผิด"
            assert acc.category in ("1", "2", "3", "4", "5", "6", "7", "8"), \
                f"{acc.code} มี category ผิด"

    def test_list_templates(self):
        from app.platform.coa_template import COATemplateService
        templates = COATemplateService.list_templates()
        assert len(templates) == 3
        ids = [t["id"] for t in templates]
        assert "trading" in ids
        assert "service" in ids
        assert "mixed" in ids

    @pytest.mark.asyncio
    async def test_key_accounts_present_trading(self, company_session: AsyncSession):
        """ตรวจบัญชีสำคัญตาม Master Prompt."""
        from app.platform.coa_template import COATemplateService
        svc = COATemplateService(company_session)
        await svc.apply_template("trading")

        key_codes = [
            "1101", "1102", "1103",   # เงินสด + ธนาคาร
            "1110", "1112",            # ลูกหนี้ + ค่าเผื่อ
            "1130",                    # สินค้า
            "1140", "1141",            # ภาษีซื้อ + WHT ถูกหัก
            "1220", "1230", "1231",    # ที่ดิน + อาคาร + ค่าเสื่อม
            "1260", "1261",            # ยานพาหนะ + ค่าเสื่อม
            "2101",                    # เจ้าหนี้
            "2120", "2121",            # ภาษีขาย + WHT ค้างนำส่ง
            "2130",                    # เงินเดือนค้างจ่าย
            "2160",                    # เงินกู้ระยะสั้น
            "3101", "3201",            # ทุน + กำไรสะสม
            "4101",                    # รายได้ขาย
            "4201",                    # ดอกเบี้ยรับ
            "5101",                    # ต้นทุนขาย
            "6101", "6501",            # เงินเดือนขาย + บริหาร
            "7101", "7102", "7201",    # ดอกเบี้ยจ่าย + ค่าธรรมเนียม + ภาษีนิติบุคคล
        ]
        result = await company_session.execute(
            select(ChartOfAccount.code).where(
                ChartOfAccount.code.in_(key_codes)
            )
        )
        found = {r[0] for r in result.all()}
        missing = set(key_codes) - found
        assert not missing, f"บัญชีสำคัญที่หายไป: {sorted(missing)}"
