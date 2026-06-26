# AccCloud — คู่มือฟีเจอร์ระบบ

**Tech Stack:** FastAPI + SQLAlchemy 2.0 async · SQLite per-company · HTMX 1.9 + Alpine.js 3 + Tailwind CSS · JWT auth (httpOnly cookie)

**กฎเหล็ก:** ทุก Journal Entry ต้องผ่าน `PostingEngine` เท่านั้น — ห้าม INSERT ตรงลงตาราง journal_entries

---

## 1. โครงสร้างระบบ

```
app/
├── api/v1/          — REST API endpoints
├── core/            — PostingEngine, models, services อัตโนมัติ
├── modules/         — AR, AP, Bank, FA, Inventory, Payroll, Petty
├── platform/        — Auth, Company, Firm, User models
├── reports/         — Report generators (BS, IS, TB, CF, Equity, Notes, WP)
├── ocr/             — Claude Vision OCR (bank statement, receipts)
├── ui/              — Jinja2 HTML routes
└── static/css/      — theme.css design system

templates/
├── ar/ ap/ bank/ assets/ inventory/ payroll/ automation/ master/ reports/
└── base.html        — Sidebar, Toast, global JS helpers
```

### Database
- Path: `data/firm_{firm_id}/company_{company_id}/db.sqlite`
- Migrations: `alembic/versions/` (015 migrations)
- CompanyDB session scoped per company — ไม่ต้อง WHERE company_id ใน query

### Auth Flow
- JWT token อยู่ใน httpOnly cookie `access_token`
- Frontend อ่านด้วย: `document.cookie.match(/access_token=([^;]+)/)?.[1]`
- API ทุก endpoint ใช้ `CTX: Annotated[AppContext, Depends(get_app_context)]`

### AppContext fields
```python
firm_id, company_id, branch_id, user_id, user_role, period: date, can_post: bool
```

---

## 2. โมดูลธุรกิจ

### AR — ลูกหนี้การค้า
| URL | ฟีเจอร์ |
|-----|---------|
| `/ar/invoices` | รายการใบแจ้งหนี้ทั้งหมด |
| `/ar/invoices/new?mode=credit` | สร้างใบแจ้งหนี้ขายเชื่อ (Dr ลูกหนี้ / Cr รายได้) |
| `/ar/invoices/new?mode=cash` | สร้างใบแจ้งหนี้ขายสด (Dr เงินสด/ธนาคาร / Cr รายได้) |
| `/ar/receipts/new` | รับชำระ (match กับ invoice) |
| `/ar/billing-notes` | ใบวางบิล |
| `/ar/quotations` | ใบเสนอราคา |

**API:** `GET/POST /api/v1/ar/invoices` · `POST /api/v1/ar/receipts` · `GET/POST /api/v1/ar/billing-notes` · `GET/POST /api/v1/ar/quotations`

---

### AP — เจ้าหนี้การค้า
| URL | ฟีเจอร์ |
|-----|---------|
| `/ap/purchases` | รายการซื้อ/ใบเสร็จจากผู้ขาย |
| `/ap/purchases/new` | บันทึกซื้อ (credit หรือ cash) |
| `/ap/payments/new` | จ่ายชำระเจ้าหนี้ |
| `/ap/po` | ใบสั่งซื้อ (Purchase Order) |

**API:** `GET/POST /api/v1/ap/purchases` · `POST /api/v1/ap/payments` · `GET/POST /api/v1/ap/purchase-orders`

---

### Bank — ธนาคาร
| URL | ฟีเจอร์ |
|-----|---------|
| `/bank/accounts` | ทะเบียนบัญชีธนาคาร (เชื่อม COA) |
| `/bank/transfers` | โอนเงินระหว่างบัญชี |
| `/bank/quick-entry` | **ฝาก/ถอนเร็ว** — บันทึกรายการต่อเนื่อง ไม่ต้อง reset บัญชี |
| `/bank/reconciliation` | **กระทบยอดธนาคาร** — OCR statement + auto-match + confirm |

