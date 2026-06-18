"""Master Module Schemas — Contact, Employee, Payroll, PettyCash."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field


# ── Contact ───────────────────────────────────────────────────────────────────

class ContactCreate(BaseModel):
    contact_type: str = Field("customer", pattern="^(customer|supplier|both)$")
    name: str = Field(min_length=1, max_length=200)
    name_en: Optional[str] = None
    tax_id: Optional[str] = None
    branch_code: str = "00000"
    address: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    credit_days: int = 30
    credit_limit: Decimal = Decimal(0)
    wht_rate: Optional[Decimal] = None
    wht_type: Optional[str] = None
    default_ar_account: str = "1110"
    default_ap_account: str = "2101"
    default_revenue_account: str = "4101"
    bank_name: Optional[str] = None
    bank_branch: Optional[str] = None
    bank_account_no: Optional[str] = None
    bank_account_name: Optional[str] = None


class ContactUpdate(BaseModel):
    name: Optional[str] = None
    name_en: Optional[str] = None
    tax_id: Optional[str] = None
    branch_code: Optional[str] = None
    address: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    credit_days: Optional[int] = None
    credit_limit: Optional[Decimal] = None
    wht_rate: Optional[Decimal] = None
    wht_type: Optional[str] = None
    default_ar_account: Optional[str] = None
    default_ap_account: Optional[str] = None
    default_revenue_account: Optional[str] = None
    bank_name: Optional[str] = None
    bank_branch: Optional[str] = None
    bank_account_no: Optional[str] = None
    bank_account_name: Optional[str] = None
    is_active: Optional[bool] = None


class ContactOut(BaseModel):
    id: int
    company_id: int
    contact_type: str
    name: str
    name_en: Optional[str]
    tax_id: Optional[str]
    branch_code: Optional[str]
    address: Optional[str]
    phone: Optional[str]
    email: Optional[str]
    credit_days: int
    credit_limit: Decimal
    wht_rate: Optional[Decimal]
    wht_type: Optional[str]
    default_ar_account: str
    default_ap_account: str
    default_revenue_account: str
    bank_name: Optional[str]
    bank_branch: Optional[str]
    bank_account_no: Optional[str]
    bank_account_name: Optional[str]
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


# ── AR/AP Aging ───────────────────────────────────────────────────────────────

class AgingBucket(BaseModel):
    contact_id: int
    contact_name: str
    current: Decimal         # ยังไม่ถึงกำหนด
    overdue_1_30: Decimal    # เกินกำหนด 1-30 วัน
    overdue_31_60: Decimal
    overdue_61_90: Decimal
    overdue_90_plus: Decimal
    total: Decimal


# ── Employee ──────────────────────────────────────────────────────────────────

class EmployeeCreate(BaseModel):
    employee_code: str = Field(min_length=1, max_length=20)
    name_th: str = Field(min_length=1, max_length=200)
    name_en: Optional[str] = None
    tax_id: Optional[str] = None
    department: Optional[str] = None
    position: Optional[str] = None
    start_date: date
    end_date: Optional[date] = None
    salary: Decimal = Field(gt=0)
    ot_rate: Decimal = Decimal(0)
    sso_rate: Decimal = Decimal("0.05")
    sso_ceiling: Decimal = Decimal(15000)
    bank_name: Optional[str] = None
    bank_account_no: Optional[str] = None
    bank_account_name: Optional[str] = None


class EmployeeUpdate(BaseModel):
    name_th: Optional[str] = None
    name_en: Optional[str] = None
    tax_id: Optional[str] = None
    department: Optional[str] = None
    position: Optional[str] = None
    end_date: Optional[date] = None
    salary: Optional[Decimal] = None
    ot_rate: Optional[Decimal] = None
    sso_rate: Optional[Decimal] = None
    sso_ceiling: Optional[Decimal] = None
    bank_name: Optional[str] = None
    bank_account_no: Optional[str] = None
    bank_account_name: Optional[str] = None
    is_active: Optional[bool] = None


class EmployeeOut(BaseModel):
    id: int
    employee_code: str
    name_th: str
    name_en: Optional[str]
    tax_id: Optional[str]
    department: Optional[str]
    position: Optional[str]
    start_date: date
    end_date: Optional[date]
    salary: Decimal
    ot_rate: Decimal
    sso_rate: Decimal
    sso_ceiling: Decimal
    bank_name: Optional[str]
    bank_account_no: Optional[str]
    bank_account_name: Optional[str]
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


# ── Payroll ───────────────────────────────────────────────────────────────────

class PayrollCalculateIn(BaseModel):
    period: str = Field(pattern=r"^\d{6}$", description="YYYYMM เช่น 202601")
    # Override สำหรับพนักงานที่มี OT / bonus พิเศษเดือนนี้
    overrides: Optional[dict[int, dict]] = None
    # {employee_id: {"ot_hours": 10, "bonus": 5000}}


class PayrollRecordOut(BaseModel):
    id: int
    period: str
    employee_id: int
    employee_name: str
    gross: Decimal
    sso_employee: Decimal
    sso_employer: Decimal
    wht: Decimal
    net: Decimal
    ot_hours: Decimal
    ot_amount: Decimal
    bonus: Decimal
    status: str
    posted_journal_no: Optional[str]
    payment_journal_no: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


class PayrollSummary(BaseModel):
    period: str
    employee_count: int
    total_gross: Decimal
    total_sso_employee: Decimal
    total_sso_employer: Decimal
    total_wht: Decimal
    total_net: Decimal
    status: str
    posted_journal_no: Optional[str]
    payment_journal_no: Optional[str]


# ── Petty Cash ────────────────────────────────────────────────────────────────

class SetupFundIn(BaseModel):
    description: Optional[str] = None
    petty_cash_account: str = "1103"
    bank_account: str = "1102"
    amount: Decimal = Field(gt=0)


class PettyCashFundOut(BaseModel):
    id: int
    fund_no: str
    description: Optional[str]
    petty_cash_account: str
    bank_account: str
    initial_amount: Decimal
    current_balance: Decimal
    status: str
    setup_journal_no: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


class RecordExpenseIn(BaseModel):
    fund_id: int
    expense_date: date
    description: str
    account_code: str          # รหัสค่าใช้จ่าย เช่น "6301"
    amount: Decimal = Field(gt=0)
    receipt_no: Optional[str] = None


class PettyCashExpenseOut(BaseModel):
    id: int
    fund_id: int
    expense_date: date
    description: str
    account_code: str
    amount: Decimal
    receipt_no: Optional[str]
    is_replenished: bool
    replenish_journal_no: Optional[str]
    expense_journal_no: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


class ReplenishResult(BaseModel):
    journal_entry_no: str
    total_replenished: Decimal
    expense_count: int
    new_balance: Decimal
