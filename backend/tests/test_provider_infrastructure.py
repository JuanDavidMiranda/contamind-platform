from uuid import uuid4

import httpx2 as httpx
import pytest

from app.providers.canonical import ProviderContext, ProviderKind
from app.providers.rate_limit import InMemoryRateLimiter
from app.providers.secrets import InMemorySecretStore, ProviderSecret
from app.providers.transport import ProviderHttpClient
from app.shared.errors import AppError

pytestmark = pytest.mark.unit


def _context(*, company_id=None, provider=ProviderKind.SIIGO):
    return ProviderContext(
        tenant_id=uuid4(),
        company_id=company_id or uuid4(),
        provider=provider,
        correlation_id="provider-test-1",
    )


def test_secret_store_isolated_by_company_and_provider():
    store = InMemorySecretStore()
    first = _context()
    other_company = _context(provider=ProviderKind.SIIGO)
    other_provider = _context(company_id=first.company_id, provider=ProviderKind.ALEGRA)
    secret = ProviderSecret({"token": "private-value"})

    store.save(first, secret)

    assert store.get(first) is secret
    assert store.get(other_company) is None
    assert store.get(other_provider) is None


def test_secret_store_revocation_and_representation_are_safe():
    store = InMemorySecretStore()
    context = _context()
    secret = ProviderSecret({"token": "private-value"})
    store.save(context, secret)

    assert "private-value" not in repr(secret)
    store.revoke(context)
    assert store.get(context) is None


@pytest.mark.asyncio
async def test_http_client_retries_transient_response_with_mock_transport():
    calls = 0
    pauses = []

    def handler(request):
        nonlocal calls
        calls += 1
        status_code = 503 if calls == 1 else 200
        return httpx.Response(status_code, json={"ok": True})

    async def sleep(seconds):
        pauses.append(seconds)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        transport = ProviderHttpClient(client, sleep=sleep)
        response = await transport.request(_context(), "GET", "https://provider.test/parties")

    assert response.status_code == 200
    assert calls == 2
    assert pauses == [0.25]


@pytest.mark.asyncio
async def test_http_client_maps_auth_errors_without_exposing_authorization(caplog):
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(401))
    ) as client:
        transport = ProviderHttpClient(client, retries=0)
        with pytest.raises(AppError) as error:
            await transport.request(
                _context(),
                "GET",
                "https://provider.test/parties",
                headers={"Authorization": "Bearer private-value"},
            )

    assert error.value.code == "PROVIDER_AUTH_FAILED"
    assert "private-value" not in caplog.text


@pytest.mark.asyncio
async def test_http_client_maps_connection_errors():
    def handler(request):
        raise httpx.ConnectError("connection refused", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        transport = ProviderHttpClient(client, retries=0)
        with pytest.raises(AppError) as error:
            await transport.request(_context(), "GET", "https://provider.test/parties")

    assert error.value.code == "PROVIDER_UNREACHABLE"


@pytest.mark.asyncio
async def test_rate_limiter_scopes_limit_by_company():
    context = _context()
    limiter = InMemoryRateLimiter({ProviderKind.SIIGO: 1}, clock=lambda: 100.0)
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200))
    ) as client:
        transport = ProviderHttpClient(client, rate_limiter=limiter)
        await transport.request(context, "GET", "https://provider.test/parties")
        with pytest.raises(AppError) as error:
            await transport.request(context, "GET", "https://provider.test/parties")

    assert error.value.code == "PROVIDER_RATE_LIMITED"
