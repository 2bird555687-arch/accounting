"""INV โ€” Product CRUD Service."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.inv.models import Product
from app.modules.inv.schemas import ProductCreate, ProductOut, ProductUpdate
from app.context import AppContext


class ProductService:

    @staticmethod
    async def create_product(data: ProductCreate, ctx: AppContext, db: AsyncSession) -> ProductOut:
        if ctx.user_role not in ("firm_admin", "accountant"):
            raise PermissionError("เธ•เนเธญเธเธเธฒเธฃเธชเธดเธ—เธเธดเน accountant เธเธถเนเธเนเธ")

        existing = await db.scalar(
            select(Product).where(
                Product.company_id == ctx.company_id,
                Product.sku == data.sku,
            )
        )
        if existing:
            raise ValueError(f"SKU '{data.sku}' เธกเธตเธญเธขเธนเนเนเธฅเนเธง")

        product = Product(
            company_id=ctx.company_id,
            **data.model_dump(),
        )
        db.add(product)
        await db.flush()
        await db.refresh(product)
        return ProductOut.model_validate(product)

    @staticmethod
    async def list_products(
        ctx: AppContext,
        db: AsyncSession,
        active_only: bool = True,
        skip: int = 0,
        limit: int = 100,
    ) -> list[ProductOut]:
        q = select(Product).where(Product.company_id == ctx.company_id)
        if active_only:
            q = q.where(Product.is_active.is_(True))
        q = q.order_by(Product.sku).offset(skip).limit(limit)
        rows = await db.scalars(q)
        return [ProductOut.model_validate(r) for r in rows]

    @staticmethod
    async def get_product(product_id: int, ctx: AppContext, db: AsyncSession) -> ProductOut:
        p = await db.scalar(
            select(Product).where(
                Product.id == product_id,
                Product.company_id == ctx.company_id,
            )
        )
        if not p:
            raise ValueError(f"Product {product_id} เนเธกเนเธเธ")
        return ProductOut.model_validate(p)

    @staticmethod
    async def update_product(
        product_id: int, data: ProductUpdate, ctx: AppContext, db: AsyncSession
    ) -> ProductOut:
        if ctx.user_role not in ("firm_admin", "accountant"):
            raise PermissionError("เธ•เนเธญเธเธเธฒเธฃเธชเธดเธ—เธเธดเน accountant เธเธถเนเธเนเธ")

        p = await db.scalar(
            select(Product).where(
                Product.id == product_id,
                Product.company_id == ctx.company_id,
            )
        )
        if not p:
            raise ValueError(f"Product {product_id} เนเธกเนเธเธ")

        for field, val in data.model_dump(exclude_none=True).items():
            setattr(p, field, val)

        await db.flush()
        await db.refresh(p)
        return ProductOut.model_validate(p)

    @staticmethod
    async def deactivate_product(product_id: int, ctx: AppContext, db: AsyncSession) -> None:
        if ctx.user_role not in ("firm_admin", "accountant"):
            raise PermissionError("เธ•เนเธญเธเธเธฒเธฃเธชเธดเธ—เธเธดเน accountant เธเธถเนเธเนเธ")

        p = await db.scalar(
            select(Product).where(
                Product.id == product_id,
                Product.company_id == ctx.company_id,
            )
        )
        if not p:
            raise ValueError(f"Product {product_id} เนเธกเนเธเธ")

        p.is_active = False
        await db.flush()

