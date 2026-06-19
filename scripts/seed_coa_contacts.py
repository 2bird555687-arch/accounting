"""
Seed script: สร้าง COA และ Contact ตัวอย่างสำหรับ company ที่กำหนด

Usage:
  python scripts/seed_coa_contacts.py --company_id 1 [--firm_id 1] [--template trading]
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

# เพิ่ม project root ใน sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.config import settings
from app.database import get_session_factory, init_company_db
from app.platform.coa_template import COATemplateService
from app.modules.ar.models import Contact
from sqlalchemy import select, text


async def seed_coa(firm_id: int, company_id: int, template: str) -> None:
    db_url = settings.get_company_db_url(firm_id, company_id)
    factory = get_session_factory(db_url)

    async with factory() as session:
        # เช็คว่ามี COA อยู่แล้วหรือไม่
        from app.core.models import ChartOfAccount
        count_result = await session.execute(
            select(ChartOfAccount).limit(1)
        )
        existing = count_result.scalar_one_or_none()
        if existing:
            print(f"[COA] COA already exists for company {company_id} — skipping")
            return

        svc = COATemplateService(session)
        inserted = await svc.apply_template(template)
        await session.commit()
        print(f"[COA] Inserted {inserted} accounts (template={template}) for company {company_id}")


async def seed_contacts(firm_id: int, company_id: int) -> None:
    db_url = settings.get_company_db_url(firm_id, company_id)
    factory = get_session_factory(db_url)

    sample_contacts = [
        dict(
            name="บจ. ตัวอย่าง เทรดดิ้ง",
            tax_id="0105560000001",
            contact_type="customer",
            branch_code="00000",
            credit_days=30,
            default_ar_account="1110",
            default_ap_account="2101",
            default_revenue_account="4101",
            credit_limit=0,
        ),
        dict(
            name="นายสมชาย ใจดี",
            tax_id="3100100000001",
            contact_type="customer",
            branch_code="00000",
            credit_days=30,
            default_ar_account="1110",
            default_ap_account="2101",
            default_revenue_account="4101",
            credit_limit=0,
        ),
        dict(
            name="บจ. ซัพพลาย เซ็นเตอร์",
            tax_id="0105570000001",
            contact_type="supplier",
            branch_code="00000",
            credit_days=30,
            default_ar_account="1110",
            default_ap_account="2101",
            default_revenue_account="4101",
            credit_limit=0,
        ),
        dict(
            name="บจ. แอดวานซ์ เทค",
            tax_id="0105580000001",
            contact_type="both",
            branch_code="00000",
            credit_days=30,
            default_ar_account="1110",
            default_ap_account="2101",
            default_revenue_account="4101",
            credit_limit=0,
        ),
    ]

    async with factory() as session:
        # เช็คว่ามี contact อยู่แล้วหรือไม่ (ตรวจ tax_id ทีละรายการ)
        inserted = 0
        for data in sample_contacts:
            existing = await session.scalar(
                select(Contact).where(
                    Contact.company_id == company_id,
                    Contact.tax_id == data["tax_id"],
                )
            )
            if existing:
                print(f"[Contact] '{data['name']}' already exists — skipping")
                continue

            contact = Contact(company_id=company_id, **data)
            session.add(contact)
            inserted += 1

        await session.commit()
        print(f"[Contact] Inserted {inserted} contacts for company {company_id}")


async def main(firm_id: int, company_id: int, template: str) -> None:
    print(f"Seeding company_id={company_id} firm_id={firm_id} ...")

    # init DB tables only if the SQLite file doesn't exist yet
    db_path = settings.DATA_DIR / f"firm_{firm_id}" / f"company_{company_id}" / "db.sqlite"
    if not db_path.exists():
        print(f"[DB] Database not found at {db_path} — initialising tables ...")
        await init_company_db(firm_id, company_id)
    else:
        print(f"[DB] Database exists at {db_path} — skipping init")

    await seed_coa(firm_id, company_id, template)
    await seed_contacts(firm_id, company_id)
    print("Done.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed COA and Contacts for a company")
    parser.add_argument("--company_id", type=int, default=1, help="Company ID (default: 1)")
    parser.add_argument("--firm_id", type=int, default=1, help="Firm ID (default: 1)")
    parser.add_argument(
        "--template",
        type=str,
        default="trading",
        choices=["trading", "service", "mixed"],
        help="COA template type (default: trading)",
    )
    args = parser.parse_args()

    asyncio.run(main(args.firm_id, args.company_id, args.template))
