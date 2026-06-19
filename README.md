# AccCloud — ระบบบัญชีออนไลน์สำหรับสำนักงานบัญชี

ระบบบัญชีครบวงจรสำหรับสำนักงานบัญชีไทย สร้างด้วย FastAPI + SQLite + HTMX

## สารบัญ

- [Tech Stack](#tech-stack)
- [Quick Start (Deploy)](#quick-start-deploy)
- [Environment Variables](#environment-variables)
- [การเพิ่มกิจการใหม่](#การเพิ่มกิจการใหม่)
- [Backup และ Restore](#backup-และ-restore)
- [SSL / HTTPS](#ssl--https)
- [โครงสร้างระบบ](#โครงสร้างระบบ)

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | FastAPI 0.115, Python 3.11 |
| Database | SQLite per-company (aiosqlite) |
| ORM | SQLAlchemy 2.0 async |
| Auth | JWT (python-jose) + bcrypt |
| Frontend | HTMX 1.9 + Alpine.js 3 + Tailwind CSS |
| OCR | Anthropic Claude Vision API |
| Reverse Proxy | Nginx 1.25 |
| Container | Docker + Docker Compose |
| Export | WeasyPrint (PDF) + openpyxl (Excel) |

---

## Quick Start (Deploy)

### Requirements

- Docker Engine 24+
- Docker Compose v2+
- Git

### ขั้นตอน deploy

```bash
# 1. Clone repository
git clone <repo_url> acccloud
cd acccloud

# 2. สร้าง .env จาก template
cp .env.example .env

# 3. แก้ไขค่าสำคัญใน .env
#    SECRET_KEY  — สร้างด้วย: openssl rand -hex 32
#    ANTHROPIC_API_KEY — ใส่ API key จาก console.anthropic.com
nano .env      # หรือ vim / notepad

# 4. Build + Deploy
make deploy

# 5. Initialize database + seed ข้อมูลเริ่มต้น
make init-db
```

เปิดเบราเซอร์ไปที่ `http://localhost` แล้ว login ด้วย `admin / admin1234`

> **สำคัญ:** เปลี่ยน password ทันทีหลัง login ครั้งแรก

---

## Environment Variables

| ตัวแปร | ค่าตัวอย่าง | คำอธิบาย |
|--------|------------|---------|
| `SECRET_KEY` | *(32-byte hex)* | JWT signing key — **ห้ามใช้ค่า default** |
| `DEBUG` | `false` | Production ต้องเป็น `false` |
| `ANTHROPIC_API_KEY` | `sk-ant-...` | API key สำหรับ OCR |
| `OCR_MODEL` | `claude-sonnet-4-6` | โมเดล Claude สำหรับ OCR |
| `DATABASE_URL` | `sqlite+aiosqlite:///./data/shared.sqlite` | URL ของ shared DB |
| `DATA_DIR` | `data` | ไดเรกทอรีเก็บ SQLite ของแต่ละกิจการ |
| `ALLOWED_ORIGINS` | `["http://localhost"]` | CORS origins ที่อนุญาต |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `60` | อายุ access token |
| `BACKUP_RETENTION_DAYS` | `30` | เก็บ backup กี่วัน |
| `MAX_UPLOAD_SIZE_MB` | `10` | ขนาดสูงสุดของไฟล์ที่ upload |

---

## การเพิ่มกิจการใหม่

### วิธีที่ 1: ผ่าน API (แนะนำ)

```bash
# 1. Login เพื่อรับ token
TOKEN=$(curl -s -X POST http://localhost/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin1234","company_id":1,"branch_id":1}' \
  | python -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

# 2. สร้างกิจการใหม่
curl -X POST http://localhost/api/v1/platform/companies \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "บริษัท ตัวอย่าง จำกัด",
    "tax_id": "0105560000002",
    "fiscal_year_start": 1
  }'

# 3. สร้าง branch หลัก
curl -X POST http://localhost/api/v1/platform/branches \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"company_id": 2, "name": "สำนักงานใหญ่", "is_main": true}'
```

### วิธีที่ 2: ผ่าน Script

```bash
# เปิด shell ใน container
make shell

# รัน seed script โดยระบุ firm_id และ company_id ใหม่
python -c "
import asyncio
from app.database import init_company_db
asyncio.run(init_company_db(firm_id=1, company_id=2))
print('Company DB initialized')
"
```

### วิธีที่ 3: Firm Dashboard (Web UI)

1. Login ด้วย FIRM_ADMIN account
2. ไปที่ **จัดการสำนักงาน** (เมนูซ้าย)
3. คลิก **+ เพิ่มบริษัท**
4. กรอกข้อมูลและบันทึก

---

## Backup และ Restore

### Backup อัตโนมัติ

ระบบ backup อัตโนมัติทุกวันเวลา **02:00 น.** ผ่าน cron ใน container `acccloud_backup`

ไฟล์ backup เก็บที่ Docker volume `backups` และ mount ที่ `/backups` ในรูปแบบ:
```
/backups/
  2026-06-18/
    acccloud_2026-06-18_020001.tar.gz
    manifest.txt
  2026-06-17/
    ...
```

### Backup ด้วยมือ

```bash
make backup
# หรือ
docker compose exec backup sh /backup.sh
```

### ดูรายการ backup ที่มี

```bash
make restore
# หรือ
bash scripts/restore.sh
```

### Restore จาก backup

```bash
# Restore จาก backup วันที่ระบุ (เลือก archive ล่าสุดของวันนั้น)
bash scripts/restore.sh 2026-06-18

# Restore จาก archive ที่ระบุชัดเจน
bash scripts/restore.sh backups/2026-06-18/acccloud_2026-06-18_020001.tar.gz
```

> **หมายเหตุ:** restore script จะ stop app → backup ข้อมูลปัจจุบัน → restore → แจ้งให้ start app ใหม่

### Copy backup ออกจาก Docker volume

```bash
# สร้าง container ชั่วคราวเพื่อ copy ไฟล์
docker run --rm \
  -v acccloud_backups:/backups:ro \
  -v $(pwd)/local_backups:/out \
  alpine cp -r /backups /out/
```

---

## SSL / HTTPS

### ใช้ Certbot (Let's Encrypt)

```bash
# 1. แก้ nginx.conf ให้ใส่ domain จริง
nano nginx/nginx.conf
# เปลี่ยน server_name _; → server_name your-domain.com;

# 2. รัน Certbot
make ssl
# หรือทำเอง:
docker compose exec nginx \
  certbot --nginx -d your-domain.com

# 3. ปลด comment SSL ใน nginx.conf
# (บรรทัด listen 443, ssl_certificate, ฯลฯ)
nano nginx/nginx.conf

# 4. Restart nginx
docker compose restart nginx
```

### ใช้ Certificate ของตัวเอง

```bash
# วาง cert ไว้ที่
mkdir -p nginx/ssl
cp fullchain.pem nginx/ssl/
cp privkey.pem nginx/ssl/

# แล้วปลด comment SSL ใน nginx.conf
```

---

## คำสั่ง make ที่ใช้บ่อย

```bash
make help          # แสดงคำสั่งทั้งหมด
make dev           # รัน dev server แบบ local (ไม่ใช้ Docker)
make deploy        # Build + start production
make stop          # หยุดทุก container
make restart       # restart app container
make logs          # ดู logs ทุก service
make logs-app      # ดู log เฉพาะ app
make shell         # เปิด shell ใน app container
make init-db       # Initialize DB + seed COA
make migrate       # รัน Alembic migrations
make backup        # Backup ด้วยมือ
make status        # แสดงสถานะ containers + health check
make clean         # ลบ containers + images ที่ไม่ใช้
```

---

## โครงสร้างระบบ

```
acccloud/
├── app/
│   ├── api/v1/          # FastAPI routers (REST API)
│   ├── core/            # Journal engine, models, recurring
│   ├── modules/
│   │   ├── ar/          # Accounts Receivable
│   │   ├── ap/          # Accounts Payable
│   │   ├── inv/         # Inventory
│   │   ├── fa/          # Fixed Assets
│   │   ├── tax/         # VAT / WHT
│   │   ├── bank/        # Bank Reconciliation
│   │   └── payroll/     # Payroll
│   ├── ocr/             # Claude Vision OCR
│   ├── reports/         # Financial reports
│   ├── platform/        # Multi-tenant, auth
│   ├── master/          # Contacts, COA
│   └── ui/              # Web UI routes + deps
├── templates/           # Jinja2 HTML templates
├── migrations/          # Alembic migrations
├── nginx/               # Nginx config
├── scripts/             # backup.sh, restore.sh, init_db.sh
├── data/                # SQLite files (gitignored)
├── backups/             # Backup archives (gitignored)
├── Dockerfile
├── docker-compose.yml
├── Makefile
└── .env.example
```

### Database layout

```
data/
├── shared.sqlite                    # Platform DB: users, firms, companies
└── firm_1/
    └── company_1/
        └── db.sqlite                # Per-company: COA, journals, AR, AP, ...
```

---

## โมดูลที่รองรับ

| โมดูล | คำอธิบาย |
|-------|---------|
| **สมุดรายวัน** | GJ, SJ, PJ, CR, CP พร้อม PostingEngine |
| **AR** | ใบเสนอราคา (Quotation), ใบแจ้งหนี้, ใบวางบิล, รับชำระ, อายุหนี้ |
| **AP** | ใบซื้อ, จ่ายชำระ, ใบสั่งซื้อ (PO) |
| **สินค้าคงคลัง** | คลังสินค้า, รับเข้า/เบิกออก |
| **สินทรัพย์ถาวร** | บันทึกทรัพย์สิน, ตารางค่าเสื่อม |
| **ภาษี** | VAT, WHT, ภพ.30, ภงด.1/3/53 |
| **เงินเดือน** | คำนวณเงินเดือน, ประกันสังคม |
| **เงินสดย่อย** | Petty cash |
| **OCR** | สแกนใบกำกับ/ใบเสร็จด้วย Claude Vision |
| **Bank Recon** | ตรวจสอบรายการธนาคาร |
| **Automation** | รายการประจำ, ปรับปรุงสิ้นงวด, ปิดงวด |
| **รายงาน** | งบดุล, P&L, Cash Flow, อายุหนี้, งบรวม |

---

## License

MIT © 2026 AccCloud
