"""Pruebas unitarias de la firma XML XAdES sin usar certificados reales."""

from __future__ import annotations

import base64
import hashlib
from datetime import UTC, datetime, timedelta

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa
from cryptography.hazmat.primitives.serialization import BestAvailableEncryption, pkcs12
from cryptography.x509.oid import NameOID
from lxml import etree

from app.integrations.dian.xades import (
    DianXadesSignaturePolicy,
    DianXadesSigner,
    DianXadesSigningError,
    sign_dian_ubl_xades,
)


pytestmark = pytest.mark.unit

_DS_NS = "http://www.w3.org/2000/09/xmldsig#"
_XADES_NS = "http://uri.etsi.org/01903/v1.3.2#"
_EXT_NS = "urn:oasis:names:specification:ubl:schema:xsd:CommonExtensionComponents-2"
_NS = {"ds": _DS_NS, "xades": _XADES_NS, "ext": _EXT_NS}
_SIGNING_TIME = datetime(2026, 8, 20, 15, 30, tzinfo=UTC)


def _ubl_xml() -> bytes:
    return b"""<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<Invoice xmlns=\"urn:oasis:names:specification:ubl:schema:xsd:Invoice-2\"
         xmlns:cbc=\"urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2\"
         xmlns:ext=\"urn:oasis:names:specification:ubl:schema:xsd:CommonExtensionComponents-2\">
  <cbc:ID>SETT-000001</cbc:ID>
</Invoice>"""


def _pfx(
    *,
    key=None,
    not_valid_before: datetime | None = None,
    not_valid_after: datetime | None = None,
) -> tuple[str, x509.Certificate]:
    private_key = key or rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = datetime.now(UTC)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Firma DIAN efimera")])
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(not_valid_before or now - timedelta(days=1))
        .not_valid_after(not_valid_after or now + timedelta(days=1))
        .sign(private_key, hashes.SHA256())
    )
    pfx = pkcs12.serialize_key_and_certificates(
        b"dian-xades-test",
        private_key,
        certificate,
        None,
        BestAvailableEncryption(b"certificate-pass"),
    )
    return base64.b64encode(pfx).decode("ascii"), certificate


def _exclusive_c14n(element: etree._Element) -> bytes:
    return etree.tostring(element, method="c14n", exclusive=True, with_comments=False)


def test_signs_ubl_with_xades_bes_and_verifiable_rsa_sha256_signature():
    pfx_base64, certificate = _pfx()

    document = DianXadesSigner().sign(
        xml=_ubl_xml(),
        certificate_pfx_base64=pfx_base64,
        certificate_password="certificate-pass",
        signing_time=_SIGNING_TIME,
    )
    root = etree.fromstring(document.signed_xml)
    signature = root.find(".//ds:Signature", namespaces=_NS)

    assert document.sha256 == hashlib.sha256(document.signed_xml).hexdigest()
    assert signature is not None
    assert signature.get("Id") == document.signature_id
    assert root.find("ext:UBLExtensions", namespaces=_NS) is root[0]
    assert signature.findtext(".//xades:SigningTime", namespaces=_NS) == "2026-08-20T15:30:00Z"
    assert signature.findtext(".//xades:SigningCertificate/xades:Cert/xades:CertDigest/ds:DigestValue", namespaces=_NS) == (
        base64.b64encode(
            hashlib.sha256(certificate.public_bytes(serialization.Encoding.DER)).digest()
        ).decode("ascii")
    )
    assert signature.find(".//xades:SignaturePolicyIdentifier", namespaces=_NS) is None

    signed_info = signature.find("ds:SignedInfo", namespaces=_NS)
    signature_value = signature.findtext("ds:SignatureValue", namespaces=_NS)
    assert signed_info is not None and signature_value is not None
    certificate.public_key().verify(
        base64.b64decode(signature_value),
        _exclusive_c14n(signed_info),
        padding.PKCS1v15(),
        hashes.SHA256(),
    )

    document_reference = next(
        reference
        for reference in signed_info.findall("ds:Reference", namespaces=_NS)
        if reference.get("URI") == ""
    )
    document_digest = document_reference.findtext("ds:DigestValue", namespaces=_NS)
    signature.getparent().remove(signature)
    assert document_digest == base64.b64encode(hashlib.sha256(_exclusive_c14n(root)).digest()).decode("ascii")

    signed_properties = signature.find(".//xades:SignedProperties", namespaces=_NS)
    assert signed_properties is not None
    properties_reference = next(
        reference
        for reference in signed_info.findall("ds:Reference", namespaces=_NS)
        if reference.get("URI") == f"#{signed_properties.get('Id')}"
    )
    assert properties_reference.findtext("ds:DigestValue", namespaces=_NS) == base64.b64encode(
        hashlib.sha256(_exclusive_c14n(signed_properties)).digest()
    ).decode("ascii")


