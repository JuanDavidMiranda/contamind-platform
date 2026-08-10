"""Adaptador financiero en memoria para probar contratos, nunca para producción."""

from dataclasses import dataclass
from typing import Any

from app.providers.canonical import (
    CANONICAL_VERSION,
    Invoice,
    JournalEntry,
    Page,
    PageRequest,
    Party,
    PartyType,
    ProviderContext,
    ProviderKind,
)
from app.providers.ports import FinancialProviderPort
from app.providers.secrets import SecretStore
from app.shared.errors import app_error


@dataclass(frozen=True)
class ProviderAuditEvent:
    company_id: str
    provider: ProviderKind
    operation: str
    correlation_id: str | None


class MockFinancialProvider(FinancialProviderPort):
    """Contrato de referencia para tests de adaptadores y mapeos canónicos."""

    canonical_version = CANONICAL_VERSION

    def __init__(
        self,
        provider: ProviderKind = ProviderKind.SIIGO,
        secret_store: SecretStore | None = None,
    ) -> None:
        if provider is ProviderKind.DIAN:
            raise ValueError("DIAN debe usar el port fiscal, no el financiero.")
        self.provider = provider
        self._secret_store = secret_store
        self._parties: dict[str, dict[str, Party]] = {}
        self._invoices_by_key: dict[tuple[str, str], Invoice] = {}
        self._audit_events: list[ProviderAuditEvent] = []

    @property
    def audit_events(self) -> tuple[ProviderAuditEvent, ...]:
        return tuple(self._audit_events)

    def authenticate(self, context: ProviderContext) -> str:
        if self._secret_store is None or self._secret_store.get(context) is None:
            raise app_error(
                "PROVIDER_AUTH_FAILED",
                details={"provider": context.provider.value},
            )
        self._audit(context, "authenticate")
        return "mock-authenticated-transport"

    def register_party(self, context: ProviderContext, party: Party) -> None:
        self._assert_company(context, party.company_id)
        if party.external_id is None:
            raise ValueError("El mock requiere external_id para registrar terceros.")
        self._parties.setdefault(str(context.company_id), {})[party.external_id] = party

    def to_provider_party(self, party: Party) -> dict[str, Any]:
        """Simula un DTO externo mínimo, sin adoptar un esquema de proveedor real."""
        return {
            "external_id": party.external_id,
            "party_type": party.party_type.value,
            "document_type": party.document_type,
            "document_number": party.document_number,
            "name": party.name,
            "email": party.email,
            "city": party.city,
        }

    def from_provider_party(self, context: ProviderContext, payload: dict[str, Any]) -> Party:
        return Party(
            company_id=context.company_id,
            party_type=PartyType(payload["party_type"]),
            name=payload["name"],
            document_type=payload.get("document_type"),
            document_number=payload.get("document_number"),
            email=payload.get("email"),
            city=payload.get("city"),
            external_id=payload.get("external_id"),
        )

    async def get_party(self, context: ProviderContext, external_id: str) -> Party:
        party = self._parties.get(str(context.company_id), {}).get(external_id)
        if party is None:
            raise app_error(
                "NOT_FOUND",
                message="Tercero no encontrado en el proveedor.",
                details={"provider": context.provider.value},
            )
        self._audit(context, "get_party")
        return party

    async def list_parties(
        self, context: ProviderContext, page: PageRequest
    ) -> Page[Party]:
        parties = sorted(
            self._parties.get(str(context.company_id), {}).values(),
            key=lambda party: party.external_id or "",
        )
        start = (page.page - 1) * page.page_size
        self._audit(context, "list_parties")
        return Page(
            items=tuple(parties[start : start + page.page_size]),
            page=page.page,
            page_size=page.page_size,
            total=len(parties),
        )

    async def create_invoice(
        self,
        context: ProviderContext,
        invoice: Invoice,
        *,
        idempotency_key: str | None = None,
    ) -> Invoice:
        self._assert_company(context, invoice.company_id)
        if idempotency_key and len(idempotency_key) > 30:
            raise ValueError("La clave de idempotencia no puede superar 30 caracteres.")
        if idempotency_key:
            key = (str(context.company_id), idempotency_key)
            if previous := self._invoices_by_key.get(key):
                self._audit(context, "create_invoice")
                return previous
            self._invoices_by_key[key] = invoice
        self._audit(context, "create_invoice")
        return invoice

    async def list_journal_entries(
        self, context: ProviderContext, page: PageRequest
    ) -> Page[JournalEntry]:
        self._audit(context, "list_journal_entries")
        return Page(items=(), page=page.page, page_size=page.page_size, total=0)

    def _audit(self, context: ProviderContext, operation: str) -> None:
        self._audit_events.append(
            ProviderAuditEvent(
                company_id=str(context.company_id),
                provider=context.provider,
                operation=operation,
                correlation_id=context.correlation_id,
            )
        )

    @staticmethod
    def _assert_company(context: ProviderContext, company_id: object) -> None:
        if company_id != context.company_id:
            raise app_error(
                "CONFLICT",
                message="La entidad no pertenece a la empresa del contexto.",
                details={"provider": context.provider.value},
            )
