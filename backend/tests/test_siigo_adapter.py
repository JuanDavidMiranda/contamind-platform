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
