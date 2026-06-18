"""
COA Template Service — ผังบัญชีสำเร็จรูป 3 แบบ

Trading  : ธุรกิจซื้อมาขายไป (สินค้าคงเหลือ + ต้นทุนขาย)
Service  : ธุรกิจบริการ (ไม่มีสินค้า + ต้นทุนบริการ)
Mixed    : ธุรกิจผสม (Trading + Service รวมกัน)

บัญชีครบตามผังบัญชีมาตรฐาน NPAEs ใน Master Prompt
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models import ChartOfAccount


@dataclass(frozen=True)
class _COAEntry:
    """ข้อมูลบัญชีหนึ่งรายการสำหรับ seed."""

    code: str
    name: str
    category: str          # 1-8
    account_type: str      # asset / liability / equity / revenue / cost_of_sales / expense / finance
    normal_balance: str    # DR / CR
    is_header: bool = False
    is_system: bool = True
    name_en: str = ""
    description: str = ""
    parent_code: Optional[str] = None


# ── Base accounts (ทุก template) ──────────────────────────────────────────────

_BASE_COA: list[_COAEntry] = [
    # ══ 1 สินทรัพย์ ══
    _COAEntry("1000", "สินทรัพย์", "1", "asset", "DR",
              is_header=True, name_en="Assets"),

    _COAEntry("1100", "สินทรัพย์หมุนเวียน", "1", "asset", "DR",
              is_header=True, parent_code="1000", name_en="Current Assets"),

    _COAEntry("1101", "เงินสด", "1", "asset", "DR",
              parent_code="1100", name_en="Cash"),
    _COAEntry("1102", "ธนาคาร-กระแสรายวัน", "1", "asset", "DR",
              parent_code="1100", name_en="Bank - Current Account"),
    _COAEntry("1103", "ธนาคาร-ออมทรัพย์", "1", "asset", "DR",
              parent_code="1100", name_en="Bank - Savings Account"),
    _COAEntry("1104", "เงินฝากประจำ", "1", "asset", "DR",
              parent_code="1100", name_en="Fixed Deposit"),

    _COAEntry("1110", "ลูกหนี้การค้า", "1", "asset", "DR",
              parent_code="1100", name_en="Accounts Receivable"),
    _COAEntry("1111", "ลูกหนี้อื่น", "1", "asset", "DR",
              parent_code="1100", name_en="Other Receivables"),
    _COAEntry("1112", "ค่าเผื่อหนี้สงสัยจะสูญ", "1", "asset", "CR",
              parent_code="1100", name_en="Allowance for Doubtful Accounts"),
    _COAEntry("1120", "ตั๋วเงินรับ", "1", "asset", "DR",
              parent_code="1100", name_en="Notes Receivable"),

    _COAEntry("1140", "ภาษีซื้อ", "1", "asset", "DR",
              parent_code="1100", name_en="Input VAT"),
    _COAEntry("1141", "ภาษีหัก ณ ที่จ่าย-ถูกหัก", "1", "asset", "DR",
              parent_code="1100", name_en="WHT Receivable"),
    _COAEntry("1150", "ค่าใช้จ่ายล่วงหน้า", "1", "asset", "DR",
              parent_code="1100", name_en="Prepaid Expenses"),
    _COAEntry("1160", "รายได้ค้างรับ", "1", "asset", "DR",
              parent_code="1100", name_en="Accrued Revenue"),

    _COAEntry("1200", "สินทรัพย์ไม่หมุนเวียน", "1", "asset", "DR",
              is_header=True, parent_code="1000", name_en="Non-Current Assets"),

    _COAEntry("1210", "เงินลงทุนระยะยาว", "1", "asset", "DR",
              parent_code="1200", name_en="Long-term Investments"),
    _COAEntry("1220", "ที่ดิน", "1", "asset", "DR",
              parent_code="1200", name_en="Land"),
    _COAEntry("1230", "อาคาร", "1", "asset", "DR",
              parent_code="1200", name_en="Building"),
    _COAEntry("1231", "ค่าเสื่อมราคาสะสม-อาคาร", "1", "asset", "CR",
              parent_code="1230", name_en="Accumulated Depreciation - Building"),
    _COAEntry("1240", "เครื่องจักรและอุปกรณ์", "1", "asset", "DR",
              parent_code="1200", name_en="Machinery & Equipment"),
    _COAEntry("1241", "ค่าเสื่อมราคาสะสม-เครื่องจักร", "1", "asset", "CR",
              parent_code="1240", name_en="Accumulated Depreciation - Machinery"),
    _COAEntry("1250", "เครื่องใช้สำนักงาน", "1", "asset", "DR",
              parent_code="1200", name_en="Office Equipment"),
    _COAEntry("1251", "ค่าเสื่อมราคาสะสม-เครื่องใช้สำนักงาน", "1", "asset", "CR",
              parent_code="1250", name_en="Accumulated Depreciation - Office Equipment"),
    _COAEntry("1260", "ยานพาหนะ", "1", "asset", "DR",
              parent_code="1200", name_en="Vehicles"),
    _COAEntry("1261", "ค่าเสื่อมราคาสะสม-ยานพาหนะ", "1", "asset", "CR",
              parent_code="1260", name_en="Accumulated Depreciation - Vehicles"),
    _COAEntry("1270", "สินทรัพย์ไม่มีตัวตน", "1", "asset", "DR",
              parent_code="1200", name_en="Intangible Assets"),
    _COAEntry("1271", "ค่าตัดจำหน่ายสะสม-สินทรัพย์ไม่มีตัวตน", "1", "asset", "CR",
              parent_code="1270", name_en="Accumulated Amortization"),

    # ══ 2 หนี้สิน ══
    _COAEntry("2000", "หนี้สิน", "2", "liability", "CR",
              is_header=True, name_en="Liabilities"),

    _COAEntry("2100", "หนี้สินหมุนเวียน", "2", "liability", "CR",
              is_header=True, parent_code="2000", name_en="Current Liabilities"),

    _COAEntry("2101", "เจ้าหนี้การค้า", "2", "liability", "CR",
              parent_code="2100", name_en="Accounts Payable"),
    _COAEntry("2102", "เจ้าหนี้อื่น", "2", "liability", "CR",
              parent_code="2100", name_en="Other Payables"),
    _COAEntry("2110", "ตั๋วเงินจ่าย", "2", "liability", "CR",
              parent_code="2100", name_en="Notes Payable"),
    _COAEntry("2120", "ภาษีขาย", "2", "liability", "CR",
              parent_code="2100", name_en="Output VAT"),
    _COAEntry("2121", "ภาษีหัก ณ ที่จ่าย-ค้างนำส่ง", "2", "liability", "CR",
              parent_code="2100", name_en="WHT Payable"),
    _COAEntry("2122", "ภาษีมูลค่าเพิ่มค้างนำส่ง", "2", "liability", "CR",
              parent_code="2100", name_en="VAT Payable"),
    _COAEntry("2130", "เงินเดือนค้างจ่าย", "2", "liability", "CR",
              parent_code="2100", name_en="Accrued Salaries"),
    _COAEntry("2131", "ประกันสังคมค้างจ่าย", "2", "liability", "CR",
              parent_code="2100", name_en="Accrued Social Security"),
    _COAEntry("2140", "ค่าใช้จ่ายค้างจ่าย", "2", "liability", "CR",
              parent_code="2100", name_en="Accrued Expenses"),
    _COAEntry("2150", "รายได้รับล่วงหน้า", "2", "liability", "CR",
              parent_code="2100", name_en="Deferred Revenue"),
    _COAEntry("2160", "เงินกู้ระยะสั้น", "2", "liability", "CR",
              parent_code="2100", name_en="Short-term Loans"),

    _COAEntry("2200", "หนี้สินไม่หมุนเวียน", "2", "liability", "CR",
              is_header=True, parent_code="2000", name_en="Non-Current Liabilities"),

    _COAEntry("2210", "เงินกู้ระยะยาว", "2", "liability", "CR",
              parent_code="2200", name_en="Long-term Loans"),
    _COAEntry("2220", "หนี้สินภาษีเงินได้รอการตัดบัญชี", "2", "liability", "CR",
              parent_code="2200", name_en="Deferred Tax Liability"),

    # ══ 3 ทุน ══
    _COAEntry("3000", "ส่วนของเจ้าของ", "3", "equity", "CR",
              is_header=True, name_en="Equity"),

    _COAEntry("3101", "ทุนชำระแล้ว", "3", "equity", "CR",
              parent_code="3000", name_en="Paid-up Capital"),
    _COAEntry("3102", "ส่วนเกินมูลค่าหุ้น", "3", "equity", "CR",
              parent_code="3000", name_en="Share Premium"),
    _COAEntry("3201", "กำไรสะสม", "3", "equity", "CR",
              parent_code="3000", name_en="Retained Earnings"),
    _COAEntry("3202", "กำไร(ขาดทุน)สุทธิปีปัจจุบัน", "3", "equity", "CR",
              parent_code="3000", name_en="Net Income (Loss) Current Year"),
    _COAEntry("3301", "เงินถอน/เงินปันผล", "3", "equity", "DR",
              parent_code="3000", name_en="Drawings / Dividends"),

    # ══ 7 การเงิน ══
    _COAEntry("7000", "รายการทางการเงิน", "7", "finance", "DR",
              is_header=True, name_en="Finance"),

    _COAEntry("7101", "ดอกเบี้ยจ่าย", "7", "finance", "DR",
              parent_code="7000", name_en="Interest Expense"),
    _COAEntry("7102", "ค่าธรรมเนียมธนาคาร", "7", "finance", "DR",
              parent_code="7000", name_en="Bank Charges"),
    _COAEntry("7103", "ขาดทุนจากอัตราแลกเปลี่ยน", "7", "finance", "DR",
              parent_code="7000", name_en="Foreign Exchange Loss"),
    _COAEntry("7104", "ขาดทุนจากการขายสินทรัพย์", "7", "finance", "DR",
              parent_code="7000", name_en="Loss on Disposal of Assets"),
    _COAEntry("7201", "ภาษีเงินได้นิติบุคคล", "7", "finance", "DR",
              parent_code="7000", name_en="Corporate Income Tax"),
]


# ── Trading-specific ──────────────────────────────────────────────────────────

_TRADING_COA: list[_COAEntry] = [
    _COAEntry("1130", "สินค้าคงเหลือ", "1", "asset", "DR",
              parent_code="1100", name_en="Inventory"),
    _COAEntry("1131", "วัตถุดิบ", "1", "asset", "DR",
              parent_code="1100", name_en="Raw Materials"),
    _COAEntry("1132", "งานระหว่างทำ", "1", "asset", "DR",
              parent_code="1100", name_en="Work in Progress"),
    _COAEntry("1133", "สินค้าสำเร็จรูป", "1", "asset", "DR",
              parent_code="1100", name_en="Finished Goods"),

    _COAEntry("4000", "รายได้", "4", "revenue", "CR",
              is_header=True, name_en="Revenue"),
    _COAEntry("4101", "รายได้จากการขายสินค้า", "4", "revenue", "CR",
              parent_code="4000", name_en="Sales Revenue"),
    _COAEntry("4102", "รายได้อื่น", "4", "revenue", "CR",
              parent_code="4000", name_en="Other Revenue"),
    _COAEntry("4201", "ดอกเบี้ยรับ", "4", "revenue", "CR",
              parent_code="4000", name_en="Interest Income"),
    _COAEntry("4202", "กำไรจากการขายสินทรัพย์", "4", "revenue", "CR",
              parent_code="4000", name_en="Gain on Disposal of Assets"),
    _COAEntry("4203", "กำไรจากอัตราแลกเปลี่ยน", "4", "revenue", "CR",
              parent_code="4000", name_en="Foreign Exchange Gain"),

    _COAEntry("4901", "ส่วนลดรับ (ซื้อ)", "4", "revenue", "CR",
              parent_code="4000", name_en="Purchase Discounts"),
    _COAEntry("4902", "รับคืนสินค้า (ซื้อ)", "4", "revenue", "CR",
              parent_code="4000", name_en="Purchase Returns"),

    _COAEntry("5000", "ต้นทุนขาย", "5", "cost_of_sales", "DR",
              is_header=True, name_en="Cost of Sales"),
    _COAEntry("5101", "ต้นทุนสินค้าขาย", "5", "cost_of_sales", "DR",
              parent_code="5000", name_en="Cost of Goods Sold"),

    _COAEntry("6000", "ค่าใช้จ่าย", "6", "expense", "DR",
              is_header=True, name_en="Expenses"),
    _COAEntry("6100", "ค่าใช้จ่ายในการขาย", "6", "expense", "DR",
              is_header=True, parent_code="6000", name_en="Selling Expenses"),
    _COAEntry("6101", "เงินเดือน-ฝ่ายขาย", "6", "expense", "DR",
              parent_code="6100", name_en="Salaries - Sales"),
    _COAEntry("6102", "ค่านายหน้า", "6", "expense", "DR",
              parent_code="6100", name_en="Commissions"),
    _COAEntry("6103", "ค่าโฆษณาและประชาสัมพันธ์", "6", "expense", "DR",
              parent_code="6100", name_en="Advertising & Promotion"),
    _COAEntry("6104", "ค่าขนส่ง-ขาออก", "6", "expense", "DR",
              parent_code="6100", name_en="Freight Out"),
    _COAEntry("6105", "ค่าใช้จ่ายในการขายอื่น", "6", "expense", "DR",
              parent_code="6100", name_en="Other Selling Expenses"),
    _COAEntry("6106", "ส่วนลดจ่าย (ขาย)", "6", "expense", "DR",
              parent_code="6100", name_en="Sales Discounts"),

    _COAEntry("6500", "ค่าใช้จ่ายในการบริหาร", "6", "expense", "DR",
              is_header=True, parent_code="6000", name_en="Administrative Expenses"),
    _COAEntry("6501", "เงินเดือน-ฝ่ายบริหาร", "6", "expense", "DR",
              parent_code="6500", name_en="Salaries - Administration"),
    _COAEntry("6502", "ค่าเช่า", "6", "expense", "DR",
              parent_code="6500", name_en="Rent"),
    _COAEntry("6503", "ค่าสาธารณูปโภค", "6", "expense", "DR",
              parent_code="6500", name_en="Utilities"),
    _COAEntry("6504", "ค่าเสื่อมราคา", "6", "expense", "DR",
              parent_code="6500", name_en="Depreciation"),
    _COAEntry("6505", "ค่าซ่อมแซมและบำรุงรักษา", "6", "expense", "DR",
              parent_code="6500", name_en="Repair & Maintenance"),
    _COAEntry("6506", "ค่าประกันภัย", "6", "expense", "DR",
              parent_code="6500", name_en="Insurance"),
    _COAEntry("6507", "ประกันสังคม-ส่วนนายจ้าง", "6", "expense", "DR",
              parent_code="6500", name_en="Social Security - Employer"),
    _COAEntry("6508", "ค่าสอบบัญชี", "6", "expense", "DR",
              parent_code="6500", name_en="Audit Fees"),
    _COAEntry("6509", "ค่าใช้จ่ายสำนักงาน", "6", "expense", "DR",
              parent_code="6500", name_en="Office Expenses"),
    _COAEntry("6510", "ค่าใช้จ่ายในการบริหารอื่น", "6", "expense", "DR",
              parent_code="6500", name_en="Other Administrative Expenses"),
    _COAEntry("6511", "ค่าขนส่ง-ขาเข้า", "6", "expense", "DR",
              parent_code="6500", name_en="Freight In"),
    _COAEntry("6512", "ค่าเบี้ยเลี้ยง", "6", "expense", "DR",
              parent_code="6500", name_en="Per Diem"),
    _COAEntry("6513", "ค่าใช้จ่ายในการเดินทาง", "6", "expense", "DR",
              parent_code="6500", name_en="Travel Expenses"),
    _COAEntry("6514", "ค่าโทรศัพท์และอินเทอร์เน็ต", "6", "expense", "DR",
              parent_code="6500", name_en="Telephone & Internet"),
    _COAEntry("6515", "ค่าเครื่องเขียนและอุปกรณ์", "6", "expense", "DR",
              parent_code="6500", name_en="Stationery & Supplies"),
    _COAEntry("6516", "ค่าฝึกอบรมและพัฒนา", "6", "expense", "DR",
              parent_code="6500", name_en="Training & Development"),
    _COAEntry("6517", "ค่าบริการทางวิชาชีพ", "6", "expense", "DR",
              parent_code="6500", name_en="Professional Services"),
    _COAEntry("6518", "หนี้สูญ", "6", "expense", "DR",
              parent_code="6500", name_en="Bad Debt Expense"),
    _COAEntry("6519", "ค่าภาษีอากร", "6", "expense", "DR",
              parent_code="6500", name_en="Taxes & Duties"),
]


# ── Service-specific additions ────────────────────────────────────────────────

_SERVICE_COA: list[_COAEntry] = [
    _COAEntry("4000", "รายได้", "4", "revenue", "CR",
              is_header=True, name_en="Revenue"),
    _COAEntry("4101", "รายได้จากการให้บริการ", "4", "revenue", "CR",
              parent_code="4000", name_en="Service Revenue"),
    _COAEntry("4102", "รายได้อื่น", "4", "revenue", "CR",
              parent_code="4000", name_en="Other Revenue"),
    _COAEntry("4201", "ดอกเบี้ยรับ", "4", "revenue", "CR",
              parent_code="4000", name_en="Interest Income"),
    _COAEntry("4202", "กำไรจากการขายสินทรัพย์", "4", "revenue", "CR",
              parent_code="4000", name_en="Gain on Disposal of Assets"),

    _COAEntry("5000", "ต้นทุนบริการ", "5", "cost_of_sales", "DR",
              is_header=True, name_en="Cost of Services"),
    _COAEntry("5102", "ต้นทุนการให้บริการ", "5", "cost_of_sales", "DR",
              parent_code="5000", name_en="Cost of Services Rendered"),
    _COAEntry("5103", "เงินเดือน-ฝ่ายปฏิบัติงาน", "5", "cost_of_sales", "DR",
              parent_code="5000", name_en="Salaries - Operations"),
    _COAEntry("5104", "ค่าวัสดุสิ้นเปลือง", "5", "cost_of_sales", "DR",
              parent_code="5000", name_en="Consumable Supplies"),
    _COAEntry("5105", "ค่าจ้างเหมา", "5", "cost_of_sales", "DR",
              parent_code="5000", name_en="Subcontractor Costs"),

    _COAEntry("6000", "ค่าใช้จ่าย", "6", "expense", "DR",
              is_header=True, name_en="Expenses"),
    _COAEntry("6500", "ค่าใช้จ่ายในการบริหาร", "6", "expense", "DR",
              is_header=True, parent_code="6000", name_en="Administrative Expenses"),
    _COAEntry("6501", "เงินเดือน-ฝ่ายบริหาร", "6", "expense", "DR",
              parent_code="6500", name_en="Salaries - Administration"),
    _COAEntry("6502", "ค่าเช่า", "6", "expense", "DR",
              parent_code="6500", name_en="Rent"),
    _COAEntry("6503", "ค่าสาธารณูปโภค", "6", "expense", "DR",
              parent_code="6500", name_en="Utilities"),
    _COAEntry("6504", "ค่าเสื่อมราคา", "6", "expense", "DR",
              parent_code="6500", name_en="Depreciation"),
    _COAEntry("6505", "ค่าซ่อมแซมและบำรุงรักษา", "6", "expense", "DR",
              parent_code="6500", name_en="Repair & Maintenance"),
    _COAEntry("6506", "ค่าประกันภัย", "6", "expense", "DR",
              parent_code="6500", name_en="Insurance"),
    _COAEntry("6507", "ประกันสังคม-ส่วนนายจ้าง", "6", "expense", "DR",
              parent_code="6500", name_en="Social Security - Employer"),
    _COAEntry("6508", "ค่าสอบบัญชี", "6", "expense", "DR",
              parent_code="6500", name_en="Audit Fees"),
    _COAEntry("6509", "ค่าใช้จ่ายสำนักงาน", "6", "expense", "DR",
              parent_code="6500", name_en="Office Expenses"),
    _COAEntry("6510", "ค่าใช้จ่ายในการบริหารอื่น", "6", "expense", "DR",
              parent_code="6500", name_en="Other Administrative Expenses"),
    _COAEntry("6514", "ค่าโทรศัพท์และอินเทอร์เน็ต", "6", "expense", "DR",
              parent_code="6500", name_en="Telephone & Internet"),
    _COAEntry("6515", "ค่าเครื่องเขียนและอุปกรณ์", "6", "expense", "DR",
              parent_code="6500", name_en="Stationery & Supplies"),
    _COAEntry("6517", "ค่าบริการทางวิชาชีพ", "6", "expense", "DR",
              parent_code="6500", name_en="Professional Services"),
    _COAEntry("6518", "หนี้สูญ", "6", "expense", "DR",
              parent_code="6500", name_en="Bad Debt Expense"),
    _COAEntry("6519", "ค่าภาษีอากร", "6", "expense", "DR",
              parent_code="6500", name_en="Taxes & Duties"),
    _COAEntry("6512", "ค่าเบี้ยเลี้ยง", "6", "expense", "DR",
              parent_code="6500", name_en="Per Diem"),
    _COAEntry("6513", "ค่าใช้จ่ายในการเดินทาง", "6", "expense", "DR",
              parent_code="6500", name_en="Travel Expenses"),
]


def _build_mixed_coa() -> list[_COAEntry]:
    """Mixed = Trading + Service extra accounts (ไม่ซ้ำ)."""
    seen_codes = {e.code for e in _TRADING_COA}
    extras = [e for e in _SERVICE_COA if e.code not in seen_codes]
    return _TRADING_COA + extras


_TEMPLATE_MAP: dict[str, list[_COAEntry]] = {
    "trading": _TRADING_COA,
    "service": _SERVICE_COA,
    "mixed": _build_mixed_coa(),
}


# ── Service ───────────────────────────────────────────────────────────────────

class COATemplateService:
    """
    Apply COA template ลง company database

    ใช้ company session (ไม่ใช่ shared session)
    """

    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def apply_template(self, template_type: str = "trading") -> int:
        """
        เพิ่มผังบัญชีตาม template ลง chart_of_accounts

        Args:
            template_type: "trading" | "service" | "mixed"

        Returns:
            จำนวนบัญชีที่เพิ่ม
        """
        if template_type not in _TEMPLATE_MAP:
            raise ValueError(
                f"template_type ไม่ถูกต้อง: {template_type!r} "
                "(ใช้ได้: trading, service, mixed)"
            )

        all_entries = _BASE_COA + _TEMPLATE_MAP[template_type]

        # ดึงบัญชีที่มีอยู่แล้ว
        existing = await self._s.execute(select(ChartOfAccount.code))
        existing_codes = {r[0] for r in existing.all()}

        # build parent_code → id map (ต้อง insert header ก่อน)
        code_to_id: dict[str, int] = {}
        inserted = 0

        # ลำดับ: header ก่อน (is_header=True) แล้วค่อย detail
        ordered = sorted(all_entries, key=lambda e: (0 if e.is_header else 1, e.code))

        for entry in ordered:
            if entry.code in existing_codes:
                # โหลด id สำหรับ parent mapping
                r = await self._s.execute(
                    select(ChartOfAccount.id).where(ChartOfAccount.code == entry.code)
                )
                val = r.scalar_one_or_none()
                if val:
                    code_to_id[entry.code] = val
                continue

            parent_id = code_to_id.get(entry.parent_code) if entry.parent_code else None

            acc = ChartOfAccount(
                code=entry.code,
                name=entry.name,
                name_en=entry.name_en or None,
                category=entry.category,
                account_type=entry.account_type,
                normal_balance=entry.normal_balance,
                parent_id=parent_id,
                is_header=entry.is_header,
                is_system=entry.is_system,
                description=entry.description or None,
            )
            self._s.add(acc)
            await self._s.flush()
            code_to_id[entry.code] = acc.id
            existing_codes.add(entry.code)
            inserted += 1

        return inserted

    async def get_template_codes(self, template_type: str) -> list[str]:
        """คืนรายการรหัสบัญชีทั้งหมดของ template นั้น."""
        if template_type not in _TEMPLATE_MAP:
            raise ValueError(f"template_type ไม่ถูกต้อง: {template_type!r}")
        all_entries = _BASE_COA + _TEMPLATE_MAP[template_type]
        return sorted({e.code for e in all_entries})

    @staticmethod
    def list_templates() -> list[dict]:  # type: ignore[type-arg]
        """คืนรายการ template ที่มี."""
        return [
            {
                "id": "trading",
                "name": "ธุรกิจซื้อมาขายไป",
                "description": "มีสินค้าคงเหลือ, ต้นทุนขาย, ค่าใช้จ่ายขายและบริหาร",
                "account_count": len(_BASE_COA) + len(_TRADING_COA),
            },
            {
                "id": "service",
                "name": "ธุรกิจบริการ",
                "description": "ต้นทุนบริการ, ค่าใช้จ่ายบริหาร (ไม่มีสินค้าคงเหลือ)",
                "account_count": len(_BASE_COA) + len(_SERVICE_COA),
            },
            {
                "id": "mixed",
                "name": "ธุรกิจผสม (ซื้อขาย + บริการ)",
                "description": "รวมทุกบัญชีจาก Trading และ Service",
                "account_count": len(_BASE_COA) + len(_build_mixed_coa()),
            },
        ]
