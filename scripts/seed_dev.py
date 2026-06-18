"""Seed development database — สร้างข้อมูลเริ่มต้นสำหรับ dev/test."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy.ext.asyncio import AsyncSession

from app.database import init_shared_db, init_company_db, get_shared_session
from app.platform.models import Firm, Company, Branch, User, UserPermission


async def seed() -> None:
    print("🌱 Seeding development database...")

    await init_shared_db()

    async with get_shared_session() as session:
        # Firm
        firm = Firm(
            name="บริษัท สำนักงานบัญชีตัวอย่าง จำกัด",
            tax_id="0105567012345",
            email="admin@example-firm.com",
        )
        session.add(firm)
        await session.flush()

        # Company
        company = Company(
            firm_id=firm.id,
            code="DEMO001",
            name="บริษัท เดโม่ธุรกิจ จำกัด",
            name_en="Demo Business Co., Ltd.",
            tax_id="0105567099999",
            business_type="ซื้อมาขายไป",
            fiscal_year_start=1,
            vat_registered=True,
        )
        session.add(company)
        await session.flush()

        # HQ Branch
        hq = Branch(
            company_id=company.id,
            branch_code="00000",
            name="สำนักงานใหญ่",
        )
        session.add(hq)
        await session.flush()

        # Admin user (password: admin1234 — bcrypt hash)
        from passlib.context import CryptContext
        pwd = CryptContext(schemes=["bcrypt"])
        admin = User(
            firm_id=firm.id,
            username="admin",
            email="admin@example.com",
            hashed_password=pwd.hash("admin1234"),
            full_name="ผู้ดูแลระบบ",
            default_role="firm_admin",
            is_superuser=True,
        )
        session.add(admin)
        await session.flush()

        # Permission
        perm = UserPermission(
            user_id=admin.id,
            company_id=company.id,
            role="firm_admin",
            granted_by=admin.id,
        )
        session.add(perm)
        print(f"  ✓ Firm: {firm.name} (id={firm.id})")
        print(f"  ✓ Company: {company.name} (id={company.id})")
        print(f"  ✓ Branch: {hq.name} (branch_code={hq.branch_code})")
        print(f"  ✓ User: {admin.username} / admin1234")

    # Init company DB + COA seed (via migration)
    await init_company_db(firm.id, company.id)
    print(f"  ✓ Company DB initialized: data/firm_{firm.id}/company_{company.id}/db.sqlite")
    print("✅ Seed complete.")


if __name__ == "__main__":
    asyncio.run(seed())
