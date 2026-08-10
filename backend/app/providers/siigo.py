"""Adaptador inicial de lectura para Siigo, aislado del dominio contable."""

import re
from collections.abc import Callable
from typing import Any

import httpx2 as httpx

from app.providers.canonical import Party, PartySyncPage, PartyType, ProviderContext, ProviderKind
from app.providers.ports import ProviderConnectionPort, ProviderPartySyncPort
from app.providers.secrets import ProviderSecret
from app.providers.transport import ProviderHttpClient
from app.shared.errors import app_error

_PARTNER_ID_PATTERN = re.compile(r"^[A-Za-z0-9]{3,100}$")
_REQUIRED_SECRET_FIELDS = frozenset({"username", "access_key", "partner_id"})
ClientFactory = Callable[..., httpx.AsyncClient]


class SiigoProviderAdapter(ProviderConnectionPort, ProviderPartySyncPort):
    """Autentica y lee terceros con el contrato público actual de Siigo API.

    El adaptador no conserva secretos, tokens ni payloads. Cada invocación recibe
    el secreto ya descifrado desde la capa de conexiones y descarta el JWT al terminar.
    """

    provider = ProviderKind.SIIGO

    def __init__(
        self,
        *,
        api_base_url: str = "https://api.siigo.com",
        client_factory: ClientFactory = httpx.AsyncClient,
        timeout_seconds: float = 30.0,
    ) -> None:
        self._api_base_url = api_base_url.rstrip("/")
        self._client_factory = client_factory
        self._timeout_seconds = timeout_seconds

    async def test_connection(self, context: ProviderContext, secret: ProviderSecret) -> None:
        await self._get_access_token(context, secret)

    async def fetch_parties(
        self,
        context: ProviderContext,
        secret: ProviderSecret,
        *,
        cursor: str | None,
        page_size: int,
    ) -> PartySyncPage:
        page = self._parse_cursor(cursor)
        token = await self._get_access_token(context, secret)
        response = await self._request(
            context,
            "GET",
            "/v1/customers",
            headers={
                "Authorization": f"Bearer {token}",
                "Partner-Id": secret.values["partner_id"],
            },
            params={"page": str(page), "page_size": str(page_size)},
        )
        payload = self._response_object(response)
        records = payload.get("results")
        if not isinstance(records, list):
            raise app_error(
                "PROVIDER_ERROR",
                message="El proveedor respondió terceros en un formato no compatible.",
                details={"provider": context.provider},
            )

        try:
            parties = tuple(self._to_party(context, record) for record in records)
        except (KeyError, TypeError, ValueError) as exc:
            raise app_error(
                "PROVIDER_ERROR",
                message="El proveedor devolvió un tercero que no puede normalizarse.",
                details={"provider": context.provider},
            ) from exc
        return PartySyncPage(
            items=parties,
            next_cursor=self._next_cursor(payload, page, page_size),
        )

    async def _get_access_token(self, context: ProviderContext, secret: ProviderSecret) -> str:
        self._validate_secret(secret)
        response = await self._request(
            context,
            "POST",
            "/auth",
            headers={
                "Partner-Id": secret.values["partner_id"],
                "Content-Type": "application/json",
            },
            json={
                "username": secret.values["username"],
                "access_key": secret.values["access_key"],
            },
        )
        token = self._response_object(response).get("access_token")
        if not isinstance(token, str) or not token.strip():
            raise app_error(
                "PROVIDER_AUTH_FAILED",
                message="El proveedor no devolvió un token de acceso válido.",
                details={"provider": context.provider},
            )
        return token

    async def _request(
        self,
        context: ProviderContext,
        method: str,
        path: str,
        *,
        headers: dict[str, str],
        params: dict[str, str] | None = None,
        json: dict[str, str] | None = None,
    ) -> httpx.Response:
        async with self._client_factory(timeout=self._timeout_seconds) as client:
            transport = ProviderHttpClient(client)
            return await transport.request(
                context,
                method,
                f"{self._api_base_url}{path}",
                headers=headers,
                params=params,
                json=json,
            )

    @staticmethod
    def _validate_secret(secret: ProviderSecret) -> None:
        missing = sorted(_REQUIRED_SECRET_FIELDS.difference(secret.values))
        if missing:
            raise app_error(
                "VALIDATION_ERROR",
                message="Faltan campos obligatorios de la credencial del proveedor.",
                details={"fields": missing},
            )
        if not _PARTNER_ID_PATTERN.fullmatch(secret.values["partner_id"]):
            raise app_error(
                "VALIDATION_ERROR",
                message="partner_id no cumple el formato requerido por el proveedor.",
                details={"field": "partner_id"},
            )

    @staticmethod
    def _parse_cursor(cursor: str | None) -> int:
        if cursor is None:
            return 1
        try:
            page = int(cursor)
        except ValueError as exc:
            raise app_error(
                "CONFLICT",
                message="El cursor almacenado para el proveedor no es válido.",
            ) from exc
        if page < 1:
            raise app_error("CONFLICT", message="El cursor almacenado para el proveedor no es válido.")
        return page

    @staticmethod
    def _response_object(response: httpx.Response) -> dict[str, Any]:
        try:
            payload = response.json()
        except ValueError as exc:
            raise app_error(
                "PROVIDER_ERROR",
                message="El proveedor respondió un contenido no compatible.",
            ) from exc
        if not isinstance(payload, dict):
            raise app_error(
                "PROVIDER_ERROR",
                message="El proveedor respondió un contenido no compatible.",
            )
        return payload

    @staticmethod
    def _next_cursor(payload: dict[str, Any], page: int, page_size: int) -> str | None:
        pagination = payload.get("pagination")
        if isinstance(pagination, dict):
            total = pagination.get("total_results")
            if isinstance(total, int) and page * page_size < total:
                return str(page + 1)
        links = payload.get("__links")
        if isinstance(links, dict) and links.get("next"):
            return str(page + 1)
        return None

    @staticmethod
    def _to_party(context: ProviderContext, payload: Any) -> Party:
        if not isinstance(payload, dict):
            raise TypeError("El tercero debe ser un objeto.")
        external_id = payload["id"]
        if not isinstance(external_id, (str, int)):
            raise ValueError("El identificador externo no es válido.")
        name = SiigoProviderAdapter._party_name(payload)
        id_type = payload.get("id_type")
        document_type = id_type.get("code") if isinstance(id_type, dict) else None
        address = payload.get("address") if isinstance(payload.get("address"), dict) else {}
        contacts = payload.get("contacts") if isinstance(payload.get("contacts"), list) else []
        phones = payload.get("phones") if isinstance(payload.get("phones"), list) else []
        return Party(
            company_id=context.company_id,
            party_type=SiigoProviderAdapter._party_type(payload.get("type")),
            name=name,
            document_type=str(document_type) if document_type is not None else None,
            document_number=SiigoProviderAdapter._optional_text(payload.get("identification")),
            email=SiigoProviderAdapter._first_text(contacts, "email"),
            phone=SiigoProviderAdapter._first_text(phones, "number"),
            city=SiigoProviderAdapter._city_name(address),
            address=SiigoProviderAdapter._optional_text(address.get("address")),
            external_id=str(external_id),
            integration_id=f"{context.company_id}:{context.provider}:{external_id}",
        )

    @staticmethod
    def _party_name(payload: dict[str, Any]) -> str:
        commercial_name = SiigoProviderAdapter._optional_text(payload.get("commercial_name"))
        if commercial_name:
            return commercial_name
        names = payload.get("name")
        if isinstance(names, list):
            normalized = " ".join(
                value.strip() for value in names if isinstance(value, str) and value.strip()
            )
            if normalized:
                return normalized
        raise ValueError("El tercero no tiene nombre.")

    @staticmethod
    def _party_type(value: Any) -> PartyType:
        normalized = str(value or "").strip().lower()
        if normalized == "supplier":
            return PartyType.SUPPLIER
        if normalized in {"other", "both"}:
            return PartyType.BOTH
        return PartyType.CUSTOMER

    @staticmethod
    def _city_name(address: dict[str, Any]) -> str | None:
        city = address.get("city")
        return SiigoProviderAdapter._optional_text(city.get("name")) if isinstance(city, dict) else None

    @staticmethod
    def _first_text(records: list[Any], field: str) -> str | None:
        for record in records:
            if isinstance(record, dict) and (value := SiigoProviderAdapter._optional_text(record.get(field))):
                return value
        return None

    @staticmethod
    def _optional_text(value: Any) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized or None
