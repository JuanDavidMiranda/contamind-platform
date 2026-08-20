"""Encabezado WS-Security requerido por los servicios SOAP de DIAN."""

from __future__ import annotations

import base64
import hashlib
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from lxml import etree

from app.integrations.dian.credentials import DianTechnicalCredentials


SOAP_NS = "http://www.w3.org/2003/05/soap-envelope"
WSSE_NS = (
    "http://docs.oasis-open.org/wss/2004/01/"
    "oasis-200401-wss-wssecurity-secext-1.0.xsd"
)
WSU_NS = (
    "http://docs.oasis-open.org/wss/2004/01/"
    "oasis-200401-wss-wssecurity-utility-1.0.xsd"
)
DS_NS = "http://www.w3.org/2000/09/xmldsig#"
WSA_NS = "http://www.w3.org/2005/08/addressing"
DIAN_NS = "http://wcf.dian.colombia"
EC_NS = "http://www.w3.org/2001/10/xml-exc-c14n#"

_EXCLUSIVE_C14N = "http://www.w3.org/2001/10/xml-exc-c14n#"
_RSA_SHA256 = "http://www.w3.org/2001/04/xmldsig-more#rsa-sha256"
_SHA256 = "http://www.w3.org/2001/04/xmlenc#sha256"
_X509_VALUE_TYPE = "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-x509-token-profile-1.0#X509v3"
_BASE64_ENCODING_TYPE = "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-soap-message-security-1.0#Base64Binary"