def test_signs_epes_only_when_caller_supplies_a_policy_hash():
    pfx_base64, _ = _pfx()
    policy_hash = base64.b64encode(hashlib.sha256(b"policy controlled by customer").digest()).decode("ascii")

    document = sign_dian_ubl_xades(
        xml=_ubl_xml(),
        certificate_pfx_base64=pfx_base64,
        certificate_password="certificate-pass",
        signing_time=_SIGNING_TIME,
        signature_policy=DianXadesSignaturePolicy(
            identifier="https://policy.example.test/dian-xades",
            digest_sha256_base64=policy_hash,
            qualifier_url="https://policy.example.test/dian-xades.pdf",
        ),
    )
    root = etree.fromstring(document.signed_xml)

    assert root.findtext(
        ".//xades:SignaturePolicyIdentifier/xades:SignaturePolicyId/"
        "xades:SigPolicyHash/ds:DigestValue",
        namespaces=_NS,
    ) == policy_hash
    assert root.findtext(
        ".//xades:SignaturePolicyIdentifier/xades:SignaturePolicyId/"
        "xades:SigPolicyQualifiers/xades:SigPolicyQualifier/xades:SPURI",
        namespaces=_NS,
    ) == "https://policy.example.test/dian-xades.pdf"


@pytest.mark.parametrize(
    ("pfx_base64", "message"),
    [
        (_pfx(not_valid_after=datetime.now(UTC) - timedelta(hours=1))[0], "vigente"),
        (
            _pfx(key=ec.generate_private_key(ec.SECP256R1()))[0],
            "clave RSA",
        ),
    ],
)
def test_rejects_expired_or_non_rsa_certificates_without_exposing_secrets(pfx_base64: str, message: str):
    with pytest.raises(DianXadesSigningError, match=message) as raised:
        DianXadesSigner().sign(
            xml=_ubl_xml(),
            certificate_pfx_base64=pfx_base64,
            certificate_password="certificate-pass",
            signing_time=_SIGNING_TIME,
        )

    assert "certificate-pass" not in str(raised.value)
    assert pfx_base64[:32] not in str(raised.value)


def test_rejects_dtd_and_previously_signed_documents():
    pfx_base64, _ = _pfx()

    with pytest.raises(DianXadesSigningError, match="DTD"):
        DianXadesSigner().sign(
            xml=b'<!DOCTYPE Invoice [<!ENTITY xxe "blocked">]><Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2">&xxe;</Invoice>',
            certificate_pfx_base64=pfx_base64,
            certificate_password="certificate-pass",
        )

    signed = DianXadesSigner().sign(
        xml=_ubl_xml(),
        certificate_pfx_base64=pfx_base64,
        certificate_password="certificate-pass",
        signing_time=_SIGNING_TIME,
    )
    with pytest.raises(DianXadesSigningError, match="ya contiene una firma"):
        DianXadesSigner().sign(
            xml=signed.signed_xml,
            certificate_pfx_base64=pfx_base64,
            certificate_password="certificate-pass",
        )
