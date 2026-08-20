"""Flujo seguro de configuración y habilitación DIAN sin llamadas externas."""

from __future__ import annotations

import asyncio
import base64
import hashlib
from datetime import UTC, datetime, timedelta
from io import BytesIO
from uuid import UUID, uuid4
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from cryptography import x509
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import BestAvailableEncryption, pkcs12
from cryptography.x509.oid import NameOID
from sqlalchemy import select, update

from app.config.settings import settings
from app.database.database import SessionLocal
from app.integrations.dian.gateway import DianGatewayError, DianGatewayResponse
from app.integrations.dian.xades import DianXadesSignaturePolicy, DianXadesSigner
from app.models.dian_electronic import (
    DianElectronicDocumentStatusEventRecord,
    DianElectronicOutboxJobRecord,
    DianElectronicSubmissionRecord,
)
from app.models.user import CompanyMembership, CompanyRole, User
from app.services.dian_electronic_habilitation_service import DianElectronicHabilitationService
from app.shared.security import create_access_token, hash_password


pytestmark = pytest.mark.integration


_POLICY_IDENTIFIER = "https://policy.example.test/dian"
_POLICY_HASH = base64.b64encode(
    hashlib.sha256(b"policy verified by customer").digest()
).decode("ascii")


def _credentials() -> tuple[dict[str, str], str]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "ContaMind DIAN habilitación")])
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(UTC) - timedelta(days=1))
        .not_valid_after(datetime.now(UTC) + timedelta(days=1))
        .sign(key, hashes.SHA256())
    )
    pfx = pkcs12.serialize_key_and_certificates(
        b"dian-habilitation-test",
        key,
        certificate,
        None,
        BestAvailableEncryption(b"certificate-pass"),
    )
    pfx_base64 = base64.b64encode(pfx).decode("ascii")
    return (
        {
            "software_id": "software-id-test",
            "software_password": "software-password-test",
            "certificate_pfx_base64": pfx_base64,
            "certificate_password": "certificate-pass",
        },
        pfx_base64,
    )


def _signed_zip(pfx_base64: str, document_number: str = "SETT1") -> bytes:
    signed_xml = DianXadesSigner().sign(
        xml=f'''<?xml version="1.0" encoding="UTF-8"?>
<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
         xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2"
         xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2">
  <cbc:ID>{document_number}</cbc:ID>
  <cbc:ProfileExecutionID>2</cbc:ProfileExecutionID>
  <cbc:IssueDate>2026-08-20</cbc:IssueDate>
  <cbc:DocumentCurrencyCode>COP</cbc:DocumentCurrencyCode>
  <cac:AccountingSupplierParty><cac:Party><cac:PartyIdentification><cbc:ID>900123456</cbc:ID></cac:PartyIdentification></cac:Party></cac:AccountingSupplierParty>
  <cac:LegalMonetaryTotal><cbc:PayableAmount>119.00</cbc:PayableAmount></cac:LegalMonetaryTotal>
</Invoice>'''.encode("utf-8"),
        certificate_pfx_base64=pfx_base64,
        certificate_password="certificate-pass",
        signature_policy=DianXadesSignaturePolicy(
            identifier=_POLICY_IDENTIFIER,
            digest_sha256_base64=_POLICY_HASH,
        ),
    ).signed_xml
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        archive.writestr("SETT1.xml", signed_xml)
    return output.getvalue()


def _user() -> User:
    db = SessionLocal()
    try:
        user = User(
            email=f"dian-habilitation-{uuid4().hex}@test.local",
            full_name="Responsable de habilitación",
            password_hash=hash_password("password123"),
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user
    finally:
        db.close()


def _headers(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user)}"}


@pytest.fixture
def dian_habilitation_enabled():
    previous_flags = dict(settings.FEATURE_FLAGS)
    previous_master_key = settings.PROVIDER_CREDENTIALS_MASTER_KEY
    settings.FEATURE_FLAGS = {**previous_flags, "DIAN_ELECTRONIC_HABILITATION_ENABLED": True}
    settings.PROVIDER_CREDENTIALS_MASTER_KEY = Fernet.generate_key().decode("ascii")
    try:
        yield
    finally:
        settings.FEATURE_FLAGS = previous_flags
        settings.PROVIDER_CREDENTIALS_MASTER_KEY = previous_master_key


