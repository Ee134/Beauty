"""Integration: full end-to-end flows across the API, plus restart and idempotency."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from helpers import (  # noqa: E402
    add_owned,
    authorize_services,
    cabinet_named,
    catalog_id_for,
    chat,
    owned_products,
    run_tick,
    upload,
)


def test_full_demo_flow(api, as_a, as_staff, demo_screenshot, client_factory):
    """import -> plan -> accept -> feedback -> review -> handoff -> staff -> progress."""
    # 1. import a demo screenshot and confirm after correcting a value
    batch = upload(api, as_a, demo_screenshot, "demo_order_screenshot_1.png").json()
    items = [
        {
            "raw_name": candidate["raw_name"],
            "custom_name": candidate["raw_name"],
            "quantity": 1 if index == 0 else 1,
            "catalog_product_id": candidate["catalog_product_id"],
        }
        for index, candidate in enumerate(batch["candidates"])
    ]
    confirmed = api.post(f"/api/v1/imports/{batch['id']}/confirm", json={"items": items}, headers=as_a)
    assert confirmed.status_code == 200
    created = confirmed.json()["created"]
    assert len(created) == 2
    sunscreen = next(p for p in created if "防晒" in p["custom_name"])

    # 2. read the product page: sources are version matched and demo labelled
    detail = api.get(f"/api/v1/owned-products/{sunscreen['id']}", headers=as_a).json()
    assert detail["sources"], "an approved product must expose its citations"
    assert all(source["is_demo"] for source in detail["sources"])

    # 3. generate and accept a plan
    draft = api.post("/api/v1/routines/drafts", json={"trigger": "demo"}, headers=as_a).json()["plan"]
    assert draft["status"] == "draft"
    assert any(step["owned_product_id"] == sunscreen["id"] for step in draft["steps"])
    accepted = api.post(
        f"/api/v1/routines/{draft['id']}/accept",
        json={"expected_version": draft["version"]},
        headers=as_a,
    )
    assert accepted.status_code == 200
    assert api.get("/api/v1/routines", headers=as_a).json()["active"]["version"] == draft["version"]

    # 4. report a negative experience on a planned product
    outcome = chat(api, as_a, f"昨晚用了{sunscreen['custom_name']}之后有点刺痛")
    assert outcome.status_code == 200, outcome.text
    cards = {card["type"] for card in outcome.json()["output"]["cards"]}
    assert {"audit_summary", "review_prompt"} <= cards
    prompt = next(c for c in outcome.json()["output"]["cards"] if c["type"] == "review_prompt")

    # 5. the review only creates a draft
    decision = api.post(
        f"/api/v1/review-prompts/{prompt['entity_id']}/decision", json={"action": "pause"}, headers=as_a
    ).json()
    assert decision["draft_created"] is True and decision["plan_changed"] is False
    new_draft = decision["plan"]
    assert all(step["owned_product_id"] != sunscreen["id"] for step in new_draft["steps"])

    # 6. handoff preview, user confirms the record selection, then submits
    candidates = api.get("/api/v1/handoffs/candidates", headers=as_a).json()
    selected = [r["id"] for r in candidates["records"] if r["type"] in {"usage_event", "memory_record"}][:3]
    handoff = api.post(
        "/api/v1/handoffs/drafts",
        json={"record_ids": selected, "request": "防晒乳刺痛问题，希望人工确认"},
        headers=as_a,
    ).json()["ticket"]
    assert handoff["status"] == "draft"
    submitted = api.post(
        f"/api/v1/handoffs/{handoff['id']}/submit",
        json={"expected_version": handoff["version"]},
        headers=as_a,
    )
    assert submitted.status_code == 200
    assert submitted.json()["ticket"]["adapter_mode"] == "local_demo"

    # 7. the staff console sees it and updates the status
    queue = api.get("/api/v1/staff/tickets", headers=as_staff).json()
    assert any(t["id"] == handoff["id"] for t in queue["tickets"])
    updated = api.patch(
        f"/api/v1/staff/tickets/{handoff['id']}",
        json={"status": "resolved", "note": "已提供一般性建议"},
        headers=as_staff,
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["ticket"]["status"] == "resolved"
    assert updated.json()["ticket"]["user_confirmed_resolution"] is False

    # 8. a new conversation asks about progress: the real status is returned
    progress = chat(api, as_a, "我上次那个工单现在怎么样了？")
    answer = progress.json()["output"]["answer"]
    assert "resolved" in answer or "已解决" in answer or "状态" in answer
    assert "品牌已收到" not in answer

    # 9. the user confirms whether it is actually resolved
    confirmed_resolution = api.post(
        f"/api/v1/tickets/{handoff['id']}/resolution",
        json={"resolved": False, "note": "还是有点刺痛"},
        headers=as_a,
    ).json()["ticket"]
    assert confirmed_resolution["user_confirmed_resolution"] is False
    assert confirmed_resolution["status"] == "in_review"

    # 10. export contains everything and no secrets
    export = api.get("/api/v1/privacy/export", headers=as_a).json()
    assert export["owned_products"] and export["usage_events"] and export["routine_plans"]
    assert "api_key" not in str(export).lower()

    # 11. data survives a restart
    restarted = client_factory()
    token = restarted.post("/api/v1/auth/demo-session", json={"persona_code": "consumer_a"}).json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    counts = restarted.get("/api/v1/me", headers=headers).json()["counts"]
    assert counts["owned_products"] == len(owned_products(api, as_a))
    assert counts["active_plan_version"] == draft["version"]


def test_chat_idempotency_replays_the_same_run(api, as_a, db):
    from sqlalchemy import select

    from app.models import AgentRun, Message

    key = "idem-turn-0001"
    first = chat(api, as_a, "我的计划怎么安排？", idem=key)
    assert first.status_code == 200, first.text
    runs_after_first = len(list(db.execute(select(AgentRun)).scalars()))
    messages_after_first = len(list(db.execute(select(Message)).scalars()))

    second = chat(api, as_a, "我的计划怎么安排？", idem=key)
    assert second.status_code == 200
    assert second.json()["output"]["run_id"] == first.json()["output"]["run_id"]
    db.expire_all()
    assert len(list(db.execute(select(AgentRun)).scalars())) == runs_after_first
    assert len(list(db.execute(select(Message)).scalars())) == messages_after_first


def test_plan_draft_uses_the_request_scoped_context(api, as_a):
    """A draft must not reference products that were never in the cabinet."""
    before = {p["id"] for p in owned_products(api, as_a)}
    draft = api.post("/api/v1/routines/drafts", json={}, headers=as_a).json()["plan"]
    referenced = {step["owned_product_id"] for step in draft["steps"] if step["owned_product_id"]}
    assert referenced <= before
    pending = {p["owned_product_id"] for p in draft["pending_products"]}
    assert not (referenced & pending), "a product is either planned or pending, never both"


def test_live_model_without_credentials_reports_unavailable(api, as_a):
    from app.config import Settings
    from app.providers.model import OpenAICompatibleProvider
    from app.services.errors import ModelUnavailableError

    provider = OpenAICompatibleProvider(
        Settings(MODEL_MODE="live", MODEL_PROVIDER="openai_compatible", MODEL_NAME="", API_BASE="", API_KEY="")
    )
    assert provider.available is False
    with pytest.raises(ModelUnavailableError):
        provider.complete_json(
            system_prompt="s", user_payload={}, schema_name="PlannerOutput", schema={}
        )


def test_trigger_rules_are_labelled_as_demo_rules(api, as_a):
    rules = api.get("/api/v1/trigger-rules", headers=as_a).json()["rules"]
    assert rules
    for rule in rules:
        assert rule["threshold_source"] == "demo_rule"
        assert rule["approval_status"] == "demo"
        assert rule["notes"], "a demo threshold must explain its status"


def test_environment_snapshot_carries_provenance(api, as_a):
    env = api.get("/api/v1/environment", headers=as_a).json()
    current = env["current"]
    for field in ("provider", "mode", "issued_at", "fetched_at", "valid_from", "valid_to", "timezone", "units"):
        assert current[field] is not None, field
    assert current["units"]["temperature"] == "°C"
    assert current["units"]["wind_speed"] == "m/s"
    assert env["is_demo"] is True


def test_scheduler_tick_produces_auditable_decisions(api, as_a):
    authorize_services(api, as_a, ["travel_support"], daily_cap=5)
    api.post(
        "/api/v1/activities",
        json={
            "activity_type": "trip",
            "title": "出差",
            "starts_at": (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat(),
            "destination_city_id": "CN-BJ",
            "user_confirmed": True,
        },
        headers=as_a,
    )
    tick = run_tick(api, as_a)
    assert tick["summary"]["decisions"]
    assert tick["summary"]["outbox"]
    decisions = api.get("/api/v1/admin/proactive-decisions", headers=as_a).json()["decisions"]
    assert decisions
    for decision in decisions:
        assert decision["reason_codes"]
        assert decision["rule_version"].startswith("demo-v")
        assert "score" not in decision or decision["score"] is None


def test_clock_shift_is_marked_everywhere(api, as_a):
    shifted = api.post("/api/v1/admin/clock", json={"mode": "demo", "day": 5}, headers=as_a)
    assert shifted.status_code == 200, shifted.text
    assert shifted.json()["clock"]["is_demo_time"] is True
    assert "第 5 天" in shifted.json()["clock"]["label"]

    me = api.get("/api/v1/me", headers=as_a).json()
    assert me["clock"]["is_demo_time"] is True
    response = chat(api, as_a, "现在的计划是什么")
    assert response.json()["output"]["clock"]["is_demo_time"] is True

    api.post("/api/v1/admin/clock", json={"mode": "real"}, headers=as_a)
    assert api.get("/api/v1/me", headers=as_a).json()["clock"]["is_demo_time"] is False


def test_scheduler_survives_restart_without_duplicate_inbox(api, as_a, client_factory):
    authorize_services(api, as_a, ["travel_support"], daily_cap=5)
    api.post(
        "/api/v1/activities",
        json={
            "activity_type": "trip",
            "title": "出差",
            "starts_at": (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat(),
            "destination_city_id": "CN-SH",
            "user_confirmed": True,
        },
        headers=as_a,
    )
    first = run_tick(api, as_a)
    assert len(first["summary"]["outbox"]) == 1
    status = api.get("/api/v1/admin/scheduler/status", headers=as_a).json()
    assert status["outbox"]

    restarted = client_factory()
    token = restarted.post("/api/v1/auth/demo-session", json={"persona_code": "consumer_a"}).json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    second = run_tick(restarted, headers)
    assert second["summary"]["outbox"] == []
    assert len(restarted.get("/api/v1/messages", headers=headers).json()["messages"]) == 1


def test_uploaded_screenshot_is_deleted_after_the_retention_window(api, as_a, demo_screenshot, db, app_settings):
    """Screenshots are deleted after confirmation + IMPORT_RETENTION_HOURS (configurable)."""
    from datetime import timedelta

    from app.models import ImportBatch

    batch = upload(api, as_a, demo_screenshot, "demo_order_screenshot_1.png").json()
    items = [{"raw_name": c["raw_name"], "quantity": 1, "catalog_product_id": c["catalog_product_id"]} for c in batch["candidates"]]
    api.post(f"/api/v1/imports/{batch['id']}/confirm", json={"items": items}, headers=as_a)

    row = db.get(ImportBatch, batch["id"])
    db.refresh(row)
    storage_key = row.storage_key
    assert storage_key, "the upload must be stored until the retention window passes"
    path = Path(app_settings.upload_dir) / storage_key
    assert path.exists()

    row.confirmed_at = row.confirmed_at - timedelta(hours=app_settings.import_retention_hours + 1)
    db.commit()

    run_tick(api, as_a)
    db.expire_all()
    refreshed = db.get(ImportBatch, batch["id"])
    assert refreshed.storage_key is None
    assert refreshed.file_deleted_at is not None
    assert not path.exists(), "the uploaded file must be removed from disk"

    serialized = api.get(f"/api/v1/imports/{batch['id']}", headers=as_a).json()
    assert serialized["file_deleted_at"] is not None
    assert serialized["raw_text"], "the confirmed source summary is kept, the image is not"


def test_restore_history_creates_a_new_draft(api, as_a):
    first = api.post("/api/v1/routines/drafts", json={}, headers=as_a).json()["plan"]
    api.post(f"/api/v1/routines/{first['id']}/accept", json={"expected_version": first["version"]}, headers=as_a)
    second = api.post("/api/v1/routines/drafts", json={}, headers=as_a).json()["plan"]
    api.post(f"/api/v1/routines/{second['id']}/accept", json={"expected_version": second["version"]}, headers=as_a)

    restored = api.post(f"/api/v1/routines/{first['id']}/restore", headers=as_a)
    assert restored.status_code == 201, restored.text
    plan = restored.json()["plan"]
    assert plan["status"] == "draft"
    assert plan["version"] > second["version"]
    assert any(r["type"] == "restored_from_history" for r in plan["reasons"])
    # the historical version is untouched and still active until the draft is accepted
    assert api.get("/api/v1/routines", headers=as_a).json()["active"]["id"] == second["id"]


def test_combination_choice_keep_changes_nothing_and_remove_creates_a_draft(api, as_a):
    active = api.get("/api/v1/routines", headers=as_a).json()["active"]
    assert active["combination_notes"], "the seeded cabinet shares an active ingredient"

    keep = api.post("/api/v1/combinations/choice", json={"note_index": 0, "choice": "keep"}, headers=as_a)
    assert keep.status_code == 200, keep.text
    assert keep.json()["plan_changed"] is False
    assert api.get("/api/v1/routines", headers=as_a).json()["active"]["version"] == active["version"]

    product_id = active["combination_notes"][0]["owned_product_ids"][0]
    removed = api.post(
        "/api/v1/combinations/choice",
        json={"note_index": 0, "choice": "remove_one", "owned_product_id": product_id},
        headers=as_a,
    )
    assert removed.status_code == 200, removed.text
    body = removed.json()
    assert body["draft_created"] is True and body["plan_changed"] is False
    assert all(step["owned_product_id"] != product_id for step in body["plan"]["steps"])
    assert api.get("/api/v1/routines", headers=as_a).json()["active"]["version"] == active["version"]


def test_atlas_latest_requires_an_explicit_view(api, as_a):
    before = api.get("/api/v1/ingredients/atlas/latest", headers=as_a).json()
    assert before["view"] is None, "the atlas must not be generated implicitly"
    generated = api.get("/api/v1/ingredients/atlas", headers=as_a).json()
    after = api.get("/api/v1/ingredients/atlas/latest", headers=as_a).json()
    assert after["view"]["version"] >= 1
    assert after["payload"]["stats"] == generated["stats"]


def test_owned_product_update_conflicts_on_version(api, as_a):
    product = owned_products(api, as_a)[0]
    ok = api.patch(
        f"/api/v1/owned-products/{product['id']}",
        json={"usage_status": "paused", "expected_version": product["version"]},
        headers=as_a,
    )
    assert ok.status_code == 200
    stale = api.patch(
        f"/api/v1/owned-products/{product['id']}",
        json={"usage_status": "active", "expected_version": product["version"]},
        headers=as_a,
    )
    assert stale.status_code == 409
    assert stale.json()["code"] == "VERSION_CONFLICT"
    assert api.get(f"/api/v1/owned-products/{product['id']}", headers=as_a).json()["usage_status"] == "paused"


def test_handoff_submit_is_idempotent_and_version_checked(api, as_a):
    records = api.get("/api/v1/handoffs/candidates", headers=as_a).json()["default_selection"]
    ticket = api.post(
        "/api/v1/handoffs/drafts",
        json={"record_ids": records[:1], "request": "确认之前的刺痛问题"},
        headers=as_a,
    ).json()["ticket"]
    submitted = api.post(
        f"/api/v1/handoffs/{ticket['id']}/submit",
        json={"expected_version": ticket["version"]},
        headers={**as_a, "Idempotency-Key": "handoff-1"},
    )
    assert submitted.status_code == 200
    replay = api.post(
        f"/api/v1/handoffs/{ticket['id']}/submit",
        json={"expected_version": ticket["version"]},
        headers={**as_a, "Idempotency-Key": "handoff-1"},
    )
    assert replay.status_code == 409, "a submitted draft cannot be submitted twice"
    assert replay.json()["code"] == "VERSION_CONFLICT"


def test_notification_preferences_reject_unconfigured_external_push(api, as_a):
    denied = api.put(
        "/api/v1/notification-preferences",
        json={"channels": ["in_app", "web_push"]},
        headers=as_a,
    )
    assert denied.status_code == 422
    assert denied.json()["code"] == "VALIDATION_ERROR"

    allowed = api.put(
        "/api/v1/notification-preferences",
        json={"channels": ["in_app", "web_push"], "external_push_enabled": True},
        headers=as_a,
    )
    assert allowed.status_code == 200, allowed.text
    channels = api.get("/api/v1/notification-preferences", headers=as_a).json()["channels"]
    assert channels["web_push"]["mode"] in {"mock", "disabled", "live"}
    assert channels["native_push"]["available"] is False
