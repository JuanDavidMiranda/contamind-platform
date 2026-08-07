import os

from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).resolve().parent

os.environ.setdefault(
    "DATABASE_URL",
    f"sqlite:///{TESTS_DIR / 'test_contamind.db'}",
)
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("AUTH_SECRET_KEY", "test-secret-key-not-for-production")

from fastapi.testclient import TestClient

import main as app_module


@pytest.fixture(scope="session")
def client() -> TestClient:
    with TestClient(app_module.app) as test_client:
        yield test_client
