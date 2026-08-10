"""Ports para las fuentes de datos, independientes de la marca o el protocolo."""

from abc import ABC

from app.data_sources.models import CompanyDataSource, ConnectionMode, ConnectorId


class DataSourcePort(ABC):
    connector_id: ConnectorId
    supported_modes: frozenset[ConnectionMode]

    def supports(self, source: CompanyDataSource) -> bool:
        return self.connector_id == source.connector_id and source.mode in self.supported_modes
