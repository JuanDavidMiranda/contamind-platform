import pytest

from app.ai.bootstrap.bootstrap import bootstrap
from app.ai.tools.registry import registry

pytestmark = pytest.mark.unit


def test_bootstrap_registers_mock_tool():
    bootstrap()
    tool = registry.get("Consultar obligaciones")
    assert tool.name == "Consultar obligaciones"
    assert tool.is_mock is True
    assert "MOCK" in tool.description
