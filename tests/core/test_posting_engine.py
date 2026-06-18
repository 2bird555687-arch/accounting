"""Tests สำหรับ PostingEngine — ทดสอบกฎเหล็กทุกข้อ."""

from __future__ import annotations

import pytest
from datetime import date
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from app.context import AppContext, DrCr, JournalType, UserRole
from app.core.engine import (
    JournalEntryInput,
    JournalLineInput,
    PostingEngine,
    ImbalancedEntryError,
    ClosedPeriodError,
    AccountNotFoundError,
    PermissionError,
    VATInfo,
    WHTInfo,
)
from app.core.editor import EditorService, AlreadyReversedError
from app.core.journals import JournalFilter, JournalService
from app.core.ledger import LedgerService
from app.core.models import Base as CoreBase, ChartOfAccount, Period
from app.shared.models import Base as SharedBase


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
async def session():
    """In-memory SQLite session พร้อม tables และ seed COA."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(CoreBase.metadata.create_all)
        await conn.run_sync(SharedBase.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        await _seed_coa(s)
        yield s

    await engine.dispose()


async def _seed_coa(session: AsyncSession) -> None:
    """Seed COA ขั้นต่ำสำหรับ test."""
    accounts = [
        ChartOfAccount(code="1101", name="เงินสด", category="1",
                       account_type="asset", normal_balance="DR",
                       is_header=False, is_system=True),
        ChartOfAccount(code="1102", name="ธนาคาร-กระแสรายวัน", category="1",
                       account_type="asset", normal_balance="DR",
                       is_header=False, is_system=True),
        ChartOfAccount(code="1110", name="ลูกหนี้การค้า", category="1",
                       account_type="asset", normal_balance="DR",
                       is_header=False, is_system=True),
        ChartOfAccount(code="1140", name="ภาษีซื้อ", category="1",
                       account_type="asset", normal_balance="DR",
                       is_header=False, is_system=True),
        ChartOfAccount(code="1141", name="ภาษีหัก ณ ที่จ่าย-ถูกหัก", category="1",
                       account_type="asset", normal_balance="DR",
                       is_header=False, is_system=True),
        ChartOfAccount(code="2101", name="เจ้าหนี้การค้า", category="2",
                       account_type="liability", normal_balance="CR",
                       is_header=False, is_system=True),
        ChartOfAccount(code="2120", name="ภาษีขาย", category="2",
                       account_type="liability", normal_balance="CR",
                       is_header=False, is_system=True),
        ChartOfAccount(code="2121", name="ภาษีหัก ณ ที่จ่าย-ค้างนำส่ง", category="2",
                       account_type="liability", normal_balance="CR",
                       is_header=False, is_system=True),
        ChartOfAccount(code="4101", name="รายได้จากการขาย", category="4",
                       account_type="revenue", normal_balance="CR",
                       is_header=False, is_system=True),
        ChartOfAccount(code="5101", name="ต้นทุนสินค้าขาย", category="5",
                       account_type="cost_of_sales", normal_balance="DR",
                       is_header=False, is_system=True),
        ChartOfAccount(code="6501", name="เงินเดือน", category="6",
                       account_type="expense", normal_balance="DR",
                       is_header=False, is_system=True),
        # header account — ห้ามบันทึก
        ChartOfAccount(code="1000", name="สินทรัพย์", category="1",
                       account_type="asset", normal_balance="DR",
                       is_header=True, is_system=True),
    ]
    session.add_all(accounts)
    await session.commit()


def make_ctx(role: UserRole = UserRole.ACCOUNTANT) -> AppContext:
    return AppContext(
        firm_id=1,
        company_id=1,
        branch_id=1,
        user_id=99,
        user_role=role,
        period=date(2026, 1, 1),
    )


def simple_entry() -> JournalEntryInput:
    """รายการบัญชีง่าย ๆ — รับเงินสด 1,000 บาท."""
    return JournalEntryInput(
        journal_type=JournalType.GJ,
        entry_date=date(2026, 1, 15),
        description="รับเงินสดจากลูกค้า",
        lines=[
            JournalLineInput("1101", DrCr.DR, Decimal("1000")),
            JournalLineInput("4101", DrCr.CR, Decimal("1000")),
        ],
    )


# ── Tests: PostingEngine ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_post_simple_entry(session):
    """กฎเหล็กข้อ 1: ทุก entry ต้องผ่าน PostingEngine."""
    engine = PostingEngine(session)
    ctx = make_ctx()

    entry_no = await engine.post(simple_entry(), ctx)

    assert entry_no.startswith("GJ202601-")
    assert entry_no.endswith("0001")


@pytest.mark.asyncio
async def test_entry_no_sequence(session):
    """entry_no เพิ่มขึ้น sequential ในเดือนเดียวกัน."""
    engine = PostingEngine(session)
    ctx = make_ctx()

    ref1 = await engine.post(simple_entry(), ctx)
    await session.commit()
    ref2 = await engine.post(simple_entry(), ctx)

    assert ref1 == "GJ202601-0001"
    assert ref2 == "GJ202601-0002"


@pytest.mark.asyncio
async def test_imbalanced_entry_raises(session):
    """กฎเหล็กข้อ 2: Dr ≠ Cr ต้องเกิด exception."""
    engine = PostingEngine(session)
    ctx = make_ctx()
    bad_entry = JournalEntryInput(
        journal_type=JournalType.GJ,
        entry_date=date(2026, 1, 15),
        description="รายการไม่สมดุล",
        lines=[
            JournalLineInput("1101", DrCr.DR, Decimal("1000")),
            JournalLineInput("4101", DrCr.CR, Decimal("999")),  # ผิด!
        ],
    )
    with pytest.raises(ImbalancedEntryError):
        await engine.post(bad_entry, ctx)


@pytest.mark.asyncio
async def test_client_viewer_cannot_post(session):
    """กฎเหล็กข้อ 4: client_viewer ไม่มีสิทธิ์ post."""
    engine = PostingEngine(session)
    ctx = make_ctx(role=UserRole.CLIENT_VIEWER)

    with pytest.raises(PermissionError):
        await engine.post(simple_entry(), ctx)


@pytest.mark.asyncio
async def test_auditor_cannot_post(session):
    """auditor ไม่มีสิทธิ์ post."""
    engine = PostingEngine(session)
    ctx = make_ctx(role=UserRole.AUDITOR)

    with pytest.raises(PermissionError):
        await engine.post(simple_entry(), ctx)


@pytest.mark.asyncio
async def test_closed_period_raises(session):
    """กฎเหล็ก: ห้าม post เข้างวดที่ปิดแล้ว."""
    # สร้างงวดที่ปิดแล้ว
    from app.core.models import Period
    import calendar

    period = Period(
        fiscal_year=2026,
        month=1,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 31),
        status="closed",
    )
    session.add(period)
    await session.commit()

    engine = PostingEngine(session)
    ctx = make_ctx()

    with pytest.raises(ClosedPeriodError):
        await engine.post(simple_entry(), ctx)


@pytest.mark.asyncio
async def test_unknown_account_raises(session):
    """ใส่รหัสบัญชีที่ไม่มีใน COA ต้องเกิด exception."""
    engine = PostingEngine(session)
    ctx = make_ctx()
    bad_entry = JournalEntryInput(
        journal_type=JournalType.GJ,
        entry_date=date(2026, 1, 15),
        description="test",
        lines=[
            JournalLineInput("9999", DrCr.DR, Decimal("100")),  # ไม่มีในระบบ
            JournalLineInput("1101", DrCr.CR, Decimal("100")),
        ],
    )
    with pytest.raises(AccountNotFoundError):
        await engine.post(bad_entry, ctx)


@pytest.mark.asyncio
async def test_header_account_raises(session):
    """ห้ามใช้ header account ในการบันทึก."""
    engine = PostingEngine(session)
    ctx = make_ctx()
    bad_entry = JournalEntryInput(
        journal_type=JournalType.GJ,
        entry_date=date(2026, 1, 15),
        description="test",
        lines=[
            JournalLineInput("1000", DrCr.DR, Decimal("100")),  # header!
            JournalLineInput("2101", DrCr.CR, Decimal("100")),
        ],
    )
    with pytest.raises(Exception):
        await engine.post(bad_entry, ctx)


@pytest.mark.asyncio
async def test_auto_vat_input_tax(session):
    """auto_vat = True สร้าง line ภาษีซื้ออัตโนมัติ."""
    engine = PostingEngine(session)
    ctx = make_ctx()

    entry = JournalEntryInput(
        journal_type=JournalType.PJ,
        entry_date=date(2026, 1, 15),
        description="ซื้อสินค้า + VAT 7%",
        lines=[
            JournalLineInput("5101", DrCr.DR, Decimal("100")),
            JournalLineInput("2101", DrCr.CR, Decimal("107")),
        ],
        auto_vat=True,
        vat_info=VATInfo(tax_base=Decimal("100"), vat_rate=Decimal("7"), input_tax=True),
    )

    # ต้องไม่ balance เพราะยังไม่รวม VAT line — engine จะเพิ่ม VAT line ให้
    # แต่ lines ที่ให้ไปบวก VAT line ต้องสมดุล
    # 5101 DR 100 + 1140 DR 7 vs 2101 CR 107 ✓
    entry_no = await engine.post(entry, ctx)
    assert entry_no.startswith("PJ202601-")

    # ตรวจว่า ledger balance ของ 1140 เพิ่มขึ้น 7 บาท
    ledger = LedgerService(session)
    vat_balance = await ledger.get_balance("1140", ctx, as_of_date=date(2026, 1, 15))
    assert vat_balance == Decimal("7")


@pytest.mark.asyncio
async def test_wht_payer(session):
    """WHTInfo is_payer=True สร้าง line 2121 อัตโนมัติ."""
    engine = PostingEngine(session)
    ctx = make_ctx()

    # จ่ายเงิน 970 + WHT 3% = 30 บาท
    entry = JournalEntryInput(
        journal_type=JournalType.CP,
        entry_date=date(2026, 1, 15),
        description="จ่ายค่าบริการ หัก ณ ที่จ่าย 3%",
        lines=[
            JournalLineInput("6501", DrCr.DR, Decimal("1000")),
            JournalLineInput("1101", DrCr.CR, Decimal("970")),
            # WHT line จะถูกเพิ่มอัตโนมัติ: 2121 CR 30
        ],
        wht_info=WHTInfo(
            base_amount=Decimal("1000"),
            wht_rate=Decimal("3"),
            wht_type="53",
            is_payer=True,
        ),
    )
    entry_no = await engine.post(entry, ctx)
    assert entry_no.startswith("CP202601-")


# ── Tests: LedgerService ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ledger_balance_after_post(session):
    """ยอดใน ledger ต้องเป็น 1,000 หลังจาก post."""
    engine = PostingEngine(session)
    ledger = LedgerService(session)
    ctx = make_ctx()

    await engine.post(simple_entry(), ctx)

    bal = await ledger.get_balance("1101", ctx, as_of_date=date(2026, 1, 15))
    assert bal == Decimal("1000")

    rev_bal = await ledger.get_balance("4101", ctx, as_of_date=date(2026, 1, 15))
    assert rev_bal == Decimal("1000")


@pytest.mark.asyncio
async def test_ledger_balance_cumulative(session):
    """ยอดสะสมหลังจาก post หลายรายการ."""
    engine = PostingEngine(session)
    ledger = LedgerService(session)
    ctx = make_ctx()

    await engine.post(simple_entry(), ctx)
    await session.commit()
    await engine.post(simple_entry(), ctx)

    bal = await ledger.get_balance("1101", ctx, as_of_date=date(2026, 1, 31))
    assert bal == Decimal("2000")


@pytest.mark.asyncio
async def test_account_statement(session):
    """account statement ต้องมี opening=0, total_dr=1000, closing=1000."""
    engine = PostingEngine(session)
    ledger = LedgerService(session)
    ctx = make_ctx()

    await engine.post(simple_entry(), ctx)

    stmt = await ledger.get_account_statement(
        "1101", ctx,
        date_from=date(2026, 1, 1),
        date_to=date(2026, 1, 31),
    )

    assert stmt.opening_balance == Decimal("0")
    assert stmt.total_debit == Decimal("1000")
    assert stmt.total_credit == Decimal("0")
    assert stmt.closing_balance == Decimal("1000")
    assert len(stmt.lines) == 1


# ── Tests: JournalService ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_by_ref(session):
    """get_by_ref คืน entry ที่ถูกต้อง."""
    engine = PostingEngine(session)
    journal = JournalService(session)
    ctx = make_ctx()

    entry_no = await engine.post(simple_entry(), ctx)
    result = await journal.get_by_ref(entry_no, ctx)

    assert result is not None
    assert result.entry_no == entry_no
    assert result.journal_type == "GJ"
    assert len(result.lines) == 2
    assert result.total_debit == Decimal("1000")
    assert result.total_credit == Decimal("1000")


@pytest.mark.asyncio
async def test_search_by_date(session):
    """search filter date_from/date_to."""
    engine = PostingEngine(session)
    journal = JournalService(session)
    ctx = make_ctx()

    await engine.post(simple_entry(), ctx)

    results = await journal.search(ctx, JournalFilter(
        date_from=date(2026, 1, 1),
        date_to=date(2026, 1, 31),
    ))
    assert len(results) == 1

    results_empty = await journal.search(ctx, JournalFilter(
        date_from=date(2026, 2, 1),
        date_to=date(2026, 2, 28),
    ))
    assert len(results_empty) == 0


@pytest.mark.asyncio
async def test_search_by_account(session):
    """search กรองตาม account_code."""
    engine = PostingEngine(session)
    journal = JournalService(session)
    ctx = make_ctx()

    await engine.post(simple_entry(), ctx)

    results = await journal.search(ctx, JournalFilter(account_code="1101"))
    assert len(results) == 1

    results_none = await journal.search(ctx, JournalFilter(account_code="2101"))
    assert len(results_none) == 0


# ── Tests: EditorService ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_reverse_entry(session):
    """กฎเหล็กข้อ 3: reverse ต้องสร้าง reversing entry ใหม่."""
    engine = PostingEngine(session)
    editor = EditorService(session)
    journal = JournalService(session)
    ctx = make_ctx()

    entry_no = await engine.post(simple_entry(), ctx)
    await session.commit()

    rev_no = await editor.reverse(entry_no, "ทดสอบกลับรายการ", ctx)

    assert rev_no != entry_no
    assert rev_no.startswith("GJ2026")

    # original ต้องเป็น reversed
    orig = await journal.get_by_ref(entry_no, ctx)
    assert orig is not None
    assert orig.status == "reversed"

    # reversing entry ต้องสมดุล
    rev = await journal.get_by_ref(rev_no, ctx)
    assert rev is not None
    assert rev.is_reversing is True
    assert rev.total_debit == rev.total_credit == Decimal("1000")

    # ledger balance ต้องกลับเป็น 0 หลัง reverse
    ledger = LedgerService(session)
    bal = await ledger.get_balance("1101", ctx, as_of_date=date(2026, 1, 31))
    assert bal == Decimal("0")


@pytest.mark.asyncio
async def test_reverse_already_reversed_raises(session):
    """ห้าม reverse entry ที่ถูก reverse ไปแล้ว."""
    engine = PostingEngine(session)
    editor = EditorService(session)
    ctx = make_ctx()

    entry_no = await engine.post(simple_entry(), ctx)
    await session.commit()
    await editor.reverse(entry_no, "ครั้งแรก", ctx)
    await session.commit()

    with pytest.raises(AlreadyReversedError):
        await editor.reverse(entry_no, "ครั้งที่สอง", ctx)


@pytest.mark.asyncio
async def test_edit_meta_allowed_fields(session):
    """แก้ description ได้ปกติ."""
    engine = PostingEngine(session)
    editor = EditorService(session)
    ctx = make_ctx()

    entry_no = await engine.post(simple_entry(), ctx)
    result = await editor.edit_meta(entry_no, {"description": "แก้ไขแล้ว"}, ctx)

    assert result.description == "แก้ไขแล้ว"


@pytest.mark.asyncio
async def test_edit_meta_immutable_raises(session):
    """ห้ามแก้ journal_type (immutable field)."""
    engine = PostingEngine(session)
    editor = EditorService(session)
    ctx = make_ctx()

    entry_no = await engine.post(simple_entry(), ctx)

    from app.core.editor import ImmutableFieldError
    with pytest.raises(ImmutableFieldError):
        await editor.edit_meta(entry_no, {"journal_type": "SJ"}, ctx)


@pytest.mark.asyncio
async def test_junior_cannot_reverse(session):
    """junior ไม่มีสิทธิ์ reverse."""
    engine = PostingEngine(session)
    editor = EditorService(session)

    ctx_acct = make_ctx(role=UserRole.ACCOUNTANT)
    ctx_junior = make_ctx(role=UserRole.JUNIOR)

    entry_no = await engine.post(simple_entry(), ctx_acct)
    await session.commit()

    with pytest.raises(PermissionError):
        await editor.reverse(entry_no, "test", ctx_junior)
