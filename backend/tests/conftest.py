from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from alembic import command
from app.ai.fake_provider import FakeAIProvider
from app.ai.provider import get_ai_provider
from app.clock import FixedClock, get_clock
from app.config import get_settings
from app.db.session import get_db
from app.main import app

BACKEND_DIR = Path(__file__).resolve().parent.parent
# Sunday 2026-10-04, evening in Casablanca.
NOW = datetime(2026, 10, 4, 18, 42, tzinfo=UTC)


@pytest.fixture(scope="session")
def engine():
    url = get_settings().test_database_url
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    config.set_main_option("sqlalchemy.url", url)
    config.attributes["configure_logging"] = False
    command.upgrade(config, "head")
    yield engine
    engine.dispose()


@pytest.fixture
def db(engine) -> Iterator[Session]:
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(
        bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False
    )
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture
def fake_ai() -> FakeAIProvider:
    return FakeAIProvider()


@pytest.fixture
def clock() -> FixedClock:
    return FixedClock(NOW)


@pytest.fixture
def client(db, fake_ai, clock) -> Iterator[TestClient]:
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_ai_provider] = lambda: fake_ai
    app.dependency_overrides[get_clock] = lambda: clock
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def register(client: TestClient, email: str = "me@example.com", **extra) -> dict:
    payload = {
        "email": email,
        "password": "correct horse battery",
        "timezone": "Africa/Casablanca",
        "default_currency": "MAD",
        **extra,
    }
    response = client.post("/v1/auth/register", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture
def auth(client) -> dict:
    tokens = register(client)
    return {"Authorization": f"Bearer {tokens['access_token']}"}
