import asyncio
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.database.database import SessionLocal
from app.models.data_source import (
    ProviderCredentialRecord,
    ProviderSyncJobRecord,
    ProviderSyncRunRecord,
)
from app.models.user import User
from app.providers.canonical import Party, PartySyncPage, PartyType
from app.providers.factory import ProviderFactory
from app.providers.ports import ProviderConnectionPort, ProviderPartySyncPort
from app.services.provider_connection_service import ProviderConnectionService
from app.shared.errors import app_error
from app.shared.security import create_access_token, hash_password

pytestmark = pytest.mark.integration


class _ProviderStub(ProviderConnectionPort, ProviderPartySyncPort):
    provider = "acme_erp"

    def __init__(self) -> None:
        self.cursors: list[str | None] = []

    async def test_connection(self, context, secret) -> None:
        assert secret.values["token"] == "secret-that-must-not-leak"

    async def fetch_parties(self, context, secret, *, cursor, page_size):
        assert secret.values["token"] == "secret-that-must-not-leak"
        self.cursors.append(cursor)
        suffix = "1" if cursor is None else "2"
        return PartySyncPage(
            items=(
                Party(
                    company_id=context.company_id,
                    party_type=PartyType.CUSTOMER,
                    name=f"Cliente externo {suffix}",
                    document_type="31",
                    document_number=f"90012345{suffix}",
                    external_id=f"external-{suffix}",
                ),
            ),
            next_cursor="2" if cursor is None else None,
        )


def _create_user(email: str, *, is_admin: bool = False) -> User:
    db = SessionLocal()
    try:
        user = User(
            email=email,
            full_name="Provider connection user",
            password_hash=hash_password("password123"),
            is_platform_admin=is_admin,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user
    finally:
        db.close()


def _headers(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user)}"}


def _process_next_sync_job():
    db = SessionLocal()
    try:
        return asyncio.run(ProviderConnectionService(db).process_next_sync_job())
    finally:
        db.close()


