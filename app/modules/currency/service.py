"""Currency service — exchange rate management."""
from __future__ import annotations
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models import ExchangeRate


class ExchangeRateIn(BaseModel):
    currency_code: str
    rate_date: date
    rate: Decimal
    source: str = "manual"


class ExchangeRateOut(BaseModel):
    id: int
    currency_code: str
    rate_date: date
    rate: Decimal
    source: Optional[str]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


async def upsert_rate(ctx, db: AsyncSession, data: ExchangeRateIn) -> ExchangeRate:
    existing = await db.scalar(
        select(ExchangeRate).where(
            ExchangeRate.company_id == ctx.company_id,
            ExchangeRate.currency_code == data.currency_code.upper(),
            ExchangeRate.rate_date == data.rate_date,
        )
    )
    if existing:
        existing.rate = data.rate
        existing.source = data.source
        await db.flush()
        return existing
    er = ExchangeRate(
        company_id=ctx.company_id,
        currency_code=data.currency_code.upper(),
        rate_date=data.rate_date,
        rate=data.rate,
        source=data.source,
        created_by=ctx.user_id,
    )
    db.add(er)
    await db.flush()
    return er


async def get_rate(ctx, db: AsyncSession, currency_code: str, as_of_date: date) -> Decimal:
    if currency_code.upper() == "THB":
        return Decimal("1")
    er = await db.scalar(
        select(ExchangeRate)
        .where(
            ExchangeRate.company_id == ctx.company_id,
            ExchangeRate.currency_code == currency_code.upper(),
            ExchangeRate.rate_date <= as_of_date,
        )
        .order_by(ExchangeRate.rate_date.desc())
        .limit(1)
    )
    if not er:
        raise ValueError(f"ไม่พบอัตราแลกเปลี่ยน {currency_code} ณ {as_of_date}")
    return er.rate


async def list_rates(
    ctx, db: AsyncSession, currency_code: Optional[str] = None, limit: int = 90
) -> list[ExchangeRate]:
    q = (
        select(ExchangeRate)
        .where(ExchangeRate.company_id == ctx.company_id)
        .order_by(ExchangeRate.rate_date.desc(), ExchangeRate.currency_code)
        .limit(limit)
    )
    if currency_code:
        q = q.where(ExchangeRate.currency_code == currency_code.upper())
    rows = await db.scalars(q)
    return list(rows)


async def convert(
    ctx,
    db: AsyncSession,
    amount: float,
    from_currency: str,
    to_currency: str,
    as_of_date: date,
) -> dict:
    from_rate = await get_rate(ctx, db, from_currency, as_of_date)
    to_rate = await get_rate(ctx, db, to_currency, as_of_date)
    thb_amount = Decimal(str(amount)) * from_rate
    result = thb_amount / to_rate
    return {
        "from_currency": from_currency.upper(),
        "to_currency": to_currency.upper(),
        "from_amount": float(amount),
        "to_amount": float(result.quantize(Decimal("0.01"))),
        "thb_amount": float(thb_amount.quantize(Decimal("0.01"))),
        "from_rate": float(from_rate),
        "to_rate": float(to_rate),
        "as_of_date": str(as_of_date),
    }