def _profile_payload() -> dict[str, object]:
    return {
        "legal_name": "Empresa de Pruebas S.A.S.",
        "nit": "900123456",
        "check_digit": "7",
        "email": "facturacion@example.test",
        "address": "Calle 1 # 2-3",
        "city_code": "11001",
        "city_name": "Bogotá",
        "department_code": "11",
        "department_name": "Bogotá, D.C.",
        "tax_responsibilities": ["O-13"],
        "software_test_set_id": "test-set-123",
        "signature_policy_identifier": _POLICY_IDENTIFIER,
        "signature_policy_digest_base64": _POLICY_HASH,
        "signature_policy_qualifier_url": "https://policy.example.test/dian.pdf",
    }


def test_habilitation_access_is_read_only_for_viewer(client, dian_habilitation_enabled):
    owner = _user()
    owner_headers = _headers(owner)
    company = client.post(
        "/api/v1/companies/onboarding",
        headers=owner_headers,
        json={"tenant_name": "Tenant DIAN lectura", "company_name": "Empresa DIAN lectura"},
    ).json()["company"]
    base = f"/api/v1/companies/{company['id']}/dian/electronic-invoicing"

    saved = client.put(f"{base}/habilitation", headers=owner_headers, json=_profile_payload())
    assert saved.status_code == 200
    assert saved.json()["can_manage_habilitation"] is True

    viewer = _user()
    db = SessionLocal()
    try:
        db.add(
            CompanyMembership(
                user_id=viewer.id,
                company_id=company["id"],
                role=CompanyRole.VIEWER.value,
            )
        )
        db.commit()
    finally:
        db.close()

    viewer_headers = _headers(viewer)
    access = client.get(f"{base}/habilitation/access", headers=viewer_headers)
    assert access.status_code == 200
    assert access.json() == {"can_manage_habilitation": False}

    profile = client.get(f"{base}/habilitation", headers=viewer_headers)
    assert profile.status_code == 200
    assert profile.json()["can_manage_habilitation"] is False

    forbidden = client.put(f"{base}/habilitation", headers=viewer_headers, json=_profile_payload())
    assert forbidden.status_code == 403