**API Bank:**
```
GET/POST /api/v1/bank/accounts
POST     /api/v1/bank/transfers
POST     /api/v1/bank/quick-entry       — source_module="bank_quick"
GET      /api/v1/bank/quick-entry       — ประวัติรายการ
POST     /api/v1/bank/statement/upload  — OCR PDF/PNG → auto-match
GET      /api/v1/bank/reconciliation/{id}
POST     /api/v1/bank/reconciliation/{id}/confirm
POST     /api/v1/bank/reconciliation/{id}/auto-post
GET      /api/v1/bank/reconciliation/{id}/report
```

**OCR:** รองรับ 5 ธนาคาร — กรุงไทย, กสิกร, SCB, กรุงเทพ, TTB

**match_status:** `MATCHED` · `NEAR_MATCH` · `STATEMENT_ONLY` · `BOOK_ONLY` · `CONFIRMED` · `MISMATCH`

---

### Inventory — สินค้าคงคลัง
| URL | ฟีเจอร์ |
|-----|---------|
| `/inventory/products` | ทะเบียนสินค้า |
| `/inventory/movements` | รับ/จ่ายสินค้า |
| `/inventory/products/{id}` | รายละเอียดสินค้า + ประวัติ |

**วิธีคำนวณต้นทุน:** AVERAGE หรือ FIFO (ตั้งค่าต่อสินค้า)

---

### Fixed Assets — สินทรัพย์ถาวร
| URL | ฟีเจอร์ |
|-----|---------|
| `/assets` | ทะเบียนสินทรัพย์ทั้งหมด |
| `/assets/{id}` | รายละเอียด + ตารางค่าเสื่อม |
| `/assets/tax-depreciation-report` | รายงานค่าเสื่อมราคาทางภาษี |

**แหล่งเงินลงทุน:** เงินสด / เงินของเจ้าของ / ค้างจ่าย / เช่าซื้อ (Hire-purchase)
**ค่าเสื่อม:** Straight-line, อายุการใช้งานมาตรฐานกรมสรรพากร, แยก book/tax depreciation

---

### Payroll — เงินเดือน
| URL | ฟีเจอร์ |
|-----|---------|
| `/payroll/employees` | ทะเบียนพนักงาน |
| `/payroll/run` | คำนวณเงินเดือน + post JE |
| `/payroll/m40` | แบบ ภ.ง.ด.1ก + สปส.1-10 |

---

### Petty Cash — เงินสดย่อย
**API:** `GET/POST /api/v1/petty/...`

---

### OCR — สแกนเอกสาร
| URL | ฟีเจอร์ |
|-----|---------|
| `/ocr` | อัปโหลดใบเสร็จ/ใบแจ้งหนี้ → Claude Vision |
| `/ocr/review/{id}` | ตรวจสอบและยืนยัน → post JE |

---

## 3. งบการเงิน & รายงาน

| URL | รายงาน | รายละเอียด |
|-----|---------|------------|
| `/ledger` | บัญชีแยกประเภท | กรองบัญชี + ช่วงวันที่ |
| `/reports/trial-balance` | งบทดลอง | ณ สิ้นงวด, export Excel |
| `/reports/balance-sheet` | งบดุล | Current/Non-current, Note mapping, Entity-type aware |
| `/reports/income` | งบกำไรขาดทุน | 3 format: by_nature / by_function (single/multi) |
| `/reports/cashflow` | งบกระแสเงินสด | Indirect method |
| `/reports/equity` | งบแสดงการเปลี่ยนแปลงส่วนของเจ้าของ | Entity-type aware (หุ้นส่วน/บริษัท) |
| `/reports/notes` | หมายเหตุประกอบงบการเงิน | Sidebar toggle enable/disable + preview |
| `/reports/working-paper` | กระดาษทำการ | 6/8/10 คอลัมน์, export Excel |
| `/reports/aging/ar` | Aging ลูกหนี้ | 0/30/60/90/90+ วัน |
| `/reports/aging/ap` | Aging เจ้าหนี้ | 0/30/60/90/90+ วัน |
| `/reports/budget` | Budget vs Actual | เปรียบเทียบงบประมาณ |
| `/reports/cost-center` | ต้นทุนแผนก | Cost Center breakdown |

**Report API prefix:** `GET /api/v1/reports/{balance-sheet|trial-balance|income-statement|equity|notes|working-paper|cashflow}`

---

## 4. อัตโนมัติ (Automation)

