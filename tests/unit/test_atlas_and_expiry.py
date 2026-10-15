"""Unit tests: atlas wording rules, life extensions and expiry/PAO rules."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.services import atlas as atlas_service  # noqa: E402
from app.services import cabinet as cabinet_service  # noqa: E402
from app.services.errors import ValidationError  # noqa: E402


@pytest.mark.parametrize(
    "text",
    [
        "你对烟酰胺过敏",
        "这个成分导致你的刺痛",
        "建议避免含水杨酸的成分",
        "可以确诊为接触性皮炎",
    ],
)
def test_forbidden_assertions_are_detected(text):
    assert atlas_service.assert_allowed_wording(text)


@pytest.mark.parametrize(
    "text",
    [
        "你的反馈中，含此成分的产品出现了 3 次负面体验",
        "此成分与你的负面反馈有统计关联，但不代表因果关系",
        "该成分的功效来自已审核来源",
    ],
)
def test_allowed_wording_passes(text):
    assert atlas_service.assert_allowed_wording(text) == []


@pytest.mark.parametrize(
    "text",
    ["多吃含此成分的食物对皮肤好", "该食物可以替代外用产品"],
)
def test_forbidden_life_extension_wording(text):
    assert atlas_service.check_life_extension_text(text)


def test_signal_statement_uses_counts_and_never_causality():
    negative = atlas_service._signal_statement(0, 3)
    both = atlas_service._signal_statement(4, 2)
    assert "出现了 3 次负面体验" in negative
    assert "不代表因果关系" in negative
    assert "不代表因果关系" in both
    assert atlas_service.assert_allowed_wording(negative) == []
    assert atlas_service.assert_allowed_wording(both) == []


def test_ensure_profile_defaults_to_insufficient(db):
    profile = atlas_service.ensure_profile(db, "Unknown-Inci-Xyz", "未审核成分")
    assert profile.approval_status == "insufficient"
    assert profile.known_effects == []
    assert profile.irritant_level == "unknown"
    assert atlas_service.serialize_profile(db, profile)["data_status"] == "insufficient"


def _owned(**kwargs):
    from app.models import OwnedProduct

    base = dict(
        tenant_id="t",
        user_id="u",
        custom_name="x",
        lifecycle_status="opened",
        usage_status="active",
        expiry_source="unknown",
    )
    base.update(kwargs)
    return OwnedProduct(**base)


def test_expiry_is_unknown_without_evidence():
    product = _owned()
    assessment = cabinet_service.assess_expiry(product)
    assert assessment.effective_expiry is None
    assert assessment.source == "unknown"
    assert assessment.unknown_reason


def test_pao_requires_both_opened_date_and_months():
    opened = datetime(2026, 1, 1, tzinfo=timezone.utc)
    without_pao = _owned(opened_date=opened, pao_months=None)
    assert cabinet_service.assess_expiry(without_pao).effective_expiry is None

    with_pao = _owned(opened_date=opened, pao_months=6)
    assessment = cabinet_service.assess_expiry(with_pao)
    assert assessment.effective_expiry is not None
    assert assessment.source == "pao_derived"
    assert assessment.effective_expiry > opened


def test_the_earliest_known_constraint_wins():
    product = _owned(
        expiry_date=datetime(2026, 3, 1, tzinfo=timezone.utc),
        expiry_source="packaging",
        opened_date=datetime(2025, 12, 1, tzinfo=timezone.utc),
        pao_months=3,
    )
    assessment = cabinet_service.assess_expiry(product)
    assert assessment.effective_expiry == datetime(2026, 3, 1, tzinfo=timezone.utc)
    assert assessment.source == "pao_derived" or assessment.source == "packaging"
    assert [c["source"] for c in assessment.candidates] == ["packaging", "pao_derived"]


def test_invalid_lifecycle_state_is_rejected(api, as_a):
    response = api.post(
        "/api/v1/owned-products",
        json={"custom_name": "x", "lifecycle_status": "not-a-state", "usage_status": "active"},
        headers=as_a,
    )
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"

    response = api.post(
        "/api/v1/owned-products",
        json={"custom_name": "x", "lifecycle_status": "opened", "usage_status": "not-a-state"},
        headers=as_a,
    )
    assert response.status_code == 422


def test_approved_ingredient_without_resolvable_sources_degrades_to_insufficient(db):
    """An 'approved' profile whose sources cannot be resolved must not emit a claim."""
    profile = atlas_service.ensure_profile(db, "Broken-Source-Inci", "来源不可解析成分")
    profile.approval_status = "approved"
    profile.irritant_level = "high"
    profile.source_ids = ["00000000-0000-0000-0000-000000000000"]
    profile.known_effects = [
        {"text": "未解析的功效主张", "source_id": "00000000-0000-0000-0000-000000000000"}
    ]
    profile.irritant_notes = [
        {"text": "未解析的致敏主张", "source_id": "00000000-0000-0000-0000-000000000000"}
    ]
    db.flush()

    serialized = atlas_service.serialize_profile(db, profile)
    assert serialized["data_status"] == "insufficient"
    assert serialized["data_note"] == "暂无充分信息"
    assert serialized["known_effects"] == []
    assert serialized["irritancy"]["notes"] == []
    assert serialized["irritancy"]["level"] == "unknown"