def test_habilitation_profile_range_and_signed_test_submission_are_scoped_and_auditable(
    client, dian_habilitation_enabled
):
    user = _user()
    headers = _headers(user)
    company = client.post(
        "/api/v1/companies/onboarding",
        headers=headers,
        json={"tenant_name": "Tenant DIAN", "company_name": "Empresa DIAN"},
    ).json()["company"]
    base = f"/api/v1/companies/{company['id']}/dian/electronic-invoicing"

    fiscal_profile = _profile_payload()
    for technical_field in (
        "software_test_set_id",
        "signature_policy_identifier",
        "signature_policy_digest_base64",
        "signature_policy_qualifier_url",
    ):
        fiscal_profile.pop(technical_field)
    saved = client.put(f"{base}/habilitation", headers=headers, json=fiscal_profile)
    assert saved.status_code == 200
    profile = saved.json()
    assert profile["environment"] == "habilitation"
    assert profile["production_locked"] is True
    assert profile["credential_configured"] is False

    parameters = client.put(
        f"{base}/habilitation-parameters",
        headers=headers,
        json={
            "software_test_set_id": "test-set-123",
            "signature_policy_identifier": _POLICY_IDENTIFIER,
            "signature_policy_digest_base64": _POLICY_HASH,
            "signature_policy_qualifier_url": "https://policy.example.test/dian.pdf",
        },
    )
    assert parameters.status_code == 200
    assert parameters.json()["software_test_set_id_configured"] is True
    assert "test-set-123" not in parameters.text
    assert _POLICY_HASH not in parameters.text

    credentials, pfx_base64 = _credentials()
    configured = client.put(
        f"{base}/technical-credentials",
        headers=headers,
        json=credentials,
    )
    assert configured.status_code == 200
    assert credentials["software_password"] not in configured.text
    assert credentials["certificate_password"] not in configured.text
    assert pfx_base64[:32] not in configured.text
    generic_credentials = client.put(
        f"/api/v1/data-sources/{profile['data_source_id']}/credentials",
        headers=headers,
        json={"credentials": credentials},
    )
    assert generic_credentials.status_code == 409
    assert credentials["software_password"] not in generic_credentials.text
    assert pfx_base64[:32] not in generic_credentials.text
    acquirer_lookup = client.post(
        f"/api/v1/companies/{company['id']}/dian/acquirers/lookup",
        headers=headers,
        json={
            "data_source_id": profile["data_source_id"],
            "document_type": "31",
            "document_number": "900123456",
            "purpose": "electronic_invoice_issuance",
            "confirmed": True,
        },
    )
    assert acquirer_lookup.status_code == 409

    profile_update = _profile_payload()
    for technical_field in (
        "software_test_set_id",
        "signature_policy_identifier",
        "signature_policy_digest_base64",
        "signature_policy_qualifier_url",
    ):
        profile_update.pop(technical_field)
    preserved = client.put(f"{base}/habilitation", headers=headers, json=profile_update)
    assert preserved.status_code == 200
    assert preserved.json()["software_test_set_id_configured"] is True
    assert preserved.json()["credential_configured"] is True

    range_response = client.post(
        f"{base}/numbering-ranges",
        headers=headers,
        json={
            "prefix": "SETT",
            "resolution_number": "18760000001",
            "resolution_date": "2026-01-01",
            "valid_from": "2026-01-01",
            "valid_to": "2027-01-01",
            "range_from": 1,
            "range_to": 10,
        },
    )
    assert range_response.status_code == 201
    assert range_response.json()["next_number"] == 1

    ready = client.get(f"{base}/habilitation", headers=headers)
    assert ready.status_code == 200
    assert ready.json()["status"] == "ready_for_habilitation"
    assert ready.json()["missing_requirements"] == []

    mismatched = client.post(
        f"{base}/test-documents",
        headers=headers,
        data={
            "prefix": "SETT",
            "consecutive": "1",
            "issue_date": "2026-08-20",
            "currency_code": "COP",
            "payable_amount": "119.00",
            "confirmed": "true",
        },
        files={"file": ("SETT1.zip", _signed_zip(pfx_base64, "OTRO1"), "application/zip")},
    )
    assert mismatched.status_code == 422

    uploaded = client.post(
        f"{base}/test-documents",
        headers={**headers, "X-Request-ID": "dian-hab-test"},
        data={
            "prefix": "SETT",
            "consecutive": "1",
            "issue_date": "2026-08-20",
            "currency_code": "COP",
            "payable_amount": "119.00",
            "confirmed": "true",
        },
        files={"file": ("SETT1.zip", _signed_zip(pfx_base64), "application/zip")},
    )
    assert uploaded.status_code == 202
    document = uploaded.json()
    assert document["document_number"] == "SETT1"
    assert document["status"] == "queued"
    assert "xml" not in uploaded.text.casefold()
    assert pfx_base64[:32] not in uploaded.text

    repeated = client.post(
        f"{base}/test-documents",
        headers=headers,
        data={
            "prefix": "SETT",
            "consecutive": "1",
            "issue_date": "2026-08-20",
            "currency_code": "COP",
            "payable_amount": "119.00",
            "confirmed": "true",
        },
        files={"file": ("SETT1.zip", _signed_zip(pfx_base64), "application/zip")},
    )
    assert repeated.status_code == 409

    listed = client.get(f"{base}/test-documents", headers=headers)
    assert listed.status_code == 200
    assert listed.json()[0]["id"] == document["id"]
    events = client.get(f"{base}/test-documents/{document['id']}/events", headers=headers)
    assert events.status_code == 200
    assert events.json()["items"][0]["code"] == "DIAN_HABILITATION_TEST_QUEUED"

    class NeverCalledGateway:
        async def send_test_set_async(self, **kwargs):
            raise AssertionError("Un envío vencido no puede transmitirse de nuevo.")

    db = SessionLocal()
    try:
        job = db.scalar(
            select(DianElectronicOutboxJobRecord).where(
                DianElectronicOutboxJobRecord.document_id == document["id"]
            )
        )
        assert job is not None
        previous_flags = dict(settings.FEATURE_FLAGS)
        settings.FEATURE_FLAGS = {
            **previous_flags,
            "DIAN_ELECTRONIC_HABILITATION_ENABLED": False,
        }
        try:
            disabled_result = asyncio.run(
                DianElectronicHabilitationService(
                    db,
                    gateway_factory=NeverCalledGateway,
                ).process_next_job()
            )
        finally:
            settings.FEATURE_FLAGS = previous_flags
        assert disabled_result is None
        db.refresh(job)
        assert job.status == "queued"

        job.status = "running"
        job.attempt_count = 1
        job.lease_expires_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=1)
        db.commit()

        recovered = asyncio.run(
            DianElectronicHabilitationService(
                db,
                gateway_factory=NeverCalledGateway,
            ).process_next_job()
        )
        assert recovered is None
        db.refresh(job)
        assert job.status == "failed"
        assert job.error_code == "DIAN_SUBMISSION_UNKNOWN"

        event = db.scalar(
            select(DianElectronicDocumentStatusEventRecord)
            .where(
                DianElectronicDocumentStatusEventRecord.document_id == document["id"],
                DianElectronicDocumentStatusEventRecord.code == "DIAN_SUBMISSION_UNKNOWN",
            )
            .limit(1)
        )
        assert event is not None and event.status == "manual_review"
        submission = db.scalar(
            select(DianElectronicSubmissionRecord)
            .where(
                DianElectronicSubmissionRecord.document_id == document["id"],
                DianElectronicSubmissionRecord.status == "unknown",
            )
            .limit(1)
        )
        assert submission is not None
    finally:
        db.close()


