from uuid import uuid4

from io import BytesIO

from openpyxl import Workbook
import pytest

from app.data_sources.csv_import import CsvPartyImportSource
from app.data_sources.models import (
    CompanyDataSource,
    ConnectionMode,
    DataCapability,
    DataSourceContext,
    DataSourceKind,
    DataSourceStatus,
    FileFormat,
    ImportEntity,
    ImportProfile,
)
from app.data_sources.registry import DataSourceRegistry
from app.data_sources.xlsx_import import XlsxPartyImportSource
from app.shared.errors import AppError

pytestmark = pytest.mark.unit


def _file_source(*, company_id=None):
    return CompanyDataSource(
        tenant_id=uuid4(),
        company_id=company_id or uuid4(),
        connector_id="csv_import",
        display_name="Carga de terceros",
        kind=DataSourceKind.FILE_IMPORT,
        mode=ConnectionMode.FILE_UPLOAD,
        capabilities={DataCapability.PARTIES, DataCapability.FILE_IMPORT_EXPORT},
        status=DataSourceStatus.ACTIVE,
    )


def _xlsx_source():
    source = _file_source()
    return source.model_copy(update={"connector_id": "xlsx_import"})


def _context(source):
    return DataSourceContext(
        tenant_id=source.tenant_id,
        company_id=source.company_id,
        data_source_id=source.id,
        connector_id=source.connector_id,
        correlation_id="import-trace-1",
    )


def test_company_source_supports_novasoft_without_hardcoded_adapter():
    source = CompanyDataSource(
        tenant_id=uuid4(),
        company_id=uuid4(),
        connector_id="novasoft_local",
        display_name="Novasoft del cliente",
        kind=DataSourceKind.ACCOUNTING_SOFTWARE,
        mode=ConnectionMode.LOCAL_AGENT,
        provider_id="novasoft",
        capabilities={DataCapability.PAYROLL, DataCapability.JOURNALS},
    )

    assert source.provider_id == "novasoft"
    assert source.mode is ConnectionMode.LOCAL_AGENT


def test_accounting_software_requires_provider_id():
    with pytest.raises(ValueError, match="provider_id"):
        CompanyDataSource(
            tenant_id=uuid4(),
            company_id=uuid4(),
            connector_id="unknown_erp",
            display_name="ERP",
            kind=DataSourceKind.ACCOUNTING_SOFTWARE,
            mode=ConnectionMode.CLOUD_API,
        )


def test_registry_resolves_file_source_without_provider_id():
    registry = DataSourceRegistry()
    importer = CsvPartyImportSource()
    registry.register(importer)

    assert registry.resolve(_file_source()) is importer


@pytest.mark.asyncio
async def test_csv_import_maps_valid_rows_and_reports_invalid_rows():
    source = _file_source()
    context = _context(source)
    profile = ImportProfile(
        data_source_id=source.id,
        entity=ImportEntity.PARTIES,
        file_format=FileFormat.CSV,
        column_mapping={
            "name": "Nombre",
            "document_type": "Tipo documento",
            "document_number": "Documento",
            "email": "Correo",
            "external_id": "Id externo",
        },
    )
    importer = CsvPartyImportSource()

    result = await importer.import_parties(
        context,
        source,
        profile,
        "Nombre,Tipo documento,Documento,Correo,Id externo\nCliente Uno,31,900123456,uno@ejemplo.co,1\n,31,900123457,dos@ejemplo.co,2\n",
    )

    assert [party.name for party in result.parties] == ["Cliente Uno"]
    assert result.parties[0].company_id == source.company_id
    assert result.rejections[0].row_number == 3
    assert importer.audit_events[-1].accepted_rows == 1
    assert importer.audit_events[-1].correlation_id == "import-trace-1"


@pytest.mark.asyncio
async def test_csv_import_rejects_profile_from_another_source():
    source = _file_source()
    profile = ImportProfile(
        data_source_id=uuid4(),
        entity=ImportEntity.PARTIES,
        file_format=FileFormat.CSV,
        column_mapping={"name": "Nombre"},
    )

    with pytest.raises(AppError) as error:
        await CsvPartyImportSource().import_parties(
            _context(source), source, profile, "Nombre\nCliente Uno\n"
        )

    assert error.value.code == "CONFLICT"


@pytest.mark.asyncio
async def test_xlsx_import_uses_the_same_mapping_profile():
    source = _xlsx_source()
    profile = ImportProfile(
        data_source_id=source.id,
        entity=ImportEntity.PARTIES,
        file_format=FileFormat.XLSX,
        column_mapping={"name": "Nombre", "document_number": "Documento"},
    )
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["Nombre", "Documento"])
    sheet.append(["Cliente XLSX", "900123456"])
    content = BytesIO()
    workbook.save(content)

    result = await XlsxPartyImportSource().import_parties(
        _context(source), source, profile, content.getvalue()
    )

    assert result.parties[0].name == "Cliente XLSX"
    assert result.parties[0].document_number == "900123456"


@pytest.mark.asyncio
async def test_xlsx_import_rejects_content_above_uncompressed_limit():
    source = _xlsx_source()
    profile = ImportProfile(
        data_source_id=source.id,
        entity=ImportEntity.PARTIES,
        file_format=FileFormat.XLSX,
        column_mapping={"name": "Nombre"},
    )
    workbook = Workbook()
    workbook.active.append(["Nombre"])
    workbook.active.append(["Cliente XLSX"])
    content = BytesIO()
    workbook.save(content)

    with pytest.raises(AppError) as error:
        await XlsxPartyImportSource(max_uncompressed_bytes=1).import_parties(
            _context(source), source, profile, content.getvalue()
        )

    assert error.value.code == "VALIDATION_ERROR"
