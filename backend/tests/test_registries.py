import pytest

from app.ai.bootstrap import bootstrap as bootstrap_module
from app.ai.registry import registry as agent_registry
from app.ai.registry.agent_registry import AgentRegistry
from app.ai.registry.exceptions import AgentNotFoundException
from app.ai.tools.registry import ToolRegistry, registry as tool_registry

pytestmark = pytest.mark.unit


class _FakeAgent:
    def __init__(self, agent_id: str):
        self.id = agent_id


class _FakeTool:
    def __init__(self, name: str):
        self.name = name


def test_agent_registry_duplicate_registration_is_idempotent():
    registry = AgentRegistry()
    registry.register(_FakeAgent("agente-1"))
    registry.register(_FakeAgent("agente-1"))
    assert registry.list() == ["agente-1"]


def test_agent_registry_get_and_not_found():
    registry = AgentRegistry()
    registry.register(_FakeAgent("existe"))
    assert registry.get("existe").id == "existe"
    with pytest.raises(AgentNotFoundException):
        registry.get("no-existe")


def test_tool_registry_duplicate_registration_is_idempotent():
    registry = ToolRegistry()
    registry.register(_FakeTool("Herramienta X"))
    registry.register(_FakeTool("Herramienta X"))
    assert registry.list() == ["Herramienta X"]


def test_bootstrap_registers_mock_tool_exactly_once(monkeypatch):
    registry = ToolRegistry()
    monkeypatch.setattr(bootstrap_module, "registry", registry)
    monkeypatch.setattr(bootstrap_module, "is_enabled", lambda name, default=False: True)

    bootstrap_module.bootstrap()
    bootstrap_module.bootstrap()

    assert registry.list() == ["Consultar obligaciones"]


def test_global_registries_have_unique_ids():
    assert len(tool_registry.list()) == len(set(tool_registry.list()))
    assert len(agent_registry.list()) == len(set(agent_registry.list()))
