#!/bin/bash
# init_db.sh — Initialize database and seed starter data
# Usage (local dev):   ./scripts/init_db.sh
# Usage (in Docker):   docker compose exec app bash /app/scripts/init_db.sh

set -euo pipefail

PYTHON="${PYTHON:-python}"
echo "============================================================"
echo "  AccCloud — Database Initialization"
echo "============================================================"

# ── 1. Run Alembic migrations ─────────────────────────────────────────────────
echo ""
echo "[init] Running database migrations..."
$PYTHON -m alembic upgrade head
echo "[init] Migrations complete."

# ── 2. Seed via Python ────────────────────────────────────────────────────────
echo ""
echo "[init] Seeding starter data..."
$PYTHON - <<'PYEOF'
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

async def seed():
    from app.database import init_shared_db, shared_db_session
    from app.platform.auth import hash_password

    await init_shared_db()

    async with shared_db_session() as session:
        from sqlalchemy import select, text
        from app.platform.models import Firm, Company, Branch, User, UserPermission
        from app.context import UserRole
        from datetime import date

        # ── Firm ──────────────────────────────────────────────────────────────
        existing_firm = await session.scalar(select(Firm).where(Firm.id == 1))
        if not existing_firm:
            firm = Firm(id=1, name="AccCloud Demo Firm", slug="demo",
                        is_active=True, plan="pro")
            session.add(firm)
            await session.flush()
            print(f"  [seed] Firm created: {firm.name}")

        # ── Company ───────────────────────────────────────────────────────────
        existing_co = await session.scalar(select(Company).where(Company.id == 1))
        if not existing_co:
            company = Company(
                id=1, firm_id=1,
                name="บริษัท เดโม จำกัด",
                tax_id="0105560000001",
                fiscal_year_start=1,
                is_active=True,
            )
            session.add(company)
            await session.flush()
            print(f"  [seed] Company created: {company.name}")

        # ── Branch ────────────────────────────────────────────────────────────
        existing_br = await session.scalar(select(Branch).where(Branch.id == 1))
        if not existing_br:
            branch = Branch(id=1, company_id=1, name="สำนักงานใหญ่",
                            is_main=True, is_active=True)
            session.add(branch)
            await session.flush()
            print("  [seed] Branch created: สำนักงานใหญ่")

        # ── Admin user ────────────────────────────────────────────────────────
        existing_user = await session.scalar(select(User).where(User.username == "admin"))
        if not existing_user:
            user = User(
                username="admin",
                email="admin@acccloud.local",
                full_name="System Administrator",
                hashed_password=hash_password("admin1234"),
                firm_id=1,
                is_active=True,
                is_superuser=True,
            )
            session.add(user)
            await session.flush()

            perm = UserPermission(
                user_id=user.id,
                company_id=1,
                branch_id=1,
                role=UserRole.FIRM_ADMIN,
                current_period=date.today().replace(day=1),
            )
            session.add(perm)
            print(f"  [seed] Admin user created: admin / admin1234")

        await session.commit()

    # ── Company DB + COA ──────────────────────────────────────────────────────
    from app.database import init_company_db, get_company_db_url
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
    from sqlalchemy.orm import sessionmaker

    print("\n[init] Initializing company database...")
    await init_company_db(firm_id=1, company_id=1)

    engine = create_async_engine(get_company_db_url(1, 1))
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        from app.core.models import ChartOfAccount
        from sqlalchemy import select

        count = await session.scalar(
            select(ChartOfAccount).where(ChartOfAccount.id > 0).with_only_columns(
                __import__('sqlalchemy').func.count()
            )
        )

        if count == 0:
            print("[init] Seeding Chart of Accounts (Thai SME standard)...")
            coas = _get_coa_seed()
            for c in coas:
                session.add(ChartOfAccount(**c))
            await session.commit()
            print(f"  [seed] {len(coas)} accounts created")
        else:
            print(f"  [skip] COA already has {count} accounts")

    await engine.dispose()
    print("\n[init] Done!")