def test_worker_sends_then_queries_status_without_retransmitting_the_document(
    client, dian_habilitation_enabled
):
    user = _user()
    headers = _headers(user)
    company = client.post(
        "/api/v1/companies/onboarding",
        headers=headers,
        json={"tenant_name": "Tenant worker", "company_name": "Empresa worker"},
    ).json()["company"]
    base = f"/api/v1/companies/{company['id']}/dian/electronic-invoicing"
    assert client.put(f"{base}/habilitation", headers=headers, json=_profile_payload()).status_code == 200
    credentials, pfx_base64 = _credentials()
    assert client.put(
        f"{base}/technical-credentials",
        headers=headers,
        json=credentials,
    ).status_code == 200
    assert client.post(
        f"{base}/numbering-ranges",
        headers=headers,
        json={
            "prefix": "SETA",
            "resolution_number": "18760000002",
            "resolution_date": "2026-01-01",
            "valid_from": "2026-01-01",
            "valid_to": "2027-01-01",
            "range_from": 1,
            "range_to": 10,
        },
    ).status_code == 201
    document = client.post(
        f"{base}/test-documents",
        headers=headers,
        data={
            "prefix": "SETA",
            "consecutive": "1",
            "issue_date": "2026-08-20",
            "currency_code": "COP",
            "payable_amount": "119.00",
            "confirmed": "true",
        },
            files={"file": ("SETA1.zip", _signed_zip(pfx_base64, "SETA1"), "application/zip")},
    ).json()

    class FakeGateway:
        sent = 0
        checked = 0

        async def send_test_set_async(self, **kwargs):
            self.sent += 1
            assert kwargs["file_name"] == "SETA1.zip"
            return DianGatewayResponse(
                track_id="track-test-1",
                status_code="00",
                status_description="Procesando",
                status_message=None,
                error_message=None,
                is_valid=None,
            )

        async def get_status_zip(self, **kwargs):
            self.checked += 1
            assert kwargs["track_id"] == "track-test-1"
            return DianGatewayResponse(
                track_id="track-test-1",
                status_code="00",
                status_description="Aceptado",
                status_message=None,
                error_message=None,
                is_valid=True,
            )

    gateway = FakeGateway()
    db = SessionLocal()
    try:
        # El cliente compartido deja una prueba del caso anterior en la base de
        # sesión. La apartamos para verificar exclusivamente este documento.
        db.execute(
            update(DianElectronicOutboxJobRecord)
            .where(
                DianElectronicOutboxJobRecord.document_id != document["id"],
                DianElectronicOutboxJobRecord.status.in_({"queued", "retrying"}),
            )
            .values(available_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(days=1))
        )
        db.commit()
        service = DianElectronicHabilitationService(db, gateway_factory=lambda: gateway)
        first = asyncio.run(service.process_next_job())
        assert first is not None and first.status == "processing"
        status_job = db.scalar(
            select(DianElectronicOutboxJobRecord).where(
                DianElectronicOutboxJobRecord.document_id == document["id"],
                DianElectronicOutboxJobRecord.status == "queued",
            )
        )
        assert status_job is not None
        status_job.status = "running"
        status_job.lease_expires_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=1)
        db.commit()
        second = asyncio.run(service.process_next_job())
        assert second is not None and second.status == "accepted"
        assert gateway.sent == 1
        assert gateway.checked == 1
    finally:
        db.close()

    events = client.get(f"{base}/test-documents/{document['id']}/events", headers=headers)
    assert events.status_code == 200
    assert [item["status"] for item in events.json()["items"]] == [
        "queued",
        "processing",
        "accepted",
    ]


