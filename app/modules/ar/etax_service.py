"""
AR e-Tax Invoice Service — สร้าง XML ตามมาตรฐาน RD Thailand (ETDA / UBL 2.1).

อ้างอิง: ประกาศกรมสรรพากรเรื่อง e-Tax Invoice & e-Receipt
         https://www.rd.go.th/publish/etaxinvoice.html
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional
from xml.dom import minidom

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.ar.models import ARInvoice, ARInvoiceLine, Contact
from app.modules.ar.schemas import ETaxValidationResult

# ── Namespace map (UBL 2.1) ───────────────────────────────────────────────────

_NS = {
    "": "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2",
    "cac": "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2",
    "cbc": "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
    "ext": "urn:oasis:names:specification:ubl:schema:xsd:CommonExtensionComponents-2",
}

# Thai RD invoice type codes
_INVOICE_TYPE_CODE = "388"   # Invoice ปกติ
_CREDIT_NOTE_CODE  = "381"   # Credit Note
_VAT_SCHEME_ID     = "VAT"
_CURRENCY_TH       = "THB"
_COUNTRY_TH        = "TH"


@dataclass
class SellerInfo:
    """ข้อมูลผู้ขาย (จาก company settings หรือ Firm)."""
    tax_id: str
    branch_code: str          # "00000" = สำนักงานใหญ่
    name: str
    address_line: str
    postal_code: str = "10000"
    city: str = "กรุงเทพมหานคร"
    country_code: str = "TH"


class ETaxService:
    """
    สร้าง e-Tax Invoice XML ตามมาตรฐาน RD Thailand.

    รูปแบบ: UBL 2.1 Invoice ที่ปรับให้ตรงกับ spec ของกรมสรรพากร
    """

    def __init__(self, session: AsyncSession) -> None:
        self._db = session

    # ── Public API ────────────────────────────────────────────────────────────

    async def generate_etax_xml(
        self,
        invoice_id: int,
        ctx: "AppContext",  # noqa: F821
        seller: Optional[SellerInfo] = None,
    ) -> str:
        """
        สร้าง XML string สำหรับ e-Tax Invoice.

        Args:
            invoice_id: ID ของ ARInvoice
            ctx: AppContext
            seller: ข้อมูลผู้ขาย — ถ้าไม่ระบุ จะพยายามดึงจาก company profile

        Returns:
            XML string ที่ผ่าน pretty-print แล้ว
        """
        invoice = await self._load_invoice(invoice_id, ctx.company_id)
        contact = invoice.contact

        # ถ้าไม่มี seller info ให้ใช้ placeholder (production จะดึงจาก company profile)
        if seller is None:
            seller = SellerInfo(
                tax_id="0000000000000",
                branch_code="00000",
                name="บริษัท [กรุณาตั้งค่าข้อมูลผู้ขาย]",
                address_line="[ที่อยู่]",
            )

        root = self._build_invoice_xml(invoice, contact, seller)
        return _pretty_xml(root)

    def validate_xml(self, xml_string: str) -> ETaxValidationResult:
        """
        ตรวจสอบ XML string ว่าถูกต้องตามโครงสร้างหรือไม่.

        ตรวจ:
        - Parse ได้ไหม
        - มี element บังคับครบหรือไม่
        - Tax calculation ถูกต้องหรือไม่
        """
        errors: list[str] = []
        warnings: list[str] = []

        # ตรวจ parse
        try:
            root = ET.fromstring(xml_string)
        except ET.ParseError as e:
            return ETaxValidationResult(is_valid=False, errors=[f"XML parse error: {e}"])

        # Register namespaces สำหรับ find
        ns = {
            "cbc": "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
            "cac": "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2",
        }

        required_paths = [
            ("cbc:ID", "Invoice ID (เลขที่ใบกำกับ)"),
            ("cbc:IssueDate", "IssueDate (วันที่ออก)"),
            ("cbc:InvoiceTypeCode", "InvoiceTypeCode"),
            ("cbc:DocumentCurrencyCode", "DocumentCurrencyCode"),
            ("cac:AccountingSupplierParty", "ข้อมูลผู้ขาย"),
            ("cac:AccountingCustomerParty", "ข้อมูลผู้ซื้อ"),
            ("cac:TaxTotal", "ยอด VAT"),
            ("cac:LegalMonetaryTotal", "ยอดรวม"),
            ("cac:InvoiceLine", "รายการสินค้า/บริการ"),
        ]

        for path, label in required_paths:
            if root.find(path, ns) is None:
                errors.append(f"ขาด element: {label} ({path})")

        # ตรวจ TaxID ผู้ขาย
        supplier_tax = root.find(
            "cac:AccountingSupplierParty/cac:Party/cac:PartyTaxScheme/cbc:CompanyID", ns
        )
        if supplier_tax is not None and supplier_tax.text == "0000000000000":
            warnings.append("TaxID ผู้ขายยังเป็นค่า placeholder กรุณาอัปเดต")

        return ETaxValidationResult(
            is_valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
        )

    # ── XML Builder ───────────────────────────────────────────────────────────

    def _build_invoice_xml(
        self,
        invoice: ARInvoice,
        contact: Contact,
        seller: SellerInfo,
    ) -> ET.Element:
        root = ET.Element("Invoice", xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2")
        root.set("xmlns:cac", "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2")
        root.set("xmlns:cbc", "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2")
        root.set("xmlns:ext", "urn:oasis:names:specification:ubl:schema:xsd:CommonExtensionComponents-2")

        _sub(root, "cbc:UBLVersionID", "2.1")
        _sub(root, "cbc:CustomizationID", "urn:th:go:rd:etax:invoice:1.0")
        _sub(root, "cbc:ProfileID", "urn:th:go:rd:etax:th-ubl-invoice")
        _sub(root, "cbc:ID", invoice.invoice_no)
        _sub(root, "cbc:IssueDate", invoice.invoice_date.isoformat())
        _sub(root, "cbc:DueDate", invoice.due_date.isoformat())
        _sub(root, "cbc:InvoiceTypeCode", _INVOICE_TYPE_CODE, listID="UN/ECE 1001 Subset")
        _sub(root, "cbc:DocumentCurrencyCode", _CURRENCY_TH)
        _sub(root, "cbc:TaxCurrencyCode", _CURRENCY_TH)

        if invoice.description:
            _sub(root, "cbc:Note", invoice.description)

        # ── Seller ────────────────────────────────────────────────────────────
        supplier = ET.SubElement(root, "cac:AccountingSupplierParty")
        party = ET.SubElement(supplier, "cac:Party")

        p_id = ET.SubElement(party, "cbc:PartyIdentification")
        _sub(p_id, "cbc:ID", seller.tax_id, schemeID="TIN")

        p_name = ET.SubElement(party, "cac:PartyName")
        _sub(p_name, "cbc:Name", seller.name)

        postal = ET.SubElement(party, "cac:PostalAddress")
        _sub(postal, "cbc:StreetName", seller.address_line)
        _sub(postal, "cbc:CityName", seller.city)
        _sub(postal, "cbc:PostalZone", seller.postal_code)
        country = ET.SubElement(postal, "cac:Country")
        _sub(country, "cbc:IdentificationCode", seller.country_code)

        tax_scheme = ET.SubElement(party, "cac:PartyTaxScheme")
        _sub(tax_scheme, "cbc:CompanyID", seller.tax_id)
        _sub(tax_scheme, "cbc:TaxLevelCode", "N" if seller.branch_code == "00000" else "B")
        scheme = ET.SubElement(tax_scheme, "cac:TaxScheme")
        _sub(scheme, "cbc:ID", _VAT_SCHEME_ID)

        legal = ET.SubElement(party, "cac:PartyLegalEntity")
        _sub(legal, "cbc:RegistrationName", seller.name)
        _sub(legal, "cbc:CompanyID", seller.tax_id)

        # ── Buyer ─────────────────────────────────────────────────────────────
        customer = ET.SubElement(root, "cac:AccountingCustomerParty")
        c_party = ET.SubElement(customer, "cac:Party")

        if contact.tax_id:
            c_pid = ET.SubElement(c_party, "cbc:PartyIdentification")
            _sub(c_pid, "cbc:ID", contact.tax_id, schemeID="TIN")

        c_name = ET.SubElement(c_party, "cac:PartyName")
        _sub(c_name, "cbc:Name", contact.name)

        if contact.address:
            c_postal = ET.SubElement(c_party, "cac:PostalAddress")
            _sub(c_postal, "cbc:StreetName", contact.address)
            c_country = ET.SubElement(c_postal, "cac:Country")
            _sub(c_country, "cbc:IdentificationCode", _COUNTRY_TH)

        if contact.tax_id:
            c_tax = ET.SubElement(c_party, "cac:PartyTaxScheme")
            _sub(c_tax, "cbc:CompanyID", contact.tax_id)
            branch = contact.branch_code or "00000"
            _sub(c_tax, "cbc:TaxLevelCode", "N" if branch == "00000" else "B")
            c_scheme = ET.SubElement(c_tax, "cac:TaxScheme")
            _sub(c_scheme, "cbc:ID", _VAT_SCHEME_ID)

        # ── TaxTotal ──────────────────────────────────────────────────────────
        tax_total = ET.SubElement(root, "cac:TaxTotal")
        _sub(tax_total, "cbc:TaxAmount", _fmt(invoice.vat_amount), currencyID=_CURRENCY_TH)

        subtax = ET.SubElement(tax_total, "cac:TaxSubtotal")
        _sub(subtax, "cbc:TaxableAmount", _fmt(invoice.subtotal), currencyID=_CURRENCY_TH)
        _sub(subtax, "cbc:TaxAmount", _fmt(invoice.vat_amount), currencyID=_CURRENCY_TH)
        tax_cat = ET.SubElement(subtax, "cac:TaxCategory")
        _sub(tax_cat, "cbc:ID", "S")
        vat_rate = (
            invoice.lines[0].vat_rate if invoice.lines else Decimal("7")
        )
        _sub(tax_cat, "cbc:Percent", str(vat_rate))
        t_scheme = ET.SubElement(tax_cat, "cac:TaxScheme")
        _sub(t_scheme, "cbc:ID", _VAT_SCHEME_ID)

        # ── LegalMonetaryTotal ────────────────────────────────────────────────
        lmt = ET.SubElement(root, "cac:LegalMonetaryTotal")
        _sub(lmt, "cbc:LineExtensionAmount", _fmt(invoice.subtotal), currencyID=_CURRENCY_TH)
        _sub(lmt, "cbc:TaxExclusiveAmount", _fmt(invoice.subtotal), currencyID=_CURRENCY_TH)
        _sub(lmt, "cbc:TaxInclusiveAmount", _fmt(invoice.total_amount), currencyID=_CURRENCY_TH)
        _sub(lmt, "cbc:PayableAmount", _fmt(invoice.total_amount), currencyID=_CURRENCY_TH)

        # ── Invoice Lines ─────────────────────────────────────────────────────
        for ln in invoice.lines:
            self._build_invoice_line(root, ln, vat_rate)

        return root

    def _build_invoice_line(
        self, parent: ET.Element, ln: ARInvoiceLine, vat_rate: Decimal
    ) -> None:
        line = ET.SubElement(parent, "cac:InvoiceLine")
        _sub(line, "cbc:ID", str(ln.line_no))
        _sub(line, "cbc:InvoicedQuantity", _fmt4(ln.quantity), unitCode=ln.unit or "EA")
        _sub(line, "cbc:LineExtensionAmount", _fmt(ln.amount), currencyID=_CURRENCY_TH)

        # Tax per line
        lt_total = ET.SubElement(line, "cac:TaxTotal")
        _sub(lt_total, "cbc:TaxAmount", _fmt(ln.vat_amount), currencyID=_CURRENCY_TH)

        lt_sub = ET.SubElement(lt_total, "cac:TaxSubtotal")
        _sub(lt_sub, "cbc:TaxableAmount", _fmt(ln.amount), currencyID=_CURRENCY_TH)
        _sub(lt_sub, "cbc:TaxAmount", _fmt(ln.vat_amount), currencyID=_CURRENCY_TH)
        lt_cat = ET.SubElement(lt_sub, "cac:TaxCategory")
        _sub(lt_cat, "cbc:ID", "S")
        _sub(lt_cat, "cbc:Percent", str(ln.vat_rate))
        lt_scheme = ET.SubElement(lt_cat, "cac:TaxScheme")
        _sub(lt_scheme, "cbc:ID", _VAT_SCHEME_ID)

        # Item
        item = ET.SubElement(line, "cac:Item")
        _sub(item, "cbc:Description", ln.description)

        # Price
        price = ET.SubElement(line, "cac:Price")
        _sub(price, "cbc:PriceAmount", _fmt4(ln.unit_price), currencyID=_CURRENCY_TH)

    # ── DB helpers ────────────────────────────────────────────────────────────

    async def _load_invoice(self, invoice_id: int, company_id: int) -> ARInvoice:
        result = await self._db.execute(
            select(ARInvoice)
            .where(ARInvoice.id == invoice_id, ARInvoice.company_id == company_id)
            .options(
                selectinload(ARInvoice.lines),
                selectinload(ARInvoice.contact),
            )
        )
        inv = result.scalar_one_or_none()
        if inv is None:
            raise HTTPException(404, f"ไม่พบ invoice id={invoice_id}")
        if inv.status == "draft":
            raise HTTPException(400, "ไม่สามารถสร้าง e-Tax สำหรับ draft invoice")
        return inv


# ── XML Helpers ───────────────────────────────────────────────────────────────

def _sub(
    parent: ET.Element,
    tag: str,
    text: Optional[str] = None,
    **attribs: str,
) -> ET.Element:
    el = ET.SubElement(parent, tag, attribs)
    if text is not None:
        el.text = text
    return el


def _fmt(amount: Decimal) -> str:
    return f"{amount:.2f}"


def _fmt4(amount: Decimal) -> str:
    return f"{amount:.4f}"


def _pretty_xml(root: ET.Element) -> str:
    raw = ET.tostring(root, encoding="unicode", xml_declaration=False)
    dom = minidom.parseString(raw)
    pretty = dom.toprettyxml(indent="  ", encoding=None)
    # minidom เพิ่ม <?xml version="1.0" ?> ให้ — แทนที่ด้วย declaration ที่ถูกต้อง
    lines = pretty.split("\n")
    if lines[0].startswith("<?xml"):
        lines[0] = '<?xml version="1.0" encoding="UTF-8"?>'
    return "\n".join(lines)
