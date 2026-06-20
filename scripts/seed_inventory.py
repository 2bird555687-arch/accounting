"""
Seed script: สร้างสินค้าตัวอย่าง + initial lots สำหรับ company ที่กำหนด

Usage:
  python scripts/seed_inventory.py --company_id 1 [--firm_id 1]
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
from app.database import get_session_factory
from app.modules.inv.models import Product, ProductLot, StockMovement


SAMPLE_PRODUCTS = [
    # (sku, name, cost_method, unit, std_cost, qty, unit_cost)
    ("SKU-AVG-001", "กระดาษ A4 80แกรม", "average", "รีม", Decimal("110"), Decimal("100"), Decimal("105")),
    ("SKU-FIFO-001", "หมึกพิมพ์ดำ", "fifo", "ตลับ", Decimal("450"), Decimal("20"), Decimal("430")),
    ("SKU-AVG-002", "ปากกาลูกลื่น น้ำเงิน", "average", "กล่อง", Decimal("60"), Decimal("50"), Decimal("58")),
]


async def seed(firm_id: int, company_id: int) -> None:
    db_url = settings.get_company_db_url(firm_id, company_id)
    factory = get_session_factory(db_url)

    async with factory() as session:
        inserted = 0
        for sku, name, method, unit, std, qty, ucost in SAMPLE_PRODUCTS:
            existing = await session.scalar(
                select(Product).where(
                    Product.company_id == company_id, Product.sku == sku
                )
            )
            if existing:
                print(f"[INV] '{sku}' already exists — skipping")
                continue

            total_value = (qty * ucost).quantize(Decimal("0.01"))
            product = Product(
                company_id=company_id,
                sku=sku,
                name=name,
                unit=unit,
                cost_method=method,
                inventory_account="1130",
                cogs_account="5101",
                current_cost=ucost,
                standard_cost=std,
                quantity_on_hand=qty,
                total_value=total_value,
                reorder_point=qty / 5,
                min_stock=qty / 10,
            )
            session.add(product)
            await session.flush()

            # Initial opening lot (FIFO ใช้ lot, average เก็บไว้อ้างอิง)
            if method == "fifo":
                session.add(ProductLot(
                    product_id=product.id,
                    lot_no=f"OPEN-{sku}",
                    received_date=date.today(),
                    quantity=qty,
                    remaining_qty=qty,
                    unit_cost=ucost,
                    source="opening",
                    source_ref="seed",
                ))

            # บันทึก movement เปิดยอด (opening — ไม่ post JE จาก seed)
            session.add(StockMovement(
                company_id=company_id,
                branch_id=1,
                product_id=product.id,
                movement_no=f"OPEN{date.today():%Y%m}-{inserted + 1:04d}",
                movement_date=date.today(),
                movement_type="receive",
                quantity=qty,
                unit_cost=ucost,
                total_cost=total_value,
                qty_after=qty,
                value_after=total_value,
                reference="ยอดยกมา (seed)",
                source_module="opening",
                created_by=1,
            ))
            inserted += 1
            print(f"[INV] + {sku} ({method}) qty={qty} @ {ucost}")

        await session.commit()
        print(f"[INV] Inserted {inserted} products for company {company_id}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed sample inventory products")
    parser.add_argument("--company_id", type=int, default=1)
    parser.add_argument("--firm_id", type=int, default=1)
    args = parser.parse_args()
    asyncio.run(seed(args.firm_id, args.company_id))
