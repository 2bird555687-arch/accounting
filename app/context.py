"""AppContext — dataclass ที่ทุก request พกพาตลอดการทำงาน."""

from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum


class UserRole(StrEnum):
    """บทบาทผู้ใช้งานในระบบ."""

    FIRM_ADMIN = "firm_admin"         # ผู้ดูแลสำนักงานบัญชี
    ACCOUNTANT = "accountant"         # นักบัญชีอาวุโส
    JUNIOR = "junior"                 # นักบัญชีผู้ช่วย
    CLIENT_VIEWER = "client_viewer"   # ลูกค้าดูอย่างเดียว
    AUDITOR = "auditor"               # ผู้ตรวจสอบ (read-only)


class JournalType(StrEnum):
    """ประเภทสมุดรายวัน."""

    GJ = "GJ"   # General Journal — ทั่วไป
    PJ = "PJ"   # Purchase Journal — ซื้อ
    SJ = "SJ"   # Sales Journal — ขาย
    CP = "CP"   # Cash Payment — จ่ายเงิน
    CR = "CR"   # Cash Receipt — รับเงิน


class AccountCategory(StrEnum):
    """หมวดหมู่ผังบัญชี 8 หมวด (NPAEs)."""

    ASSET = "1"           # สินทรัพย์
    LIABILITY = "2"       # หนี้สิน
    EQUITY = "3"          # ทุน
    REVENUE = "4"         # รายได้
    COST_OF_SALES = "5"   # ต้นทุนขาย
    EXPENSE = "6"         # ค่าใช้จ่าย
    FINANCE = "7"         # การเงิน
    OTHER = "8"           # อื่นๆ


class DrCr(StrEnum):
    """เดบิต / เครดิต."""

    DR = "DR"
    CR = "CR"


@dataclass(frozen=True, slots=True)
class AppContext:
    """
    Context ที่ทุก request พกพา ใช้แทน global state.

    ส่งผ่านเป็น dependency injection ใน FastAPI:
        ctx: AppContext = Depends(get_app_context)
    """

    firm_id: int
    company_id: int
    branch_id: int
    user_id: int
    user_role: UserRole
    period: date                        # งวดบัญชีปัจจุบัน (วันที่ 1 ของเดือน)
    fiscal_year: int = field(init=False)
    fiscal_month: int = field(init=False)

    def __post_init__(self) -> None:
        # frozen dataclass ต้องใช้ object.__setattr__
        object.__setattr__(self, "fiscal_year", self.period.year)
        object.__setattr__(self, "fiscal_month", self.period.month)

    # ── Permission helpers ───────────────────────────────────────────────────

    @property
    def can_post(self) -> bool:
        """มีสิทธิ์บันทึกรายการบัญชีหรือไม่."""
        return self.user_role in (UserRole.FIRM_ADMIN, UserRole.ACCOUNTANT, UserRole.JUNIOR)

    @property
    def can_approve(self) -> bool:
        """มีสิทธิ์อนุมัติ/ยืนยันรายการหรือไม่."""
        return self.user_role in (UserRole.FIRM_ADMIN, UserRole.ACCOUNTANT)

    @property
    def can_close_period(self) -> bool:
        """มีสิทธิ์ปิดงวดบัญชีหรือไม่."""
        return self.user_role == UserRole.FIRM_ADMIN

    @property
    def is_read_only(self) -> bool:
        """เป็น read-only user หรือไม่."""
        return self.user_role in (UserRole.CLIENT_VIEWER, UserRole.AUDITOR)

    @property
    def is_hq(self) -> bool:
        """branch ปัจจุบันเป็น HQ หรือไม่ (branch_code 00000)."""
        # branch_id=1 ถูก seed เป็น HQ เสมอ — ตรวจจาก branch record จริงในชั้น service
        return self.branch_id == 1

    # ── DB routing ───────────────────────────────────────────────────────────

    @property
    def db_key(self) -> str:
        """key สำหรับ lookup connection pool ของ company นี้."""
        return f"firm_{self.firm_id}_company_{self.company_id}"

    def to_audit_dict(self) -> dict[str, int | str]:
        """แปลงเป็น dict สำหรับบันทึก audit log."""
        return {
            "firm_id": self.firm_id,
            "company_id": self.company_id,
            "branch_id": self.branch_id,
            "user_id": self.user_id,
            "user_role": str(self.user_role),
            "period": self.period.isoformat(),
        }
