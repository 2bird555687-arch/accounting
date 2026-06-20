"""
Seed script: สร้างสินทรัพย์ถาวรตัวอย่าง (vehicle + computer) สำหรับ company

Usage:
  python scripts/seed_fixed_assets.py --company_id 1 [--firm_id 1]
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select

from app.config import settings
from app.context import AppContext, UserRole
from app.database import get_session_factory
from app.modules.fa.models import FixedAsset
from app.modules.fa.schemas import AssetCreate
from app.modules.fa.asset_service import AssetService


SAMPLE_ASSETS = [
    AssetCreate(
        asset_code="FA-0001",
        asset_name="รถกระบะ Toyota Hilux",
        category="vehicle",            # 1260 / 1261
        purchase_date=date(2026, 1, 15),
        cost=Decimal("780000"),
        salvage_value=Decimal("80000"),
        useful_life_months=60,         # 5 ปี
        credit_account="2101",         # เจ้าหนี้การค้า
    ),
    AssetCreate(
        asset_code="FA-0002",
        asset_name="คอมพิวเตอร์ Dell OptiPlex",
        category="it",                 # 1250 / 1251
        purchase_date=date(2026, 2, 1),
        cost=Decimal("35000"),
        salvage_value=Decimal("2000"),
        useful_life_months=36,         # 3 ปี
        credit_account="1101",         # เงินสด
    ),
]


async def seed_assets(firm_id: int, company_id: int) -> None:
    db_url = settings.get_company_db_url(firm_id, company_id)
    factory = get_session_factory(db_url)

    ctx = AppContext(
        firm_id=firm_id,
        company_id=company_id,
        branch_id=1,
        user_id=1,
        user_role=UserRole.ACCOUNTANT,
        period=date.today().replace(day=1),
    )

    async with factory() as session:
        inserted = 0
        for data in SAMPLE_ASSETS:
            existing = await session.scalar(
                select(FixedAsset).where(
                    FixedAsset.company_id == company_id,
                    FixedAsset.asset_code == data.asset_code,
                )
            )
            if existing:
                print(f"[FA] '{data.asset_code}' already exists — skipping")
                continue
            out = await AssetService.create_asset(data, ctx, session)
            print(f"[FA] Created {out.asset_code} {out.asset_name} "
                  f"cost={out.cost} JE={out.purchase_journal_no}")
            inserted += 1
        await session.commit()
        print(f"[FA] Inserted {inserted} fixed assets for company {company_id}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed sample fixed assets")
    parser.add_argument("--company_id", type=int, default=1)
    parser.add_argument("--firm_id", type=int, default=1)
    args = parser.parse_args()

    asyncio.run(seed_assets(args.firm_id, args.company_id))
