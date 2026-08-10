import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app.config.settings import settings

BACKEND_DIR = Path(__file__).resolve().parents[1]

RUN_POSTGRES = os.environ.get("RUN_POSTGRES_TESTS") == "1"

pytestmark = [
    pytest.mark.postgres,
    pytest.mark.skipif(
        not RUN_POSTGRES,
        reason="opt-in: define RUN_POSTGRES_TESTS=1 para ejecutar contra PostgreSQL",
    ),
]

BASE_URL = os.environ.get(
    "POSTGRES_TEST_DATABASE_URL",
    "postgresql+psycopg2://contamind:contamind@localhost:5433/contamind",
)


def _admin_url() -> str:
    return make_url(BASE_URL).set(database="postgres").render_as_string(hide_password=False)


def test_migrations_apply_on_empty_database():
    scratch_db = f"contamind_test_{os.getpid()}"
    scratch_url = make_url(BASE_URL).set(database=scratch_db).render_as_string(hide_password=False)
    admin_engine = create_engine(_admin_url(), isolation_level="AUTOCOMMIT")

    with admin_engine.connect() as connection:
        connection.execute(text(f'DROP DATABASE IF EXISTS "{scratch_db}"'))
        connection.execute(text(f'CREATE DATABASE "{scratch_db}"'))

    previous_url = settings.DATABASE_URL
    settings.DATABASE_URL = scratch_url
    try:
        config = Config()
        config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
        command.upgrade(config, "head")

        engine = create_engine(scratch_url)
        try:
            with engine.connect() as connection:
                tables = set(
                    connection.execute(
                        text("SELECT tablename FROM pg_tables WHERE schemaname='public'")
                    ).scalars()
                )
                assert {
                    "users",
                    "subscriptions",
                    "tenants",
                    "companies",
                    "tenant_memberships",
                    "company_memberships",
                    "company_data_sources",
                    "import_profiles",
                    "import_batches",
                    "parties",
                } <= tables
                version = connection.execute(
                    text("SELECT version_num FROM alembic_version")
                ).scalar()
                assert version is not None
        finally:
            engine.dispose()
    finally:
        settings.DATABASE_URL = previous_url
        with admin_engine.connect() as connection:
            connection.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    f"WHERE datname = '{scratch_db}' AND pid <> pg_backend_pid()"
                )
            )
            connection.execute(text(f'DROP DATABASE IF EXISTS "{scratch_db}"'))
        admin_engine.dispose()
