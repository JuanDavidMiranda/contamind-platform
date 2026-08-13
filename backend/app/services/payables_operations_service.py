"""Consultas operativas de cuentas por pagar sobre facturas de compra."""

from datetime import date
from uuid import UUID

from sqlalchemy.orm import Session

from app.services.receivables_operations_service import (
    OpenReceivableItem,
    OpenReceivablesPage,
    ReceivablesOperationsService,
)


OpenPayableItem = OpenReceivableItem
OpenPayablesPage = OpenReceivablesPage


class PayablesOperationsService:
    """Expone obligaciones de compra abiertas sin reutilizar seguimientos de cobro.

    Los pagos reducen el saldo únicamente si coinciden con la moneda de la factura.
    No programa pagos, no concilia bancos y no entrega datos de proveedores al chat.
    """

    def __init__(self, db: Session) -> None:
        self._operations = ReceivablesOperationsService(db)

    def open_items(
        self,
        company_id: UUID,
        *,
        as_of: date,
        limit: int,
        offset: int,
    ) -> OpenPayablesPage:
        return self._operations.open_items(
            company_id,
            as_of=as_of,
            limit=limit,
            offset=offset,
            invoice_type="purchase",
            include_collection_followups=False,
        )

    def update_terms(self, company_id: UUID, invoice_id: UUID, **kwargs):
        return self._operations.update_terms(
            company_id,
            invoice_id,
            invoice_type="purchase",
            invoice_label="Factura de compra",
            **kwargs,
        )
