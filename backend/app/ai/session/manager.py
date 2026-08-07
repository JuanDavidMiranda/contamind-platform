import time
from abc import ABC, abstractmethod
from collections import OrderedDict

from app.ai.core.context import Context
from app.config.settings import settings

# Persistencia TEMPORAL (Fase 0): las sesiones viven únicamente en memoria
# del proceso. No sobreviven a reinicios ni se comparten entre instancias.
# Para Fase 1 el SessionManager debe migrar a un backend persistente
# (p.ej. Redis) implementando la interfaz SessionStore, sin cambiar la API
# pública usada por los controladores (get/save/delete).
TEMPORARY_PERSISTENCE = True


class SessionStore(ABC):

    @abstractmethod
    def get(self, conversation_id: str) -> Context | None:
        ...

    @abstractmethod
    def save(self, conversation_id: str, context: Context) -> None:
        ...

    @abstractmethod
    def delete(self, conversation_id: str) -> None:
        ...

    @abstractmethod
    def size(self) -> int:
        ...


class InMemorySessionStore(SessionStore):

    def __init__(
        self,
        max_size: int = 1000,
        ttl_seconds: int = 3600,
    ):
        self.max_size = max(max_size, 1)
        self.ttl_seconds = ttl_seconds
        self._sessions: OrderedDict[str, tuple[float, Context]] = OrderedDict()

    def _purge_expired(self, now: float) -> None:
        expired = [
            key
            for key, (last_access, _) in self._sessions.items()
            if now - last_access > self.ttl_seconds
        ]
        for key in expired:
            self._sessions.pop(key, None)

    def _evict_lru(self) -> None:
        while len(self._sessions) > self.max_size:
            self._sessions.popitem(last=False)

    def get(self, conversation_id: str) -> Context | None:
        now = time.monotonic()
        self._purge_expired(now)
        entry = self._sessions.get(conversation_id)
        if entry is None:
            return None
        _, context = entry
        self._sessions[conversation_id] = (now, context)
        return context

    def save(self, conversation_id: str, context: Context) -> None:
        now = time.monotonic()
        self._purge_expired(now)
        self._sessions[conversation_id] = (now, context)
        self._evict_lru()

    def delete(self, conversation_id: str) -> None:
        self._sessions.pop(conversation_id, None)

    def size(self) -> int:
        return len(self._sessions)


class SessionManager:

    def __init__(
        self,
        store: SessionStore | None = None,
        max_sessions: int | None = None,
        ttl_seconds: int | None = None,
    ):
        self.store = store or InMemorySessionStore(
            max_size=max_sessions if max_sessions is not None else settings.SESSION_MAX_ACTIVE,
            ttl_seconds=ttl_seconds if ttl_seconds is not None else settings.SESSION_TTL_SECONDS,
        )

    def get(self, conversation_id: str) -> Context:
        context = self.store.get(conversation_id)
        if context is None:
            context = Context(conversation_id=conversation_id)
            self.store.save(conversation_id, context)
        return context

    def save(self, context: Context) -> None:
        self.store.save(context.conversation_id, context)

    def delete(self, conversation_id: str) -> None:
        self.store.delete(conversation_id)

    def active_count(self) -> int:
        return self.store.size()