def build_signed_soap_envelope(
    *,
    action: str,
    endpoint: str,
    body: etree._Element,
    credentials: DianTechnicalCredentials,
) -> bytes:
    """Construye el sobre SOAP 1.2 firmado, con WS-A y timestamp breve.

    La forma sigue la configuración publicada por DIAN para su cliente SOAP:
    Basic Auth en HTTP más token X509, WS-Addressing y firma RSA-SHA256 sobre
    ``wsa:To``. El XML tributario ya viene firmado en el ZIP y no se altera.
    """

    issued_at = datetime.now(UTC)
    to_id = f"id-{uuid4()}"
    timestamp_id = f"TS-{uuid4()}"
    token_id = f"X509-{uuid4()}"
    signature_id = f"SIG-{uuid4()}"
    nsmap = {
        "soap": SOAP_NS,
        "wcf": DIAN_NS,
        "wsa": WSA_NS,
        "wsse": WSSE_NS,
        "wsu": WSU_NS,
        "ds": DS_NS,
        "ec": EC_NS,
    }
    envelope = etree.Element(etree.QName(SOAP_NS, "Envelope"), nsmap=nsmap)
    header = etree.SubElement(envelope, etree.QName(SOAP_NS, "Header"))
    action_node = etree.SubElement(header, etree.QName(WSA_NS, "Action"))
    action_node.text = action
    to = etree.SubElement(header, etree.QName(WSA_NS, "To"))
    to.set(etree.QName(WSU_NS, "Id"), to_id)
    to.text = endpoint
    soap_body = etree.SubElement(envelope, etree.QName(SOAP_NS, "Body"))
    soap_body.append(body)

    security = etree.SubElement(header, etree.QName(WSSE_NS, "Security"))
    security.set(etree.QName(SOAP_NS, "mustUnderstand"), "true")
    token = etree.SubElement(security, etree.QName(WSSE_NS, "BinarySecurityToken"))
    token.set("EncodingType", _BASE64_ENCODING_TYPE)
    token.set("ValueType", _X509_VALUE_TYPE)
    token.set(etree.QName(WSU_NS, "Id"), token_id)
    token.text = base64.b64encode(
        credentials.certificate.public_bytes(serialization.Encoding.DER)
    ).decode("ascii")

    signature = etree.SubElement(security, etree.QName(DS_NS, "Signature"))
    signature.set("Id", signature_id)
    signed_info = etree.SubElement(signature, etree.QName(DS_NS, "SignedInfo"))
    canonicalization = etree.SubElement(signed_info, etree.QName(DS_NS, "CanonicalizationMethod"))
    canonicalization.set("Algorithm", _EXCLUSIVE_C14N)
    inclusive = etree.SubElement(canonicalization, etree.QName(EC_NS, "InclusiveNamespaces"))
    inclusive.set("PrefixList", "soap wcf wsa")
    signature_method = etree.SubElement(signed_info, etree.QName(DS_NS, "SignatureMethod"))
    signature_method.set("Algorithm", _RSA_SHA256)
    reference = etree.SubElement(signed_info, etree.QName(DS_NS, "Reference"))
    reference.set("URI", f"#{to_id}")
    transforms = etree.SubElement(reference, etree.QName(DS_NS, "Transforms"))
    transform = etree.SubElement(transforms, etree.QName(DS_NS, "Transform"))
    transform.set("Algorithm", _EXCLUSIVE_C14N)
    transform_inclusive = etree.SubElement(transform, etree.QName(EC_NS, "InclusiveNamespaces"))
    transform_inclusive.set("PrefixList", "soap wcf")
    digest_method = etree.SubElement(reference, etree.QName(DS_NS, "DigestMethod"))
    digest_method.set("Algorithm", _SHA256)
    etree.SubElement(reference, etree.QName(DS_NS, "DigestValue"))
    etree.SubElement(signature, etree.QName(DS_NS, "SignatureValue"))
    key_info = etree.SubElement(signature, etree.QName(DS_NS, "KeyInfo"))
    token_reference = etree.SubElement(key_info, etree.QName(WSSE_NS, "SecurityTokenReference"))
    token_reference.set(etree.QName(WSU_NS, "Id"), f"STR-{uuid4()}")
    reference_value = etree.SubElement(token_reference, etree.QName(WSSE_NS, "Reference"))
    reference_value.set("URI", f"#{token_id}")
    reference_value.set("ValueType", _X509_VALUE_TYPE)

    timestamp = etree.SubElement(security, etree.QName(WSU_NS, "Timestamp"))
    timestamp.set(etree.QName(WSU_NS, "Id"), timestamp_id)
    etree.SubElement(timestamp, etree.QName(WSU_NS, "Created")).text = _timestamp(issued_at)
    etree.SubElement(timestamp, etree.QName(WSU_NS, "Expires")).text = _timestamp(
        issued_at + timedelta(seconds=60)
    )

    # Reanalizar antes de firmar asegura que el árbol canonicalizado sea el que
    # se envía por la red, incluidos los espacios de nombres relevantes.
    wire_envelope = etree.fromstring(etree.tostring(envelope, encoding="utf-8"))
    wire_to = wire_envelope.find("soap:Header/wsa:To", namespaces=nsmap)
    wire_signed_info = wire_envelope.find(".//ds:SignedInfo", namespaces=nsmap)
    wire_digest_value = wire_envelope.find(".//ds:DigestValue", namespaces=nsmap)
    wire_signature_value = wire_envelope.find(".//ds:SignatureValue", namespaces=nsmap)
    assert wire_to is not None and wire_signed_info is not None
    assert wire_digest_value is not None and wire_signature_value is not None
    wire_digest_value.text = _digest(wire_to, inclusive_prefixes=("soap", "wcf"))
    signed_info_bytes = _canonicalize(
        wire_signed_info,
        inclusive_prefixes=("soap", "wcf", "wsa"),
    )
    wire_signature_value.text = base64.b64encode(
        credentials.private_key.sign(signed_info_bytes, padding.PKCS1v15(), hashes.SHA256())
    ).decode("ascii")
    return etree.tostring(wire_envelope, xml_declaration=True, encoding="utf-8")


def _timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _canonicalize(element: Any, *, inclusive_prefixes: tuple[str, ...]) -> bytes:
    return etree.tostring(
        element,
        method="c14n",
        exclusive=True,
        with_comments=False,
        inclusive_ns_prefixes=list(inclusive_prefixes),
    )


def _digest(element: Any, *, inclusive_prefixes: tuple[str, ...]) -> str:
    return base64.b64encode(
        hashlib.sha256(_canonicalize(element, inclusive_prefixes=inclusive_prefixes)).digest()
    ).decode("ascii")
