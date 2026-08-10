"""Puertos que consumen el dominio y que implementarán los adaptadores."""

from abc import ABC, abstractmethod

from app.providers.canonical import (
    CANONICAL_VERSION,
    Invoice,
    JournalEntry,
    Page,
    PageRequest,
    Party,
    ProviderContext,
    ProviderKind,
)


class ProviderPort(ABC):
    provider: ProviderKind
    canonical_version: str = CANONICAL_VERSION


class FinancialProviderPort(ProviderPort):
    """Contrato para sistemas financieros, no para servicios institucionales DIAN."""

    @abstractmethod
    async def get_party(self, context: ProviderContext, external_id: str) -> Party:
        """Obtiene un tercero en el modelo canónico."""

    @abstractmethod
    async def list_parties(
        self, context: ProviderContext, page: PageRequest
    ) -> Page[Party]:
        """Lista terceros usando la paginación nativa del adaptador."""

    @abstractmethod
    async def create_invoice(self, context: ProviderContext, invoice: Invoice) -> Invoice:
        """Crea una factura canónica e informa sus identificadores externos."""

    @abstractmethod
    async def list_journal_entries(
        self, context: ProviderContext, page: PageRequest
    ) -> Page[JournalEntry]:
        """Lista comprobantes contables canónicos."""


class FiscalProviderPort(ProviderPort):
    """Contrato para verticales institucionales como DIAN."""

    @abstractmethod
    async def get_acquirer_information(
        self,
        context: ProviderContext,
        document_type: str,
        document_number: str,
    ) -> Party:
        """Consulta información de adquiriente permitida por la autoridad fiscal."""
