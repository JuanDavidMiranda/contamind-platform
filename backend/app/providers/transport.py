"""Cliente HTTP compartido para adaptadores, con manejo seguro de fallos."""

import asyncio
import logging
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

import httpx2 as httpx

from app.providers.canonical import ProviderContext
from app.providers.rate_limit import InMemoryRateLimiter
from app.shared.errors import app_error

logger = logging.getLogger("contamind.provider_http")

Sleep = Callable[[float], Awaitable[None]]


class ProviderHttpClient:
    """Transporte reutilizable; no construye ni almacena credenciales."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        rate_limiter: InMemoryRateLimiter | None = None,
        retries: int = 2,
        retry_delay_seconds: float = 0.25,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        if retries < 0 or retry_delay_seconds < 0:
            raise ValueError("Los reintentos y el retraso deben ser valores no negativos.")
        self._client = client
        self._rate_limiter = rate_limiter
        self._retries = retries
        self._retry_delay_seconds = retry_delay_seconds
        self._sleep = sleep

    async def request(
        self,
        context: ProviderContext,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, str] | None = None,
        json: Any = None,
        content: bytes | str | None = None,
    ) -> httpx.Response:
        """Ejecuta una solicitud y traduce fallos sin filtrar datos sensibles."""
        if self._rate_limiter is not None:
            await self._rate_limiter.acquire(context)

        response: httpx.Response | None = None
        for attempt in range(self._retries + 1):
            try:
                response = await self._client.request(
                    method,
                    url,
                    headers=headers,
                    params=params,
                    json=json,
                    content=content,
                )
            except httpx.RequestError as exc:
                if attempt < self._retries:
                    await self._backoff(attempt)
                    continue
                raise app_error(
                    "PROVIDER_UNREACHABLE",
                    details={"provider": context.provider},
                ) from exc

            if response.status_code == 429 or response.status_code >= 500:
                if attempt < self._retries:
                    await self._backoff(attempt)
                    continue
            break

        assert response is not None
        self._log_response(context, method, response.status_code)
        self._raise_for_status(context, response.status_code)
        return response

    async def _backoff(self, attempt: int) -> None:
        await self._sleep(self._retry_delay_seconds * (attempt + 1))

    @staticmethod
    def _raise_for_status(context: ProviderContext, status_code: int) -> None:
        details = {"provider": context.provider}
        if status_code in (401, 403):
            raise app_error("PROVIDER_AUTH_FAILED", details=details)
        if status_code == 429:
            raise app_error("PROVIDER_RATE_LIMITED", details=details)
        if status_code >= 400:
            raise app_error("PROVIDER_ERROR", details=details)

    @staticmethod
    def _log_response(context: ProviderContext, method: str, status_code: int) -> None:
        logger.info(
            "provider request completed",
            extra={
                "request_id": context.correlation_id,
                "method": method,
                "status_code": status_code,
                "provider": context.provider,
                "company_id": str(context.company_id),
            },
        )
