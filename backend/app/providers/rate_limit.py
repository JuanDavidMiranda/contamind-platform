"""Rate limiting local por empresa y proveedor para la capa de transporte."""

import time
from collections import deque
from collections.abc import Callable, Mapping

from app.providers.canonical import ProviderContext, ProviderId, normalize_provider_id
from app.shared.errors import app_error


class InMemoryRateLimiter:
    """Ventana móvil in-process; reemplazable por Redis al escalar horizontalmente."""

    def __init__(
        self,
        requests_per_minute: Mapping[ProviderId, int],
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if any(limit < 1 for limit in requests_per_minute.values()):
            raise ValueError("Los límites de solicitudes deben ser positivos.")
        self._limits = {
            normalize_provider_id(provider): limit
            for provider, limit in requests_per_minute.items()
        }
        self._clock = clock
        self._requests: dict[tuple[str, ProviderId], deque[float]] = {}

    async def acquire(self, context: ProviderContext) -> None:
        limit = self._limits.get(context.provider)
        if limit is None:
            return

        now = self._clock()
        key = (str(context.company_id), context.provider)
        requests = self._requests.setdefault(key, deque())
        while requests and now - requests[0] >= 60:
            requests.popleft()
        if len(requests) >= limit:
            raise app_error(
                "PROVIDER_RATE_LIMITED",
                details={"provider": context.provider},
            )
        requests.append(now)
