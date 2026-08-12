import os
import tempfile

from pathlib import Path
from uuid import uuid4

import pytest

TEST_DATABASE_PATH = (
    Path(tempfile.gettempdir())
    / f"contamind-tests-{os.getpid()}-{uuid4().hex}.db"
)

# Cada ejecución necesita un archivo nuevo: ``create_all`` no actualiza una
# base SQLite previa si cambian los modelos entre ejecuciones.
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DATABASE_PATH.as_posix()}"
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("AUTH_SECRET_KEY", "test-secret-key-not-for-production")

from fastapi.testclient import TestClient

import main as app_module
from app.database import engine


@pytest.fixture(scope="session")
def client() -> TestClient:
    with TestClient(app_module.app) as test_client:
        yield test_client
    engine.dispose()
    TEST_DATABASE_PATH.unlink(missing_ok=True)