def test_only_a_definitive_rejection_can_reuse_a_consecutive_as_a_linked_correction(
    client, dian_habilitation_enabled
):
    user = _user()
    headers = _headers(user)
    company = client.post(
        "/api/v1/companies/onboarding",
        headers=headers,
        json={"tenant_name": "Tenant correcciones", "company_name": "Empresa correcciones"},
    ).json()["company"]
    base = f"/api/v1/companies/{company['id']}/dian/electronic-invoicing"
    assert client.put(f"{base}/habilitation", headers=headers, json=_profile_payload()).status_code == 200
    credentials, pfx_base64 = _credentials()
    assert client.put(
        f"{base}/technical-credentials",
        headers=headers,
        json=credentials,
    ).status_code == 200
    assert client.post(
        f"{base}/numbering-ranges",
        headers=headers,
        json={
            "prefix": "SETC",
            "resolution_number": "18760000003",
            "resolution_date": "2026-01-01",
            "valid_from": "2026-01-01",
            "valid_to": "2027-01-01",
            "range_from": 1,
            "range_to": 10,
        },
    ).status_code == 201

    request_data = {
        "prefix": "SETC",
        "consecutive": "1",
        "issue_date": "2026-08-20",
        "currency_code": "COP",
        "payable_amount": "119.00",
        "confirmed": "true",
    }
    original = client.post(
        f"{base}/test-documents",
        headers=headers,
        data=request_data,
        files={"file": ("SETC1.zip", _signed_zip(pfx_base64, "SETC1"), "application/zip")},
    )
    assert original.status_code == 202
    original_document = original.json()

    class RejectedGateway:
        async def send_test_set_async(self, **kwargs):
            return DianGatewayResponse(
                track_id="track-rejected-1",
                status_code="90",
                status_description="Recibido",
                status_message=None,
                error_message=None,
                is_valid=False,
            )

        async def get_status_zip(self, **kwargs):
            assert kwargs["track_id"] == "track-rejected-1"
            return DianGatewayResponse(
                track_id="track-rejected-1",
                status_code="90",
                status_description="Rechazado",
                status_message="El XML no superó las reglas de DIAN.",
                error_message=None,
                is_valid=False,
            )

    db = SessionLocal()
    try:
        db.execute(
            update(DianElectronicOutboxJobRecord)
            .where(
                DianElectronicOutboxJobRecord.document_id != original_document["id"],
                DianElectronicOutboxJobRecord.status.in_({"queued", "retrying"}),
            )
            .values(available_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(days=1))
        )
        db.commit()
        service = DianElectronicHabilitationService(db, gateway_factory=RejectedGateway)
        received = asyncio.run(service.process_next_job())
        assert received is not None and received.status == "processing"
        db.execute(
            update(DianElectronicOutboxJobRecord)
            .where(
                DianElectronicOutboxJobRecord.document_id == original_document["id"],
                DianElectronicOutboxJobRecord.operation == "check_status",
                DianElectronicOutboxJobRecord.status == "queued",
            )
            .values(available_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=1))
        )
        db.commit()
        rejected = asyncio.run(service.process_next_job())
        assert rejected is not None and rejected.status == "rejected"
    finally:
        db.close()

    correction = client.post(
        f"{base}/test-documents",
        headers=headers,
        data=request_data,
        files={"file": ("SETC1.zip", _signed_zip(pfx_base64, "SETC1"), "application/zip")},
    )
    assert correction.status_code == 202
    correction_document = correction.json()
    assert correction_document["corrects_document_id"] == original_document["id"]

    ranges = client.get(f"{base}/numbering-ranges", headers=headers)
    assert ranges.status_code == 200
    assert ranges.json()[0]["next_number"] == 2

    class AmbiguousGateway:
        async def send_test_set_async(self, **kwargs):
            raise DianGatewayError(
                "PROVIDER_UNREACHABLE",
                "La conexión se interrumpió después de enviar la solicitud.",
                may_have_been_submitted=True,
            )

    db = SessionLocal()
    try:
        manual_review = asyncio.run(
            DianElectronicHabilitationService(
                db,
                gateway_factory=AmbiguousGateway,
            ).process_next_job()
        )
        assert manual_review is not None and manual_review.id == UUID(correction_document["id"])
        assert manual_review.status == "manual_review"
    finally:
        db.close()

    blocked = client.post(
        f"{base}/test-documents",
        headers=headers,
        data=request_data,
        files={"file": ("SETC1.zip", _signed_zip(pfx_base64, "SETC1"), "application/zip")},
    )
    assert blocked.status_code == 409

    original_events = client.get(
        f"{base}/test-documents/{original_document['id']}/events", headers=headers
    )
    assert original_events.status_code == 200
    assert "DIAN_HABILITATION_CORRECTION_LINKED" in {
        event["code"] for event in original_events.json()["items"]
    }
    correction_events = client.get(
        f"{base}/test-documents/{correction_document['id']}/events", headers=headers
    )
    assert correction_events.status_code == 200
    assert "DIAN_HABILITATION_CORRECTION_QUEUED" in {
        event["code"] for event in correction_events.json()["items"]
    }
