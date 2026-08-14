"""Cortes bancarios verificados para la posición de tesorería."""

from datetime import date, timedelta
from uuid import uuid4

import pytest

from app.database.database import SessionLocal
from app.models.user import User
from app.shared.security import create_access_token, hash_password


pytestmark = pytest.mark.integration


def _user(email: str) -> User:
    db = SessionLocal()
    try:
        record = User(
            email=email,
            full_name="Bank balance snapshot user",
            password_hash=hash_password("password123"),
        )
        db.add(record)
        db.commit()
        db.refresh(record)
        return record
    finally:
        db.close()


def _headers(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user)}"}


def test_verified_bank_balance_snapshot_requires_confirmation_and_preserves_cut(client):
    suffix = uuid4().hex
    owner = _user(f"balance-owner-{suffix}@test.local")
    viewer = _user(f"balance-viewer-{suffix}@test.local")
    owner_headers = _headers(owner)
    onboarding = client.post(
        "/api/v1/companies/onboarding",
        headers=owner_headers,
        json={"tenant_name": f"Tenant saldos {suffix}", "company_name": "Empresa saldos"},
    )
    assert onboarding.status_code == 201
    company_id = onboarding.json()["company"]["id"]
    assert client.put(
        "/api/v1/company-memberships",
        headers=owner_headers,
        json={"user_id": viewer.id, "company_id": company_id, "role": "viewer"},
    ).status_code == 200

    account = client.post(
        f"/api/v1/companies/{company_id}/bank-reconciliation/accounts",
        headers=owner_headers,
        json={"name": "Cuenta saldo COP", "currency_code": "COP", "confirmed": True},
    )
    assert account.status_code == 201
    account_id = account.json()["id"]
    endpoint = (
        f"/api/v1/companies/{company_id}/bank-reconciliation/"
        f"accounts/{account_id}/balance-snapshots"
    )
    today = date.today()

    missing_confirmation = client.post(
        endpoint,
        headers=owner_headers,
        json={"as_of_date": today.isoformat(), "balance": "1500"},
    )
    assert missing_confirmation.status_code == 422

    created = client.post(
        endpoint,
        headers=owner_headers,
        json={"as_of_date": today.isoformat(), "balance": "1500.50", "confirmed": True},
    )
    assert created.status_code == 201
    assert created.json()["currency_code"] == "COP"
    assert created.json()["balance"] == "1500.50"
    assert created.json()["verified_by_user_id"] == owner.id

    duplicate = client.post(
        endpoint,
        headers=owner_headers,
        json={"as_of_date": today.isoformat(), "balance": "1500.50", "confirmed": True},
    )
    assert duplicate.status_code == 409
    future = client.post(
        endpoint,
        headers=owner_headers,
        json={
            "as_of_date": (today + timedelta(days=1)).isoformat(),
            "balance": "1600",
            "confirmed": True,
        },
    )
    assert future.status_code == 422
    denied = client.post(
        endpoint,
        headers=_headers(viewer),
        json={"as_of_date": today.isoformat(), "balance": "1500", "confirmed": True},
    )
    assert denied.status_code == 403

    listed = client.get(
        f"/api/v1/companies/{company_id}/bank-reconciliation/balance-snapshots",
        headers=_headers(viewer),
    )
    assert listed.status_code == 200
    assert listed.json()["can_manage"] is False
    assert listed.json()["snapshots"] == [
        {
            "id": created.json()["id"],
            "bank_account_id": account_id,
            "as_of_date": today.isoformat(),
            "balance": "1500.50",
            "currency_code": "COP",
            "verified_by_user_id": owner.id,
            "verified_at": created.json()["verified_at"],
        }
    ]
