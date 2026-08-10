"""Registro de adaptadores habilitables para los casos de uso de conexiones."""

from app.config.features import is_provider_enabled
from app.providers.factory import ProviderFactory
from app.providers.siigo import SiigoProviderAdapter


def default_provider_factory() -> ProviderFactory:
    """Construye un registry por solicitud sin seleccionar un proveedor por defecto.

    Los adaptadores registrados permanecen deshabilitados hasta que el despliegue
    active explícitamente su feature flag. Agregar otro proveedor solo amplía este
    ensamblaje; no modifica el dominio ni las fuentes existentes.
    """

    factory = ProviderFactory(feature_checker=is_provider_enabled)
    factory.register(SiigoProviderAdapter())
    return factory
