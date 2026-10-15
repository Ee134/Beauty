"""品牌需求反馈：内部草稿与演示品牌台聚合。

MVP 只生成内部草稿，绝不自动外发；真实分享需要用户单独同意分享范围，
并由品牌运营审核。聚合默认在群体不足 BRAND_MIN_COHORT 人时抑制展示。
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Iterable, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import Settings, get_settings
from ..models import BrandInsightDraft, CatalogProduct
from ..services import audit
from ..services.clock import now as clock_now
from ..services.errors import ValidationError, not_found

CATEGORIES = {
    "source_gap",
    "service_gap",
    "explicit_product_request",
    "feature_request",
}
CATEGORY_LABELS = {
    "source_gap": "资料缺失",
    "service_gap": "服务缺失",
    "explicit_product_request": "显式产品需求",
    "feature_request": "功能建议",
}


def create_draft(
    db: Session,
    *,
    tenant_id: str,
    user_id: str | None,
    category: str,
    summary: str,
    evidence_refs: Sequence[dict[str, Any]] = (),
    explicitness: str = "inferred",
    brand_scope: str | None = None,
    catalog_product_id: str | None = None,
    mode: str = "mock",
    actor: str | None = None,
) -> BrandInsightDraft:
    if category not in CATEGORIES:
        raise ValidationError(f"未知类别：{category}")
    if explicitness not in {"explicit", "inferred"}:
        raise ValidationError("explicitness 只能是 explicit / inferred")
    if category == "explicit_product_request" and explicitness != "explicit":
        raise ValidationError("显式产品需求必须由用户明确表达，不能由库存缺口推断")
    existing = db.execute(
        select(BrandInsightDraft).where(
            BrandInsightDraft.tenant_id == tenant_id,
            BrandInsightDraft.user_id == user_id,
            BrandInsightDraft.category == category,
            BrandInsightDraft.summary == summary,
            BrandInsightDraft.review_status == "draft",
        )
    ).scalar_one_or_none()
    if existing is not None:
        existing.occurrence_count += 1
        db.flush()
        return existing
    row = BrandInsightDraft(
        tenant_id=tenant_id,
        user_id=user_id,
        category=category,
        summary=summary[:500],
        evidence_refs=list(evidence_refs),
        explicitness=explicitness,
        user_consent=False,
        review_status="draft",
        mode=mode,
        brand_scope=brand_scope,
        catalog_product_id=catalog_product_id,
    )
    db.add(row)
    db.flush()
    audit.record(
        db,
        action="brand_insight.draft_created",
        actor_user_id=actor or user_id,
        tenant_id=tenant_id,
        entity_type="brand_insight_draft",
        entity_id=row.id,
        meta={"category": category, "explicitness": explicitness},
    )
    return row


def record_source_gap(
    db: Session,
    *,
    tenant_id: str,
    user_id: str,
    catalog_product: CatalogProduct | None,
    reason: str,
    mode: str = "mock",
) -> BrandInsightDraft:
    label = catalog_product.name if catalog_product else "未匹配产品"
    return create_draft(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        category="source_gap",
        summary=f"{label} 缺少已审核资料（{reason}）",
        evidence_refs=[{"type": "catalog_product", "id": catalog_product.id if catalog_product else None}],
        explicitness="inferred",
        brand_scope=catalog_product.brand if catalog_product else None,
        catalog_product_id=catalog_product.id if catalog_product else None,
        mode=mode,
    )


def list_for_user(db: Session, *, tenant_id: str, user_id: str) -> list[BrandInsightDraft]:
    return list(
        db.execute(
            select(BrandInsightDraft)
            .where(BrandInsightDraft.tenant_id == tenant_id, BrandInsightDraft.user_id == user_id)
            .order_by(BrandInsightDraft.created_at.desc())
        ).scalars()
    )


def get_draft(db: Session, *, tenant_id: str, draft_id: str, user_id: str | None = None) -> BrandInsightDraft:
    row = db.get(BrandInsightDraft, draft_id)
    if row is None or row.tenant_id != tenant_id:
        raise not_found("需求草稿")
    if user_id is not None and row.user_id != user_id:
        raise not_found("需求草稿")
    return row


def set_consent(
    db: Session,
    *,
    draft: BrandInsightDraft,
    granted: bool,
    scope: str | None,
    actor: str | None,
) -> BrandInsightDraft:
    draft.user_consent = granted
    draft.consent_version = f"consent-{clock_now(db).date().isoformat()}" if granted else None
    draft.review_status = "pending_review" if granted else "draft"
    if scope:
        draft.brand_scope = scope
    db.flush()
    audit.record(
        db,
        action="brand_insight.consent_changed",
        actor_user_id=actor,
        tenant_id=draft.tenant_id,
        entity_type="brand_insight_draft",
        entity_id=draft.id,
        meta={"granted": granted},
    )
    return draft


def serialize(draft: BrandInsightDraft) -> dict[str, Any]:
    return {
        "id": draft.id,
        "category": draft.category,
        "category_label": CATEGORY_LABELS.get(draft.category, draft.category),
        "summary": draft.summary,
        "evidence_refs": draft.evidence_refs,
        "explicitness": draft.explicitness,
        "user_consent": draft.user_consent,
        "consent_version": draft.consent_version,
        "review_status": draft.review_status,
        "mode": draft.mode,
        "brand_scope": draft.brand_scope,
        "occurrence_count": draft.occurrence_count,
        "created_at": draft.created_at.isoformat(),
        "notice": "内部草稿：未发送给任何品牌；真实外发需要用户同意与品牌运营审核。",
    }


def aggregate(
    db: Session, *, tenant_id: str, settings: Settings | None = None
) -> dict[str, Any]:
    """Demo brand console aggregation. Never mixes tenants, suppresses small cohorts."""
    settings = settings or get_settings()
    rows = list(
        db.execute(select(BrandInsightDraft).where(BrandInsightDraft.tenant_id == tenant_id)).scalars()
    )
    distinct_users = {r.user_id for r in rows if r.user_id}
    cohort = len(distinct_users)
    suppressed = cohort < settings.brand_min_cohort
    by_category: dict[str, list[BrandInsightDraft]] = defaultdict(list)
    for row in rows:
        by_category[row.category].append(row)
    groups: list[dict[str, Any]] = []
    for category, items in sorted(by_category.items()):
        themes = Counter(item.summary for item in items)
        consented = [i for i in items if i.user_consent]
        groups.append(
            {
                "category": category,
                "category_label": CATEGORY_LABELS.get(category, category),
                "draft_count": len(items),
                "distinct_users": len({i.user_id for i in items if i.user_id}),
                "consented_count": len(consented),
                "explicit_count": sum(1 for i in items if i.explicitness == "explicit"),
                "inferred_count": sum(1 for i in items if i.explicitness == "inferred"),
                "themes": [
                    {"theme": theme, "count": count} for theme, count in themes.most_common(5)
                ],
                "sample_redacted": [
                    {
                        "summary": item.summary[:80],
                        "occurrence_count": item.occurrence_count,
                        "review_status": item.review_status,
                    }
                    for item in items[:3]
                ],
            }
        )
    return {
        "tenant_id": tenant_id,
        "mode": "mock",
        "cohort_size": cohort,
        "min_cohort": settings.brand_min_cohort,
        "suppressed": suppressed,
        "suppression_notice": (
            f"群体不足 {settings.brand_min_cohort} 人，已抑制明细展示（去标识不等于绝对匿名）。"
            if suppressed
            else None
        ),
        "groups": [] if suppressed else groups,
        "totals": {
            "drafts": len(rows),
            "consented": sum(1 for r in rows if r.user_consent),
            "explicit": sum(1 for r in rows if r.explicitness == "explicit"),
        },
        "notice": (
            "演示品牌台：仅展示本租户的合成/汇总数据，不含原始对话、症状、精确定位或订单截图；"
            "不存在任何真实外发通道。"
        ),
    }
