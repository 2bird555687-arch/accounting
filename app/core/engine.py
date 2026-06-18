"""
PostingEngine — หัวใจของระบบบัญชี

กฎเหล็ก:
  1. ทุก JournalEntry ต้องผ่าน PostingEngine.post() เท่านั้น
  2. Dr รวม == Cr รวม เสมอ (ตรวจก่อน write ทุกครั้ง)
  3. ห้าม write ตรงไปยัง journal_entries / ledger_entries โดยไม่ผ่าน engine
  4. ทุก entry ต้องมี branch_id, user_id, timestamp จาก AppContext
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.context import AppContext, DrCr, JournalType, UserRole
from app.core.models import (
    AccountBalance,
    ChartOfAccount,
    JournalEntry as JournalEntryORM,
    JournalLine as JournalLineORM,
    LedgerEntry,
    Period,
)


# ── Input dataclasses (domain objects ไม่ผูกกับ ORM) ─────────────────────────

@dataclass
class JournalLineInput:
    """บรรทัดรายการบัญชี — input ให้ PostingEngine."""

    account_code: str           # รหัสบัญชี 4 หลัก เช่น "1101"
    side: DrCr                  # DrCr.DR หรือ DrCr.CR
    amount: Decimal             # ต้องเป็น positive เสมอ
    description: Optional[str] = None
    sub_account: Optional[str] = None   # รหัสย่อย สำหรับ AR/AP
    tax_rate: Optional[Decimal] = None  # อัตราภาษี เช่น Decimal("7")
    tax_base_amount: Optional[Decimal] = None
    cost_center: Optional[str] = None

    def __post_init__(self) -> None:
        if not isinstance(self.amount, Decimal):
            self.amount = Decimal(str(self.amount))
        if self.amount <= 0:
            raise ValueError(
                f"amount ต้องเป็น positive ได้รับ {self.amount} (account: {self.account_code})"
            )
        if not re.fullmatch(r"\d{4,10}", self.account_code):
            raise ValueError(f"account_code ไม่ถูกต้อง: {self.account_code!r}")


@dataclass
class VATInfo:
    """ข้อมูล VAT แนบมากับ entry — PostingEngine จะสร้าง line ภาษีให้อัตโนมัติ."""

    tax_base: Decimal
    vat_rate: Decimal = Decimal("7")   # %
    input_tax: bool = True             # True = ภาษีซื้อ (1140), False = ภาษีขาย (2120)

    @property
    def vat_amount(self) -> Decimal:
        return (self.tax_base * self.vat_rate / 100).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )


@dataclass
class WHTInfo:
    """ข้อมูล Withholding Tax แนบมากับ entry."""

    base_amount: Decimal
    wht_rate: Decimal              # % เช่น Decimal("3")
    wht_type: str                  # "3" | "53" | "1" ตามแบบ ภงด.
    payee_tax_id: Optional[str] = None
    is_payer: bool = True          # True = เราหัก ณ ที่จ่าย (2121), False = ถูกหัก (1141)

    @property
    def wht_amount(self) -> Decimal:
        return (self.base_amount * self.wht_rate / 100).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )


@dataclass
class JournalEntryInput:
    """Input ให้ PostingEngine.post() — domain object ไม่ผูกกับ ORM."""

    journal_type: JournalType
    entry_date: date
    description: str
    lines: list[JournalLineInput]
    reference: Optional[str] = None        # เลขที่เอกสารอ้างอิง
    source_module: Optional[str] = None    # ar / ap / inv / fa / gl / ...
    source_id: Optional[int] = None
    ocr_ref: Optional[str] = None
    vat_info: Optional[VATInfo] = None
    wht_info: Optional[WHTInfo] = None
    auto_vat: bool = False   # ถ้า True จะสร้าง VAT line อัตโนมัติจาก vat_info


# ── Exceptions ────────────────────────────────────────────────────────────────

class PostingError(Exception):
    """Base exception สำหรับ posting errors."""


class ImbalancedEntryError(PostingError):
    """Dr รวม ≠ Cr รวม."""


class ClosedPeriodError(PostingError):
    """พยายาม post เข้างวดที่ปิดแล้ว."""


class PermissionError(PostingError):  # noqa: A001
    """ผู้ใช้ไม่มีสิทธิ์บันทึกรายการ."""


class AccountNotFoundError(PostingError):
    """ไม่พบรหัสบัญชีใน COA."""


class InvalidEntryError(PostingError):
    """Entry ไม่ถูกต้องในด้านอื่น ๆ."""


# ── PostingEngine ─────────────────────────────────────────────────────────────

class PostingEngine:
    """
    Engine หลักสำหรับบันทึกรายการบัญชี

    Usage::

        engine = PostingEngine(session)
        ref = await engine.post(entry_input, ctx)
    """

    # รหัสบัญชี VAT / WHT ที่ระบบใช้
    VAT_INPUT_CODE = "1140"    # ภาษีซื้อ
    VAT_OUTPUT_CODE = "2120"   # ภาษีขาย
    WHT_PAYABLE_CODE = "2121"  # ภาษีหัก ณ ที่จ่าย-ค้างนำส่ง (เราหัก)
    WHT_RECEIVABLE_CODE = "1141"  # ภาษีหัก ณ ที่จ่าย-ถูกหัก

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ── Public API ────────────────────────────────────────────────────────────

    async def post(self, entry: JournalEntryInput, ctx: AppContext) -> str:
        """
        บันทึกรายการบัญชี — entry point หลักของระบบ

        Flow: validate permission → validate period → expand VAT/WHT →
              validate balance → resolve accounts → write journal →
              write ledger → update balance → return entry_no

        Returns:
            entry_no: เลขที่รายการ เช่น "GJ202601-0001"

        Raises:
            PermissionError: ถ้า user ไม่มีสิทธิ์ post
            ClosedPeriodError: ถ้างวดปิดแล้ว
            ImbalancedEntryError: ถ้า Dr ≠ Cr
            AccountNotFoundError: ถ้ารหัสบัญชีไม่มีใน COA
        """
        self._check_permission(ctx)
        period = await self._get_or_create_period(entry.entry_date)
        self._check_period_open(period)

        lines = self._expand_tax_lines(entry)
        self._validate_balance(lines)

        account_map = await self._resolve_accounts(lines)
        entry_no = await self._next_ref(entry.journal_type, ctx, entry.entry_date)

        orm_entry = await self._write_journal(entry, lines, entry_no, period, ctx)
        await self._write_ledger(orm_entry, lines, account_map, period, ctx)

        return entry_no

    # ── Validation ────────────────────────────────────────────────────────────

    def _check_permission(self, ctx: AppContext) -> None:
        if not ctx.can_post:
            raise PermissionError(
                f"user_id={ctx.user_id} role={ctx.user_role} ไม่มีสิทธิ์บันทึกรายการบัญชี"
            )

    def _check_period_open(self, period: Period) -> None:
        if not period.is_open:
            raise ClosedPeriodError(
                f"งวด {period.fiscal_year}/{period.month:02d} "
                f"มีสถานะ '{period.status}' ไม่สามารถบันทึกได้"
            )

    def _validate_balance(self, lines: list[JournalLineInput]) -> None:
        """ตรวจว่า Dr รวม == Cr รวม (กฎเหล็กข้อ 2)."""
        total_dr = sum(ln.amount for ln in lines if ln.side == DrCr.DR)
        total_cr = sum(ln.amount for ln in lines if ln.side == DrCr.CR)
        if total_dr != total_cr:
            raise ImbalancedEntryError(
                f"Dr รวม {total_dr} ≠ Cr รวม {total_cr} "
                f"(ผลต่าง {abs(total_dr - total_cr)})"
            )

    # ── Tax expansion ─────────────────────────────────────────────────────────

    def _expand_tax_lines(self, entry: JournalEntryInput) -> list[JournalLineInput]:
        """เพิ่ม VAT/WHT lines อัตโนมัติถ้ามี auto_vat หรือ wht_info."""
        lines = list(entry.lines)

        if entry.auto_vat and entry.vat_info:
            v = entry.vat_info
            if v.input_tax:
                lines.append(JournalLineInput(
                    account_code=self.VAT_INPUT_CODE,
                    side=DrCr.DR,
                    amount=v.vat_amount,
                    description=f"ภาษีซื้อ {v.vat_rate}% บนฐาน {v.tax_base:,.2f}",
                    tax_rate=v.vat_rate,
                    tax_base_amount=v.tax_base,
                ))
            else:
                lines.append(JournalLineInput(
                    account_code=self.VAT_OUTPUT_CODE,
                    side=DrCr.CR,
                    amount=v.vat_amount,
                    description=f"ภาษีขาย {v.vat_rate}% บนฐาน {v.tax_base:,.2f}",
                    tax_rate=v.vat_rate,
                    tax_base_amount=v.tax_base,
                ))

        if entry.wht_info:
            w = entry.wht_info
            if w.is_payer:
                # เราหัก: ลดยอดจ่าย (Cr ลดลง) + ตั้งหนี้ภาษีค้างนำส่ง
                lines.append(JournalLineInput(
                    account_code=self.WHT_PAYABLE_CODE,
                    side=DrCr.CR,
                    amount=w.wht_amount,
                    description=(
                        f"ภงด.{w.wht_type} หัก ณ ที่จ่าย {w.wht_rate}% "
                        f"บนฐาน {w.base_amount:,.2f}"
                    ),
                    tax_rate=w.wht_rate,
                    tax_base_amount=w.base_amount,
                ))
            else:
                # ถูกหัก: สินทรัพย์ WHT รอเครดิต
                lines.append(JournalLineInput(
                    account_code=self.WHT_RECEIVABLE_CODE,
                    side=DrCr.DR,
                    amount=w.wht_amount,
                    description=(
                        f"ภงด.{w.wht_type} ถูกหัก ณ ที่จ่าย {w.wht_rate}% "
                        f"บนฐาน {w.base_amount:,.2f}"
                    ),
                    tax_rate=w.wht_rate,
                    tax_base_amount=w.base_amount,
                ))

        return lines

    # ── Account resolution ────────────────────────────────────────────────────

    async def _resolve_accounts(
        self, lines: list[JournalLineInput]
    ) -> dict[str, ChartOfAccount]:
        """ตรวจสอบและโหลด COA records สำหรับทุก account_code."""
        codes = {ln.account_code for ln in lines}
        stmt = select(ChartOfAccount).where(
            ChartOfAccount.code.in_(codes),
            ChartOfAccount.is_active == True,  # noqa: E712
        )
        result = await self._session.execute(stmt)
        found = {acc.code: acc for acc in result.scalars().all()}

        missing = codes - found.keys()
        if missing:
            raise AccountNotFoundError(
                f"ไม่พบรหัสบัญชีใน COA: {', '.join(sorted(missing))}"
            )

        # ห้ามใช้ header account
        for code, acc in found.items():
            if acc.is_header:
                raise InvalidEntryError(
                    f"รหัส {code} เป็นบัญชีหมวด (header) ไม่สามารถบันทึกได้"
                )

        return found

    # ── Sequence number ───────────────────────────────────────────────────────

    async def _next_ref(
        self,
        journal_type: JournalType,
        ctx: AppContext,
        entry_date: date,
    ) -> str:
        """
        สร้างเลขที่รายการแบบ running ต่อเดือน

        Format: {JT}{YYYYMM}-{seq:04d}
        ตัวอย่าง: GJ202601-0001, SJ202601-0042
        """
        prefix = f"{journal_type}{entry_date.year}{entry_date.month:02d}-"

        stmt = (
            select(func.count())
            .select_from(JournalEntryORM)
            .where(JournalEntryORM.entry_no.like(f"{prefix}%"))
        )
        count: int = (await self._session.execute(stmt)).scalar_one()
        return f"{prefix}{count + 1:04d}"

    # ── DB writes ─────────────────────────────────────────────────────────────

    async def _get_or_create_period(self, entry_date: date) -> Period:
        """คืน Period ที่ตรงกับ entry_date สร้างใหม่ถ้ายังไม่มี."""
        stmt = select(Period).where(
            Period.fiscal_year == entry_date.year,
            Period.month == entry_date.month,
        )
        result = await self._session.execute(stmt)
        period = result.scalar_one_or_none()

        if period is None:
            import calendar
            last_day = calendar.monthrange(entry_date.year, entry_date.month)[1]
            period = Period(
                fiscal_year=entry_date.year,
                month=entry_date.month,
                start_date=entry_date.replace(day=1),
                end_date=entry_date.replace(day=last_day),
                status="open",
            )
            self._session.add(period)
            await self._session.flush()

        return period

    async def _write_journal(
        self,
        entry: JournalEntryInput,
        lines: list[JournalLineInput],
        entry_no: str,
        period: Period,
        ctx: AppContext,
    ) -> JournalEntryORM:
        """เขียน journal_entries + journal_lines."""
        orm_entry = JournalEntryORM(
            entry_no=entry_no,
            journal_type=str(entry.journal_type),
            period_id=period.id,
            entry_date=entry.entry_date,
            reference=entry.reference,
            description=entry.description,
            branch_id=ctx.branch_id,
            user_id=ctx.user_id,
            status="posted",
            source_module=entry.source_module,
            source_id=entry.source_id,
            ocr_ref=entry.ocr_ref,
            posted_at=datetime.now(tz=timezone.utc),
        )
        self._session.add(orm_entry)
        await self._session.flush()  # ได้ orm_entry.id

        for i, ln in enumerate(lines, start=1):
            stmt = select(ChartOfAccount).where(ChartOfAccount.code == ln.account_code)
            acc = (await self._session.execute(stmt)).scalar_one()

            orm_line = JournalLineORM(
                entry_id=orm_entry.id,
                line_no=i,
                account_id=acc.id,
                description=ln.description,
                debit_amount=ln.amount if ln.side == DrCr.DR else Decimal(0),
                credit_amount=ln.amount if ln.side == DrCr.CR else Decimal(0),
                tax_rate=ln.tax_rate,
                tax_base_amount=ln.tax_base_amount,
                cost_center=ln.cost_center,
            )
            self._session.add(orm_line)

        await self._session.flush()
        return orm_entry

    async def _write_ledger(
        self,
        orm_entry: JournalEntryORM,
        lines: list[JournalLineInput],
        account_map: dict[str, ChartOfAccount],
        period: Period,
        ctx: AppContext,
    ) -> None:
        """เขียน ledger_entries + อัปเดต account_balances."""
        # โหลด journal lines ที่เพิ่งบันทึก (ต้องการ id)
        stmt = select(JournalLineORM).where(JournalLineORM.entry_id == orm_entry.id)
        result = await self._session.execute(stmt)
        orm_lines = {ln.line_no: ln for ln in result.scalars().all()}

        for i, ln in enumerate(lines, start=1):
            acc = account_map[ln.account_code]
            orm_line = orm_lines[i]

            running_balance = await self._compute_running_balance(
                account_id=acc.id,
                side=ln.side,
                amount=ln.amount,
                normal_balance=acc.normal_balance,
                period=period,
                ctx=ctx,
            )

            ledger = LedgerEntry(
                account_id=acc.id,
                period_id=period.id,
                entry_id=orm_entry.id,
                line_id=orm_line.id,
                entry_date=orm_entry.entry_date,
                debit_amount=ln.amount if ln.side == DrCr.DR else Decimal(0),
                credit_amount=ln.amount if ln.side == DrCr.CR else Decimal(0),
                running_balance=running_balance,
                branch_id=ctx.branch_id,
            )
            self._session.add(ledger)

            await self._update_account_balance(
                account_id=acc.id,
                period=period,
                branch_id=ctx.branch_id,
                side=ln.side,
                amount=ln.amount,
                normal_balance=acc.normal_balance,
            )

        await self._session.flush()

    async def _compute_running_balance(
        self,
        account_id: int,
        side: DrCr,
        amount: Decimal,
        normal_balance: str,
        period: Period,
        ctx: AppContext,
    ) -> Decimal:
        """คำนวณ running balance หลังจากบันทึก line นี้."""
        stmt = (
            select(LedgerEntry.running_balance)
            .where(
                LedgerEntry.account_id == account_id,
                LedgerEntry.branch_id == ctx.branch_id,
            )
            .order_by(LedgerEntry.id.desc())
            .limit(1)
        )
        result = await self._session.execute(stmt)
        prev_balance: Decimal = result.scalar_one_or_none() or Decimal(0)

        # normal_balance DR: Dr เพิ่ม, Cr ลด
        # normal_balance CR: Cr เพิ่ม, Dr ลด
        if normal_balance == DrCr.DR:
            delta = amount if side == DrCr.DR else -amount
        else:
            delta = -amount if side == DrCr.DR else amount

        return prev_balance + delta

    async def _update_account_balance(
        self,
        account_id: int,
        period: Period,
        branch_id: int,
        side: DrCr,
        amount: Decimal,
        normal_balance: str,
    ) -> None:
        """Upsert account_balances — denormalized summary."""
        stmt = select(AccountBalance).where(
            AccountBalance.account_id == account_id,
            AccountBalance.period_id == period.id,
            AccountBalance.branch_id == branch_id,
        )
        result = await self._session.execute(stmt)
        bal = result.scalar_one_or_none()

        if bal is None:
            bal = AccountBalance(
                account_id=account_id,
                period_id=period.id,
                branch_id=branch_id,
                opening_balance=Decimal(0),
                total_debit=Decimal(0),
                total_credit=Decimal(0),
                closing_balance=Decimal(0),
            )
            self._session.add(bal)
            await self._session.flush()

        if side == DrCr.DR:
            bal.total_debit += amount
        else:
            bal.total_credit += amount

        if normal_balance == DrCr.DR:
            bal.closing_balance = bal.opening_balance + bal.total_debit - bal.total_credit
        else:
            bal.closing_balance = bal.opening_balance + bal.total_credit - bal.total_debit
