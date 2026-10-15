"""Unit tests: knowledge retrieval, citation validation and product matching."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.knowledge import service as knowledge  # noqa: E402


def test_tokenizer_handles_cjk_and_latin():
    tokens = knowledge.tokenize("Niacinamide 烟酰胺 SPF50 每日一次")
    assert "niacinamide" in tokens
    assert "烟" in tokens and "酰胺" in tokens
    assert "spf50" in tokens or "50" in tokens


def test_normalize_name_ignores_spacing_and_brackets():
    assert knowledge.normalize_name("澄泉 光感-精华（30ml）") == knowledge.normalize_name("澄泉光感精华30ml")


def test_search_returns_only_approved_sources(api, as_a, db):
    from app.models import KnowledgeSource

    catalog_id = _catalog_id("DEMO-SR-03-v2")
    results = knowledge.search(db, "使用方法", product_ids=[catalog_id], limit=5)
    assert results, "approved usage instructions must be retrievable"
    for result in results:
        source = db.get(KnowledgeSource, result["citation"]["source_id"])
        assert source.status == "approved"


def test_search_never_crosses_product_versions(api, as_a, db):
    v2 = _catalog_id("DEMO-SR-03-v2")
    v1 = _catalog_id("DEMO-SR-03-v1")
    v2_hits = knowledge.search(db, "使用方法", product_ids=[v2], limit=5)
    v1_hits = knowledge.search(db, "使用方法", product_ids=[v1], limit=5)
    assert v2_hits and v1_hits
    assert {r["citation"]["product_id"] for r in v2_hits} == {v2}
    assert {r["citation"]["product_id"] for r in v1_hits} == {v1}
    assert not ({r["citation"]["citation_id"] for r in v2_hits} & {r["citation"]["citation_id"] for r in v1_hits})


def test_pending_source_is_not_usable(db):
    from app.knowledge import service as ks
    from app.models import CatalogProduct
    from sqlalchemy import select

    pending = db.execute(
        select(CatalogProduct).where(CatalogProduct.formula_version == "DEMO-SR-12-v1")
    ).scalar_one()
    pk = ks.load_product_knowledge(db, pending)
    assert pk.has_sources is False
    assert pk.error_code == "SOURCE_MISSING"
    assert pk.usage_instructions == []
    assert "没有已审核" in pk.message


def test_fabricated_citation_is_rejected(db):
    result = knowledge.validate_citations(db, ["not-a-real-chunk-id"], require=True)
    assert result.ok is False
    assert result.missing == ["not-a-real-chunk-id"]
    assert result.error_code == "SOURCE_MISSING"


def test_citation_must_match_the_expected_product(db):
    v1 = _catalog_id("DEMO-SR-03-v1")
    v2 = _catalog_id("DEMO-SR-03-v2")
    chunk = knowledge.search(db, "使用方法", product_ids=[v2], limit=1)[0]["citation"]["chunk_id"]
    good = knowledge.validate_citations(db, [chunk], expected_product_id=v2, require=True)
    bad = knowledge.validate_citations(db, [chunk], expected_product_id=v1, require=True)
    assert good.ok is True
    assert bad.ok is False
    assert bad.wrong_product == [chunk]


def test_catalog_matching_offers_candidates_with_reasons(db):
    results = knowledge.match_catalog_products(db, "澄泉光感精华", limit=5)
    assert len({r["catalog_product_id"] for r in results}) >= 2
    for result in results:
        assert result["match_reasons"], "a candidate must explain why it matched"
        assert 0 < result["score"] <= 1


def test_source_status_summary_counts_states(db):
    summary = knowledge.source_status_summary(db, _catalog_id("DEMO-SR-12-v1"))
    assert summary["approved"] == 0
    assert summary["pending"] == 1
    approved = knowledge.source_status_summary(db, _catalog_id("DEMO-SR-03-v2"))
    assert approved["approved"] >= 1


def _catalog_id(formula: str) -> str:
    from sqlalchemy import select

    from app.db import get_session_factory
    from app.models import CatalogProduct

    session = get_session_factory()()
    try:
        return session.execute(
            select(CatalogProduct).where(CatalogProduct.formula_version == formula)
        ).scalar_one().id
    finally:
        session.close()
