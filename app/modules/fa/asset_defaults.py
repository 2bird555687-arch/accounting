"""FA — Thai Revenue Department standard useful-life defaults (static config).

อ้างอิงเพดานค่าเสื่อมตาม พ.ร.ฎ. (ฉบับที่ 145) พ.ศ. 2527 และที่แก้ไขเพิ่มเติม.
ใช้เป็นค่าตั้งต้น (default) สำหรับอายุการใช้งานทางบัญชีและทางภาษี.

หมายเหตุ COA codes ตรงกับ coa_template.py จริง:
  1220 ที่ดิน, 1230/1231 อาคาร, 1240/1241 เครื่องจักร,
  1250/1251 เครื่องใช้สำนักงาน/IT/เฟอร์นิเจอร์, 1260/1261 ยานพาหนะ
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class AssetTypeConfig:
    asset_type: str               # internal key
    label_th: str                 # Thai display name
    asset_account_code: str       # COA code for asset
    accum_dep_account_code: str   # COA code for accumulated dep ("" = none)
    tax_max_rate_pct: float       # e.g. 20.0
    tax_min_life_years: int       # minimum life years (legal floor)
    default_life_years: int       # recommended = tax_min_life_years
    has_cost_cap: bool            # True only for passenger car ≤10 seats
    cost_cap_amount: Optional[int]  # 1_000_000 if has_cost_cap else None
    depreciable: bool             # False for land
    category: str = "other"       # map to ASSET_CATEGORY_ACCOUNTS key


ASSET_TYPE_DEFAULTS: dict[str, AssetTypeConfig] = {
    "land": AssetTypeConfig(
        asset_type="land", label_th="ที่ดิน",
        asset_account_code="1220", accum_dep_account_code="",
        tax_max_rate_pct=0, tax_min_life_years=0, default_life_years=0,
        has_cost_cap=False, cost_cap_amount=None, depreciable=False,
        category="land",
    ),
    "building": AssetTypeConfig(
        asset_type="building", label_th="อาคาร",
        asset_account_code="1230", accum_dep_account_code="1231",
        tax_max_rate_pct=5.0, tax_min_life_years=20, default_life_years=20,
        has_cost_cap=False, cost_cap_amount=None, depreciable=True,
        category="building",
    ),
    "machinery": AssetTypeConfig(
        asset_type="machinery", label_th="เครื่องจักร/อุปกรณ์",
        asset_account_code="1240", accum_dep_account_code="1241",
        tax_max_rate_pct=20.0, tax_min_life_years=5, default_life_years=5,
        has_cost_cap=False, cost_cap_amount=None, depreciable=True,
        category="equipment",
    ),
    "furniture": AssetTypeConfig(
        asset_type="furniture", label_th="เครื่องตกแต่ง/เฟอร์นิเจอร์",
        asset_account_code="1250", accum_dep_account_code="1251",
        tax_max_rate_pct=20.0, tax_min_life_years=5, default_life_years=5,
        has_cost_cap=False, cost_cap_amount=None, depreciable=True,
        category="furniture",
    ),
    "vehicle": AssetTypeConfig(
        asset_type="vehicle", label_th="ยานพาหนะ — เพื่อกิจการ/รถบรรทุก",
        asset_account_code="1260", accum_dep_account_code="1261",
        tax_max_rate_pct=20.0, tax_min_life_years=5, default_life_years=5,
        has_cost_cap=False, cost_cap_amount=None, depreciable=True,
        category="vehicle",
    ),
    "vehicle_passenger": AssetTypeConfig(
        asset_type="vehicle_passenger",
        label_th="ยานพาหนะ — รถยนต์นั่งส่วนบุคคล (≤10 ที่นั่ง)",
        asset_account_code="1260", accum_dep_account_code="1261",
        tax_max_rate_pct=20.0, tax_min_life_years=5, default_life_years=5,
        has_cost_cap=True, cost_cap_amount=1_000_000, depreciable=True,
        category="vehicle",
    ),
    "computer": AssetTypeConfig(
        asset_type="computer", label_th="คอมพิวเตอร์/อุปกรณ์ IT",
        asset_account_code="1250", accum_dep_account_code="1251",
        tax_max_rate_pct=33.33, tax_min_life_years=3, default_life_years=3,
        has_cost_cap=False, cost_cap_amount=None, depreciable=True,
        category="it",
    ),
}


def asset_type_list() -> list[dict]:
    """Serializable list of all asset type configs (for API)."""
    out = []
    for cfg in ASSET_TYPE_DEFAULTS.values():
        out.append({
            "asset_type": cfg.asset_type,
            "label_th": cfg.label_th,
            "asset_account_code": cfg.asset_account_code,
            "accum_dep_account_code": cfg.accum_dep_account_code,
            "tax_max_rate_pct": cfg.tax_max_rate_pct,
            "tax_min_life_years": cfg.tax_min_life_years,
            "default_life_years": cfg.default_life_years,
            "has_cost_cap": cfg.has_cost_cap,
            "cost_cap_amount": cfg.cost_cap_amount,
            "depreciable": cfg.depreciable,
            "category": cfg.category,
        })
    return out
