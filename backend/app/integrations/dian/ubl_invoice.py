"""Núcleo determinista para construir una factura UBL 2.1 orientada a DIAN.

Este módulo solamente materializa la estructura contable base de una factura.
No calcula CUFE, no agrega extensiones DIAN, no firma XAdES y no transmite el
documento. Por ello, el XML resultante es un artefacto intermedio y nunca debe
enviarse por sí solo a DIAN.

Las validaciones viven junto al constructor para que las capas de persistencia,
API y worker puedan reutilizar las mismas reglas antes de reservar numeración o
generar una firma.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Final, Sequence

from lxml import etree


_INVOICE_NS: Final = "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
_CBC_NS: Final = "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2"
_CAC_NS: Final = "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
_EXT_NS: Final = "urn:oasis:names:specification:ubl:schema:xsd:CommonExtensionComponents-2"
_DIAN_STS_NS: Final = "dian:gov:co:facturaelectronica:Structures-2-1"
_NSMAP: Final = {
    None: _INVOICE_NS,
    "cbc": _CBC_NS,
    "cac": _CAC_NS,
    "ext": _EXT_NS,
    "sts": _DIAN_STS_NS,
}

_COLOMBIA_TIMEZONE: Final = timezone(timedelta(hours=-5))
_DEFAULT_ISSUE_TIME: Final = time(0, 0, tzinfo=_COLOMBIA_TIMEZONE)
_MONEY_QUANTUM: Final = Decimal("0.01")
_PRICE_QUANTUM: Final = Decimal("0.000001")
_QUANTITY_QUANTUM: Final = Decimal("0.000001")
_RATE_QUANTUM: Final = Decimal("0.01")
_DOCUMENT_IDENTIFIER_PATTERN: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,49}$")
_DOCUMENT_NUMBER_PATTERN: Final = re.compile(r"^[A-Za-z0-9-]{1,30}$")
_NIT_PATTERN: Final = re.compile(r"^[0-9]{5,15}$")
_DOCUMENT_TYPE_PATTERN: Final = re.compile(r"^[0-9]{2}$")
_CURRENCY_PATTERN: Final = re.compile(r"^[A-Z]{3}$")
_UNIT_CODE_PATTERN: Final = re.compile(r"^[A-Z0-9]{2,10}$")
_EMAIL_PATTERN: Final = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


class DianUblValidationError(ValueError):
    """Error de entrada seguro para exponer desde una capa posterior de API."""

    def __init__(self, field: str, message: str) -> None:
        super().__init__(message)
        self.field = field


@dataclass(frozen=True, slots=True)
class DianInvoiceParty:
    """Datos fiscales mínimos del emisor o adquiriente de una factura."""

    document_number: str
    legal_name: str
    document_type: str = "31"
    check_digit: str | None = None
    tax_scheme_id: str = "01"
    tax_scheme_name: str = "IVA"
    email: str | None = None


@dataclass(frozen=True, slots=True)
class DianInvoiceTax:
    """Impuesto por línea expresado con el catálogo fiscal DIAN.

    El constructor no infiere la tarifa: recibirla de forma explícita evita que
    una futura regla comercial cambie los totales de un documento ya preparado.
    """

    rate: Decimal | int | str = Decimal("19")
    scheme_id: str = "01"
    scheme_name: str = "IVA"


@dataclass(frozen=True, slots=True)
class DianInvoiceLine:
    """Línea comercial con IVA explícito, sin descuentos ni cargos todavía."""

    description: str
    quantity: Decimal | int | str
    unit_price: Decimal | int | str
    tax: DianInvoiceTax = field(default_factory=DianInvoiceTax)
    unit_code: str = "EA"


@dataclass(frozen=True, slots=True)
class DianUblInvoice:
    """Entrada estable para la primera etapa de generación UBL 2.1 en habilitación."""

    identifier: str
    issue_date: date
    supplier: DianInvoiceParty
    customer: DianInvoiceParty
    lines: Sequence[DianInvoiceLine]
    issue_time: time = _DEFAULT_ISSUE_TIME
    currency_code: str = "COP"
    profile_execution_id: str = "2"
    customization_id: str = "10"
    invoice_type_code: str = "01"


# Los dos alias representan roles distintos, aunque comparten el conjunto de
# datos fiscales base. Permiten a una capa superior expresar con claridad qué
# parte está construyendo sin duplicar los datos en el documento firmado.
DianInvoiceIssuer = DianInvoiceParty
DianInvoiceAcquirer = DianInvoiceParty

__all__ = [
    "DianInvoiceAcquirer",
    "DianInvoiceIssuer",
    "DianInvoiceLine",
    "DianInvoiceParty",
    "DianInvoiceTax",
    "DianInvoiceTotals",
    "DianUbl21InvoiceBuilder",
    "DianUblInvoice",
    "DianUblInvoiceDocument",
    "DianUblValidationError",
    "build_dian_ubl_21_invoice",
    "build_dian_ubl_21_invoice_xml",
]


@dataclass(frozen=True, slots=True)
class DianInvoiceTotals:
    """Totales calculados a partir de las líneas normalizadas."""

    line_extension_amount: Decimal
    tax_exclusive_amount: Decimal
    tax_amount: Decimal
    tax_inclusive_amount: Decimal
    payable_amount: Decimal


@dataclass(frozen=True, slots=True)
class DianUblInvoiceDocument:
    """Resultado serializado, sin firma, y sus totales verificables."""

    xml: bytes
    totals: DianInvoiceTotals


@dataclass(frozen=True, slots=True)
class _NormalizedParty:
    document_number: str
    legal_name: str
    document_type: str
    check_digit: str | None
    tax_scheme_id: str
    tax_scheme_name: str
    email: str | None


@dataclass(frozen=True, slots=True)
class _NormalizedLine:
    description: str
    quantity: Decimal
    unit_price: Decimal
    tax_rate: Decimal
    tax_scheme_id: str
    tax_scheme_name: str
    unit_code: str
    line_extension_amount: Decimal
    tax_amount: Decimal


@dataclass(frozen=True, slots=True)
class _NormalizedTax:
    rate: Decimal
    scheme_id: str
    scheme_name: str


class DianUbl21InvoiceBuilder:
    """Construye siempre el mismo XML para la misma entrada validada.

    La etapa posterior deberá completar las extensiones oficiales, el CUFE y la
    firma XAdES antes de empaquetar y remitir el documento a DIAN.
    """

    def build(self, invoice: DianUblInvoice) -> DianUblInvoiceDocument:
        normalized = _normalize_invoice(invoice)
        root = etree.Element(etree.QName(_INVOICE_NS, "Invoice"), nsmap=_NSMAP)

        _cbc(root, "UBLVersionID", "UBL 2.1")
        _cbc(root, "CustomizationID", normalized.customization_id)
        _cbc(root, "ProfileID", "DIAN 2.1")
        _cbc(root, "ProfileExecutionID", normalized.profile_execution_id)
        _cbc(root, "ID", normalized.identifier)
        _cbc(root, "IssueDate", normalized.issue_date.isoformat())
        _cbc(root, "IssueTime", normalized.issue_time.isoformat(timespec="seconds"))
        _cbc(root, "InvoiceTypeCode", normalized.invoice_type_code)
        currency = _cbc(root, "DocumentCurrencyCode", normalized.currency_code)
        currency.set("listID", "ISO 4217")
        currency.set("listAgencyID", "6")
        currency.set("listName", "Currency")
        _cbc(root, "LineCountNumeric", str(len(normalized.lines)))

        _party(root, "AccountingSupplierParty", normalized.supplier, account_type="1")
        _party(root, "AccountingCustomerParty", normalized.customer, account_type="2")

        tax_groups = _group_taxes(normalized.lines)
        for tax_group in tax_groups:
            _tax_total(
                root,
                taxable_amount=tax_group.taxable_amount,
                tax_amount=tax_group.tax_amount,
                tax_rate=tax_group.tax_rate,
                tax_scheme_id=tax_group.tax_scheme_id,
                tax_scheme_name=tax_group.tax_scheme_name,
                currency_code=normalized.currency_code,
            )

        totals = _calculate_totals(normalized.lines)
        monetary_total = etree.SubElement(root, etree.QName(_CAC_NS, "LegalMonetaryTotal"))
        _amount(
            monetary_total,
            "LineExtensionAmount",
            totals.line_extension_amount,
            normalized.currency_code,
        )
        _amount(
            monetary_total,
            "TaxExclusiveAmount",
            totals.tax_exclusive_amount,
            normalized.currency_code,
        )
        _amount(monetary_total, "TaxInclusiveAmount", totals.tax_inclusive_amount, normalized.currency_code)
        _amount(monetary_total, "PayableAmount", totals.payable_amount, normalized.currency_code)

        for line_number, line in enumerate(normalized.lines, start=1):
            _invoice_line(
                root,
                line_number=line_number,
                line=line,
                currency_code=normalized.currency_code,
            )

        return DianUblInvoiceDocument(
            xml=etree.tostring(root, encoding="UTF-8", xml_declaration=True),
            totals=totals,
        )

    def build_xml(self, invoice: DianUblInvoice) -> bytes:
        """Atajo para el consumidor que solo necesita el XML intermedio."""

        return self.build(invoice).xml


def build_dian_ubl_21_invoice(invoice: DianUblInvoice) -> DianUblInvoiceDocument:
    """Construye la factura UBL 2.1 usando el constructor predeterminado."""

    return DianUbl21InvoiceBuilder().build(invoice)


def build_dian_ubl_21_invoice_xml(invoice: DianUblInvoice) -> bytes:
    """Devuelve los bytes XML UBL 2.1 que consumirá la etapa de firmado."""

    return DianUbl21InvoiceBuilder().build_xml(invoice)


@dataclass(frozen=True, slots=True)
class _NormalizedInvoice:
    identifier: str
    issue_date: date
    issue_time: time
    supplier: _NormalizedParty
    customer: _NormalizedParty
    lines: tuple[_NormalizedLine, ...]
    currency_code: str
    profile_execution_id: str
    customization_id: str
    invoice_type_code: str


@dataclass(frozen=True, slots=True)
class _TaxGroup:
    tax_rate: Decimal
    tax_scheme_id: str
    tax_scheme_name: str
    taxable_amount: Decimal
    tax_amount: Decimal


def _normalize_invoice(invoice: DianUblInvoice) -> _NormalizedInvoice:
    if not isinstance(invoice, DianUblInvoice):
        raise DianUblValidationError("invoice", "Se requiere una factura UBL DIAN válida.")

    identifier = _required_text(invoice.identifier, "identifier", maximum=50)
    if not _DOCUMENT_IDENTIFIER_PATTERN.fullmatch(identifier):
        raise DianUblValidationError(
            "identifier", "El consecutivo solo puede contener letras, números, punto, guion o barra."
        )
    if not isinstance(invoice.issue_date, date) or isinstance(invoice.issue_date, datetime):
        raise DianUblValidationError("issue_date", "La fecha de emisión debe ser una fecha de calendario.")
    if not isinstance(invoice.issue_time, time):
        raise DianUblValidationError("issue_time", "La hora de emisión no tiene un formato válido.")
    if invoice.issue_time.tzinfo is None or invoice.issue_time.utcoffset() is None:
        raise DianUblValidationError(
            "issue_time", "La hora de emisión debe incluir el desfase horario de Colombia (-05:00)."
        )
    if invoice.issue_time.utcoffset() != timedelta(hours=-5):
        raise DianUblValidationError(
            "issue_time", "La hora de emisión debe usar el desfase horario de Colombia (-05:00)."
        )

    currency_code = _required_text(invoice.currency_code, "currency_code", maximum=3).upper()
    if not _CURRENCY_PATTERN.fullmatch(currency_code):
        raise DianUblValidationError("currency_code", "La moneda debe usar un código ISO 4217 de tres letras.")
    profile_execution_id = _required_text(
        invoice.profile_execution_id, "profile_execution_id", maximum=1
    )
    if profile_execution_id != "2":
        raise DianUblValidationError(
            "profile_execution_id", "Esta etapa solo admite el perfil DIAN 2 (habilitación)."
        )
    customization_id = _required_text(invoice.customization_id, "customization_id", maximum=3)
    if customization_id != "10":
        raise DianUblValidationError(
            "customization_id", "Esta etapa solo admite la personalización DIAN 10 para factura de venta."
        )
    invoice_type_code = _required_text(invoice.invoice_type_code, "invoice_type_code", maximum=2)
    if invoice_type_code != "01":
        raise DianUblValidationError(
            "invoice_type_code", "Esta etapa solo admite el tipo de factura electrónica de venta 01."
        )

    if isinstance(invoice.lines, (str, bytes)) or not isinstance(invoice.lines, Sequence):
        raise DianUblValidationError("lines", "Las líneas de factura deben ser una secuencia ordenada.")
    if not invoice.lines:
        raise DianUblValidationError("lines", "La factura debe incluir al menos una línea.")
    if len(invoice.lines) > 1_000:
        raise DianUblValidationError("lines", "La factura supera el máximo de mil líneas permitido.")

    return _NormalizedInvoice(
        identifier=identifier,
        issue_date=invoice.issue_date,
        issue_time=invoice.issue_time,
        supplier=_normalize_party(invoice.supplier, "supplier", is_supplier=True),
        customer=_normalize_party(invoice.customer, "customer", is_supplier=False),
        lines=tuple(_normalize_line(line, index) for index, line in enumerate(invoice.lines, start=1)),
        currency_code=currency_code,
        profile_execution_id=profile_execution_id,
        customization_id=customization_id,
        invoice_type_code=invoice_type_code,
    )


def _normalize_party(
    party: DianInvoiceParty, field: str, *, is_supplier: bool
) -> _NormalizedParty:
    if not isinstance(party, DianInvoiceParty):
        raise DianUblValidationError(field, "Los datos fiscales de la parte no tienen un formato válido.")
    document_number = _required_text(party.document_number, f"{field}.document_number", maximum=30)
    if not _DOCUMENT_NUMBER_PATTERN.fullmatch(document_number):
        raise DianUblValidationError(
            f"{field}.document_number", "El documento fiscal contiene caracteres no permitidos."
        )
    legal_name = _required_text(party.legal_name, f"{field}.legal_name", maximum=450)
    document_type = _required_text(party.document_type, f"{field}.document_type", maximum=2)
    if not _DOCUMENT_TYPE_PATTERN.fullmatch(document_type):
        raise DianUblValidationError(
            f"{field}.document_type", "El tipo de documento DIAN debe tener dos dígitos."
        )
    check_digit = _optional_text(party.check_digit, f"{field}.check_digit", maximum=1)
    if check_digit is not None and not check_digit.isdigit():
        raise DianUblValidationError(
            f"{field}.check_digit", "El dígito de verificación debe ser un único número."
        )
    if is_supplier and document_type != "31":
        raise DianUblValidationError(
            f"{field}.document_type", "El emisor debe identificarse con NIT (tipo 31)."
        )
    if document_type == "31" and check_digit is None:
        raise DianUblValidationError(
            f"{field}.check_digit", "El NIT debe incluir su dígito de verificación."
        )
    if document_type == "31" and not _NIT_PATTERN.fullmatch(document_number):
        raise DianUblValidationError(
            f"{field}.document_number", "El NIT debe contener entre 5 y 15 dígitos."
        )

    tax_scheme_id = _required_text(party.tax_scheme_id, f"{field}.tax_scheme_id", maximum=2)
    if not _DOCUMENT_TYPE_PATTERN.fullmatch(tax_scheme_id):
        raise DianUblValidationError(
            f"{field}.tax_scheme_id", "El código del impuesto debe tener dos dígitos."
        )
    tax_scheme_name = _required_text(party.tax_scheme_name, f"{field}.tax_scheme_name", maximum=50)
    email = _optional_text(party.email, f"{field}.email", maximum=254)
    if email is not None and not _EMAIL_PATTERN.fullmatch(email):
        raise DianUblValidationError(f"{field}.email", "El correo fiscal no tiene un formato válido.")

    return _NormalizedParty(
        document_number=document_number,
        legal_name=legal_name,
        document_type=document_type,
        check_digit=check_digit,
        tax_scheme_id=tax_scheme_id,
        tax_scheme_name=tax_scheme_name,
        email=email,
    )


def _normalize_line(line: DianInvoiceLine, index: int) -> _NormalizedLine:
    field = f"lines[{index}]"
    if not isinstance(line, DianInvoiceLine):
        raise DianUblValidationError(field, "La línea de factura no tiene un formato válido.")
    description = _required_text(line.description, f"{field}.description", maximum=500)
    quantity = _decimal(
        line.quantity,
        f"{field}.quantity",
        quantum=_QUANTITY_QUANTUM,
        strictly_positive=True,
    )
    unit_price = _decimal(
        line.unit_price,
        f"{field}.unit_price",
        quantum=_PRICE_QUANTUM,
        strictly_positive=True,
    )
    tax = _normalize_tax(line.tax, f"{field}.tax")
    tax_rate = tax.rate
    unit_code = _required_text(line.unit_code, f"{field}.unit_code", maximum=10).upper()
    if not _UNIT_CODE_PATTERN.fullmatch(unit_code):
        raise DianUblValidationError(
            f"{field}.unit_code", "La unidad de medida debe usar un código alfanumérico en mayúsculas."
        )

    line_extension_amount = (quantity * unit_price).quantize(_MONEY_QUANTUM, rounding=ROUND_HALF_UP)
    tax_amount = (line_extension_amount * tax_rate / Decimal("100")).quantize(
        _MONEY_QUANTUM, rounding=ROUND_HALF_UP
    )
    return _NormalizedLine(
        description=description,
        quantity=quantity,
        unit_price=unit_price,
        tax_rate=tax_rate,
        tax_scheme_id=tax.scheme_id,
        tax_scheme_name=tax.scheme_name,
        unit_code=unit_code,
        line_extension_amount=line_extension_amount,
        tax_amount=tax_amount,
    )


def _normalize_tax(tax: DianInvoiceTax, field: str) -> _NormalizedTax:
    if not isinstance(tax, DianInvoiceTax):
        raise DianUblValidationError(field, "El impuesto de la línea no tiene un formato válido.")
    rate = _decimal(
        tax.rate,
        f"{field}.rate",
        quantum=_RATE_QUANTUM,
        strictly_positive=False,
    )
    if rate > Decimal("100"):
        raise DianUblValidationError(f"{field}.rate", "La tarifa de impuesto no puede superar 100.")
    scheme_id = _required_text(tax.scheme_id, f"{field}.scheme_id", maximum=2)
    if not _DOCUMENT_TYPE_PATTERN.fullmatch(scheme_id):
        raise DianUblValidationError(
            f"{field}.scheme_id", "El código del impuesto debe tener dos dígitos."
        )
    return _NormalizedTax(
        rate=rate,
        scheme_id=scheme_id,
        scheme_name=_required_text(tax.scheme_name, f"{field}.scheme_name", maximum=50),
    )


def _required_text(value: object, field: str, *, maximum: int) -> str:
    if not isinstance(value, str):
        raise DianUblValidationError(field, "Este campo debe ser texto.")
    normalized = value.strip()
    if not normalized:
        raise DianUblValidationError(field, "Este campo es obligatorio.")
    if len(normalized) > maximum:
        raise DianUblValidationError(field, f"Este campo no puede exceder {maximum} caracteres.")
    if any(_is_invalid_xml_character(character) for character in normalized):
        raise DianUblValidationError(field, "Este campo contiene caracteres no permitidos en XML.")
    return normalized


def _optional_text(value: object, field: str, *, maximum: int) -> str | None:
    if value is None:
        return None
    return _required_text(value, field, maximum=maximum)


def _is_invalid_xml_character(character: str) -> bool:
    codepoint = ord(character)
    return codepoint < 0x20 and character not in {"\t", "\n", "\r"}


def _decimal(
    value: Decimal | int | str,
    field: str,
    *,
    quantum: Decimal,
    strictly_positive: bool,
) -> Decimal:
    if isinstance(value, bool) or isinstance(value, float):
        raise DianUblValidationError(
            field, "Use Decimal, entero o texto decimal; los flotantes no son deterministas."
        )
    if not isinstance(value, (Decimal, int, str)):
        raise DianUblValidationError(field, "El valor debe ser Decimal, entero o texto decimal.")
    try:
        number = Decimal(value)
    except (InvalidOperation, ValueError) as exc:
        raise DianUblValidationError(field, "El valor numérico no tiene un formato válido.") from exc
    if not number.is_finite():
        raise DianUblValidationError(field, "El valor numérico debe ser finito.")
    if strictly_positive and number <= 0:
        raise DianUblValidationError(field, "El valor debe ser mayor que cero.")
    if not strictly_positive and number < 0:
        raise DianUblValidationError(field, "El valor no puede ser negativo.")
    if abs(number) >= Decimal("1000000000000000"):
        raise DianUblValidationError(field, "El valor supera el límite soportado por esta etapa.")
    try:
        normalized = number.quantize(quantum)
    except InvalidOperation as exc:
        raise DianUblValidationError(field, "El valor numérico no tiene una precisión válida.") from exc
    if normalized != number:
        places = max(0, -quantum.as_tuple().exponent)
        raise DianUblValidationError(field, f"El valor no puede tener más de {places} decimales.")
    return normalized


def _calculate_totals(lines: tuple[_NormalizedLine, ...]) -> DianInvoiceTotals:
    line_extension_amount = sum((line.line_extension_amount for line in lines), Decimal())
    tax_amount = sum((line.tax_amount for line in lines), Decimal())
    tax_inclusive_amount = line_extension_amount + tax_amount
    return DianInvoiceTotals(
        line_extension_amount=line_extension_amount,
        tax_exclusive_amount=line_extension_amount,
        tax_amount=tax_amount,
        tax_inclusive_amount=tax_inclusive_amount,
        payable_amount=tax_inclusive_amount,
    )


def _group_taxes(lines: tuple[_NormalizedLine, ...]) -> tuple[_TaxGroup, ...]:
    grouped: defaultdict[tuple[Decimal, str, str], list[Decimal]] = defaultdict(
        lambda: [Decimal(), Decimal()]
    )
    for line in lines:
        key = (line.tax_rate, line.tax_scheme_id, line.tax_scheme_name)
        grouped[key][0] += line.line_extension_amount
        grouped[key][1] += line.tax_amount
    return tuple(
        _TaxGroup(
            tax_rate=tax_rate,
            tax_scheme_id=tax_scheme_id,
            tax_scheme_name=tax_scheme_name,
            taxable_amount=amounts[0],
            tax_amount=amounts[1],
        )
        for (tax_rate, tax_scheme_id, tax_scheme_name), amounts in sorted(
            grouped.items(), key=lambda item: item[0]
        )
    )


def _party(parent: etree._Element, tag: str, party: _NormalizedParty, *, account_type: str) -> None:
    accounting_party = etree.SubElement(parent, etree.QName(_CAC_NS, tag))
    _cbc(accounting_party, "AdditionalAccountID", account_type)
    party_element = etree.SubElement(accounting_party, etree.QName(_CAC_NS, "Party"))

    party_identification = etree.SubElement(party_element, etree.QName(_CAC_NS, "PartyIdentification"))
    identification = _cbc(party_identification, "ID", party.document_number)
    _identification_attributes(identification, party)

    party_name = etree.SubElement(party_element, etree.QName(_CAC_NS, "PartyName"))
    _cbc(party_name, "Name", party.legal_name)

    party_tax_scheme = etree.SubElement(party_element, etree.QName(_CAC_NS, "PartyTaxScheme"))
    _cbc(party_tax_scheme, "RegistrationName", party.legal_name)
    company_id = _cbc(party_tax_scheme, "CompanyID", party.document_number)
    _identification_attributes(company_id, party)
    tax_scheme = etree.SubElement(party_tax_scheme, etree.QName(_CAC_NS, "TaxScheme"))
    _cbc(tax_scheme, "ID", party.tax_scheme_id)
    _cbc(tax_scheme, "Name", party.tax_scheme_name)

    if party.email is not None:
        contact = etree.SubElement(party_element, etree.QName(_CAC_NS, "Contact"))
        _cbc(contact, "ElectronicMail", party.email)


def _identification_attributes(element: etree._Element, party: _NormalizedParty) -> None:
    element.set("schemeAgencyID", "195")
    element.set("schemeAgencyName", "CO, DIAN (Direccion de Impuestos y Aduanas Nacionales)")
    element.set("schemeName", party.document_type)
    if party.check_digit is not None:
        element.set("schemeID", party.check_digit)


def _tax_total(
    parent: etree._Element,
    *,
    taxable_amount: Decimal,
    tax_amount: Decimal,
    tax_rate: Decimal,
    tax_scheme_id: str,
    tax_scheme_name: str,
    currency_code: str,
) -> None:
    tax_total = etree.SubElement(parent, etree.QName(_CAC_NS, "TaxTotal"))
    _amount(tax_total, "TaxAmount", tax_amount, currency_code)
    tax_subtotal = etree.SubElement(tax_total, etree.QName(_CAC_NS, "TaxSubtotal"))
    _amount(tax_subtotal, "TaxableAmount", taxable_amount, currency_code)
    _amount(tax_subtotal, "TaxAmount", tax_amount, currency_code)
    _tax_category(tax_subtotal, tax_rate, tax_scheme_id, tax_scheme_name)


def _invoice_line(
    parent: etree._Element,
    *,
    line_number: int,
    line: _NormalizedLine,
    currency_code: str,
) -> None:
    invoice_line = etree.SubElement(parent, etree.QName(_CAC_NS, "InvoiceLine"))
    _cbc(invoice_line, "ID", str(line_number))
    quantity = _cbc(invoice_line, "InvoicedQuantity", _format_decimal(line.quantity, _QUANTITY_QUANTUM))
    quantity.set("unitCode", line.unit_code)
    _amount(invoice_line, "LineExtensionAmount", line.line_extension_amount, currency_code)
    _tax_total(
        invoice_line,
        taxable_amount=line.line_extension_amount,
        tax_amount=line.tax_amount,
        tax_rate=line.tax_rate,
        tax_scheme_id=line.tax_scheme_id,
        tax_scheme_name=line.tax_scheme_name,
        currency_code=currency_code,
    )
    item = etree.SubElement(invoice_line, etree.QName(_CAC_NS, "Item"))
    _cbc(item, "Description", line.description)
    _tax_category(item, line.tax_rate, line.tax_scheme_id, line.tax_scheme_name)
    price = etree.SubElement(invoice_line, etree.QName(_CAC_NS, "Price"))
    _amount(price, "PriceAmount", line.unit_price, currency_code, quantum=_PRICE_QUANTUM)
    base_quantity = _cbc(price, "BaseQuantity", "1")
    base_quantity.set("unitCode", line.unit_code)


def _tax_category(
    parent: etree._Element,
    tax_rate: Decimal,
    tax_scheme_id: str,
    tax_scheme_name: str,
) -> None:
    tax_category = etree.SubElement(parent, etree.QName(_CAC_NS, "TaxCategory"))
    _cbc(tax_category, "ID", "S" if tax_rate else "O")
    _cbc(tax_category, "Percent", _format_decimal(tax_rate, _RATE_QUANTUM))
    tax_scheme = etree.SubElement(tax_category, etree.QName(_CAC_NS, "TaxScheme"))
    _cbc(tax_scheme, "ID", tax_scheme_id)
    _cbc(tax_scheme, "Name", tax_scheme_name)


def _cbc(parent: etree._Element, tag: str, value: str) -> etree._Element:
    element = etree.SubElement(parent, etree.QName(_CBC_NS, tag))
    element.text = value
    return element


def _amount(
    parent: etree._Element,
    tag: str,
    value: Decimal,
    currency_code: str,
    *,
    quantum: Decimal = _MONEY_QUANTUM,
) -> etree._Element:
    amount = _cbc(parent, tag, _format_decimal(value, quantum))
    amount.set("currencyID", currency_code)
    return amount


def _format_decimal(value: Decimal, quantum: Decimal) -> str:
    places = max(0, -quantum.as_tuple().exponent)
    return format(value.quantize(quantum), f".{places}f")