def test_connection_lifecycle_encrypts_credentials_and_audits_syncs(client, monkeypatch):
    from app.services import provider_connection_service as connection_module

    stub = _ProviderStub()
    factory = ProviderFactory()
    factory.register(stub)
    monkeypatch.setattr(connection_module, "default_provider_factory", lambda: factory)

    suffix = uuid4().hex
    owner = _create_user(f"provider-owner-{suffix}@test.local")
    operator = _create_user(f"provider-operator-{suffix}@test.local")
    owner_headers = _headers(owner)
    onboarding = client.post(
        "/api/v1/companies/onboarding",
        headers=owner_headers,
        json={"tenant_name": f"Tenant provider {suffix}", "company_name": "Empresa proveedor"},
    )
    assert onboarding.status_code == 201
    tenant_id = onboarding.json()["tenant"]["id"]
    company_id = onboarding.json()["company"]["id"]
    assert client.put(
        "/api/v1/company-memberships",
        headers=owner_headers,
        json={"user_id": operator.id, "company_id": company_id, "role": "operator"},
    ).status_code == 200

    source_response = client.post(
        "/api/v1/data-sources",
        headers=owner_headers,
        json={
            "tenant_id": tenant_id,
            "company_id": company_id,
            "connector_id": "acme_api",
            "display_name": "Acme ERP",
            "kind": "accounting_software",
            "mode": "cloud_api",
            "capabilities": ["parties"],
            "provider_id": "acme_erp",
        },
    )
    assert source_response.status_code == 201
    source_id = source_response.json()["id"]
    assert source_response.json()["status"] == "pending"

    invalid_credentials = client.put(
        f"/api/v1/data-sources/{source_id}/credentials",
        headers=owner_headers,
        json={"credentials": {"invalid-key!": "must-never-appear"}},
    )
    assert invalid_credentials.status_code == 422
    assert "must-never-appear" not in str(invalid_credentials.json())

    credentials_response = client.put(
        f"/api/v1/data-sources/{source_id}/credentials",
        headers=owner_headers,
        json={"credentials": {"token": "secret-that-must-not-leak"}},
    )
    assert credentials_response.status_code == 200
    assert credentials_response.json() == {
        "data_source_id": source_id,
        "provider_id": "acme_erp",
        "status": "pending",
        "credential_configured": True,
    }
    assert client.put(
        f"/api/v1/data-sources/{source_id}/credentials",
        headers=_headers(operator),
        json={"credentials": {"token": "not-allowed"}},
    ).status_code == 403

    db = SessionLocal()
    try:
        credential = db.scalar(
            select(ProviderCredentialRecord).where(
                ProviderCredentialRecord.data_source_id == source_id
            )
        )
        assert credential is not None
        assert "secret-that-must-not-leak" not in credential.ciphertext
    finally:
        db.close()

    test_response = client.post(
        f"/api/v1/data-sources/{source_id}/connection-test",
        headers={**owner_headers, "X-Request-ID": "provider-connection-trace"},
    )
    assert test_response.status_code == 200
    assert test_response.json()["operation"] == "connection_test"
    assert test_response.json()["status"] == "succeeded"
    assert test_response.json()["correlation_id"] == "provider-connection-trace"

    operator_headers = _headers(operator)
    enqueued_sync = client.post(
        f"/api/v1/data-sources/{source_id}/sync/parties?page_size=1",
        headers=operator_headers,
    )
    assert enqueued_sync.status_code == 202
    job_id = enqueued_sync.json()["id"]
    assert enqueued_sync.json()["status"] == "queued"
    assert enqueued_sync.json()["processed_records"] == 0
    duplicate_sync = client.post(
        f"/api/v1/data-sources/{source_id}/sync/parties?page_size=1",
        headers=operator_headers,
    )
    assert duplicate_sync.status_code == 409

    first_page = _process_next_sync_job()
    assert first_page is not None
    assert first_page.status.value == "queued"
    assert first_page.cursor == "2"
    assert first_page.pages_processed == 1
    finished_job = _process_next_sync_job()
    assert finished_job is not None
    assert finished_job.status.value == "succeeded"
    assert finished_job.cursor is None
    assert finished_job.processed_records == 2
    assert stub.cursors == [None, "2"]

    job_response = client.get(
        f"/api/v1/data-sources/{source_id}/sync/jobs/{job_id}", headers=operator_headers
    )
    assert job_response.status_code == 200
    assert job_response.json()["status"] == "succeeded"
    assert job_response.json()["pages_processed"] == 2

    runs = client.get(
        f"/api/v1/data-sources/{source_id}/connection-runs", headers=operator_headers
    )
    assert runs.status_code == 200
    assert [run["operation"] for run in runs.json()].count("sync_parties") == 2
    assert [run["operation"] for run in runs.json()].count("connection_test") == 1
    assert "secret-that-must-not-leak" not in str(runs.json())

    assert client.delete(
        f"/api/v1/data-sources/{source_id}/credentials", headers=owner_headers
    ).status_code == 204
    failed_test = client.post(
        f"/api/v1/data-sources/{source_id}/connection-test", headers=owner_headers
    )
    assert failed_test.status_code == 401
    assert failed_test.json()["error"]["code"] == "PROVIDER_AUTH_FAILED"
    db = SessionLocal()
    try:
        latest = db.scalar(
            select(ProviderSyncRunRecord)
            .where(
                ProviderSyncRunRecord.data_source_id == source_id,
                ProviderSyncRunRecord.error_code == "PROVIDER_AUTH_FAILED",
            )
            .order_by(ProviderSyncRunRecord.completed_at.desc())
        )
        assert latest is not None
        assert latest.status == "failed"
        assert latest.error_code == "PROVIDER_AUTH_FAILED"
    finally:
        db.close()


