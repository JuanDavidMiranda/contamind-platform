"""Registro de conectores de fuentes de datos sin condicionales por proveedor."""

from app.data_sources.models import CompanyDataSource, ConnectorId, normalize_connector_id
from app.data_sources.ports import DataSourcePort
from app.shared.errors import app_error


class DataSourceRegistry:
    def __init__(self) -> None:
        self._connectors: dict[ConnectorId, DataSourcePort] = {}

    def register(self, connector: DataSourcePort) -> None:
        self._connectors[normalize_connector_id(connector.connector_id)] = connector

    def unregister(self, connector_id: ConnectorId) -> None:
        self._connectors.pop(normalize_connector_id(connector_id), None)

    def resolve(self, source: CompanyDataSource) -> DataSourcePort:
        connector = self._connectors.get(source.connector_id)
        if connector is None:
            raise app_error(
                "NOT_FOUND",
                message="No existe un conector registrado para esta fuente de datos.",
                details={"connector_id": source.connector_id},
            )
        if not connector.supports(source):
            raise app_error(
                "CONFLICT",
                message="El conector no admite la modalidad configurada para esta fuente.",
                details={"connector_id": source.connector_id, "mode": source.mode.value},
            )
        return connector

    def registered(self) -> list[ConnectorId]:
        return list(self._connectors)
