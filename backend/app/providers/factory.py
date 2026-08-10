"""Registro neutral y por empresa de los puertos de proveedores."""

from collections.abc import Callable

from app.providers.canonical import ProviderContext, ProviderId, normalize_provider_id
from app.providers.ports import (
    FinancialProviderPort,
    FiscalProviderPort,
    ProviderConnectionPort,
    ProviderPartySyncPort,
    ProviderPort,
)
from app.shared.errors import app_error

FeatureChecker = Callable[[ProviderId], bool]


def _major_version(version: str) -> str:
    return version.split(".", maxsplit=1)[0]


def _always_enabled(provider: ProviderId) -> bool:
    return True


class ProviderFactory:
    """Resuelve adaptadores registrados sin exponer sus tipos al dominio."""

    def __init__(self, feature_checker: FeatureChecker = _always_enabled) -> None:
        self._feature_checker = feature_checker
        self._providers: dict[ProviderId, ProviderPort] = {}

    def register(self, provider: ProviderPort) -> None:
        self._providers[normalize_provider_id(provider.provider)] = provider

    def unregister(self, provider: ProviderId) -> None:
        self._providers.pop(normalize_provider_id(provider), None)

    def resolve_financial(self, context: ProviderContext) -> FinancialProviderPort:
        provider = self._resolve(context)
        if not isinstance(provider, FinancialProviderPort):
            raise app_error(
                "CONFLICT",
                message="El proveedor registrado no es de tipo financiero.",
                details={"provider": context.provider},
            )
        return provider

    def resolve_fiscal(self, context: ProviderContext) -> FiscalProviderPort:
        provider = self._resolve(context)
        if not isinstance(provider, FiscalProviderPort):
            raise app_error(
                "CONFLICT",
                message="El proveedor registrado no es de tipo fiscal.",
                details={"provider": context.provider},
            )
        return provider

    def resolve_connection(self, context: ProviderContext) -> ProviderConnectionPort:
        provider = self._resolve(context)
        if not isinstance(provider, ProviderConnectionPort):
            raise app_error(
                "CONFLICT",
                message="El proveedor registrado no admite prueba de conexión.",
                details={"provider": context.provider},
            )
        return provider

    def resolve_party_sync(self, context: ProviderContext) -> ProviderPartySyncPort:
        provider = self._resolve(context)
        if not isinstance(provider, ProviderPartySyncPort):
            raise app_error(
                "CONFLICT",
                message="El proveedor registrado no admite sincronizar terceros.",
                details={"provider": context.provider},
            )
        return provider

    def registered(self) -> list[ProviderId]:
        return list(self._providers)

    def _resolve(self, context: ProviderContext) -> ProviderPort:
        if not self._feature_checker(context.provider):
            raise app_error(
                "DEPENDENCY_DISABLED",
                details={"provider": context.provider},
            )

        provider = self._providers.get(context.provider)
        if provider is None:
            raise app_error(
                "NOT_FOUND",
                message="Proveedor no registrado.",
                details={"provider": context.provider},
            )

        if _major_version(provider.canonical_version) != _major_version(context.canonical_version):
            raise app_error(
                "CONFLICT",
                message="El proveedor no es compatible con la versión canónica solicitada.",
                details={
                    "provider": context.provider,
                    "adapter_version": provider.canonical_version,
                    "requested_version": context.canonical_version,
                },
            )
        return provider