def test_sync_job_retries_transient_provider_errors(client, monkeypatch):
    from app.services import provider_connection_service as connection_module

    class RetryOnceProvider(_ProviderStub):
        def __init__(self) -> None:
            super().__init__()
            self.calls = 0

        async def fetch_parties(self, context, secret, *, cursor, page_size):
            self.calls += 1
            if self.calls == 1:
                raise app_error("PROVIDER_UNREACHABLE", details={"provider": context.provider})
            return await super().fetch_parties(context, secret, cursor=cursor, page_size=page_size)

    provider = RetryOnceProvider()
    factory = ProviderFactory()
    factory.register(provider)
    monkeypatch.setattr(connection_module, "default_provider_factory", lambda: factory)

    suffix = uuid4().hex
    owner = _create_user(f"provider-retry-{suffix}@test.local")
    headers = _headers(owner)
    onboarding = client.post(
        "/api/v1/companies/onboarding",
        headers=headers,
        json={"tenant_name": f"Tenant retry {suffix}", "company_name": "Empresa retry"},
    ).json()
    source = client.post(
        "/api/v1/data-sources",
        headers=headers,
        json={
            "tenant_id": onboarding["tenant"]["id"],
            "company_id": onboarding["company"]["id"],
            "connector_id": "acme_retry",
            "display_name": "Acme retry",
            "kind": "accounting_software",
            "mode": "cloud_api",
            "provider_id": "acme_erp",
        },
    ).json()
    source_id = source["id"]
    assert client.put(
        f"/api/v1/data-sources/{source_id}/credentials",
        headers=headers,
        json={"credentials": {"token": "secret-that-must-not-leak"}},
    ).status_code == 200
    assert client.post(
        f"/api/v1/data-sources/{source_id}/connection-test", headers=headers
    ).status_code == 200

    enqueued = client.post(f"/api/v1/data-sources/{source_id}/sync/parties", headers=headers)
    assert enqueued.status_code == 202
    job_id = enqueued.json()["id"]
    retrying = _process_next_sync_job()
    assert retrying is not None
    assert retrying.status.value == "retrying"
    assert retrying.attempt_count == 1
    assert retrying.error_code == "PROVIDER_UNREACHABLE"

    db = SessionLocal()
    try:
        record = db.get(ProviderSyncJobRecord, job_id)
        assert record is not None
        record.available_at = datetime.now(UTC).replace(tzinfo=None)
        db.commit()
    finally:
        db.close()

    assert _process_next_sync_job().status.value == "queued"
    completed = _process_next_sync_job()
    assert completed is not None
    assert completed.status.value == "succeeded"
    assert completed.pages_processed == 2
    assert provider.calls == 3


def test_connection_failure_is_audited_without_exposing_credentials(client, monkeypatch):
    from app.services import provider_connection_service as connection_module

    class FailingProvider(_ProviderStub):
        async def test_connection(self, context, secret) -> None:
            raise app_error("PROVIDER_UNREACHABLE", details={"provider": context.provider})

    factory = ProviderFactory()
    factory.register(FailingProvider())
    monkeypatch.setattr(connection_module, "default_provider_factory", lambda: factory)

    suffix = uuid4().hex
    owner = _create_user(f"provider-failure-{suffix}@test.local")
    headers = _headers(owner)
    onboarding = client.post(
        "/api/v1/companies/onboarding",
        headers=headers,
        json={"tenant_name": f"Tenant failure {suffix}", "company_name": "Empresa failure"},
    ).json()
    source = client.post(
        "/api/v1/data-sources",
        headers=headers,
        json={
            "tenant_id": onboarding["tenant"]["id"],
            "company_id": onboarding["company"]["id"],
            "connector_id": "acme_failure",
            "display_name": "Acme failure",
            "kind": "accounting_software",
            "mode": "cloud_api",
            "provider_id": "acme_erp",
        },
    ).json()
    assert client.put(
        f"/api/v1/data-sources/{source['id']}/credentials",
        headers=headers,
        json={"credentials": {"token": "failure-secret"}},
    ).status_code == 200
    response = client.post(
        f"/api/v1/data-sources/{source['id']}/connection-test", headers=headers
    )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "PROVIDER_UNREACHABLE"
    assert "failure-secret" not in str(response.json())
