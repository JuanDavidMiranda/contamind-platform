import logging

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config.settings import settings
from app.shared.errors import register_exception_handlers
from app.shared.logging import JsonFormatter

pytestmark = pytest.mark.unit


class _Collector(logging.Handler):
    def __init__(self):
        super().__init__()
        self.lines = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(self.format(record))


def test_json_formatter_includes_correlation_id():
    record = logging.LogRecord(
        name="contamind.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="request",
        args=(),
        exc_info=None,
    )
    record.request_id = "trace-123"

    collector = _Collector()
    collector.setFormatter(JsonFormatter())
    collector.emit(record)

    assert '"request_id": "trace-123"' in collector.lines[0]


def test_secret_key_never_appears_in_error_logs(monkeypatch):
    monkeypatch.setattr(settings, "AUTH_SECRET_KEY", "S3CR3T-VALUE-DEBUG-123")

    app = FastAPI()

    @app.get("/boom")
    def boom():
        raise RuntimeError("fallo interno")

    register_exception_handlers(app)

    error_logger = logging.getLogger("contamind.error")
    collector = _Collector()
    collector.setFormatter(JsonFormatter())
    error_logger.addHandler(collector)
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            client.get("/boom")
    finally:
        error_logger.removeHandler(collector)

    assert collector.lines
    for line in collector.lines:
        assert "S3CR3T-VALUE-DEBUG-123" not in line
