"""Gestión de secretos de proveedores, aislada del dominio y de los logs."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping

from app.providers.canonical import ProviderContext, ProviderId


@dataclass(frozen=True, repr=False)
class ProviderSecret:
    """Valores opacos de autenticación; nunca se serializan ni se registran."""

    values: Mapping[str, str] = field(repr=False)

    def __post_init__(self) -> None:
        if not self.values or any(not key or not value for key, value in self.values.items()):
            raise ValueError("Un secreto de proveedor debe contener valores no vacíos.")
        object.__setattr__(self, "values", MappingProxyType(dict(self.values)))

    def __repr__(self) -> str:
        return "ProviderSecret(**redacted**)"


class SecretStore(ABC):
    """Puerto de secretos con alcance obligatorio por empresa y proveedor."""

    @abstractmethod
    def get(self, context: ProviderContext) -> ProviderSecret | None:
        """Obtiene el secreto vigente sin exponerlo al dominio."""

    @abstractmethod
    def save(self, context: ProviderContext, secret: ProviderSecret) -> None:
        """Guarda o rota el secreto de una integración específica."""

    @abstractmethod
    def revoke(self, context: ProviderContext) -> None:
        """Invalida el secreto de una empresa para forzar un estado fail-closed."""


class InMemorySecretStore(SecretStore):
    """Store efímero para pruebas. No es apto para producción ni reinicios."""

    def __init__(self) -> None:
        self._secrets: dict[tuple[str, str, str | None, ProviderId], ProviderSecret] = {}

    @staticmethod
    def _key(context: ProviderContext) -> tuple[str, str, str | None, ProviderId]:
        return (
            str(context.tenant_id),
            str(context.company_id),
            str(context.data_source_id) if context.data_source_id else None,
            context.provider,
        )

    def get(self, context: ProviderContext) -> ProviderSecret | None:
        return self._secrets.get(self._key(context))

    def save(self, context: ProviderContext, secret: ProviderSecret) -> None:
        self._secrets[self._key(context)] = secret

    def revoke(self, context: ProviderContext) -> None:
        self._secrets.pop(self._key(context), None)
