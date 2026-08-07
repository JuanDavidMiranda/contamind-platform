import pytest

from app.ai.core.context import Context
from app.ai.session import session_manager
from app.ai.session.manager import SessionManager, SessionStore

pytestmark = pytest.mark.unit


def test_get_creates_context_when_missing():
    manager = SessionManager(max_sessions=10, ttl_seconds=3600)
    context = manager.get("conv-1")
    assert isinstance(context, Context)
    assert context.conversation_id == "conv-1"
    assert manager.active_count() == 1


def test_save_and_get_roundtrip_preserves_state():
    manager = SessionManager(max_sessions=10, ttl_seconds=3600)
    context = manager.get("conv-1")
    context.state = "WAITING_NIT"
    context.variables["nit"] = "900123456"
    manager.save(context)

    restored = manager.get("conv-1")
    assert restored.state == "WAITING_NIT"
    assert restored.variables["nit"] == "900123456"


def test_sessions_are_isolated():
    manager = SessionManager(max_sessions=10, ttl_seconds=3600)
    first = manager.get("conv-a")
    first.variables["nit"] = "111"
    second = manager.get("conv-b")
    assert second is not first
    assert "nit" not in second.variables
    assert manager.get("conv-a").variables["nit"] == "111"


def test_delete_removes_session():
    manager = SessionManager(max_sessions=10, ttl_seconds=3600)
    manager.get("conv-1")
    manager.delete("conv-1")
    assert manager.active_count() == 0
    assert manager.get("conv-1").variables == {}


def test_evicts_oldest_when_limit_reached():
    manager = SessionManager(max_sessions=2, ttl_seconds=3600)
    first = manager.get("a")
    first.variables["mark"] = "keep"
    manager.save(first)
    manager.get("b")
    manager.get("c")
    assert manager.active_count() == 2
    assert manager.get("c").conversation_id == "c"
    recreated = manager.get("a")
    assert "mark" not in recreated.variables


def test_expired_sessions_do_not_accumulate():
    manager = SessionManager(max_sessions=10, ttl_seconds=-1)
    manager.get("conv-1")
    manager.get("conv-1")
    assert manager.active_count() == 1


def test_custom_store_is_injected():
    calls = []

    class RecordingStore(SessionStore):

        def get(self, conversation_id):
            calls.append(("get", conversation_id))
            return None

        def save(self, conversation_id, context):
            calls.append(("save", conversation_id))

        def delete(self, conversation_id):
            calls.append(("delete", conversation_id))

        def size(self):
            return 0

    store = RecordingStore()
    manager = SessionManager(store=store, max_sessions=5, ttl_seconds=3600)
    manager.get("conv-1")
    manager.save(manager.get("conv-1"))
    manager.delete("conv-1")
    assert ("get", "conv-1") in calls
    assert ("save", "conv-1") in calls
    assert ("delete", "conv-1") in calls


def test_context_never_holds_secrets():
    context = Context(conversation_id="conv-1")
    fields = set(context.__dataclass_fields__)
    assert "password" not in fields
    assert "secret" not in fields
    assert "token" not in fields


def test_singleton_preserves_public_api():
    assert isinstance(session_manager, SessionManager)
    context = session_manager.get("singleton-1")
    session_manager.save(context)
    session_manager.delete("singleton-1")
