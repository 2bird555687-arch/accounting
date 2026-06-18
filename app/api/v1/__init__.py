"""API v1 router — รวม sub-routers ทั้งหมด."""

from fastapi import APIRouter

from app.api.v1.ap_routes import router as ap_router
from app.api.v1.ar_routes import router as ar_router
from app.api.v1.auth_routes import router as auth_router
from app.api.v1.coa_routes import router as coa_router
from app.api.v1.contact_routes import router as contact_router
from app.api.v1.fa_routes import router as fa_router
from app.api.v1.inv_routes import router as inv_router
from app.api.v1.journal_routes import router as journal_router
from app.api.v1.ledger_routes import router as ledger_router
from app.api.v1.payroll_routes import router as payroll_router
from app.api.v1.bank_routes import router as bank_router
from app.api.v1.ocr_routes import router as ocr_router
from app.api.v1.petty_routes import router as petty_router
from app.api.v1.platform_routes import router as platform_router
from app.api.v1.tax_routes import router as tax_router

router = APIRouter()


@router.get("/health", tags=["System"])
async def health_check() -> dict[str, str]:
    return {"status": "ok"}


router.include_router(auth_router)
router.include_router(platform_router)
router.include_router(coa_router)
router.include_router(journal_router)
router.include_router(ledger_router)
router.include_router(contact_router)
router.include_router(ar_router)
router.include_router(ap_router)
router.include_router(inv_router)
router.include_router(fa_router)
router.include_router(tax_router)
router.include_router(payroll_router)
router.include_router(petty_router)
router.include_router(ocr_router)
router.include_router(bank_router)