def _get_coa_seed():
    return [
        # 1xxx — Assets
        {"code":"1100","name":"สินทรัพย์หมุนเวียน","category":"1","normal_balance":"DR","is_header":True},
        {"code":"1101","name":"เงินสด","category":"1","normal_balance":"DR","parent_code":"1100"},
        {"code":"1102","name":"เงินฝากธนาคาร","category":"1","normal_balance":"DR","parent_code":"1100"},
        {"code":"1103","name":"เงินฝากออมทรัพย์","category":"1","normal_balance":"DR","parent_code":"1100"},
        {"code":"1110","name":"ลูกหนี้การค้า","category":"1","normal_balance":"DR","parent_code":"1100"},
        {"code":"1111","name":"ค่าเผื่อหนี้สงสัยจะสูญ","category":"1","normal_balance":"CR","parent_code":"1100"},
        {"code":"1120","name":"สินค้าคงเหลือ","category":"1","normal_balance":"DR","parent_code":"1100"},
        {"code":"1130","name":"วัตถุดิบ","category":"1","normal_balance":"DR","parent_code":"1100"},
        {"code":"1150","name":"ค่าใช้จ่ายล่วงหน้า","category":"1","normal_balance":"DR","parent_code":"1100"},
        {"code":"1160","name":"ภาษีมูลค่าเพิ่มซื้อ","category":"1","normal_balance":"DR","parent_code":"1100"},
        {"code":"1170","name":"ภาษีถูกหักณที่จ่าย","category":"1","normal_balance":"DR","parent_code":"1100"},
        {"code":"1200","name":"สินทรัพย์ไม่หมุนเวียน","category":"1","normal_balance":"DR","is_header":True},
        {"code":"1201","name":"ที่ดิน","category":"1","normal_balance":"DR","parent_code":"1200"},
        {"code":"1210","name":"อาคาร","category":"1","normal_balance":"DR","parent_code":"1200"},
        {"code":"1211","name":"ค่าเสื่อมราคาสะสม-อาคาร","category":"1","normal_balance":"CR","parent_code":"1200"},
        {"code":"1220","name":"เครื่องจักรและอุปกรณ์","category":"1","normal_balance":"DR","parent_code":"1200"},
        {"code":"1221","name":"ค่าเสื่อมราคาสะสม-เครื่องจักร","category":"1","normal_balance":"CR","parent_code":"1200"},
        {"code":"1230","name":"เครื่องใช้สำนักงาน","category":"1","normal_balance":"DR","parent_code":"1200"},
        {"code":"1231","name":"ค่าเสื่อมราคาสะสม-เครื่องใช้สำนักงาน","category":"1","normal_balance":"CR","parent_code":"1200"},
        {"code":"1240","name":"ยานพาหนะ","category":"1","normal_balance":"DR","parent_code":"1200"},
        {"code":"1241","name":"ค่าเสื่อมราคาสะสม-ยานพาหนะ","category":"1","normal_balance":"CR","parent_code":"1200"},
        {"code":"1601","name":"สินทรัพย์ถาวรสุทธิ (รวม)","category":"1","normal_balance":"DR","parent_code":"1200"},
        # 2xxx — Liabilities
        {"code":"2100","name":"หนี้สินหมุนเวียน","category":"2","normal_balance":"CR","is_header":True},
        {"code":"2101","name":"เจ้าหนี้การค้า","category":"2","normal_balance":"CR","parent_code":"2100"},
        {"code":"2102","name":"เจ้าหนี้อื่น","category":"2","normal_balance":"CR","parent_code":"2100"},
        {"code":"2110","name":"ภาษีมูลค่าเพิ่มขาย","category":"2","normal_balance":"CR","parent_code":"2100"},
        {"code":"2120","name":"ภาษีเงินได้หัก ณ ที่จ่าย (ค้างจ่าย)","category":"2","normal_balance":"CR","parent_code":"2100"},
        {"code":"2130","name":"เงินประกันสังคมนำส่ง","category":"2","normal_balance":"CR","parent_code":"2100"},
        {"code":"2140","name":"รายได้รับล่วงหน้า","category":"2","normal_balance":"CR","parent_code":"2100"},
        {"code":"2150","name":"ค่าใช้จ่ายค้างจ่าย","category":"2","normal_balance":"CR","parent_code":"2100"},
        {"code":"2199","name":"หนี้สินค้างจ่ายอื่น","category":"2","normal_balance":"CR","parent_code":"2100"},
        {"code":"2200","name":"หนี้สินไม่หมุนเวียน","category":"2","normal_balance":"CR","is_header":True},
        {"code":"2201","name":"เงินกู้ยืมระยะยาว","category":"2","normal_balance":"CR","parent_code":"2200"},
        {"code":"2210","name":"หนี้สินเช่าการเงิน","category":"2","normal_balance":"CR","parent_code":"2200"},
        # 3xxx — Equity
        {"code":"3000","name":"ส่วนของผู้ถือหุ้น","category":"3","normal_balance":"CR","is_header":True},
        {"code":"3001","name":"ทุนจดทะเบียน","category":"3","normal_balance":"CR","parent_code":"3000"},
        {"code":"3002","name":"ส่วนเกินมูลค่าหุ้น","category":"3","normal_balance":"CR","parent_code":"3000"},
        {"code":"3010","name":"กำไรสะสม","category":"3","normal_balance":"CR","parent_code":"3000"},
        {"code":"3011","name":"กำไร(ขาดทุน)ปีปัจจุบัน","category":"3","normal_balance":"CR","parent_code":"3000"},
        # 4xxx — Revenue
        {"code":"4000","name":"รายได้","category":"4","normal_balance":"CR","is_header":True},
        {"code":"4001","name":"รายได้จากการขาย","category":"4","normal_balance":"CR","parent_code":"4000"},
        {"code":"4002","name":"รายได้จากการให้บริการ","category":"4","normal_balance":"CR","parent_code":"4000"},
        {"code":"4010","name":"รายได้อื่น","category":"4","normal_balance":"CR","parent_code":"4000"},
        {"code":"4011","name":"ดอกเบี้ยรับ","category":"4","normal_balance":"CR","parent_code":"4000"},
        {"code":"4020","name":"กำไรจากการขายสินทรัพย์","category":"4","normal_balance":"CR","parent_code":"4000"},
        # 5xxx — COGS
        {"code":"5000","name":"ต้นทุนขาย","category":"5","normal_balance":"DR","is_header":True},
        {"code":"5001","name":"ต้นทุนสินค้า","category":"5","normal_balance":"DR","parent_code":"5000"},
        {"code":"5002","name":"ต้นทุนงานบริการ","category":"5","normal_balance":"DR","parent_code":"5000"},
        # 6xxx — Expenses
        {"code":"6000","name":"ค่าใช้จ่ายในการดำเนินงาน","category":"6","normal_balance":"DR","is_header":True},
        {"code":"6001","name":"เงินเดือนและค่าจ้าง","category":"6","normal_balance":"DR","parent_code":"6000"},
        {"code":"6002","name":"ค่าล่วงเวลา","category":"6","normal_balance":"DR","parent_code":"6000"},
        {"code":"6003","name":"ประกันสังคม (ส่วนนายจ้าง)","category":"6","normal_balance":"DR","parent_code":"6000"},
        {"code":"6010","name":"ค่าเช่า","category":"6","normal_balance":"DR","parent_code":"6000"},
        {"code":"6020","name":"ค่าสาธารณูปโภค","category":"6","normal_balance":"DR","parent_code":"6000"},
        {"code":"6030","name":"ค่าโทรศัพท์และอินเทอร์เน็ต","category":"6","normal_balance":"DR","parent_code":"6000"},
        {"code":"6040","name":"ค่าซ่อมแซมและบำรุงรักษา","category":"6","normal_balance":"DR","parent_code":"6000"},
        {"code":"6050","name":"ค่าพัสดุและเครื่องใช้สำนักงาน","category":"6","normal_balance":"DR","parent_code":"6000"},
        {"code":"6060","name":"ค่าโฆษณาและประชาสัมพันธ์","category":"6","normal_balance":"DR","parent_code":"6000"},
        {"code":"6070","name":"ค่าขนส่งและเดินทาง","category":"6","normal_balance":"DR","parent_code":"6000"},
        {"code":"6080","name":"ค่าประกันภัย","category":"6","normal_balance":"DR","parent_code":"6000"},
        {"code":"6090","name":"ค่าวิชาชีพ (ตรวจสอบบัญชี/กฎหมาย)","category":"6","normal_balance":"DR","parent_code":"6000"},
        {"code":"6100","name":"ค่าเสื่อมราคา","category":"6","normal_balance":"DR","parent_code":"6000"},
        {"code":"6601","name":"ค่าเสื่อมราคา (สำหรับปรับปรุง)","category":"6","normal_balance":"DR","parent_code":"6000"},
        {"code":"6999","name":"ค่าใช้จ่ายค้างจ่ายอื่น","category":"6","normal_balance":"DR","parent_code":"6000"},
        # 7xxx — Finance costs
        {"code":"7000","name":"ต้นทุนทางการเงิน","category":"7","normal_balance":"DR","is_header":True},
        {"code":"7001","name":"ดอกเบี้ยจ่าย","category":"7","normal_balance":"DR","parent_code":"7000"},
        {"code":"7002","name":"ค่าธรรมเนียมธนาคาร","category":"7","normal_balance":"DR","parent_code":"7000"},
        {"code":"7010","name":"ขาดทุนจากอัตราแลกเปลี่ยน","category":"7","normal_balance":"DR","parent_code":"7000"},
        # 8xxx — Tax / Other
        {"code":"8001","name":"ภาษีเงินได้นิติบุคคล","category":"8","normal_balance":"DR"},
        {"code":"8002","name":"ภาษีหัก ณ ที่จ่าย (จ่าย)","category":"8","normal_balance":"DR"},
    ]

asyncio.run(seed())
PYEOF

echo ""
echo "============================================================"
echo "  Initialization complete!"
echo "  Login: admin / admin1234"
echo "============================================================"
