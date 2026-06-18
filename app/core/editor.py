"""
EditorService — แก้ไข/ยกเลิกรายการบัญชี

กฎเหล็ก:
  - ห้าม UPDATE/DELETE journal_entries หรือ journal_lines โดยตรง
  - การ "ยกเลิก" ต้องใช้ Reversing Entry เท่านั้น
  - แก้ได้เฉพาะ non-accounting fields (description, reference, ocr_ref)
  - ทุก action บันทึก AuditLog
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.context import AppContext, DrCr, JournalType
from app.core.engine import (
    JournalEntryInput,
    JournalLineInput,
    PostingEngine,
    PostingError,
    PermissionError as PostingPermissionError,
)
from app.core.journals import JournalEntryResult, JournalService
from app.core.models import (
    JournalEntry as JournalEntryORM,
    JournalLine as JournalLineORM,
    Period,
)


# ── Exceptions ────────────────────────────────────────────────────────────────

class EditorError(Exception):
    """Base exception สำหรับ editor operations."""


class EntryNotFoundError(EditorError):
    """ไม่พบรายการที่ระบุ."""


class AlreadyReversedError(EditorError):
    """รายการถูก reverse ไปแล้ว."""


class CannotEditPostedError(EditorError):
    """ห้ามแก้ไข accounting fields ของ posted entry."""


class ImmutableFieldError(EditorError):
    """field ที่ระบุเป็น immutable (accounting fields)."""


# fields ที่ห้ามแก้ไขหลัง post
_IMMUTABLE_FIELDS = frozenset({
    "journal_type", "entry_date", "period_id",
    "branch_id", "user_id", "status",
    "is_reversing", "reversed_entry_id",
    "source_module", "source_id",
})

# fields ที่อนุญาตให้แก้ได้
_EDITABLE_FIELDS = frozenset({"description", "reference", "ocr_ref"})


class EditorService:
    """
    บริการแก้ไขรายการบัญชี — ใช้หลัก Reversing Entry + Audit Trail

    Usage::

        editor = EditorService(session)
        new_ref = await editor.reverse("GJ202601-0001", "แก้รายการผิด", user_id=1, ctx=ctx)
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._journal_svc = JournalService(session)

    # ── Reverse ───────────────────────────────────────────────────────────────

    async def reverse(
        self,
        entry_no: str,
        reason: str,
        ctx: AppContext,
        reverse_date: Optional[date] = None,
    ) -> str:
        """
        สร้าง Reversing Entry — กลับรายการที่ post ไปแล้ว

        Args:
            entry_no: เลขที่รายการที่ต้องการกลับ
            reason: เหตุผลการกลับรายการ (บันทึกใน description)
            ctx: AppContext (ต้องมี can_approve)
            reverse_date: วันที่ reversing entry — ถ้า None ใช้วันปัจจุบัน

        Returns:
            entry_no ของ reversing entry ใหม่

        Raises:
            EntryNotFoundError: ไม่พบรายการ
            AlreadyReversedError: รายการถูก reverse ไปแล้ว
            PermissionError: ไม่มีสิทธิ์ reverse
        """
        if not ctx.can_approve:
            raise PostingPermissionError(
                f"user_id={ctx.user_id} role={ctx.user_role} ต้องมีสิทธิ์ approve จึงจะ reverse ได้"
            )

        orm_entry = await self._load_entry(entry_no)
        self._check_reversible(orm_entry)

        rev_date = reverse_date or datetime.now(tz=timezone.utc).date()

        # สร้าง input สำหรับ reversing entry (กลับ Dr↔Cr)
        rev_lines: list[JournalLineInput] = []
        for ln in sorted(orm_entry.lines, key=lambda x: x.line_no):
            if ln.debit_amount > 0:
                side = DrCr.CR   # Dr → กลับเป็น Cr
                amount = ln.debit_amount
            else:
                side = DrCr.DR   # Cr → กลับเป็น Dr
                amount = ln.credit_amount

            rev_lines.append(JournalLineInput(
                account_code=ln.account.code,
                side=side,
                amount=amount,
                description=ln.description,
                tax_rate=ln.tax_rate,
                tax_base_amount=ln.tax_base_amount,
                cost_center=ln.cost_center,
            ))

        rev_entry_input = JournalEntryInput(
            journal_type=JournalType(orm_entry.journal_type),
            entry_date=rev_date,
            description=f"[กลับรายการ {entry_no}] {reason}",
            lines=rev_lines,
            reference=orm_entry.reference,
            source_module=orm_entry.source_module,
            source_id=orm_entry.source_id,
        )

        engine = PostingEngine(self._session)
        new_entry_no = await engine.post(rev_entry_input, ctx)

        # Mark original entry ว่า reversed + link ไป reversing entry
        new_orm = await self._load_entry(new_entry_no)
        new_orm.is_reversing = True
        new_orm.reversed_entry_id = orm_entry.id
        orm_entry.status = "reversed"

        await self._session.flush()

        await self._write_audit(
            action="REVERSE",
            resource_type="journal_entry",
            resource_id=entry_no,
            description=f"กลับรายการ → {new_entry_no} เหตุผล: {reason}",
            before_data={"status": "posted"},
            after_data={"status": "reversed", "reversing_entry": new_entry_no},
            ctx=ctx,
        )

        return new_entry_no

    # ── Edit meta ─────────────────────────────────────────────────────────────

    async def edit_meta(
        self,
        entry_no: str,
        fields: dict[str, str],
        ctx: AppContext,
    ) -> JournalEntryResult:
        """
        แก้ไข non-accounting fields ของรายการ

        อนุญาต: description, reference, ocr_ref
        ห้าม: journal_type, entry_date, lines และทุก accounting field

        Args:
            entry_no: เลขที่รายการ
            fields: dict ของ field ที่ต้องการแก้ เช่น {"description": "แก้ไขคำอธิบาย"}
            ctx: AppContext

        Raises:
            ImmutableFieldError: ถ้าพยายามแก้ immutable field
            CannotEditPostedError: ถ้าพยายามแก้ accounting field ของ posted entry
        """
        if not ctx.can_post:
            raise PostingPermissionError(
                f"user_id={ctx.user_id} ไม่มีสิทธิ์แก้ไขรายการ"
            )

        # ตรวจ fields ที่ไม่อนุญาต
        disallowed = set(fields) - _EDITABLE_FIELDS
        if disallowed:
            if disallowed & _IMMUTABLE_FIELDS:
                raise ImmutableFieldError(
                    f"ไม่สามารถแก้ไข fields เหล่านี้ได้: {', '.join(sorted(disallowed))}. "
                    "ต้องการแก้ accounting data ให้ใช้ reverse() แทน"
                )
            raise EditorError(
                f"ไม่รู้จัก fields: {', '.join(sorted(disallowed))}. "
                f"fields ที่แก้ได้: {', '.join(sorted(_EDITABLE_FIELDS))}"
            )

        orm_entry = await self._load_entry(entry_no)
        before = {f: getattr(orm_entry, f, None) for f in fields}

        for f, val in fields.items():
            setattr(orm_entry, f, val)

        await self._session.flush()

        await self._write_audit(
            action="UPDATE",
            resource_type="journal_entry",
            resource_id=entry_no,
            description=f"แก้ไข meta fields: {', '.join(fields)}",
            before_data=before,
            after_data=fields,
            ctx=ctx,
        )

        result = await self._journal_svc.get_by_ref(entry_no, ctx)
        assert result is not None
        return result

    # ── Audit Trail ───────────────────────────────────────────────────────────

    async def get_audit_trail(
        self,
        entry_no: str,
        ctx: AppContext,
    ) -> list[dict]:  # type: ignore[type-arg]
        """
        ดึง audit trail ทั้งหมดของรายการ

        Returns:
            list ของ audit log records เรียงตาม created_at ASC
        """
        # AuditLog อยู่ใน shared DB — ใช้ shared session แยกต่างหาก
        # ที่นี่ return from shared db via separate call (caller ต้องจัดการ)
        # ตรงนี้ return placeholder — implement เต็มใน audit module
        return [
            {
                "note": (
                    "get_audit_trail ต้องเรียกผ่าน shared session "
                    "ดู app/shared/audit_service.py"
                ),
                "entry_no": entry_no,
            }
        ]

    # ── Void (draft only) ─────────────────────────────────────────────────────

    async def void_draft(
        self,
        entry_no: str,
        reason: str,
        ctx: AppContext,
    ) -> None:
        """
        ยกเลิก draft entry (ยังไม่ post)

        เปลี่ยน status เป็น "reversed" โดยไม่ต้องสร้าง reversing entry
        เพราะยังไม่มีผลต่อ ledger

        Raises:
            EditorError: ถ้า entry ไม่ใช่ draft
        """
        if not ctx.can_post:
            raise PostingPermissionError(
                f"user_id={ctx.user_id} ไม่มีสิทธิ์ยกเลิกรายการ"
            )

        orm_entry = await self._load_entry(entry_no)
        if orm_entry.status != "draft":
            raise EditorError(
                f"รายการ {entry_no} มีสถานะ '{orm_entry.status}' "
                "void_draft ใช้ได้เฉพาะ status='draft' เท่านั้น"
            )

        orm_entry.status = "reversed"
        await self._session.flush()

        await self._write_audit(
            action="DELETE",
            resource_type="journal_entry",
            resource_id=entry_no,
            description=f"ยกเลิก draft: {reason}",
            before_data={"status": "draft"},
            after_data={"status": "reversed"},
            ctx=ctx,
        )

    # ── Private helpers ───────────────────────────────────────────────────────

    async def _load_entry(self, entry_no: str) -> JournalEntryORM:
        stmt = (
            select(JournalEntryORM)
            .options(
                selectinload(JournalEntryORM.lines).selectinload(JournalLineORM.account)
            )
            .where(JournalEntryORM.entry_no == entry_no)
        )
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()
        if orm is None:
            raise EntryNotFoundError(f"ไม่พบรายการ {entry_no!r}")
        return orm

    def _check_reversible(self, orm: JournalEntryORM) -> None:
        if orm.status == "reversed":
            raise AlreadyReversedError(
                f"รายการ {orm.entry_no} ถูกกลับรายการไปแล้ว"
            )
        if orm.status != "posted":
            raise EditorError(
                f"รายการ {orm.entry_no} มีสถานะ '{orm.status}' "
                "สามารถ reverse ได้เฉพาะ status='posted' เท่านั้น"
            )

    async def _write_audit(
        self,
        action: str,
        resource_type: str,
        resource_id: str,
        description: str,
        before_data: dict,  # type: ignore[type-arg]
        after_data: dict,   # type: ignore[type-arg]
        ctx: AppContext,
    ) -> None:
        """บันทึก audit log ลง shared DB — ใช้ inline insert เพราะ model อยู่คนละ session."""
        from sqlalchemy import text

        # audit_logs อยู่ใน shared DB — ใน dev/test อาจไม่มีตาราง จึง try/except
        # TODO: production ให้ inject shared_session แยก
        try:
            await self._session.execute(
                text(
                    """
                    INSERT INTO audit_logs
                        (firm_id, company_id, branch_id, user_id, user_role,
                         action, resource_type, resource_id,
                         description, before_data, after_data, created_at)
                    VALUES
                        (:firm_id, :company_id, :branch_id, :user_id, :user_role,
                         :action, :resource_type, :resource_id,
                         :description, :before_data, :after_data, CURRENT_TIMESTAMP)
                    """
                ),
                {
                    "firm_id": ctx.firm_id,
                    "company_id": ctx.company_id,
                    "branch_id": ctx.branch_id,
                    "user_id": ctx.user_id,
                    "user_role": str(ctx.user_role),
                    "action": action,
                    "resource_type": resource_type,
                    "resource_id": resource_id,
                    "description": description,
                    "before_data": json.dumps(before_data, ensure_ascii=False, default=str),
                    "after_data": json.dumps(after_data, ensure_ascii=False, default=str),
                },
            )
        except Exception:
            # ถ้า audit_logs ไม่มี (เช่น test env ใช้ company DB เพียงอย่างเดียว) ข้ามไป
            pass
