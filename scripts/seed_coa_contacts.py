"""
Seed script: สร้าง COA และ Contact ตัวอย่างสำหรับ company ที่กำหนด

Usage:
  python scripts/seed_coa_contacts.py --company_id 1 [--firm_id 1]
  python scripts/seed_coa_contacts.py --company_id 1 --reset     # ลบ COA เดิมแล้ว seed ใหม่
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.config import settings
from app.database import get_session_factory, init_company_db
from app.platform.coa_template import COATemplateService
from app.modules.ar.models import Contact
from sqlalchemy import select, text


async def seed_coa(firm_id: int, company_id: int, reset: bool = False) -> None:
    db_url = settings.get_company_db_url(firm_id, company_id)
    factory = get_session_factory(db_url)

    async with factory() as session:
        from app.core.models import ChartOfAccount

        # เพิ่ม note_id / note_required column ถ้ายังไม่มี (migration B2 compat)
        pragma = await session.execute(text("PRAGMA table_info(chart_of_accounts)"))
        existing_cols = {row[1] for row in pragma.fetchall()}
        if "note_id" not in existing_cols:
            await session.execute(text("ALTER TABLE chart_of_accounts ADD COLUMN note_id VARCHAR(50)"))
            print("[COA] Added note_id column to chart_of_accounts")
        if "note_required" not in existing_cols:
            await session.execute(text("ALTER TABLE chart_of_accounts ADD COLUMN note_required BOOLEAN NOT NULL DEFAULT 0"))
            print("[COA] Added note_required column to chart_of_accounts")
        await session.commit()

        if reset:
            # ลบ COA ทั้งหมด (is_system=True) แล้ว seed ใหม่
            await session.execute(
                text("DELETE FROM chart_of_accounts WHERE is_system = 1")
            )
            await session.commit()
            print(f"[COA] Reset: ลบ COA เดิมสำหรับ company {company_id} แล้ว")
        else:
            # ตรวจว่ามีบัญชีอยู่แล้ว
            count_result = await session.execute(select(ChartOfAccount).limit(1))
            existing = count_result.scalar_one_or_none()
            if existing:
                print(f"[COA] COA already exists for company {company_id} — ใช้ --reset เพื่อ seed ใหม่")
                return

        svc = COATemplateService(session)
        inserted = await svc.apply_template("standard")
        await session.commit()
        print(f"[COA] Inserted {inserted} accounts (standard 113) for company {company_id}")


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
            default_ar_account="1111",
            default_ap_account="3101",
            default_revenue_account="6100",
            credit_limit=0,
        ),
        dict(
            name="นายสมชาย ใจดี",
            tax_id="3100100000001",
            contact_type="customer",
            branch_code="00000",
            credit_days=30,
            default_ar_account="1111",
            default_ap_account="3101",
            default_revenue_account="6100",
            credit_limit=0,
        ),
        dict(
            name="บจ. ซัพพลาย เซ็นเตอร์",
            tax_id="0105570000001",
            contact_type="supplier",
            branch_code="00000",
            credit_days=30,
            default_ar_account="1111",
            default_ap_account="3101",
            default_revenue_account="6100",
            credit_limit=0,
        ),
        dict(
            name="บจ. แอดวานซ์ เทค",
            tax_id="0105580000001",
            contact_type="both",
            branch_code="00000",
            credit_days=30,
            default_ar_account="1111",
            default_ap_account="3101",
            default_revenue_account="6100",
            credit_limit=0,
        ),
    ]

    async with factory() as session:
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


async def main(firm_id: int, company_id: int, reset: bool) -> None:
    print(f"Seeding company_id={company_id} firm_id={firm_id} reset={reset}...")

    db_path = settings.DATA_DIR / f"firm_{firm_id}" / f"company_{company_id}" / "db.sqlite"
    if not db_path.exists():
        print(f"[DB] Database not found at {db_path} — initialising tables ...")
        await init_company_db(firm_id, company_id)
    else:
        print(f"[DB] Database exists at {db_path}")

    await seed_coa(firm_id, company_id, reset=reset)
    await seed_contacts(firm_id, company_id)
    print("Done.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed COA (113 standard) and Contacts")
    parser.add_argument("--company_id", type=int, default=1)
    parser.add_argument("--firm_id", type=int, default=1)
    parser.add_argument("--reset", action="store_true",
                        help="ลบ COA เดิม (is_system=True) แล้ว seed ใหม่ทั้งหมด")
    parser.add_argument("--yes", "-y", action="store_true",
                        help="ข้ามการยืนยัน (ใช้ร่วมกับ --reset)")
    args = parser.parse_args()

    if args.reset and not args.yes:
        confirm = input(f"จะลบและ seed COA ใหม่ทั้งหมดสำหรับ company {args.company_id} ยืนยัน? (y/n): ")
        if confirm.strip().lower() != "y":
            print("ยกเลิก")
            sys.exit(0)

    asyncio.run(main(args.firm_id, args.company_id, args.reset))
