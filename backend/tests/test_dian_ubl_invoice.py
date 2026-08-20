from datetime import date, time, timedelta, timezone
from decimal import Decimal

import pytest
from lxml import etree

from app.integrations.dian.ubl_invoice import (
    DianInvoiceLine,
    DianInvoiceParty,
    DianInvoiceTax,
    DianUbl21InvoiceBuilder,
    DianUblInvoice,
    DianUblValidationError,
    build_dian_ubl_21_invoice_xml,
)


pytestmark = pytest.mark.unit

_NAMESPACES = {
    "inv": "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2",
    "cbc": "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
    "cac": "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2",
    "ext": "urn:oasis:names:specification:ubl:schema:xsd:CommonExtensionComponents-2",
    "sts": "dian:gov:co:facturaelectronica:Structures-2-1",
}
_COLOMBIA_TIMEZONE = timezone(timedelta(hours=-5))


def _party(document_number: str, *, check_digit: str = "7") -> DianInvoiceParty:
    return DianInvoiceParty(
        document_number=document_number,
        legal_name="Comercializadora Prueba S.A.S.",
        check_digit=check_digit,
        email="facturacion@example.test",
    )


def _invoice(*, lines: tuple[DianInvoiceLine, ...] | None = None, **changes) -> DianUblInvoice:
    values = {
        "identifier": "SETT-000001",
        "issue_date": date(2026, 8, 20),
        "issue_time": time(9, 30, tzinfo=_COLOMBIA_TIMEZONE),
        "supplier": _party("900123456"),
        "customer": _party("901234567", check_digit="4"),
        "lines": lines
        if lines is not None
        else (
            DianInvoiceLine(
                description="Servicio contable mensual",
                quantity=Decimal("2"),
                unit_price=Decimal("100.00"),
                tax=DianInvoiceTax(rate=Decimal("19")),
            ),
            DianInvoiceLine(
                description="Concepto excluido",
                quantity="1",
                unit_price="50",
                tax=DianInvoiceTax(rate="0"),
            ),
        ),
    }
    values.update(changes)
    return DianUblInvoice(**values)


def test_builds_deterministic_ubl_21_with_namespaces_and_calculated_totals():
    builder = DianUbl21InvoiceBuilder()
    invoice = _invoice()

    document = builder.build(invoice)
    root = etree.fromstring(document.xml)

    assert document.xml == builder.build_xml(invoice)
    assert document.xml == build_dian_ubl_21_invoice_xml(invoice)
    assert etree.QName(root).namespace == _NAMESPACES["inv"]
    assert root.nsmap["cbc"] == _NAMESPACES["cbc"]
    assert root.nsmap["cac"] == _NAMESPACES["cac"]
    assert root.nsmap["ext"] == _NAMESPACES["ext"]
    assert root.nsmap["sts"] == _NAMESPACES["sts"]
    assert root.findtext("cbc:UBLVersionID", namespaces=_NAMESPACES) == "UBL 2.1"
    assert root.findtext("cbc:ProfileID", namespaces=_NAMESPACES) == "DIAN 2.1"
    assert root.findtext("cbc:ProfileExecutionID", namespaces=_NAMESPACES) == "2"
    assert root.findtext("cbc:IssueTime", namespaces=_NAMESPACES) == "09:30:00-05:00"
    assert root.findtext("cbc:LineCountNumeric", namespaces=_NAMESPACES) == "2"

    total = root.find("cac:LegalMonetaryTotal", namespaces=_NAMESPACES)
    assert total.findtext("cbc:LineExtensionAmount", namespaces=_NAMESPACES) == "250.00"
    assert total.findtext("cbc:TaxExclusiveAmount", namespaces=_NAMESPACES) == "250.00"
    assert total.findtext("cbc:TaxInclusiveAmount", namespaces=_NAMESPACES) == "288.00"
    assert total.findtext("cbc:PayableAmount", namespaces=_NAMESPACES) == "288.00"
    assert total.find("cbc:PayableAmount", namespaces=_NAMESPACES).get("currencyID") == "COP"
    assert [
        tax_total.findtext("cbc:TaxAmount", namespaces=_NAMESPACES)
        for tax_total in root.findall("cac:TaxTotal", namespaces=_NAMESPACES)
    ] == ["0.00", "38.00"]
    assert document.totals.line_extension_amount == Decimal("250.00")
    assert document.totals.tax_amount == Decimal("38.00")
    assert document.totals.payable_amount == Decimal("288.00")


@pytest.mark.parametrize(
    ("invoice", "field"),
    [
        (_invoice(lines=()), "lines"),
        (
            _invoice(
                lines=(
                    DianInvoiceLine(
                        description="Servicio inválido",
                        quantity="0",
                        unit_price="100",
                    ),
                )
            ),
            "lines[1].quantity",
        ),
        (
            _invoice(
                lines=(
                    DianInvoiceLine(
                        description="Precio no determinista",
                        quantity="1",
                        unit_price=100.0,
                    ),
                )
            ),
            "lines[1].unit_price",
        ),
        (_invoice(supplier=DianInvoiceParty("900123456", "Emisor sin DV")), "supplier.check_digit"),
        (
            _invoice(supplier=DianInvoiceParty("NIT-INVALIDO", "Emisor inválido", check_digit="7")),
            "supplier.document_number",
        ),
        (_invoice(profile_execution_id="1"), "profile_execution_id"),
        (_invoice(profile_execution_id="9"), "profile_execution_id"),
    ],
)
def test_rejects_invalid_input_before_building_xml(invoice: DianUblInvoice, field: str):
    with pytest.raises(DianUblValidationError) as error:
        DianUbl21InvoiceBuilder().build(invoice)

    assert error.value.field == field


def test_rejects_xml_control_characters_in_business_text():
    invoice = _invoice(
        lines=(
            DianInvoiceLine(
                description="Servicio\x01 no serializable",
                quantity="1",
                unit_price="100",
            ),
        )
    )

    with pytest.raises(DianUblValidationError) as error:
        DianUbl21InvoiceBuilder().build(invoice)

    assert error.value.field == "lines[1].description"
