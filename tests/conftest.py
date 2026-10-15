"""Shared pytest fixtures.

Every test gets a fresh SQLite database plus the reproducible demo seed, and a
TestClient wired to it. This is a real database integration setup (the spec
requires real DB integration tests), not a mocked repository layer.
"""

from __future__ import annotations

import io
import os
import sys
from pathlib import Path
from typing import Any, Iterator

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.config import get_settings, reset_settings_cache  # noqa: E402
from app.db import get_engine, get_session_factory, reset_engine, session_scope  # noqa: E402
from app.models import Base, User  # noqa: E402
from app.services import seed  # noqa: E402

DEMO_DIR = ROOT / "data" / "fixtures" / "imports"


@pytest.fixture()
def app_settings(tmp_path, monkeypatch) -> Iterator[Any]:
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+pysqlite:///{db_path}")
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("SCHEDULER_ENABLED", "false")
    monkeypatch.setenv("AUTH_MODE", "demo")
    monkeypatch.setenv("MODEL_MODE", "mock")
    monkeypatch.setenv("VISION_MODE", "mock")
    monkeypatch.setenv("WEATHER_MODE", "mock")
    monkeypatch.setenv("NOTIFICATION_MODE", "in_app")
    monkeypatch.setenv("ATLAS_MIN_EVENTS", "3")
    monkeypatch.setenv("SERVICE_DAILY_CAP", "1")
    monkeypatch.setenv("BRAND_MIN_COHORT", "10")
    monkeypatch.setenv("CORS_ORIGINS", "http://localhost:5173")
    reset_settings_cache()
    settings = get_settings()
    reset_engine(settings.database_url)
    Base.metadata.create_all(get_engine())
    with session_scope() as db:
        seed.seed_all(db, settings)
    yield settings
    reset_settings_cache()
    engine = get_engine()
    engine.dispose()


@pytest.fixture()
def db(app_settings):
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def api(app_settings):
    from fastapi.testclient import TestClient

    from app.main import create_app

    app = create_app(app_settings)
    with TestClient(app) as client:
        yield client


@pytest.fixture()
def client_factory(app_settings):
    """Build additional clients (used to simulate a restart against the same DB)."""
    from fastapi.testclient import TestClient

    from app.main import create_app

    created = []

    def factory():
        client = TestClient(create_app(app_settings))
        client.__enter__()
        created.append(client)
        return client

    yield factory
    for client in created:
        client.__exit__(None, None, None)


def _login(api, persona: str) -> dict[str, str]:
    response = api.post("/api/v1/auth/demo-session", json={"persona_code": persona})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['token']}"}


@pytest.fixture()
def tokens(api) -> dict[str, str]:
    return {
        persona: _login(api, persona)["Authorization"].split(" ", 1)[1]
        for persona in ("consumer_a", "consumer_b", "staff", "brand")
    }


@pytest.fixture()
def as_a(tokens) -> dict[str, str]:
    return {"Authorization": f"Bearer {tokens['consumer_a']}"}


@pytest.fixture()
def as_b(tokens) -> dict[str, str]:
    return {"Authorization": f"Bearer {tokens['consumer_b']}"}


@pytest.fixture()
def as_staff(tokens) -> dict[str, str]:
    return {"Authorization": f"Bearer {tokens['staff']}"}


@pytest.fixture()
def as_brand(tokens) -> dict[str, str]:
    return {"Authorization": f"Bearer {tokens['brand']}"}


@pytest.fixture()
def demo_screenshot() -> bytes:
    return (DEMO_DIR / "demo_order_screenshot_1.png").read_bytes()


@pytest.fixture()
def demo_screenshot_2() -> bytes:
    return (DEMO_DIR / "demo_order_screenshot_2.png").read_bytes()
