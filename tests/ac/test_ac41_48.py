"""AC41–AC48: ingredient atlas, combination reasoning and life-scenario extensions."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from helpers import add_owned, cabinet_named, catalog_id_for, chat, owned_products, plan_count  # noqa: E402


def make_event(api, headers, product_id: str, text: str, event_type: str, days_ago: int = 1):
    response = api.post(
        "/api/v1/usage-events",
        json={
            "reported_text": text,
            "owned_product_ids": [product_id],
            "occurred_at": (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat(),
            "time_precision": "day",
            "event_type": event_type,
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()["event"]


def atlas(api, headers, min_events: int = 3):
    response = api.get("/api/v1/ingredients/atlas", params={"min_events": min_events}, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def card_for(payload, common_name: str):
    return next((c for c in payload["cards"] if c["common_name"] == common_name), None)


# --- AC41 / AC42 ---------------------------------------------------------------


def test_ac41_shared_active_ingredient_is_reported_with_sources(api, as_a):
    draft = api.post("/api/v1/routines/drafts", json={}, headers=as_a).json()
    notes = draft["plan"]["combination_notes"]
    shared = [n for n in notes if n["type"] == "shared_active"]
    assert shared, notes
    note = shared[0]
    assert note["ingredient_inci"] == "Demo Clarify Acid"
    assert len(note["owned_product_ids"]) >= 3, "three or more cabinet products share the active"
    assert note["citation_ids"], "every combination note needs an approved source"
    assert note["decided_by_system"] is False
    assert set(note["options"]) == {"keep", "space_out", "remove_one"}

    # the wording offers information and a choice, it does not decide for the user
    for forbidden in ("不能叠用", "禁止", "必须停用", "确定冲突"):
        assert forbidden not in note["text"]
    assert "可能增加刺激风险" in note["text"]
    assert "不判定" in note["text"]

    # every citation resolves to an approved source of the right product
    for citation_id in note["citation_ids"]:
        source = api.get(f"/api/v1/sources/{api_citation_source(api, as_a, citation_id)}", headers=as_a)
        assert source.status_code == 200, source.text
        assert source.json()["status"] == "approved"
        assert source.json()["is_demo"] is True
    combinations = api.get("/api/v1/combinations", headers=as_a).json()
    assert combinations["combination_notes"]


def api_citation_source(api, headers, citation_id: str) -> str:
    from app.db import get_session_factory
    from app.models import KnowledgeChunk

    session = get_session_factory()()
    try:
        chunk = session.get(KnowledgeChunk, citation_id)
        assert chunk is not None, f"citation {citation_id} must resolve to a real chunk"
        return chunk.source_id
    finally:
        session.close()


def test_ac42_product_without_ingredient_sources_is_pending_and_excluded(api, as_a):
    draft = api.post("/api/v1/routines/drafts", json={}, headers=as_a).json()
    pending = draft["plan"]["pending_products"]
    missing = [p for p in pending if p["reason"] in {"SOURCE_MISSING", "SOURCE_CONFLICT"}]
    assert missing, pending
    excluded_ids = {p["owned_product_id"] for p in missing}
    for note in draft["plan"]["combination_notes"]:
        assert not (set(note.get("owned_product_ids") or []) & excluded_ids)

    combinations = api.get("/api/v1/combinations", headers=as_a).json()
    product = next(p for p in combinations["products"] if p["owned_product_id"] in excluded_ids)
    assert product["key_actives"] == [], "no ingredient may be invented for an unsourced product"
    assert product["ingredient_source_status"] == "missing"

    detail = api.get(f"/api/v1/owned-products/{product['owned_product_id']}", headers=as_a).json()
    assert detail["knowledge"]["has_approved_sources"] is False
    assert "没有已审核" in detail["knowledge"]["message"]


# --- AC43 / AC44 ---------------------------------------------------------------


def test_ac43_negative_feedback_only_creates_a_review_question(api, as_a):
    product = cabinet_named(api, as_a, "澄泉平衡爽肤水")
    before_plans = plan_count()
    response = api.post(
        "/api/v1/usage-events",
        json={
            "reported_text": "昨晚用了平衡爽肤水之后有刺痛",
            "owned_product_ids": [product["id"]],
            "occurred_at": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),
            "time_precision": "day",
        },
        headers=as_a,
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["review_prompt"] is not None
    assert body["review_prompt"]["options"] == ["pause", "keep", "adjust"]
    assert plan_count() == before_plans, "a report must not create a new plan by itself"

    current = api.get("/api/v1/routines", headers=as_a).json()
    assert current["active"]["version"] == 1
    assert current["active"]["status"] == "active"
    still_in_plan = any(
        step["owned_product_id"] == product["id"] for step in current["active"]["steps"]
    )
    assert still_in_plan, "the step must not be removed automatically"
    detail = api.get(f"/api/v1/owned-products/{product['id']}", headers=as_a).json()
    assert detail["usage_status"] == "active", "the product must not be paused automatically"
    assert detail["review_flag"] is True


def test_ac44_confirming_pause_then_accepting_creates_v_plus_1(api, as_a, db):
    from app.models import RoutinePlan, UsageEvent

    product = cabinet_named(api, as_a, "澄泉修护晚霜")
    created = api.post(
        "/api/v1/usage-events",
        json={
            "reported_text": "用了修护晚霜之后有点刺痛",
            "owned_product_ids": [product["id"]],
            "occurred_at": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),
            "time_precision": "day",
        },
        headers=as_a,
    ).json()["review_prompt"]
    old_plan = api.get("/api/v1/routines", headers=as_a).json()["active"]

    decision = api.post(
        f"/api/v1/review-prompts/{created['id']}/decision", json={"action": "pause"}, headers=as_a
    )
    assert decision.status_code == 200, decision.text
    body = decision.json()
    assert body["plan_changed"] is False, "the pause only produces a draft"
    assert body["draft_created"] is True
    draft = body["plan"]
    assert draft["status"] == "draft"
    assert draft["version"] == old_plan["version"] + 1
    assert all(step["owned_product_id"] != product["id"] for step in draft["steps"])
    assert api.get("/api/v1/routines", headers=as_a).json()["active"]["version"] == old_plan["version"]

    accepted = api.post(
        f"/api/v1/routines/{draft['id']}/accept",
        json={"expected_version": draft["version"]},
        headers=as_a,
    )
    assert accepted.status_code == 200, accepted.text
    routines = api.get("/api/v1/routines", headers=as_a).json()
    assert routines["active"]["version"] == draft["version"]
    assert all(step["owned_product_id"] != product["id"] for step in routines["active"]["steps"])
    history = {p["id"]: p["status"] for p in routines["history"]}
    assert history[old_plan["id"]] == "superseded"

    events = api.get("/api/v1/usage-events", headers=as_a).json()["events"]
    assert any("用了修护晚霜之后有点刺痛" == e["reported_text"] for e in events), "feedback stays in memory"
    kept = list(db.execute(select(UsageEvent)).scalars())
    assert len([e for e in kept if e.reported_text == "用了修护晚霜之后有点刺痛"]) == 1


# --- AC45 / AC46 ---------------------------------------------------------------


def test_ac45_below_threshold_shows_insufficient_sample(api, as_b):
    payload = atlas(api, as_b)
    assert payload["cards"] == [], "one feedback event is below the minimum sample"
    assert payload["below_threshold"], payload
    entry = payload["below_threshold"][0]
    assert entry["min_events"] == 3
    assert entry["positive_count"] + entry["negative_count"] < 3
    assert "样本不足" in entry["message"]

    catalog = atlas(api, as_b, min_events=1)
    assert catalog["cards"], "with a lower threshold the signal appears"


def test_ac46_ingredient_without_approved_sources_shows_no_claims(api, as_a):
    product = add_owned(
        api, as_a, "澄泉维C亮肤精华", catalog_product_id=catalog_id_for("DEMO-SR-06-v1"), match_status="matched"
    )
    for index in range(3):
        make_event(api, as_a, product["id"], f"用了维C精华第 {index + 1} 次，皮肤状态不错", "positive", index + 1)

    payload = atlas(api, as_a)
    mystic = card_for(payload, "澄泉神秘提取物")
    assert mystic is not None, payload["stats"]
    assert mystic["data_status"] == "insufficient"
    assert mystic["data_note"] == "暂无充分信息"
    assert mystic["known_effects"] == []
    assert mystic["irritancy"]["notes"] == []
    assert mystic["irritancy"]["level"] == "unknown"
    assert mystic["uncertainty"] and mystic["disclaimer"]

    conflicting = card_for(payload, "澄泉琥珀活性物")
    assert conflicting is not None
    assert conflicting["data_status"] == "pending_review"
    assert conflicting["data_note"] == "信息存在冲突，待审核"
    assert conflicting["known_effects"] == [], "a conflicted ingredient must not pick a side"

    profile = api.get(f"/api/v1/ingredients/{mystic['ingredient_id']}", headers=as_a).json()
    assert profile["data_status"] == "insufficient"
    assert profile["known_effects"] == []


# --- AC47 / AC48 ---------------------------------------------------------------


def test_ac47_deleting_a_report_invalidates_the_signal_and_the_atlas(api, as_a, db, client_factory):
    from app.models import UserIngredientSignal

    before = atlas(api, as_a)
    clarisy = card_for(before, "澄泉净澈酸")
    assert clarisy is not None
    assert clarisy["user_signal"]["negative_count"] >= 3
    negative_event_id = clarisy["user_signal"]["negative_event_ids"][0]

    deleted = api.delete(f"/api/v1/usage-events/{negative_event_id}", headers=as_a)
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["derived_invalidated"]["signals"] >= 1

    db.expire_all()
    signals = list(db.execute(select(UserIngredientSignal)).scalars())
    invalidated = [s for s in signals if s.invalidated_at is not None]
    assert invalidated, "the signal depending on the deleted event must be invalidated"

    after = atlas(api, as_a)
    remaining = card_for(after, "澄泉净澈酸")
    if remaining is not None:
        assert negative_event_id not in remaining["user_signal"]["negative_event_ids"]
        assert remaining["user_signal"]["negative_count"] < 3 or remaining["data_status"] == "approved"
    assert negative_event_id not in str(after["cards"])

    # the deletion survives a restart
    restarted = client_factory()
    token = restarted.post("/api/v1/auth/demo-session", json={"persona_code": "consumer_a"}).json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    events = restarted.get("/api/v1/usage-events", headers=headers).json()["events"]
    assert negative_event_id not in {e["id"] for e in events}
    fresh = atlas(restarted, headers)
    assert negative_event_id not in str(fresh["cards"]) + str(fresh["below_threshold"])


def test_ac48_life_extension_without_an_approved_source_is_not_shown(api, as_a):
    payload = atlas(api, as_a)
    dropped = payload["dropped_life_extensions"]
    assert any(d["reason"] == "SOURCE_NOT_APPROVED" for d in dropped), dropped
    forbidden_text = "多吃含此成分的食物对皮肤好"
    assert any(d["text"] == forbidden_text for d in dropped)
    assert forbidden_text not in str(payload["cards"])

    clarisy = card_for(payload, "澄泉净澈酸")
    assert clarisy is not None
    assert all(ext["kind"] != "diet" for ext in clarisy["life_extensions"])

    # a source backed extension is shown with its notice
    retinol = card_for(payload, "澄泉类视黄醇酯")
    assert retinol is not None
    assert retinol["life_extensions"], "the reviewed sun-care extension must be shown"
    for extension in retinol["life_extensions"]:
        assert extension["notice"] == "此延伸基于已审核来源，非个人诊断"
        assert extension["citation"]["source_id"]