| URL | ฟีเจอร์ |
|-----|---------|
| `/automation/recurring` | **รายการบัญชีประจำ** — สร้าง template, monthly/quarterly/yearly, Run อัตโนมัติ |
| `/automation/adjusting` | **ปรับปรุงสิ้นงวด** — Checklist 5 ประเภท (depreciation/accrual/prepaid/deferred_revenue/allowance) |
| `/automation/period-close` | **ปิดงวดบัญชี** — Checklist ก่อนปิด, ปิดงวด, reopen พร้อมเหตุผล |

**Adjusting preset accounts:**
```
depreciation:      Dr 6601 | Cr 1601
accrual:           Dr 6999 | Cr 2199
prepaid:           Dr 2199 | Cr 1301
deferred_revenue:  Dr 2301 | Cr 4101
allowance:         Dr 6701 | Cr 1102
```

**API:**
```
GET/POST /api/v1/recurring
GET      /api/v1/recurring/due?as_of=YYYY-MM-DD
POST     /api/v1/recurring/{id}/execute
GET      /api/v1/adjusting?period=YYYY-MM-DD
POST     /api/v1/adjusting
GET      /api/v1/period/{year}/{month}/checklist
POST     /api/v1/period/{year}/{month}/close
POST     /api/v1/period/{year}/{month}/reopen
```

---

## 5. Master Data

| URL | ฟีเจอร์ |
|-----|---------|
| `/master/coa` | ผังบัญชี — Tree view, add/edit modal, 8 หมวด |
| `/master/contacts` | ลูกค้า/Supplier — 3 tabs (ลูกค้า/ผู้ขาย/ทั้งหมด), aging popup |
| `/settings/exchange-rates` | อัตราแลกเปลี่ยน Multi-currency |

**COA หมวดหลัก (category 1-8):**
1. สินทรัพย์หมุนเวียน
2. สินทรัพย์ไม่หมุนเวียน
3. หนี้สินหมุนเวียน
4. หนี้สินไม่หมุนเวียน
5. ส่วนของเจ้าของ
6. รายได้
7. ต้นทุนขาย
8. ค่าใช้จ่าย

---

## 6. Platform (Multi-tenant)

```
GET/POST /api/v1/firms              — Firm management
GET/POST /api/v1/companies          — Company per firm
POST     /api/v1/auth/login
POST     /api/v1/auth/refresh
```

**Entity types:** `company` · `partnership` · `individual`
**Income statement formats:** `by_nature` · `by_function_single` · `by_function_multi`

---

## 7. Design System

**CSS classes หลัก:**
```
panel / panel-head / panel-title / panel-body
btn / btn-primary / btn-ghost / btn-sm / btn-danger
badge / b-green / b-red / b-amber / b-blue / b-gray / b-teal
form-group / form-grid / form-actions
grid2 / grid3
sb-section / sb-group-head / sb-sub / sb-item
kpi-card / summary-bar
```

**Icons:** Tabler Icons CDN — `<i class="ti ti-{name}"></i>`

**Global JS (base.html):**
```javascript
notify(msg, type)     — Toast notification
getCookie(name)       — Read cookie
api(method, url, body) — Fetch wrapper with Bearer token
```

**Toast:** dispatch `window.dispatchEvent(new CustomEvent('notify', {detail: {msg, type}}))`

---

## 8. Jinja2 Filters

```python
{{ value | currency }}   — จัดรูปแบบตัวเลข 2 ทศนิยม
{{ value | thdate }}     — วันที่ไทย เช่น "1 ม.ค. 68"
{{ value | default("fallback") }}   — ค่าเริ่มต้น (ใช้แทน hasattr)
```

**หมายเหตุ:** Jinja2 ไม่มี `hasattr()` — ใช้ `| default()` filter แทนเสมอ

---

## 9. Migrations

| Migration | เนื้อหา |
|-----------|---------|
| 001–010 | Core models, AR, AP, Bank, FA, Inventory, Payroll, Petty |
| 011 | OCR history |
| 012 | Recurring/Adjusting templates |
| 013 | entity_type + income_statement_format บน Company |
| 014 | note_id mapping บน COA + NoteTemplate |
| 015 | EquityChange model |

---

## 10. GitHub

**Repo:** https://github.com/2bird555687-arch/accounting

**Push:** `git push origin main`

**Branch:** `main` (production-ready)
