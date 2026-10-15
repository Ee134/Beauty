"""Reviewed knowledge: retrieval, source-version checks and citation validation.

Rules implemented here (spec section 8):
  * only `approved` sources for the exact product version/region are used;
  * every citation must resolve to a chunk of the same product version;
  * conflicting sources suspend the related deterministic advice;
  * user screenshots are never treated as approved efficacy knowledge.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterable, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import CatalogProduct, KnowledgeChunk, KnowledgeSource

_LATIN = re.compile(r"[a-zA-Z][a-zA-Z0-9\-]+")
_CJK = re.compile(r"[\u4e00-\u9fff]")


def tokenize(text: str) -> list[str]:
    """Deterministic lexical tokenizer: latin words + CJK character bigrams."""
    text = (text or "").lower()
    tokens = _LATIN.findall(text)
    cjk = _CJK.findall(text)
    tokens.extend(cjk)
    for i in range(len(cjk) - 1):
        tokens.append(cjk[i] + cjk[i + 1])
    nums = re.findall(r"\d+(?:\.\d+)?", text)
    tokens.extend(nums)
    return tokens


@dataclass
class Citation:
    citation_id: str
    source_id: str
    chunk_id: str
    product_id: str | None
    title: str
    locator: str | None
    url: str | None
    file_ref: str | None
    retrieved_at: str | None
    reviewed_at: str | None
    source_type: str
    is_demo: bool
    excerpt: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "citation_id": self.citation_id,
            "source_id": self.source_id,
            "chunk_id": self.chunk_id,
            "product_id": self.product_id,
            "title": self.title,
            "locator": self.locator,
            "url": self.url,
            "file_ref": self.file_ref,
            "retrieved_at": self.retrieved_at,
            "reviewed_at": self.reviewed_at,
            "source_type": self.source_type,
            "is_demo": self.is_demo,
            "excerpt": self.excerpt,
        }


@dataclass
class ProductKnowledge:
    """Aggregated approved knowledge for one catalog product version."""

    product_id: str
    has_sources: bool = False
    sources: list[KnowledgeSource] = field(default_factory=list)
    chunks: list[KnowledgeChunk] = field(default_factory=list)
    ingredients: list[dict[str, Any]] = field(default_factory=list)
    irritants: list[dict[str, Any]] = field(default_factory=list)
    usage_instructions: list[tuple[KnowledgeChunk, KnowledgeSource]] = field(default_factory=list)
    frequencies: list[tuple[KnowledgeChunk, KnowledgeSource]] = field(default_factory=list)
    order_hints: list[tuple[KnowledgeChunk, KnowledgeSource]] = field(default_factory=list)
    period_hints: list[str] = field(default_factory=list)
    error_code: str | None = None
    message: str | None = None

    @property
    def is_usable(self) -> bool:
        return self.has_sources and bool(self.usage_instructions)


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def approved_sources_for_product(
    db: Session, catalog_product_id: str, variant: str | None = None
) -> list[KnowledgeSource]:
    stmt = select(KnowledgeSource).where(
        KnowledgeSource.catalog_product_id == catalog_product_id,
        KnowledgeSource.status == "approved",
    )
    rows = list(db.execute(stmt).scalars())
    if variant:
        rows = [r for r in rows if not r.applies_to_variant or r.applies_to_variant == variant]
    return rows


def _chunks_for_sources(db: Session, source_ids: Sequence[str]) -> list[KnowledgeChunk]:
    if not source_ids:
        return []
    stmt = select(KnowledgeChunk).where(KnowledgeChunk.source_id.in_(list(source_ids)))
    return list(db.execute(stmt).scalars())


def citation_for(chunk: KnowledgeChunk, source: KnowledgeSource) -> Citation:
    excerpt = chunk.text.strip()
    if len(excerpt) > 220:
        excerpt = excerpt[:220] + "…"
    return Citation(
        citation_id=chunk.id,
        source_id=source.id,
        chunk_id=chunk.id,
        product_id=chunk.catalog_product_id or source.catalog_product_id,
        title=source.title,
        locator=chunk.locator,
        url=source.url,
        file_ref=source.file_ref,
        retrieved_at=_iso(source.retrieved_at),
        reviewed_at=_iso(source.reviewed_at),
        source_type=source.source_type,
        is_demo=source.is_demo,
        excerpt=excerpt,
    )


def load_product_knowledge(
    db: Session, catalog_product: CatalogProduct | None
) -> ProductKnowledge:
    """Load approved knowledge for one product version, or explain why it is missing."""
    if catalog_product is None:
        return ProductKnowledge(
            product_id="",
            error_code="UNKNOWN_PRODUCT",
            message="未能匹配到目录产品，无法引用官方资料。",
        )
    pk = ProductKnowledge(product_id=catalog_product.id)
    sources = approved_sources_for_product(db, catalog_product.id, catalog_product.variant)
    if not sources:
        pk.error_code = "SOURCE_MISSING"
        pk.message = "该产品当前没有已审核的官方资料，暂不自动排入计划。"
        return pk
    conflict_groups: set[str] = set()
    for s in sources:
        if s.conflict_group:
            conflict_groups.add(s.conflict_group)
    pk.sources = sources
    chunks = _chunks_for_sources(db, [s.id for s in sources])
    pk.chunks = chunks
    pk.has_sources = True
    by_id = {s.id: s for s in sources}
    for chunk in chunks:
        source = by_id[chunk.source_id]
        claims = set(chunk.claim_types or [])
        if "usage_instruction" in claims:
            pk.usage_instructions.append((chunk, source))
        if "frequency" in claims:
            pk.frequencies.append((chunk, source))
        if "order_dependency" in claims:
            pk.order_hints.append((chunk, source))
        for ing in (chunk.structured or {}).get("ingredients", []) or []:
            if not isinstance(ing, dict) or not ing.get("inci"):
                continue
            entry = {
                "inci": ing.get("inci"),
                "common_name": ing.get("common_name") or ing.get("inci"),
                "role": ing.get("role", "unknown"),
                "period": ing.get("period"),
                "note": ing.get("note"),
                "citation_id": chunk.id,
                "source_id": source.id,
                "source_title": source.title,
            }
            if entry["role"] == "irritant":
                pk.irritants.append(entry)
            else:
                pk.ingredients.append(entry)
        period = (chunk.structured or {}).get("period")
        if period and period not in pk.period_hints:
            pk.period_hints.append(period)
    if conflict_groups:
        pk.error_code = "SOURCE_CONFLICT"
        pk.message = (
            "该产品的资料存在版本冲突（冲突组：" + "、".join(sorted(conflict_groups)) + "），"
            "相关确定性建议已暂停，待人工审核。"
        )
    return pk


def resolve_citations(db: Session, citation_ids: Iterable[str]) -> list[Citation]:
    """Resolve citation ids. Unknown ids are dropped, never invented."""
    ids = [c for c in dict.fromkeys(citation_ids) if c]
    if not ids:
        return []
    chunks = list(
        db.execute(select(KnowledgeChunk).where(KnowledgeChunk.id.in_(ids))).scalars()
    )
    if not chunks:
        return []
    sources = {
        s.id: s
        for s in db.execute(
            select(KnowledgeSource).where(
                KnowledgeSource.id.in_({c.source_id for c in chunks})
            )
        ).scalars()
    }
    out: list[Citation] = []
    for chunk in chunks:
        source = sources.get(chunk.source_id)
        if source is None or source.status != "approved":
            continue
        out.append(citation_for(chunk, source))
    return out


@dataclass
class CitationValidation:
    ok: bool
    valid: list[Citation]
    missing: list[str]
    wrong_product: list[str]
    not_approved: list[str]
    error_code: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "valid_count": len(self.valid),
            "missing": self.missing,
            "wrong_product": self.wrong_product,
            "not_approved": self.not_approved,
            "error_code": self.error_code,
        }


def validate_citations(
    db: Session,
    citation_ids: Iterable[str],
    *,
    expected_product_id: str | None = None,
    require: bool = True,
) -> CitationValidation:
    """Confirm citations exist, belong to the right product and support the claim."""
    ids = [c for c in dict.fromkeys(citation_ids) if c]
    missing: list[str] = []
    wrong: list[str] = []
    not_approved: list[str] = []
    valid: list[Citation] = []
    for cid in ids:
        chunk = db.get(KnowledgeChunk, cid)
        if chunk is None:
            missing.append(cid)
            continue
        source = db.get(KnowledgeSource, chunk.source_id)
        if source is None or source.status != "approved":
            not_approved.append(cid)
            continue
        if expected_product_id and (chunk.catalog_product_id or source.catalog_product_id) not in {
            expected_product_id,
            None,
        }:
            wrong.append(cid)
            continue
        valid.append(citation_for(chunk, source))
    ok = not missing and not wrong and not not_approved and (bool(valid) or not require)
    code = None
    if missing or wrong or not_approved:
        code = "SOURCE_MISSING"
    elif require and not valid:
        code = "SOURCE_MISSING"
    return CitationValidation(
        ok=ok,
        valid=valid,
        missing=missing,
        wrong_product=wrong,
        not_approved=not_approved,
        error_code=code,
    )


def search(
    db: Session,
    query: str,
    *,
    product_ids: Sequence[str] | None = None,
    claim_types: Sequence[str] | None = None,
    limit: int = 5,
    approved_only: bool = True,
) -> list[dict[str, Any]]:
    """Lexical BM25 retrieval with exact product/version filtering."""
    stmt = select(KnowledgeChunk)
    if product_ids:
        stmt = stmt.where(KnowledgeChunk.catalog_product_id.in_(list(product_ids)))
    chunks = list(db.execute(stmt).scalars())
    if not chunks:
        return []
    sources = {
        s.id: s
        for s in db.execute(
            select(KnowledgeSource).where(
                KnowledgeSource.id.in_({c.source_id for c in chunks})
            )
        ).scalars()
    }
    docs: list[tuple[KnowledgeChunk, KnowledgeSource, list[str]]] = []
    for c in chunks:
        s = sources.get(c.source_id)
        if s is None:
            continue
        if approved_only and s.status != "approved":
            continue
        if claim_types and not (set(c.claim_types or []) & set(claim_types)):
            continue
        docs.append((c, s, tokenize((c.heading or "") + " " + c.text)))
    if not docs:
        return []
    q_tokens = tokenize(query)
    n = len(docs)
    df: Counter[str] = Counter()
    for _, _, toks in docs:
        for t in set(toks):
            df[t] += 1
    avgdl = sum(len(t) for _, _, t in docs) / max(n, 1)
    k1, b = 1.5, 0.75
    scored: list[tuple[float, KnowledgeChunk, KnowledgeSource]] = []
    for chunk, source, toks in docs:
        tf = Counter(toks)
        dl = max(len(toks), 1)
        score = 0.0
        for qt in q_tokens:
            if qt not in tf:
                continue
            idf = math.log(1 + (n - df[qt] + 0.5) / (df[qt] + 0.5))
            score += idf * (tf[qt] * (k1 + 1)) / (tf[qt] + k1 * (1 - b + b * dl / avgdl))
        if score > 0:
            scored.append((score, chunk, source))
    scored.sort(key=lambda item: (-item[0], item[1].id))
    out = []
    for score, chunk, source in scored[:limit]:
        cit = citation_for(chunk, source)
        out.append(
            {
                "score": round(score, 4),
                "claim_types": list(chunk.claim_types or []),
                "structured": chunk.structured or {},
                "citation": cit.to_dict(),
            }
        )
    return out


ALLOWED_URL_SCHEMES = {"http", "https"}


def source_url_allowed(url: str | None, allowed_domains: Sequence[str]) -> tuple[bool, str | None]:
    """Only reviewed hosts (or local file refs) may be exposed as source links.

    The backend never fetches a user supplied URL, so this is not a fetch guard —
    it is a guard against surfacing an unreviewed link to the user.
    """
    if not url:
        return True, None
    value = url.strip()
    if value.startswith("demo://") or value.startswith("local://"):
        return True, None
    from urllib.parse import urlparse

    parsed = urlparse(value)
    if parsed.scheme not in ALLOWED_URL_SCHEMES:
        return False, f"不支持的链接协议：{parsed.scheme or '（空）'}"
    host = (parsed.hostname or "").lower()
    if not host:
        return False, "链接缺少主机名"
    allowed = [d.strip().lower() for d in allowed_domains if d.strip()]
    if any(host == domain or host.endswith("." + domain) for domain in allowed):
        return True, None
    return False, f"未在 ALLOWED_SOURCE_DOMAINS 中的来源主机：{host}"


def normalize_name(text: str) -> str:
    return re.sub(r"[\s\-_/（）()【】\[\]]+", "", (text or "").lower())


def match_catalog_products(db: Session, text: str, limit: int = 3) -> list[dict[str, Any]]:
    """Candidate retrieval with an explicit match reason. Never auto-adds to the cabinet."""
    norm = normalize_name(text)
    if not norm:
        return []
    products = list(db.execute(select(CatalogProduct)).scalars())
    q_tokens = set(tokenize(text))
    results: list[dict[str, Any]] = []
    for p in products:
        reasons: list[str] = []
        score = 0.0
        names = [p.name, *(p.aliases or [])]
        for candidate in names:
            nc = normalize_name(candidate)
            if not nc:
                continue
            if nc == norm:
                score = max(score, 1.0)
                reasons.append(f"名称完全匹配「{candidate}」")
            elif nc and (nc in norm or norm in nc):
                score = max(score, 0.82)
                reasons.append(f"名称部分匹配「{candidate}」")
        p_tokens = set(tokenize(p.name)) | {t for a in (p.aliases or []) for t in tokenize(a)}
        overlap = q_tokens & p_tokens
        if overlap:
            ratio = len(overlap) / max(len(p_tokens), 1)
            score = max(score, min(0.75, 0.35 + ratio))
            reasons.append("关键词重合：" + "、".join(sorted(overlap)[:5]))
        if p.brand and normalize_name(p.brand) in norm:
            score += 0.08
            reasons.append(f"品牌匹配「{p.brand}」")
        if score <= 0:
            continue
        results.append(
            {
                "catalog_product_id": p.id,
                "brand": p.brand,
                "name": p.name,
                "category": p.category,
                "region": p.region,
                "variant": p.variant,
                "size": p.size,
                "verification_status": p.verification_status,
                "is_demo": p.is_demo,
                "score": round(min(score, 1.0), 3),
                "match_reasons": reasons,
                "has_approved_source": bool(approved_sources_for_product(db, p.id)),
            }
        )
    results.sort(key=lambda r: (-r["score"], r["name"]))
    return results[:limit]


def source_status_summary(db: Session, catalog_product_id: str) -> dict[str, Any]:
    sources = list(
        db.execute(
            select(KnowledgeSource).where(KnowledgeSource.catalog_product_id == catalog_product_id)
        ).scalars()
    )
    by_status: Counter[str] = Counter(s.status for s in sources)
    return {
        "total": len(sources),
        "approved": by_status.get("approved", 0),
        "pending": by_status.get("pending", 0),
        "revoked": by_status.get("revoked", 0),
        "has_conflict": any(s.conflict_group for s in sources if s.status == "approved"),
    }
