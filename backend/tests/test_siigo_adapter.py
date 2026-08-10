import json
from uuid import uuid4

import httpx2 as httpx
import pytest

from app.providers.canonical import ProviderContext, ProviderKind
from app.providers.secrets import ProviderSecret
from app.providers.siigo import SiigoProviderAdapter
from app.shared.errors import AppError

pytestmark = pytest.mark.unit


def _context() -> ProviderContext:
    return ProviderContext(
        tenant_id=uuid4(),
        company_id=uuid4(),
        data_source_id=uuid4(),
        provider=ProviderKind.SIIGO,
    )


def _secret() -> ProviderSecret:
    return ProviderSecret(
        {
            "username": "integracion@cliente.test",
            "access_key": "private-access-key",
            "partner_id": "ContaMind",
        }
    )


def _client_factory(transport):
    def build_client(**kwargs):
        return httpx.AsyncClient(transport=transport, **kwargs)

    return build_client


@pytest.mark.asyncio
async def test_siigo_adapter_tests_connection_and_syncs_a_party_page():
    requests = []

    def handler(request):
        requests.append(request)
        if request.url.path == "/auth":
            assert json.loads(request.content) == {
                "username": "integracion@cliente.test",
                "access_key": "private-access-key",
            }
            assert request.headers["partner-id"] == "ContaMind"
            return httpx.Response(201, json={"access_token": "short-lived-token"})
        assert request.url.path == "/v1/customers"
        assert request.headers["authorization"] == "Bearer short-lived-token"
        assert request.url.params["page"] == "1"
        return httpx.Response(
            200,
            json={
                "pagination": {"total_results": 2},
                "results": [
                    {
                        "id": "external-party-1",
                        "type": "Customer",
                        "id_type": {"code": "31"},
                        "identification": "900123456",
                        "commercial_name": "Cliente Siigo",
                        "contacts": [{"email": "contacto@cliente.test"}],
                    }
                ],
            },
        )

    adapter = SiigoProviderAdapter(
        api_base_url="https://siigo.test",
        client_factory=_client_factory(httpx.MockTransport(handler)),
    )
    context = _context()
    secret = _secret()

    await adapter.test_connection(context, secret)
    page = await adapter.fetch_parties(context, secret, cursor=None, page_size=1)

    assert len(requests) == 3
    assert page.next_cursor == "2"
    assert page.items[0].company_id == context.company_id
    assert page.items[0].external_id == "external-party-1"
    assert page.items[0].document_number == "900123456"


@pytest.mark.asyncio
async def test_siigo_adapter_rejects_incomplete_credentials_without_transporting_them():
    adapter = SiigoProviderAdapter(api_base_url="https://siigo.test")

    with pytest.raises(AppError) as error:
        await adapter.test_connection(_context(), ProviderSecret({"username": "user"}))

    assert error.value.code == "VALIDATION_ERROR"
    assert "username" not in str(error.value.details)


@pytest.mark.asyncio
async def test_siigo_adapter_rejects_invalid_partner_id_before_making_a_request():
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        return httpx.Response(500)

    adapter = SiigoProviderAdapter(
        api_base_url="https://siigo.test",
        client_factory=_client_factory(httpx.MockTransport(handler)),
    )
    secret = ProviderSecret(
        {
            "username": "integracion@cliente.test",
            "access_key": "private-access-key",
            "partner_id": "partner id con espacios",
        }
    )

    with pytest.raises(AppError) as error:
        await adapter.test_connection(_context(), secret)

    assert calls == 0
    assert error.value.code == "VALIDATION_ERROR"
    assert error.value.details == {"field": "partner_id"}


@pytest.mark.asyncio
async def test_siigo_adapter_normalizes_authentication_failures_without_leaking_secrets():
    def handler(request):
        assert b"private-access-key" in request.content
        return httpx.Response(401, json={"message": "invalid access key"})

    adapter = SiigoProviderAdapter(
        api_base_url="https://siigo.test",
        client_factory=_client_factory(httpx.MockTransport(handler)),
    )

    with pytest.raises(AppError) as error:
        await adapter.test_connection(_context(), _secret())

    assert error.value.code == "PROVIDER_AUTH_FAILED"
    assert error.value.details == {"provider": ProviderKind.SIIGO}
    assert "private-access-key" not in str(error.value)
    assert "private-access-key" not in str(error.value.details)


@pytest.mark.asyncio
async def test_siigo_adapter_rejects_an_auth_response_without_access_token():
    def handler(request):
        return httpx.Response(201, json={"expires_in": 86400})

    adapter = SiigoProviderAdapter(
        api_base_url="https://siigo.test",
        client_factory=_client_factory(httpx.MockTransport(handler)),
    )

    with pytest.raises(AppError) as error:
        await adapter.test_connection(_context(), _secret())

    assert error.value.code == "PROVIDER_AUTH_FAILED"


@pytest.mark.asyncio
async def test_siigo_adapter_normalizes_rate_limit_after_retries():
    customer_calls = 0

    def handler(request):
        nonlocal customer_calls
        if request.url.path == "/auth":
            return httpx.Response(201, json={"access_token": "short-lived-token"})
        customer_calls += 1
        return httpx.Response(429, json={"message": "rate limit"})

    adapter = SiigoProviderAdapter(
        api_base_url="https://siigo.test",
        client_factory=_client_factory(httpx.MockTransport(handler)),
    )

    with pytest.raises(AppError) as error:
        await adapter.fetch_parties(_context(), _secret(), cursor=None, page_size=10)

    assert customer_calls == 3
    assert error.value.code == "PROVIDER_RATE_LIMITED"


@pytest.mark.asyncio
async def test_siigo_adapter_normalizes_an_invalid_customer_payload():
    def handler(request):
        if request.url.path == "/auth":
            return httpx.Response(201, json={"access_token": "short-lived-token"})
        return httpx.Response(200, json={"results": [{"id": "party-without-name"}]})

    adapter = SiigoProviderAdapter(
        api_base_url="https://siigo.test",
        client_factory=_client_factory(httpx.MockTransport(handler)),
    )

    with pytest.raises(AppError) as error:
        await adapter.fetch_parties(_context(), _secret(), cursor=None, page_size=10)

    assert error.value.code == "PROVIDER_ERROR"
    assert error.value.details == {"provider": ProviderKind.SIIGO}


@pytest.mark.asyncio
async def test_siigo_adapter_rejects_an_invalid_saved_cursor_before_authentication():
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        return httpx.Response(500)

    adapter = SiigoProviderAdapter(
        api_base_url="https://siigo.test",
        client_factory=_client_factory(httpx.MockTransport(handler)),
    )

    with pytest.raises(AppError) as error:
        await adapter.fetch_parties(_context(), _secret(), cursor="invalid", page_size=10)

    assert calls == 0
    assert error.value.code == "CONFLICT"
