from fastapi import APIRouter

from app.api.v1.admin import router as admin_router
from app.api.v1.auth import router as auth_router
from app.api.v1.bank_reconciliation import router as bank_reconciliation_router
from app.api.v1.chat.controller import company_chat_router, router as chat_router
from app.api.v1.collection_followups import router as collection_followups_router
from app.api.v1.payables_operations import router as payables_operations_router
from app.api.v1.company_memberships import router as company_memberships_router
from app.api.v1.companies import router as companies_router, tenant_router
from app.api.v1.data_sources import router as data_sources_router
from app.api.v1.dian import router as dian_router
from app.api.v1.dian_electronic_invoicing import router as dian_electronic_invoicing_router
from app.api.v1.electronic_invoicing import router as electronic_invoicing_router
from app.api.v1.exogenous_information import router as exogenous_information_router
from app.api.v1.health import router as health_router
from app.api.v1.manual_accounting import router as manual_accounting_router
from app.api.v1.receivables_operations import router as receivables_operations_router

api_router = APIRouter()

api_router.include_router(health_router)
api_router.include_router(chat_router)
api_router.include_router(company_chat_router)
api_router.include_router(auth_router)
api_router.include_router(bank_reconciliation_router)
api_router.include_router(admin_router)
api_router.include_router(companies_router)
api_router.include_router(tenant_router)
api_router.include_router(company_memberships_router)
api_router.include_router(collection_followups_router)
api_router.include_router(payables_operations_router)
api_router.include_router(receivables_operations_router)
api_router.include_router(data_sources_router)
api_router.include_router(data_sources_router, prefix="/admin", include_in_schema=False)
api_router.include_router(dian_router)
api_router.include_router(dian_electronic_invoicing_router)
api_router.include_router(manual_accounting_router)
api_router.include_router(electronic_invoicing_router)
api_router.include_router(exogenous_information_router)
