"""Contact Master Service — CRUD ผู้ติดต่อ (ลูกค้า/เจ้าหนี้)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.context import AppContext
from app.modules.ar.models import Contact
from app.master.schemas import ContactCreate, ContactOut, ContactUpdate


class ContactService:

    @staticmethod
    async def create_contact(data: ContactCreate, ctx: AppContext, db: AsyncSession) -> ContactOut:
        if ctx.user_role not in ("firm_admin", "accountant"):
            raise PermissionError("ต้องการสิทธิ์ accountant ขึ้นไป")

        contact = Contact(
            company_id=ctx.company_id,
            **data.model_dump(),
        )
        db.add(contact)
        await db.flush()
        await db.refresh(contact)
        return ContactOut.model_validate(contact)

    @staticmethod
    async def list_contacts(
        ctx: AppContext,
        db: AsyncSession,
        contact_type: str | None = None,
        active_only: bool = True,
        skip: int = 0,
        limit: int = 100,
    ) -> list[ContactOut]:
        q = select(Contact).where(Contact.company_id == ctx.company_id)
        if contact_type:
            q = q.where(Contact.contact_type == contact_type)
        if active_only:
            q = q.where(Contact.is_active.is_(True))
        q = q.order_by(Contact.name).offset(skip).limit(limit)
        rows = await db.scalars(q)
        return [ContactOut.model_validate(r) for r in rows]

    @staticmethod
    async def get_contact(contact_id: int, ctx: AppContext, db: AsyncSession) -> ContactOut:
        c = await db.scalar(
            select(Contact).where(
                Contact.id == contact_id,
                Contact.company_id == ctx.company_id,
            )
        )
        if not c:
            raise ValueError(f"Contact {contact_id} ไม่พบ")
        return ContactOut.model_validate(c)

    @staticmethod
    async def update_contact(
        contact_id: int, data: ContactUpdate, ctx: AppContext, db: AsyncSession
    ) -> ContactOut:
        if ctx.user_role not in ("firm_admin", "accountant"):
            raise PermissionError("ต้องการสิทธิ์ accountant ขึ้นไป")

        c = await db.scalar(
            select(Contact).where(
                Contact.id == contact_id,
                Contact.company_id == ctx.company_id,
            )
        )
        if not c:
            raise ValueError(f"Contact {contact_id} ไม่พบ")

        for field, val in data.model_dump(exclude_none=True).items():
            setattr(c, field, val)

        await db.flush()
        await db.refresh(c)
        return ContactOut.model_validate(c)

    @staticmethod
    async def deactivate_contact(contact_id: int, ctx: AppContext, db: AsyncSession) -> None:
        if ctx.user_role not in ("firm_admin", "accountant"):
            raise PermissionError("ต้องการสิทธิ์ accountant ขึ้นไป")
        c = await db.scalar(
            select(Contact).where(
                Contact.id == contact_id,
                Contact.company_id == ctx.company_id,
            )
        )
        if not c:
            raise ValueError(f"Contact {contact_id} ไม่พบ")
        c.is_active = False
        await db.flush()
