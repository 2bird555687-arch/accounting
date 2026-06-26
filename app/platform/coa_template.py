"""
COA Template Service — ผังบัญชีมาตรฐาน AccCloud (113 บัญชี, 8 หมวด)

มาตรฐาน TFRS NPAEs 2565 (สำหรับกิจการที่ไม่มีส่วนได้เสียสาธารณะ)

หมวด:
  1 — สินทรัพย์หมุนเวียน
  2 — สินทรัพย์ไม่หมุนเวียน
  3 — หนี้สินหมุนเวียน
  4 — หนี้สินไม่หมุนเวียน
  5 — ส่วนของเจ้าของ
  6 — รายได้
  7 — ต้นทุนขาย
  8 — ค่าใช้จ่าย
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from sqlalchemy import select, text
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
    note_id: Optional[str] = None


# ── account_type ตาม category ─────────────────────────────────────────────────

def _atype(category: str, code: str) -> str:
    mapping = {
        "1": "asset",
        "2": "asset",
        "3": "liability",
        "4": "liability",
        "5": "equity",
        "6": "revenue",
        "7": "cost_of_sales",
        "8": "expense",
    }
    # หมวด 8 หมวดย่อย 8300 (Finance Costs) → finance
    if category == "8" and code >= "8300":
        return "finance"
    return mapping.get(category, "expense")


# ── Standard COA 113 บัญชี (TFRS NPAEs 2565) ─────────────────────────────────

_BASE_COA: list[_COAEntry] = [

    # ══════════════════════════════════════════════════════
    # หมวด 1 — สินทรัพย์หมุนเวียน (Current Assets)
    # ══════════════════════════════════════════════════════
    _COAEntry("1000", "สินทรัพย์หมุนเวียน", "1", _atype("1","1000"), "DR",
              is_header=True, name_en="Current Assets"),

    _COAEntry("1100", "เงินสดและรายการเทียบเท่าเงินสด", "1", _atype("1","1100"), "DR",
              is_header=True, parent_code="1000", name_en="Cash and Cash Equivalents", note_id="cash"),

    _COAEntry("1101", "เงินสดในมือ", "1", _atype("1","1101"), "DR",
              parent_code="1100", name_en="Cash on Hand", note_id="cash"),
    _COAEntry("1102", "เงินฝากธนาคาร — ออมทรัพย์", "1", _atype("1","1102"), "DR",
              parent_code="1100", name_en="Savings Deposit", note_id="cash"),
    _COAEntry("1103", "เงินฝากธนาคาร — กระแสรายวัน", "1", _atype("1","1103"), "DR",
              parent_code="1100", name_en="Current Deposit", note_id="cash"),
    _COAEntry("1104", "เงินฝากประจำ (ไม่เกิน 3 เดือน)", "1", _atype("1","1104"), "DR",
              parent_code="1100", name_en="Fixed Deposit (<=3m)", note_id="cash"),

    _COAEntry("1110", "ลูกหนี้การค้าและลูกหนี้หมุนเวียนอื่น", "1", _atype("1","1110"), "DR",
              is_header=True, parent_code="1000", name_en="Trade and Other Receivables", note_id="ar"),

    _COAEntry("1111", "ลูกหนี้การค้า", "1", _atype("1","1111"), "DR",
              parent_code="1110", name_en="Trade Receivables", note_id="ar"),
    _COAEntry("1112", "ค่าเผื่อหนี้สงสัยจะสูญ", "1", _atype("1","1112"), "CR",
              parent_code="1110", name_en="Allowance for Doubtful Accounts", note_id="ar"),
    _COAEntry("1113", "ลูกหนี้อื่น", "1", _atype("1","1113"), "DR",
              parent_code="1110", name_en="Other Receivables", note_id="ar"),
    _COAEntry("1114", "รายได้ค้างรับ", "1", _atype("1","1114"), "DR",
              parent_code="1110", name_en="Accrued Income", note_id="ar"),

    _COAEntry("1120", "สินค้าคงเหลือ", "1", _atype("1","1120"), "DR",
              is_header=True, parent_code="1000", name_en="Inventories", note_id="inv"),

    _COAEntry("1121", "วัตถุดิบ", "1", _atype("1","1121"), "DR",
              parent_code="1120", name_en="Raw Materials", note_id="inv"),
    _COAEntry("1122", "งานระหว่างทำ", "1", _atype("1","1122"), "DR",
              parent_code="1120", name_en="Work in Progress", note_id="inv"),
    _COAEntry("1123", "สินค้าสำเร็จรูป", "1", _atype("1","1123"), "DR",
              parent_code="1120", name_en="Finished Goods", note_id="inv"),

    _COAEntry("1130", "สินทรัพย์หมุนเวียนอื่น", "1", _atype("1","1130"), "DR",
              is_header=True, parent_code="1000", name_en="Other Current Assets"),

    _COAEntry("1131", "ภาษีซื้อรอเรียกคืน", "1", _atype("1","1131"), "DR",
              parent_code="1130", name_en="Input VAT Receivable"),
    _COAEntry("1132", "ค่าใช้จ่ายจ่ายล่วงหน้า", "1", _atype("1","1132"), "DR",
              parent_code="1130", name_en="Prepaid Expenses"),
    _COAEntry("1133", "เงินมัดจำและเงินประกัน", "1", _atype("1","1133"), "DR",
              parent_code="1130", name_en="Deposits and Guarantees"),

    # ══════════════════════════════════════════════════════
    # หมวด 2 — สินทรัพย์ไม่หมุนเวียน (Non-Current Assets)
    # ══════════════════════════════════════════════════════
    _COAEntry("2000", "สินทรัพย์ไม่หมุนเวียน", "2", _atype("2","2000"), "DR",
              is_header=True, name_en="Non-Current Assets"),

    _COAEntry("2100", "ที่ดิน อาคารและอุปกรณ์", "2", _atype("2","2100"), "DR",
              is_header=True, parent_code="2000", name_en="Property, Plant and Equipment", note_id="ppe"),

    _COAEntry("2101", "ที่ดิน", "2", _atype("2","2101"), "DR",
              parent_code="2100", name_en="Land", note_id="ppe"),
    _COAEntry("2102", "อาคาร", "2", _atype("2","2102"), "DR",
              parent_code="2100", name_en="Buildings", note_id="ppe"),
    _COAEntry("2103", "ส่วนปรับปรุงอาคาร", "2", _atype("2","2103"), "DR",
              parent_code="2100", name_en="Building Improvements", note_id="ppe"),
    _COAEntry("2104", "เครื่องจักรและอุปกรณ์", "2", _atype("2","2104"), "DR",
              parent_code="2100", name_en="Machinery and Equipment", note_id="ppe"),
    _COAEntry("2105", "เฟอร์นิเจอร์และอุปกรณ์สำนักงาน", "2", _atype("2","2105"), "DR",
              parent_code="2100", name_en="Furniture and Office Equipment", note_id="ppe"),
    _COAEntry("2106", "ยานพาหนะ", "2", _atype("2","2106"), "DR",
              parent_code="2100", name_en="Vehicles", note_id="ppe"),
    _COAEntry("2107", "คอมพิวเตอร์และอุปกรณ์", "2", _atype("2","2107"), "DR",
              parent_code="2100", name_en="Computers and Equipment", note_id="ppe"),
    _COAEntry("2108", "งานระหว่างก่อสร้าง", "2", _atype("2","2108"), "DR",
              parent_code="2100", name_en="Construction in Progress", note_id="ppe"),
    _COAEntry("2190", "ค่าเสื่อมราคาสะสม — อาคาร", "2", _atype("2","2190"), "CR",
              parent_code="2100", name_en="Accum. Depr. Buildings", note_id="ppe"),
    _COAEntry("2191", "ค่าเสื่อมราคาสะสม — เครื่องจักร", "2", _atype("2","2191"), "CR",
              parent_code="2100", name_en="Accum. Depr. Machinery", note_id="ppe"),
    _COAEntry("2192", "ค่าเสื่อมราคาสะสม — เฟอร์นิเจอร์", "2", _atype("2","2192"), "CR",
              parent_code="2100", name_en="Accum. Depr. Furniture", note_id="ppe"),
    _COAEntry("2193", "ค่าเสื่อมราคาสะสม — ยานพาหนะ", "2", _atype("2","2193"), "CR",
              parent_code="2100", name_en="Accum. Depr. Vehicles", note_id="ppe"),
    _COAEntry("2194", "ค่าเสื่อมราคาสะสม — คอมพิวเตอร์", "2", _atype("2","2194"), "CR",
              parent_code="2100", name_en="Accum. Depr. Computers", note_id="ppe"),

    _COAEntry("2200", "สินทรัพย์ไม่มีตัวตน", "2", _atype("2","2200"), "DR",
              is_header=True, parent_code="2000", name_en="Intangible Assets", note_id="intangible"),

    _COAEntry("2201", "ซอฟต์แวร์คอมพิวเตอร์", "2", _atype("2","2201"), "DR",
              parent_code="2200", name_en="Computer Software", note_id="intangible"),
    _COAEntry("2202", "ค่าความนิยม (Goodwill)", "2", _atype("2","2202"), "DR",
              parent_code="2200", name_en="Goodwill", note_id="intangible"),
    _COAEntry("2290", "ค่าตัดจำหน่ายสะสม", "2", _atype("2","2290"), "CR",
              parent_code="2200", name_en="Accumulated Amortization", note_id="intangible"),

    _COAEntry("2300", "เงินลงทุนระยะยาว", "2", _atype("2","2300"), "DR",
              parent_code="2000", name_en="Long-term Investments", note_id="invest"),
    _COAEntry("2400", "เงินมัดจำระยะยาว", "2", _atype("2","2400"), "DR",
              parent_code="2000", name_en="Long-term Deposits"),

    # ══════════════════════════════════════════════════════
    # หมวด 3 — หนี้สินหมุนเวียน (Current Liabilities)
    # ══════════════════════════════════════════════════════
    _COAEntry("3000", "หนี้สินหมุนเวียน", "3", _atype("3","3000"), "CR",
              is_header=True, name_en="Current Liabilities"),

    _COAEntry("3100", "เจ้าหนี้การค้าและเจ้าหนี้หมุนเวียนอื่น", "3", _atype("3","3100"), "CR",
              is_header=True, parent_code="3000", name_en="Trade and Other Payables", note_id="ap"),

    _COAEntry("3101", "เจ้าหนี้การค้า", "3", _atype("3","3101"), "CR",
              parent_code="3100", name_en="Trade Payables", note_id="ap"),
    _COAEntry("3102", "เจ้าหนี้อื่น", "3", _atype("3","3102"), "CR",
              parent_code="3100", name_en="Other Payables", note_id="ap"),
    _COAEntry("3103", "ค่าใช้จ่ายค้างจ่าย", "3", _atype("3","3103"), "CR",
              parent_code="3100", name_en="Accrued Expenses", note_id="ap"),
    _COAEntry("3104", "เงินเดือนค้างจ่าย", "3", _atype("3","3104"), "CR",
              parent_code="3100", name_en="Accrued Salaries", note_id="ap"),
    _COAEntry("3105", "ดอกเบี้ยค้างจ่าย", "3", _atype("3","3105"), "CR",
              parent_code="3100", name_en="Accrued Interest", note_id="ap"),

    _COAEntry("3200", "รายได้รับล่วงหน้า", "3", _atype("3","3200"), "CR",
              parent_code="3000", name_en="Deferred Revenue"),
    _COAEntry("3300", "เงินกู้ยืมระยะสั้น", "3", _atype("3","3300"), "CR",
              parent_code="3000", name_en="Short-term Borrowings"),
    _COAEntry("3301", "เงินกู้ยืมกรรมการ — ระยะสั้น", "3", _atype("3","3301"), "CR",
              parent_code="3000", name_en="Director Loans Short-term", note_id="related"),
    _COAEntry("3302", "เงินกู้ยืมระยะยาว — ส่วนครบกำหนด 1 ปี", "3", _atype("3","3302"), "CR",
              parent_code="3000", name_en="Current Portion of LT Debt", note_id="longdebt"),

    _COAEntry("3400", "ภาษีค้างจ่าย", "3", _atype("3","3400"), "CR",
              is_header=True, parent_code="3000", name_en="Tax Payables", note_id="tax_pay"),

    _COAEntry("3401", "ภาษีมูลค่าเพิ่มขาย", "3", _atype("3","3401"), "CR",
              parent_code="3400", name_en="Output VAT", note_id="tax_pay"),
    _COAEntry("3402", "ภาษีหัก ณ ที่จ่ายค้างจ่าย", "3", _atype("3","3402"), "CR",
              parent_code="3400", name_en="WHT Payable", note_id="tax_pay"),
    _COAEntry("3403", "ภาษีเงินได้นิติบุคคลค้างจ่าย", "3", _atype("3","3403"), "CR",
              parent_code="3400", name_en="Corporate Income Tax Payable", note_id="tax_pay"),
    _COAEntry("3404", "ประกันสังคมค้างจ่าย", "3", _atype("3","3404"), "CR",
              parent_code="3400", name_en="Social Security Payable", note_id="tax_pay"),

    # ══════════════════════════════════════════════════════
    # หมวด 4 — หนี้สินไม่หมุนเวียน (Non-Current Liabilities)
    # ══════════════════════════════════════════════════════
    _COAEntry("4000", "หนี้สินไม่หมุนเวียน", "4", _atype("4","4000"), "CR",
              is_header=True, name_en="Non-Current Liabilities"),

    _COAEntry("4100", "เงินกู้ยืมระยะยาว", "4", _atype("4","4100"), "CR",
              parent_code="4000", name_en="Long-term Borrowings", note_id="longdebt"),
    _COAEntry("4101", "หนี้สินตามสัญญาเช่าซื้อ", "4", _atype("4","4101"), "CR",
              parent_code="4000", name_en="Hire-purchase Liabilities", note_id="longdebt"),
    _COAEntry("4200", "ประมาณการผลประโยชน์พนักงาน", "4", _atype("4","4200"), "CR",
              parent_code="4000", name_en="Employee Benefit Obligations", note_id="emp_benefit"),
    _COAEntry("4300", "หนี้สินไม่หมุนเวียนอื่น", "4", _atype("4","4300"), "CR",
              parent_code="4000", name_en="Other Non-Current Liabilities"),

    # ══════════════════════════════════════════════════════
    # หมวด 5 — ส่วนของเจ้าของ (Owner's Equity)
    # ══════════════════════════════════════════════════════
    _COAEntry("5000", "ส่วนของเจ้าของ", "5", _atype("5","5000"), "CR",
              is_header=True, name_en="Owner's Equity"),

    _COAEntry("5101", "ทุนจดทะเบียน", "5", _atype("5","5101"), "CR",
              parent_code="5000", name_en="Registered Capital", note_id="capital"),
    _COAEntry("5102", "ทุนที่ออกและชำระแล้ว", "5", _atype("5","5102"), "CR",
              parent_code="5000", name_en="Issued and Paid-up Capital", note_id="capital"),
    _COAEntry("5103", "ส่วนเกินมูลค่าหุ้นสามัญ", "5", _atype("5","5103"), "CR",
              parent_code="5000", name_en="Share Premium", note_id="capital"),
    _COAEntry("5110", "ทุนสำรองตามกฎหมาย", "5", _atype("5","5110"), "CR",
              parent_code="5000", name_en="Legal Reserve"),

    _COAEntry("5120", "กำไร (ขาดทุน) สะสม", "5", _atype("5","5120"), "CR",
              is_header=True, parent_code="5000", name_en="Retained Earnings (Deficit)"),

    _COAEntry("5121", "กำไรสะสมยังไม่ได้จัดสรร", "5", _atype("5","5121"), "CR",
              parent_code="5120", name_en="Unappropriated Retained Earnings"),
    _COAEntry("5130", "เงินปันผลจ่าย", "5", _atype("5","5130"), "DR",
              parent_code="5000", name_en="Dividends Paid"),

    # สำหรับห้างหุ้นส่วน
    _COAEntry("5201", "ทุน — หุ้นส่วนผู้จัดการ (ห้างฯ)", "5", _atype("5","5201"), "CR",
              parent_code="5000", name_en="Capital — Managing Partner", note_id="capital"),
    _COAEntry("5202", "ทุน — หุ้นส่วน (ห้างฯ)", "5", _atype("5","5202"), "CR",
              parent_code="5000", name_en="Capital — Partner", note_id="capital"),
    _COAEntry("5210", "ส่วนแบ่งกำไร — หุ้นส่วน", "5", _atype("5","5210"), "CR",
              parent_code="5000", name_en="Profit Share — Partner"),

    # ══════════════════════════════════════════════════════
    # หมวด 6 — รายได้ (Revenue)
    # ══════════════════════════════════════════════════════
    _COAEntry("6000", "รายได้", "6", _atype("6","6000"), "CR",
              is_header=True, name_en="Revenue"),

    _COAEntry("6100", "รายได้จากการขายสินค้า", "6", _atype("6","6100"), "CR",
              parent_code="6000", name_en="Sales Revenue"),
    _COAEntry("6101", "ส่วนลดการค้า (หักจากยอดขาย)", "6", _atype("6","6101"), "DR",
              parent_code="6000", name_en="Trade Discount"),
    _COAEntry("6102", "สินค้าส่งคืน", "6", _atype("6","6102"), "DR",
              parent_code="6000", name_en="Sales Returns"),
    _COAEntry("6110", "รายได้จากการให้บริการ", "6", _atype("6","6110"), "CR",
              parent_code="6000", name_en="Service Revenue"),

    _COAEntry("6200", "รายได้อื่น", "6", _atype("6","6200"), "CR",
              is_header=True, parent_code="6000", name_en="Other Income"),

    _COAEntry("6201", "ดอกเบี้ยรับ", "6", _atype("6","6201"), "CR",
              parent_code="6200", name_en="Interest Income"),
    _COAEntry("6202", "กำไรจากการจำหน่ายสินทรัพย์", "6", _atype("6","6202"), "CR",
              parent_code="6200", name_en="Gain on Disposal of Assets"),
    _COAEntry("6203", "รายได้ค่าเช่า", "6", _atype("6","6203"), "CR",
              parent_code="6200", name_en="Rental Income"),
    _COAEntry("6204", "กำไรจากอัตราแลกเปลี่ยน", "6", _atype("6","6204"), "CR",
              parent_code="6200", name_en="Foreign Exchange Gain"),

    # ══════════════════════════════════════════════════════
    # หมวด 7 — ต้นทุนขาย (Cost of Sales)
    # ══════════════════════════════════════════════════════
    _COAEntry("7000", "ต้นทุนขาย", "7", _atype("7","7000"), "DR",
              is_header=True, name_en="Cost of Sales"),

    _COAEntry("7100", "ต้นทุนขายสินค้า", "7", _atype("7","7100"), "DR",
              parent_code="7000", name_en="Cost of Goods Sold"),
    _COAEntry("7110", "ต้นทุนบริการ", "7", _atype("7","7110"), "DR",
              parent_code="7000", name_en="Cost of Services"),
    _COAEntry("7120", "วัตถุดิบใช้ไป", "7", _atype("7","7120"), "DR",
              parent_code="7000", name_en="Raw Materials Used"),
    _COAEntry("7130", "ค่าแรงทางตรง", "7", _atype("7","7130"), "DR",
              parent_code="7000", name_en="Direct Labor"),
    _COAEntry("7140", "ค่าโสหุ้ยการผลิต", "7", _atype("7","7140"), "DR",
              parent_code="7000", name_en="Manufacturing Overhead"),

    # ══════════════════════════════════════════════════════
    # หมวด 8 — ค่าใช้จ่าย (Expenses)
    # ══════════════════════════════════════════════════════
    _COAEntry("8000", "ค่าใช้จ่าย", "8", _atype("8","8000"), "DR",
              is_header=True, name_en="Expenses"),

    _COAEntry("8100", "ค่าใช้จ่ายในการขาย", "8", _atype("8","8100"), "DR",
              is_header=True, parent_code="8000", name_en="Selling Expenses"),

    _COAEntry("8101", "เงินเดือน — ฝ่ายขาย", "8", _atype("8","8101"), "DR",
              parent_code="8100", name_en="Salaries Sales"),
    _COAEntry("8102", "ค่านายหน้าและค่าคอมมิชชัน", "8", _atype("8","8102"), "DR",
              parent_code="8100", name_en="Commissions"),
    _COAEntry("8103", "ค่าโฆษณาและประชาสัมพันธ์", "8", _atype("8","8103"), "DR",
              parent_code="8100", name_en="Advertising and PR"),
    _COAEntry("8104", "ค่าขนส่งและจัดส่งสินค้า", "8", _atype("8","8104"), "DR",
              parent_code="8100", name_en="Freight and Delivery"),
    _COAEntry("8105", "ค่าใช้จ่ายการขายอื่น", "8", _atype("8","8105"), "DR",
              parent_code="8100", name_en="Other Selling Expenses"),

    _COAEntry("8200", "ค่าใช้จ่ายในการบริหาร", "8", _atype("8","8200"), "DR",
              is_header=True, parent_code="8000", name_en="Administrative Expenses"),

    _COAEntry("8201", "เงินเดือน — ฝ่ายบริหาร", "8", _atype("8","8201"), "DR",
              parent_code="8200", name_en="Salaries Admin"),
    _COAEntry("8202", "ค่าเช่าสำนักงาน", "8", _atype("8","8202"), "DR",
              parent_code="8200", name_en="Office Rent"),
    _COAEntry("8203", "ค่าสาธารณูปโภค", "8", _atype("8","8203"), "DR",
              parent_code="8200", name_en="Utilities"),
    _COAEntry("8204", "ค่าซ่อมบำรุง", "8", _atype("8","8204"), "DR",
              parent_code="8200", name_en="Repairs and Maintenance"),
    _COAEntry("8205", "ค่าเสื่อมราคา", "8", _atype("8","8205"), "DR",
              parent_code="8200", name_en="Depreciation"),
    _COAEntry("8206", "ค่าตัดจำหน่ายสินทรัพย์ไม่มีตัวตน", "8", _atype("8","8206"), "DR",
              parent_code="8200", name_en="Amortization"),
    _COAEntry("8207", "ค่าประกันภัย", "8", _atype("8","8207"), "DR",
              parent_code="8200", name_en="Insurance"),
    _COAEntry("8208", "ค่าธรรมเนียมวิชาชีพ", "8", _atype("8","8208"), "DR",
              parent_code="8200", name_en="Professional Fees"),
    _COAEntry("8209", "เครื่องใช้สำนักงาน", "8", _atype("8","8209"), "DR",
              parent_code="8200", name_en="Office Supplies"),
    _COAEntry("8210", "ค่าใช้จ่ายเดินทางและพาหนะ", "8", _atype("8","8210"), "DR",
              parent_code="8200", name_en="Travel and Transportation"),
    _COAEntry("8211", "ค่าประกันสังคม — นายจ้าง", "8", _atype("8","8211"), "DR",
              parent_code="8200", name_en="Social Security Employer"),
    _COAEntry("8212", "ค่าใช้จ่ายบริหารอื่น", "8", _atype("8","8212"), "DR",
              parent_code="8200", name_en="Other Admin Expenses"),

    _COAEntry("8300", "ค่าใช้จ่ายทางการเงิน", "8", _atype("8","8300"), "DR",
              is_header=True, parent_code="8000", name_en="Finance Costs"),

    _COAEntry("8301", "ดอกเบี้ยจ่าย", "8", _atype("8","8301"), "DR",
              parent_code="8300", name_en="Interest Expense"),
    _COAEntry("8302", "ค่าธรรมเนียมธนาคาร", "8", _atype("8","8302"), "DR",
              parent_code="8300", name_en="Bank Charges"),
    _COAEntry("8303", "ขาดทุนจากอัตราแลกเปลี่ยน", "8", _atype("8","8303"), "DR",
              parent_code="8300", name_en="Foreign Exchange Loss"),

    _COAEntry("8400", "ภาษีเงินได้นิติบุคคล", "8", _atype("8","8400"), "DR",
              parent_code="8000", name_en="Corporate Income Tax"),
]


# ── Service ───────────────────────────────────────────────────────────────────

class COATemplateService:
    """Apply COA template ลง company database (ใช้ company session)."""

    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def apply_template(self, template_type: str = "standard") -> int:
        """
        Seed ผังบัญชีมาตรฐาน 113 บัญชี

        Args:
            template_type: "standard" (เท่านั้น — legacy types ถูกยกเลิก)

        Returns:
            จำนวนบัญชีที่เพิ่ม
        """
        all_entries = _BASE_COA

        # ตรวจสอบว่า note_id column มีในตาราง SQLite หรือยัง (migration B2)
        pragma = await self._s.execute(text("PRAGMA table_info(chart_of_accounts)"))
        _table_cols = {row[1] for row in pragma.fetchall()}
        _has_note_id = "note_id" in _table_cols

        # ดึงบัญชีที่มีอยู่แล้ว
        existing = await self._s.execute(select(ChartOfAccount.code))
        existing_codes = {r[0] for r in existing.all()}

        code_to_id: dict[str, int] = {}
        inserted = 0

        # header ก่อน แล้ว detail
        ordered = sorted(all_entries, key=lambda e: (0 if e.is_header else 1, e.code))

        for entry in ordered:
            if entry.code in existing_codes:
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
            # set note_id เฉพาะเมื่อ column มีในตาราง SQLite จริงๆ
            if _has_note_id:
                acc.note_id = entry.note_id
            self._s.add(acc)
            await self._s.flush()
            code_to_id[entry.code] = acc.id
            existing_codes.add(entry.code)
            inserted += 1

        return inserted

    # seed() เป็น alias ของ apply_template เพื่อ backward compat
    async def seed(self, template_type: str = "standard") -> int:
        return await self.apply_template(template_type)

    async def get_template_codes(self, template_type: str = "standard") -> list[str]:
        return sorted({e.code for e in _BASE_COA})

    @staticmethod
    def list_templates() -> list[dict]:  # type: ignore[type-arg]
        return [
            {
                "id": "standard",
                "name": "มาตรฐาน TFRS NPAEs 2565",
                "description": "113 บัญชี 8 หมวด ครอบคลุมทุกประเภทธุรกิจ",
                "account_count": len(_BASE_COA),
            },
        ]
