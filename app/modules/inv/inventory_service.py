"""INV โ€” Inventory Service (receive / issue / adjust / stock balance)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.inv.models import Product, ProductLot, StockMovement
from app.modules.inv.schemas import (
    AdjustStockIn,
    IssueStockIn,
    ProductLotOut,
    ReceiveStockIn,
    StockBalance,
    StockMovementOut,
)
from app.context import AppContext
from app.core.engine import PostingEngine, JournalLineInput as JournalLineIn


async def _next_movement_no(company_id: int, movement_date: date, prefix: str, db: AsyncSession) -> str:
    from sqlalchemy import func as sqlfunc
    month_str = movement_date.strftime("%Y%m")
    pattern = f"{prefix}{month_str}-%"
    count = await db.scalar(
        select(sqlfunc.count()).select_from(StockMovement).where(
            StockMovement.company_id == company_id,
            StockMovement.movement_no.like(pattern),
        )
    )
    return f"{prefix}{month_str}-{(count or 0) + 1:04d}"


class InventoryService:

    @staticmethod
    async def receive(data: ReceiveStockIn, ctx: AppContext, db: AsyncSession) -> StockMovementOut:
        """เธฃเธฑเธเธชเธดเธเธเนเธฒเน€เธเนเธฒเธเธฅเธฑเธ โ€” Dr 1130 | Cr เธ•เธฒเธก AP/เน€เธเธดเธเธชเธ” (GJ)."""
        if ctx.user_role not in ("firm_admin", "accountant", "junior"):
            raise PermissionError("เนเธกเนเธกเธตเธชเธดเธ—เธเธดเนเธฃเธฑเธเธชเธดเธเธเนเธฒ")

        product = await db.scalar(
            select(Product).where(
                Product.id == data.product_id,
                Product.company_id == ctx.company_id,
            )
        )
        if not product:
            raise ValueError("เนเธกเนเธเธเธชเธดเธเธเนเธฒ")

        qty = data.quantity
        unit_cost = data.unit_cost
        total_cost = (qty * unit_cost).quantize(Decimal("0.01"), ROUND_HALF_UP)

        # เธญเธฑเธเน€เธ”เธ• lot (FIFO)
        lot: ProductLot | None = None
        if product.cost_method == "fifo":
            lot_no = data.lot_no or f"L{data.movement_date.strftime('%Y%m%d')}-{data.source_ref or 'RCV'}"
            lot = ProductLot(
                product_id=product.id,
                lot_no=lot_no,
                received_date=data.movement_date,
                quantity=qty,
                remaining_qty=qty,
                unit_cost=unit_cost,
                source=data.source,
                source_ref=data.source_ref,
            )
            db.add(lot)
            await db.flush()

        # เธญเธฑเธเน€เธ”เธ• average cost
        old_qty = product.quantity_on_hand
        old_value = product.total_value
        new_qty = old_qty + qty
        new_value = old_value + total_cost

        if product.cost_method == "average":
            product.current_cost = (new_value / new_qty).quantize(Decimal("0.0001"), ROUND_HALF_UP) if new_qty else unit_cost
        else:
            product.current_cost = unit_cost  # FIFO เนเธเน last received cost เน€เธเนเธ approximation

        product.quantity_on_hand = new_qty
        product.total_value = new_value

        movement_no = await _next_movement_no(ctx.company_id, data.movement_date, "RCV", db)

        mv = StockMovement(
            company_id=ctx.company_id,
            branch_id=ctx.branch_id,
            product_id=product.id,
            movement_no=movement_no,
            movement_date=data.movement_date,
            movement_type="receive",
            quantity=qty,
            unit_cost=unit_cost,
            total_cost=total_cost,
            qty_after=new_qty,
            value_after=new_value,
            lot_id=lot.id if lot else None,
            reference=data.reference,
            reason=data.reason,
            source_module=data.source,
            source_id=data.ap_purchase_id,
            created_by=ctx.user_id,
        )

        # Journal: Dr 1130 | Cr เน€เธเนเธฒเธซเธเธตเน/เน€เธเธดเธเธชเธ”
        lines = [
            JournalLineIn(account_code=product.inventory_account, dr_cr="DR", amount=total_cost),
            JournalLineIn(account_code="2101", dr_cr="CR", amount=total_cost),
        ]
        je = await PostingEngine(db).post(
            ctx=ctx,
            journal_type="GJ",
            lines=lines,
            description=f"เธฃเธฑเธเธชเธดเธเธเนเธฒ {product.sku} x{qty} @ {unit_cost}",
            source_module="INV",
            source_id=None,
        )
        mv.journal_entry_no = je.entry_no
        db.add(mv)
        await db.flush()
        await db.refresh(mv)
        return StockMovementOut.model_validate(mv)

    @staticmethod
    async def issue(data: IssueStockIn, ctx: AppContext, db: AsyncSession) -> list[StockMovementOut]:
        """เธเนเธฒเธขเธชเธดเธเธเนเธฒเธญเธญเธเธเธฅเธฑเธ โ€” Dr 5101 (COGS) | Cr 1130 (GJ).

        เธชเธณเธซเธฃเธฑเธ FIFO เธเธฐ return เธซเธฅเธฒเธข movement (1 lot เธ•เนเธญ 1 movement)
        """
        if ctx.user_role not in ("firm_admin", "accountant", "junior"):
            raise PermissionError("เนเธกเนเธกเธตเธชเธดเธ—เธเธดเนเธเนเธฒเธขเธชเธดเธเธเนเธฒ")

        product = await db.scalar(
            select(Product).where(
                Product.id == data.product_id,
                Product.company_id == ctx.company_id,
            )
        )
        if not product:
            raise ValueError("เนเธกเนเธเธเธชเธดเธเธเนเธฒ")

        if product.quantity_on_hand < data.quantity:
            raise ValueError(f"เธชเธดเธเธเนเธฒเนเธกเนเธเธญ (เธเธเน€เธซเธฅเธทเธญ {product.quantity_on_hand})")

        results: list[StockMovementOut] = []
        remaining = data.quantity

        if product.cost_method == "fifo":
            lots = await db.scalars(
                select(ProductLot).where(
                    ProductLot.product_id == product.id,
                    ProductLot.remaining_qty > 0,
                ).order_by(ProductLot.received_date, ProductLot.id)
            )
            for lot in lots:
                if remaining <= 0:
                    break
                take = min(lot.remaining_qty, remaining)
                cost = (take * lot.unit_cost).quantize(Decimal("0.01"), ROUND_HALF_UP)
                lot.remaining_qty -= take
                remaining -= take
                product.quantity_on_hand -= take
                product.total_value -= cost

                movement_no = await _next_movement_no(ctx.company_id, data.movement_date, "ISS", db)
                mv = StockMovement(
                    company_id=ctx.company_id,
                    branch_id=ctx.branch_id,
                    product_id=product.id,
                    movement_no=movement_no,
                    movement_date=data.movement_date,
                    movement_type="issue",
                    quantity=take,
                    unit_cost=lot.unit_cost,
                    total_cost=cost,
                    qty_after=product.quantity_on_hand,
                    value_after=product.total_value,
                    lot_id=lot.id,
                    reference=data.reference,
                    reason=data.reason,
                    source_module=data.source_module,
                    source_id=data.source_id,
                    created_by=ctx.user_id,
                )
                lines = [
                    JournalLineIn(account_code=product.cogs_account, dr_cr="DR", amount=cost),
                    JournalLineIn(account_code=product.inventory_account, dr_cr="CR", amount=cost),
                ]
                je = await PostingEngine(db).post(
                    ctx=ctx, journal_type="GJ", lines=lines,
                    description=f"เธเนเธฒเธขเธชเธดเธเธเนเธฒ {product.sku} x{take} FIFO",
                    source_module="INV", source_id=None,
                )
                mv.journal_entry_no = je.entry_no
                db.add(mv)
                await db.flush()
                await db.refresh(mv)
                results.append(StockMovementOut.model_validate(mv))
        else:
            # Average cost
            qty = data.quantity
            unit_cost = product.current_cost
            total_cost = (qty * unit_cost).quantize(Decimal("0.01"), ROUND_HALF_UP)
            product.quantity_on_hand -= qty
            product.total_value -= total_cost
            if product.total_value < 0:
                product.total_value = Decimal(0)

            movement_no = await _next_movement_no(ctx.company_id, data.movement_date, "ISS", db)
            mv = StockMovement(
                company_id=ctx.company_id,
                branch_id=ctx.branch_id,
                product_id=product.id,
                movement_no=movement_no,
                movement_date=data.movement_date,
                movement_type="issue",
                quantity=qty,
                unit_cost=unit_cost,
                total_cost=total_cost,
                qty_after=product.quantity_on_hand,
                value_after=product.total_value,
                reference=data.reference,
                reason=data.reason,
                source_module=data.source_module,
                source_id=data.source_id,
                created_by=ctx.user_id,
            )
            lines = [
                JournalLineIn(account_code=product.cogs_account, dr_cr="DR", amount=total_cost),
                JournalLineIn(account_code=product.inventory_account, dr_cr="CR", amount=total_cost),
            ]
            je = await PostingEngine(db).post(
                ctx=ctx, journal_type="GJ", lines=lines,
                description=f"เธเนเธฒเธขเธชเธดเธเธเนเธฒ {product.sku} x{qty} @ avg {unit_cost}",
                source_module="INV", source_id=None,
            )
            mv.journal_entry_no = je.entry_no
            db.add(mv)
            await db.flush()
            await db.refresh(mv)
            results.append(StockMovementOut.model_validate(mv))

        return results

    @staticmethod
    async def adjust(data: AdjustStockIn, ctx: AppContext, db: AsyncSession) -> StockMovementOut:
        """เธเธฃเธฑเธเธเธฃเธดเธกเธฒเธ“เธชเธดเธเธเนเธฒ โ€” Dr/Cr 1130 (GJ)."""
        if ctx.user_role not in ("firm_admin", "accountant"):
            raise PermissionError("เธ•เนเธญเธเธเธฒเธฃเธชเธดเธ—เธเธดเน accountant เธเธถเนเธเนเธเธชเธณเธซเธฃเธฑเธเธเธฒเธฃเธเธฃเธฑเธเธเธฃเธดเธกเธฒเธ“")

        product = await db.scalar(
            select(Product).where(
                Product.id == data.product_id,
                Product.company_id == ctx.company_id,
            )
        )
        if not product:
            raise ValueError("เนเธกเนเธเธเธชเธดเธเธเนเธฒ")

        old_qty = product.quantity_on_hand
        new_qty = data.new_quantity
        diff = new_qty - old_qty
        unit_cost = data.new_unit_cost or product.current_cost
        total_cost = (abs(diff) * unit_cost).quantize(Decimal("0.01"), ROUND_HALF_UP)

        if diff == 0:
            raise ValueError("เธเธฃเธดเธกเธฒเธ“เน€เธ—เนเธฒเน€เธ”เธดเธก เนเธกเนเธกเธตเธเธฒเธฃเธเธฃเธฑเธ")

        movement_type = "adjust_in" if diff > 0 else "adjust_out"

        if diff > 0:
            product.quantity_on_hand = new_qty
            product.total_value += total_cost
            dr_acc, cr_acc = product.inventory_account, "5901"  # Cr เธเนเธฒเธเธฃเธฑเธเธเธฃเธดเธกเธฒเธ“
        else:
            product.quantity_on_hand = new_qty
            product.total_value = max(Decimal(0), product.total_value - total_cost)
            dr_acc, cr_acc = "5901", product.inventory_account  # Dr เธเนเธฒเธเธฃเธฑเธเธเธฃเธดเธกเธฒเธ“

        if product.quantity_on_hand > 0:
            product.current_cost = (product.total_value / product.quantity_on_hand).quantize(
                Decimal("0.0001"), ROUND_HALF_UP
            )

        movement_no = await _next_movement_no(ctx.company_id, data.movement_date, "ADJ", db)
        mv = StockMovement(
            company_id=ctx.company_id,
            branch_id=ctx.branch_id,
            product_id=product.id,
            movement_no=movement_no,
            movement_date=data.movement_date,
            movement_type=movement_type,
            quantity=abs(diff),
            unit_cost=unit_cost,
            total_cost=total_cost,
            qty_after=product.quantity_on_hand,
            value_after=product.total_value,
            reason=data.reason,
            created_by=ctx.user_id,
        )
        lines = [
            JournalLineIn(account_code=dr_acc, dr_cr="DR", amount=total_cost),
            JournalLineIn(account_code=cr_acc, dr_cr="CR", amount=total_cost),
        ]
        je = await PostingEngine(db).post(
            ctx=ctx, journal_type="GJ", lines=lines,
            description=f"เธเธฃเธฑเธเธชเธ•เนเธญเธ {product.sku}: {old_qty} โ’ {new_qty}",
            source_module="INV", source_id=None,
        )
        mv.journal_entry_no = je.entry_no
        db.add(mv)
        await db.flush()
        await db.refresh(mv)
        return StockMovementOut.model_validate(mv)

    @staticmethod
    async def get_stock_balance(
        ctx: AppContext,
        db: AsyncSession,
        product_id: int | None = None,
    ) -> list[StockBalance]:
        q = select(Product).where(
            Product.company_id == ctx.company_id,
            Product.is_active.is_(True),
        )
        if product_id:
            q = q.where(Product.id == product_id)
        q = q.order_by(Product.sku)
        rows = await db.scalars(q)
        return [
            StockBalance(
                product_id=r.id,
                sku=r.sku,
                name=r.name,
                unit=r.unit,
                cost_method=r.cost_method,
                quantity_on_hand=r.quantity_on_hand,
                current_cost=r.current_cost,
                total_value=r.total_value,
                reorder_point=r.reorder_point,
                below_reorder=r.quantity_on_hand <= r.reorder_point,
            )
            for r in rows
        ]

    @staticmethod
    async def get_lots(product_id: int, ctx: AppContext, db: AsyncSession) -> list[ProductLotOut]:
        rows = await db.scalars(
            select(ProductLot).where(
                ProductLot.product_id == product_id,
                ProductLot.remaining_qty > 0,
            ).order_by(ProductLot.received_date)
        )
        return [ProductLotOut.model_validate(r) for r in rows]

    @staticmethod
    async def list_movements(
        ctx: AppContext,
        db: AsyncSession,
        product_id: int | None = None,
        skip: int = 0,
        limit: int = 100,
    ) -> list[StockMovementOut]:
        q = select(StockMovement).where(StockMovement.company_id == ctx.company_id)
        if product_id:
            q = q.where(StockMovement.product_id == product_id)
        q = q.order_by(StockMovement.movement_date.desc(), StockMovement.id.desc()).offset(skip).limit(limit)
        rows = await db.scalars(q)
        return [StockMovementOut.model_validate(r) for r in rows]


