"""Plain test helpers (no pytest fixtures) shared by the AC suites."""

from __future__ import annotations

import io
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "backend") not in sys.path:
    sys.path.insert(0, str(ROOT / "backend"))

from app.db import get_session_factory  # noqa: E402


def owned_products(api, headers) -> list[dict[str, Any]]:
    response = api.get("/api/v1/owned-products", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()["products"]


def cabinet_named(api, headers, name: str) -> dict[str, Any]:
    for product in owned_products(api, headers):
        if product["custom_name"] == name:
            return product
    raise AssertionError(f"{name} not in cabinet")


def catalog_id_for(formula_fragment: str) -> str:
    from sqlalchemy import select

    from app.models import CatalogProduct

    session = get_session_factory()()
    try:
        rows = list(session.execute(select(CatalogProduct)).scalars())
        for row in rows:
            if row.formula_version and formula_fragment in row.formula_version:
                return row.id
        raise AssertionError(f"catalog product {formula_fragment} not found")
    finally:
        session.close()


def add_owned(api, headers, name: str, **extra) -> dict[str, Any]:
    payload = {"custom_name": name, "lifecycle_status": "opened", "usage_status": "active"}
    payload.update(extra)
    response = api.post("/api/v1/owned-products", json=payload, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def run_tick(api, headers, expect: int = 200) -> dict[str, Any]:
    response = api.post("/api/v1/admin/scheduler/tick", headers=headers)
    assert response.status_code == expect, response.text
    return response.json()


def set_weather_scenario(api, headers, name: str) -> None:
    response = api.post("/api/v1/admin/weather-scenario", json={"name": name}, headers=headers)
    assert response.status_code == 200, response.text


def authorize_services(api, headers, services: list[str], **extra) -> dict[str, Any]:
    """Authorize service types with a deterministic (always open) quiet window.

    Tests that specifically exercise quiet hours override these two fields.
    """
    payload: dict[str, Any] = {
        "service_types": services,
        "daily_cap": 10,
        "quiet_hours_start": "00:00",
        "quiet_hours_end": "00:00",
    }
    payload.update(extra)
    response = api.put("/api/v1/notification-preferences", json=payload, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()["preferences"]


def make_png(text: str = "demo") -> bytes:
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (320, 120), "white")
    ImageDraw.Draw(image).text((10, 40), text, fill="black")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def upload(api, headers, data: bytes, filename: str = "shot.png", mime: str = "image/png"):
    return api.post(
        "/api/v1/imports",
        headers=headers,
        files={"file": (filename, data, mime)},
    )


def chat(api, headers, message: str, session_id: str | None = None, idem: str | None = None):
    body: dict[str, Any] = {"message": message}
    if session_id:
        body["session_id"] = session_id
    extra = {"Idempotency-Key": idem} if idem else {}
    return api.post("/api/v1/chat/messages", json=body, headers={**headers, **extra})


def plan_count() -> int:
    from sqlalchemy import select

    from app.models import RoutinePlan

    session = get_session_factory()()
    try:
        return len(list(session.execute(select(RoutinePlan)).scalars()))
    finally:
        session.close()


def agent_run_count() -> int:
    from sqlalchemy import select

    from app.models import AgentRun

    session = get_session_factory()()
    try:
        return len(list(session.execute(select(AgentRun)).scalars()))
    finally:
        session.close()
