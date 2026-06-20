"""
Seed script: สร้างบัญชีธนาคาร/เงินสดตัวอย่างสำหรับ company ที่กำหนด

COA codes (จาก app/platform/coa_template.py):
  1101 เงินสด
  1102 ธนาคาร-กระแสรายวัน
  1103 ธนาคาร-ออมทรัพย์

Usage:
  python scripts/seed_bank_accounts.py --company_id 1 [--firm_id 1]
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select

from app.config import settings
from app.database import get_session_factory
from app.modules.bank.models import BankAccount


SAMPLE_ACCOUNTS = [
    dict(
        bank_name="กรุงไทย",
        account_name="กระแสรายวัน",
        account_number="123-4-56789-0",
        account_type="current",
        coa_account_code="1102",  # ธนาคาร-กระแสรายวัน
    ),
    dict(
        bank_name="กสิกรไทย",
        account_name="ออมทรัพย์",
        account_number="098-7-65432-1",
        account_type="savings",
        coa_account_code="1103",  # ธนาคาร-ออมทรัพย์
    ),
    dict(
        bank_name="เงินสดในมือ",
        account_name="เงินสด",
        account_number=None,
        account_type="cash",
        coa_account_code="1101",  # เงินสด
    ),
]


async def seed(firm_id: int, company_id: int) -> None:
    db_url = settings.get_company_db_url(firm_id, company_id)
    factory = get_session_factory(db_url)

    async with factory() as session:
        inserted = 0
        for data in SAMPLE_ACCOUNTS:
            existing = await session.scalar(
                select(BankAccount).where(
                    BankAccount.company_id == company_id,
                    BankAccount.coa_account_code == data["coa_account_code"],
                )
            )
            if existing:
                print(f"[Bank] '{data['bank_name']}' (COA {data['coa_account_code']}) already exists — skipping")
                continue
            session.add(BankAccount(company_id=company_id, **data))
            inserted += 1

        await session.commit()
        print(f"[Bank] Inserted {inserted} bank accounts for company {company_id}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed bank accounts for a company")
    parser.add_argument("--company_id", type=int, default=1)
    parser.add_argument("--firm_id", type=int, default=1)
    args = parser.parse_args()

    asyncio.run(seed(args.firm_id, args.company_id))
