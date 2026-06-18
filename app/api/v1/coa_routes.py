"""COA routes — ผังบัญชี CRUD."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, field_validator
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.deps import CTX, CompanyDB
from app.api.responses import ok
from app.context import UserRole
from app.core.models import ChartOfAccount

router = APIRouter(prefix="/coa", tags=["Chart of Accounts"])


# ── Response schemas ──────────────────────────────────────────────────────────

class COAOut(BaseModel):
    id: int
    code: str
    name: str
    name_en: Optional[str]
    category: str
    account_type: str
    normal_balance: str
    parent_id: Optional[int]
    is_header: bool
    is_active: bool
    is_system: bool
    description: Optional[str]
    children_count: int = 0

    model_config = {"from_attributes": True}


class COACreate(BaseModel):
    code: str
    name: str
    name_en: Optional[str] = None
    category: str
    account_type: str
    normal_balance: str
    parent_code: Optional[str] = None
    description: Optional[str] = None

    @field_validator("code")
    @classmethod
    def validate_code(cls, v: str) -> str:
        import re
        if not re.fullmatch(r"\d{4,10}", v):
            raise ValueError("รหัสบัญชีต้องเป็นตัวเลข 4-10 หลัก")
        return v

    @field_validator("category")
    @classmethod
    def validate_category(cls, v: str) -> str:
        if v not in ("1", "2", "3", "4", "5", "6", "7", "8"):
            raise ValueError("category ต้องเป็น 1-8")
        return v

    @field_validator("normal_balance")
    @classmethod
    def validate_nb(cls, v: str) -> str:
        if v not in ("DR", "CR"):
            raise ValueError("normal_balance ต้องเป็น DR หรือ CR")
        return v.upper()


class COAUpdate(BaseModel):
    name: Optional[str] = None
    name_en: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None


class COATreeNode(BaseModel):
    """Node ใน tree view ของผังบัญชี."""

    id: int
    code: str
    name: str
    name_en: Optional[str]
    category: str
    account_type: str
    normal_balance: str
    is_header: bool
    is_active: bool
    is_system: bool
    children: list["COATreeNode"] = []

    model_config = {"from_attributes": True}


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("", response_model=dict, summary="ผังบัญชีทั้งหมด")
async def list_coa(
    ctx: CTX,
    company_db: CompanyDB,
    category: Optional[str] = Query(None, description="กรองตามหมวด 1-8"),
    account_type: Optional[str] = Query(None, description="asset/liability/equity/..."),
    active_only: bool = Query(True),
    include_headers: bool = Query(True, description="รวม header accounts"),
    search: Optional[str] = Query(None, description="ค้นหาด้วยรหัสหรือชื่อ"),
    as_tree: bool = Query(False, description="คืนแบบ tree structure"),
) -> dict:
    """
    ดึงผังบัญชีทั้งหมดของ company

    - `as_tree=true` คืนแบบ nested tree (สำหรับ UI แสดงลำดับชั้น)
    - `as_tree=false` คืนแบบ flat list (สำหรับ dropdown)
    """
    stmt = select(ChartOfAccount)

    if active_only:
        stmt = stmt.where(ChartOfAccount.is_active == True)  # noqa: E712
    if not include_headers:
        stmt = stmt.where(ChartOfAccount.is_header == False)  # noqa: E712
    if category:
        stmt = stmt.where(ChartOfAccount.category == category)
    if account_type:
        stmt = stmt.where(ChartOfAccount.account_type == account_type)
    if search:
        stmt = stmt.where(
            ChartOfAccount.code.ilike(f"%{search}%")
            | ChartOfAccount.name.ilike(f"%{search}%")
        )

    stmt = stmt.order_by(ChartOfAccount.code)
    result = await company_db.execute(stmt)
    accounts = result.scalars().all()

    if as_tree:
        tree = _build_tree(accounts)
        return ok(tree)

    out = [COAOut(
        id=a.id,
        code=a.code,
        name=a.name,
        name_en=a.name_en,
        category=a.category,
        account_type=a.account_type,
        normal_balance=a.normal_balance,
        parent_id=a.parent_id,
        is_header=a.is_header,
        is_active=a.is_active,
        is_system=a.is_system,
        description=a.description,
        children_count=sum(1 for x in accounts if x.parent_id == a.id),
    ) for a in accounts]

    return ok(out)


@router.get("/{code}", response_model=dict, summary="ข้อมูลบัญชีด้วยรหัส")
async def get_account(code: str, ctx: CTX, company_db: CompanyDB) -> dict:
    result = await company_db.execute(
        select(ChartOfAccount).where(ChartOfAccount.code == code)
    )
    acc = result.scalar_one_or_none()
    if acc is None:
        raise HTTPException(404, f"ไม่พบรหัสบัญชี {code!r}")
    return ok(COAOut.model_validate(acc))


@router.post(
    "",
    response_model=dict,
    status_code=status.HTTP_201_CREATED,
    summary="เพิ่มบัญชีใหม่",
)
async def create_account(data: COACreate, ctx: CTX, company_db: CompanyDB) -> dict:
    """
    เพิ่มบัญชีใหม่ในผังบัญชี

    - ต้องมีสิทธิ์ accountant ขึ้นไป
    - รหัสต้องไม่ซ้ำ
    """
    if not ctx.can_approve:
        raise HTTPException(403, "ต้องเป็น accountant ขึ้นไปเพื่อแก้ไขผังบัญชี")

    # ตรวจซ้ำ
    dup = await company_db.execute(
        select(ChartOfAccount.id).where(ChartOfAccount.code == data.code)
    )
    if dup.scalar_one_or_none():
        raise HTTPException(409, f"รหัสบัญชี {data.code!r} มีอยู่แล้ว")

    # resolve parent
    parent_id: Optional[int] = None
    if data.parent_code:
        pr = await company_db.execute(
            select(ChartOfAccount.id).where(ChartOfAccount.code == data.parent_code)
        )
        parent_id = pr.scalar_one_or_none()
        if parent_id is None:
            raise HTTPException(400, f"ไม่พบ parent_code {data.parent_code!r}")

    acc = ChartOfAccount(
        code=data.code,
        name=data.name,
        name_en=data.name_en,
        category=data.category,
        account_type=data.account_type,
        normal_balance=data.normal_balance,
        parent_id=parent_id,
        description=data.description,
        is_system=False,
    )
    company_db.add(acc)
    await company_db.flush()
    return ok(COAOut.model_validate(acc), "เพิ่มบัญชีสำเร็จ")


@router.put("/{code}", response_model=dict, summary="แก้ไขบัญชี")
async def update_account(
    code: str,
    data: COAUpdate,
    ctx: CTX,
    company_db: CompanyDB,
) -> dict:
    """
    แก้ไขข้อมูลบัญชี

    - ห้ามแก้ `code`, `normal_balance`, `category` ของ system accounts
    - แก้ได้: name, name_en, description, is_active
    """
    if not ctx.can_approve:
        raise HTTPException(403, "ต้องเป็น accountant ขึ้นไปเพื่อแก้ไขผังบัญชี")

    result = await company_db.execute(
        select(ChartOfAccount).where(ChartOfAccount.code == code)
    )
    acc = result.scalar_one_or_none()
    if acc is None:
        raise HTTPException(404, f"ไม่พบรหัสบัญชี {code!r}")

    for field, val in data.model_dump(exclude_none=True).items():
        setattr(acc, field, val)

    await company_db.flush()
    return ok(COAOut.model_validate(acc), "แก้ไขสำเร็จ")


@router.get("/categories/summary", response_model=dict, summary="สรุปตามหมวด")
async def coa_category_summary(ctx: CTX, company_db: CompanyDB) -> dict:
    """สรุปจำนวนบัญชีแบ่งตามหมวด 1-8."""
    result = await company_db.execute(
        select(ChartOfAccount.category, ChartOfAccount.is_active)
        .where(ChartOfAccount.is_active == True)  # noqa: E712
    )
    rows = result.all()

    category_names = {
        "1": "สินทรัพย์",
        "2": "หนี้สิน",
        "3": "ทุน",
        "4": "รายได้",
        "5": "ต้นทุนขาย",
        "6": "ค่าใช้จ่าย",
        "7": "การเงิน",
        "8": "อื่นๆ",
    }

    summary: dict[str, dict] = {}
    for cat, _ in rows:
        if cat not in summary:
            summary[cat] = {"category": cat, "name": category_names.get(cat, ""), "count": 0}
        summary[cat]["count"] += 1

    return ok(sorted(summary.values(), key=lambda x: x["category"]))


# ── Tree builder ──────────────────────────────────────────────────────────────

def _build_tree(accounts: list[ChartOfAccount]) -> list[dict]:  # type: ignore[type-arg]
    """แปลง flat list → nested tree."""
    id_map: dict[int, dict] = {}  # type: ignore[type-arg]
    roots: list[dict] = []  # type: ignore[type-arg]

    for a in accounts:
        node = {
            "id": a.id,
            "code": a.code,
            "name": a.name,
            "name_en": a.name_en,
            "category": a.category,
            "account_type": a.account_type,
            "normal_balance": a.normal_balance,
            "is_header": a.is_header,
            "is_active": a.is_active,
            "is_system": a.is_system,
            "children": [],
        }
        id_map[a.id] = node

    for a in accounts:
        if a.parent_id and a.parent_id in id_map:
            id_map[a.parent_id]["children"].append(id_map[a.id])
        elif a.parent_id is None:
            roots.append(id_map[a.id])

    return roots
