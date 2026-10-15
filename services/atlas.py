"""Ingredient atlas: source backed, per user, signal only — never causal.

Hard constraints implemented here (spec 8.1):
  * effects / irritancy / life extensions only from approved sources;
  * conflicting sources -> pending_review, no side is chosen;
  * missing sources -> “暂无充分信息”, never filled in by the model;
  * life extensions without an approved source are dropped;
  * a signal needs >= min_events linked events;
  * wording uses association counts, never “过敏 / 导致 / 避免”;
  * the atlas is generated on demand and never pushed.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Iterable, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..knowledge import service as knowledge
from ..models import (
    CatalogProduct,
    IngredientAtlasView,
    IngredientFeedback,
    IngredientProfile,
    KnowledgeChunk,
    KnowledgeSource,
    OwnedProduct,
    UsageEvent,
    UserIngredientSignal,
)
from . import audit
from .clock import now as clock_now
from .errors import ValidationError, not_found

DISCLAIMER = "此信息仅供日常参考，不替代专业建议。"
SOURCE_CONFLICT_NOTE = "信息存在冲突，待审核"
INSUFFICIENT_NOTE = "暂无充分信息"

FORBIDDEN_ASSERTIONS = [
    r"你对[^，。；]*过敏",
    r"过敏(?!反应记录|史确认|诊断|体质需要确认)",
    r"导致你的",
    r"会导致",
    r"避免[^，。；]{0,12}成分",
    r"确诊",
]
FORBIDDEN_LIFE_EXTENSION = [
    r"多吃[^，。；]{0,12}对皮肤好",
    r"可以替代[^，。；]{0,12}产品",
    r"食物可以替代",
]


def assert_allowed_wording(text: str) -> list[str]:
    """Return the forbidden patterns found. Used by generators and by tests."""
    hits = [p for p in FORBIDDEN_ASSERTIONS if re.search(p, text or "")]
    return hits


def check_life_extension_text(text: str) -> list[str]:
    return [p for p in FORBIDDEN_LIFE_EXTENSION if re.search(p, text or "")]


def _citation_map(db: Session, citation_ids: Iterable[str]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for cit in knowledge.resolve_citations(db, list(citation_ids)):
        if cit.citation_id not in out:
            out[cit.citation_id] = cit.to_dict()
    return out


def approved_citation_for_source(db: Session, source_id: str) -> dict[str, Any] | None:
    source = db.get(KnowledgeSource, source_id)
    if source is None or source.status != "approved":
        return None
    chunks = list(
        db.execute(
            select(KnowledgeChunk)
            .where(KnowledgeChunk.source_id == source_id)
            .order_by(KnowledgeChunk.locator)
        ).scalars()
    )
    if not chunks:
        return None
    return knowledge.citation_for(chunks[0], source).to_dict()


def ensure_profile(db: Session, inci_name: str, common_name: str | None = None) -> IngredientProfile:
    row = db.execute(
        select(IngredientProfile).where(IngredientProfile.inci_name == inci_name)
    ).scalar_one_or_none()
    if row is not None:
        return row
    row = IngredientProfile(
        inci_name=inci_name,
        common_name=common_name or inci_name,
        known_effects=[],
        irritant_level="unknown",
        irritant_notes=[],
        life_extensions=[],
        source_ids=[],
        approval_status="insufficient",
        is_demo=True,
    )
    db.add(row)
    db.flush()
    return row


# --- signals --------------------------------------------------------------


def mark_views_stale(db: Session, *, tenant_id: str, user_id: str) -> int:
    views = list(
        db.execute(
            select(IngredientAtlasView).where(
                IngredientAtlasView.tenant_id == tenant_id,
                IngredientAtlasView.user_id == user_id,
                IngredientAtlasView.status == "current",
            )
        ).scalars()
    )
    for view in views:
        view.status = "stale"
    db.flush()
    return len(views)


def invalidate_signals_for_events(db: Session, events: Sequence[UsageEvent]) -> int:
    """Invalidate signals whose lineage includes a deleted event (AC47)."""
    if not events:
        return 0
    user_ids = {(e.tenant_id, e.user_id) for e in events}
    event_ids = {e.id for e in events}
    changed = 0
    for tenant_id, user_id in user_ids:
        signals = list(
            db.execute(
                select(UserIngredientSignal).where(
                    UserIngredientSignal.tenant_id == tenant_id,
                    UserIngredientSignal.user_id == user_id,
                    UserIngredientSignal.invalidated_at.is_(None),
                )
            ).scalars()
        )
        for signal in signals:
            contributing = [eid for eid in (signal.contributing_event_ids or []) if eid in event_ids]
            if not contributing:
                continue
            remaining = [eid for eid in (signal.contributing_event_ids or []) if eid not in event_ids]
            signal.contributing_event_ids = remaining
            signal.event_count = len(remaining)
            signal.invalidated_at = clock_now(db)
            signal.invalidation_reason = "source_event_deleted"
            changed += 1
        db.flush()
    return changed


def _event_ingredients(db: Session, event: UsageEvent) -> set[tuple[str, str]]:
    """(ingredient_id, citation_id) pairs supported by approved sources."""
    out: set[tuple[str, str]] = set()
    for pid in event.owned_product_ids or []:
        product = db.get(OwnedProduct, pid)
        if product is None or not product.catalog_product_id:
            continue
        catalog = db.get(CatalogProduct, product.catalog_product_id)
        pk = knowledge.load_product_knowledge(db, catalog)
        for entry in pk.ingredients + pk.irritants:
            profile = ensure_profile(db, entry["inci"], entry.get("common_name"))
            out.add((profile.id, entry["citation_id"]))
    return out


def rebuild_signals(db: Session, *, tenant_id: str, user_id: str) -> list[UserIngredientSignal]:
    events = list(
        db.execute(
            select(UsageEvent).where(
                UsageEvent.tenant_id == tenant_id,
                UsageEvent.user_id == user_id,
                UsageEvent.invalidated_at.is_(None),
                UsageEvent.event_type.in_(["positive", "negative"]),
            )
        ).scalars()
    )
    counts: dict[tuple[str, str], dict[str, Any]] = {}
    for event in events:
        for ingredient_id, citation_id in _event_ingredients(db, event):
            polarity = "positive" if event.event_type == "positive" else "negative"
            bucket = counts.setdefault(
                (ingredient_id, polarity),
                {"event_ids": [], "citation_ids": set(), "last": None},
            )
            if event.id not in bucket["event_ids"]:
                bucket["event_ids"].append(event.id)
            bucket["citation_ids"].add(citation_id)
            if event.occurred_at and (bucket["last"] is None or event.occurred_at > bucket["last"]):
                bucket["last"] = event.occurred_at

    existing = list(
        db.execute(
            select(UserIngredientSignal).where(
                UserIngredientSignal.tenant_id == tenant_id,
                UserIngredientSignal.user_id == user_id,
            )
        ).scalars()
    )
    by_key = {(s.ingredient_id, s.signal_type): s for s in existing}
    result: list[UserIngredientSignal] = []
    for (ingredient_id, polarity), bucket in counts.items():
        signal = by_key.get((ingredient_id, polarity))
        if signal is None:
            signal = UserIngredientSignal(
                tenant_id=tenant_id,
                user_id=user_id,
                ingredient_id=ingredient_id,
                signal_type=polarity,
            )
            db.add(signal)
            existing.append(signal)
        signal.event_count = len(bucket["event_ids"])
        signal.contributing_event_ids = sorted(bucket["event_ids"])
        signal.last_occurred_at = bucket["last"]
        signal.computed_at = clock_now(db)
        signal.invalidated_at = None
        signal.invalidation_reason = None
        result.append(signal)
    db.flush()
    return result


# --- payload --------------------------------------------------------------


def _effect_entries(db: Session, profile: IngredientProfile) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for entry in profile.known_effects or []:
        citation = approved_citation_for_source(db, entry.get("source_id", ""))
        if citation is None:
            continue
        out.append({"text": entry.get("text"), "citation": citation})
    return out


def _irritancy(db: Session, profile: IngredientProfile) -> dict[str, Any]:
    """An irritancy level is only shown when a citation actually resolves.

    If the profile claims a level but no approved source can back it, the level is
    reported as unknown instead of presenting an unsourced claim.
    """
    notes: list[dict[str, Any]] = []
    for entry in profile.irritant_notes or []:
        citation = approved_citation_for_source(db, entry.get("source_id", ""))
        if citation is None:
            continue
        notes.append({"text": entry.get("text"), "citation": citation})
    has_source = bool(notes) or (
        profile.irritant_level not in {"unknown", ""}
        and any(
            approved_citation_for_source(db, source_id) is not None
            for source_id in (profile.source_ids or [])
        )
    )
    level = profile.irritant_level if has_source else "unknown"
    return {"level": level, "notes": notes, "has_source": has_source}


def _life_extensions(db: Session, profile: IngredientProfile) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Returns (accepted, dropped). Dropped entries are reported, never shown as advice."""
    accepted: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
    for entry in profile.life_extensions or []:
        source = db.get(KnowledgeSource, entry.get("source_id", ""))
        text = entry.get("text") or ""
        if source is None or source.status != "approved":
            dropped.append({"text": text, "reason": "SOURCE_NOT_APPROVED"})
            continue
        if check_life_extension_text(text):
            dropped.append({"text": text, "reason": "FORBIDDEN_WORDING"})
            continue
        citation = approved_citation_for_source(db, source.id)
        if citation is None:
            dropped.append({"text": text, "reason": "SOURCE_MISSING"})
            continue
        accepted.append(
            {
                "kind": entry.get("kind", "other"),
                "text": text,
                "citation": citation,
                "notice": "此延伸基于已审核来源，非个人诊断",
            }
        )
    return accepted, dropped


def _signal_statement(positive: int, negative: int) -> str:
    parts: list[str] = []
    if negative:
        parts.append(f"你的反馈中，含此成分的产品出现了 {negative} 次负面体验")
    if positive:
        parts.append(f"含此成分的产品出现了 {positive} 次正面体验")
    statement = "；".join(parts) if parts else "暂无与该成分关联的反馈事件"
    if positive and negative:
        statement += "。此成分与你的负面反馈有统计关联，但不代表因果关系"
    elif negative:
        statement += "。此成分与你的负面反馈有统计关联，但不代表因果关系"
    return statement + "。"


def build_payload(
    db: Session,
    *,
    tenant_id: str,
    user_id: str,
    min_events: int = 3,
    persist: bool = True,
) -> dict[str, Any]:
    signals = rebuild_signals(db, tenant_id=tenant_id, user_id=user_id)
    live_signals = [s for s in signals if s.invalidated_at is None]
    by_ingredient: dict[str, dict[str, Any]] = {}
    below: list[dict[str, Any]] = []
    for signal in live_signals:
        bucket = by_ingredient.setdefault(signal.ingredient_id, {"positive": None, "negative": None})
        bucket[signal.signal_type] = signal

    cards: list[dict[str, Any]] = []
    pending: list[dict[str, Any]] = []
    dropped_extensions: list[dict[str, Any]] = []

    for ingredient_id, bucket in by_ingredient.items():
        profile = db.get(IngredientProfile, ingredient_id)
        if profile is None:
            pending.append({"ingredient_id": ingredient_id, "reason": "INGREDIENT_PROFILE_MISSING"})
            continue
        positive = bucket.get("positive")
        negative = bucket.get("negative")
        positive_count = positive.event_count if positive else 0
        negative_count = negative.event_count if negative else 0
        total = positive_count + negative_count
        if total < min_events:
            below.append(
                {
                    "ingredient_id": ingredient_id,
                    "inci_name": profile.inci_name,
                    "common_name": profile.common_name,
                    "positive_count": positive_count,
                    "negative_count": negative_count,
                    "min_events": min_events,
                    "message": f"样本不足（需要至少 {min_events} 次关联反馈，当前 {total} 次），不生成个人化信号。",
                }
            )
            continue

        effects = _effect_entries(db, profile)
        irritancy = _irritancy(db, profile)
        if profile.approval_status == "insufficient" or not (profile.source_ids or []):
            data_status = "insufficient"
            effects = []
            irritancy = {"level": "unknown", "notes": [], "has_source": False}
            note = INSUFFICIENT_NOTE
        elif profile.conflict_flag or profile.approval_status == "pending_review":
            data_status = "pending_review"
            effects = []
            irritancy = {"level": "unknown", "notes": [], "has_source": False}
            note = SOURCE_CONFLICT_NOTE
        elif not effects and not irritancy["has_source"]:
            # approved in the database, but nothing resolves to a usable citation
            data_status = "insufficient"
            effects = []
            irritancy = {"level": "unknown", "notes": [], "has_source": False}
            note = INSUFFICIENT_NOTE
        else:
            data_status = "approved"
            note = None

        life_extensions, dropped = _life_extensions(db, profile)
        for entry in dropped:
            dropped_extensions.append(
                {"ingredient_id": ingredient_id, "inci_name": profile.inci_name, **entry}
            )

        event_ids = sorted(
            {
                *(positive.contributing_event_ids if positive else []),
                *(negative.contributing_event_ids if negative else []),
            }
        )
        citation_ids = [c for c in (profile.source_ids or [])]
        citations = _citation_map(db, citation_ids)
        card = {
            "ingredient_id": ingredient_id,
            "inci_name": profile.inci_name,
            "common_name": profile.common_name,
            "is_demo": profile.is_demo,
            "data_status": data_status,
            "approval_status": profile.approval_status,
            "data_note": note,
            "known_effects": effects,
            "irritancy": irritancy,
            "user_signal": {
                "positive_count": positive_count,
                "negative_count": negative_count,
                "total_count": total,
                "positive_event_ids": sorted(positive.contributing_event_ids) if positive else [],
                "negative_event_ids": sorted(negative.contributing_event_ids) if negative else [],
                "event_refs": event_ids,
                "statement": _signal_statement(positive_count, negative_count),
                "causality_notice": "统计关联不代表因果关系。",
            },
            "life_extensions": life_extensions,
            "uncertainty": (
                "该成分的功效与致敏性来自已审核来源；个人反馈只是关联统计，"
                "样本量小的时候尤其不能作为因果结论。"
            ),
            "disclaimer": DISCLAIMER,
        }
        hits = assert_allowed_wording(card["user_signal"]["statement"])
        if hits:
            pending.append(
                {"ingredient_id": ingredient_id, "reason": "FORBIDDEN_WORDING", "patterns": hits}
            )
            continue
        missing = [
            key
            for key in ("inci_name", "common_name", "user_signal", "uncertainty", "disclaimer")
            if not card.get(key)
        ]
        if missing:
            pending.append(
                {"ingredient_id": ingredient_id, "reason": "MISSING_REQUIRED_FIELDS", "fields": missing}
            )
            continue
        cards.append(card)

    cards.sort(key=lambda c: (-c["user_signal"]["negative_count"], -c["user_signal"]["positive_count"], c["inci_name"]))
    below.sort(key=lambda b: (-(b["positive_count"] + b["negative_count"]), b["inci_name"]))

    feedback = [
        {
            "id": f.id,
            "ingredient_id": f.ingredient_id,
            "statement": f.statement,
            "provenance_type": f.provenance_type,
            "created_at": f.created_at.isoformat(),
        }
        for f in db.execute(
            select(IngredientFeedback).where(
                IngredientFeedback.tenant_id == tenant_id,
                IngredientFeedback.user_id == user_id,
                IngredientFeedback.status == "active",
            )
        ).scalars()
    ]

    now = clock_now(db)
    payload: dict[str, Any] = {
        "generated_at": now.isoformat(),
        "min_events": min_events,
        "mode": "mock",
        "notice": "图鉴为用户主动查看时生成，不自动推送。",
        "disclaimer": DISCLAIMER,
        "signal_wording_notice": "以下为你自己的反馈关联统计，不构成因果结论，不替代专业建议。",
        "cards": cards,
        "below_threshold": below,
        "pending": pending,
        "dropped_life_extensions": dropped_extensions,
        "ingredient_feedback": feedback,
        "signal_ids": [s.id for s in live_signals],
        "stats": {
            "card_count": len(cards),
            "below_threshold_count": len(below),
            "pending_count": len(pending),
            "approved_card_count": sum(1 for c in cards if c["data_status"] == "approved"),
            "insufficient_card_count": sum(1 for c in cards if c["data_status"] == "insufficient"),
            "pending_review_card_count": sum(1 for c in cards if c["data_status"] == "pending_review"),
        },
    }
    if persist:
        previous = db.execute(
            select(IngredientAtlasView)
            .where(
                IngredientAtlasView.tenant_id == tenant_id,
                IngredientAtlasView.user_id == user_id,
            )
            .order_by(IngredientAtlasView.version.desc())
        ).scalars().first()
        version = (previous.version + 1) if previous else 1
        for view in db.execute(
            select(IngredientAtlasView).where(
                IngredientAtlasView.tenant_id == tenant_id,
                IngredientAtlasView.user_id == user_id,
                IngredientAtlasView.status == "current",
            )
        ).scalars():
            view.status = "stale"
        view = IngredientAtlasView(
            tenant_id=tenant_id,
            user_id=user_id,
            version=version,
            min_events=min_events,
            payload=payload,
            signal_ids=payload["signal_ids"],
            generated_at=now,
            status="current",
        )
        db.add(view)
        db.flush()
        payload["view_id"] = view.id
        payload["version"] = version
    return payload


def latest_view(db: Session, *, tenant_id: str, user_id: str) -> IngredientAtlasView | None:
    return (
        db.execute(
            select(IngredientAtlasView)
            .where(
                IngredientAtlasView.tenant_id == tenant_id,
                IngredientAtlasView.user_id == user_id,
            )
            .order_by(IngredientAtlasView.version.desc())
        )
        .scalars()
        .first()
    )


def get_ingredient(db: Session, ingredient_id: str) -> dict[str, Any]:
    profile = db.get(IngredientProfile, ingredient_id)
    if profile is None:
        raise not_found("成分")
    return serialize_profile(db, profile)


def serialize_profile(db: Session, profile: IngredientProfile) -> dict[str, Any]:
    effects = _effect_entries(db, profile)
    irritancy = _irritancy(db, profile)
    life_extensions, dropped = _life_extensions(db, profile)
    status = profile.approval_status
    if profile.conflict_flag or status == "pending_review":
        data_status = "pending_review"
        note = SOURCE_CONFLICT_NOTE
        effects = []
        irritancy = {"level": "unknown", "notes": [], "has_source": False}
    elif status == "approved" and (effects or irritancy["has_source"]):
        data_status = "approved"
        note = None
    else:
        data_status = "insufficient"
        note = INSUFFICIENT_NOTE
        effects = []
        irritancy = {"level": "unknown", "notes": [], "has_source": False}
    return {
        "id": profile.id,
        "inci_name": profile.inci_name,
        "common_name": profile.common_name,
        "categories": list(profile.categories or []),
        "typical_period": profile.typical_period,
        "is_demo": profile.is_demo,
        "data_status": data_status,
        "approval_status": status,
        "data_note": note,
        "known_effects": effects,
        "irritancy": irritancy,
        "life_extensions": life_extensions,
        "dropped_life_extensions": dropped,
        "sources": _citation_map(db, profile.source_ids or []),
        "conflict_note": profile.conflict_note,
        "disclaimer": DISCLAIMER,
    }


def add_ingredient_feedback(
    db: Session,
    *,
    tenant_id: str,
    user_id: str,
    ingredient_id: str,
    statement: str,
    source_message_id: str | None = None,
    actor: str | None = None,
) -> IngredientFeedback:
    profile = db.get(IngredientProfile, ingredient_id)
    if profile is None:
        raise not_found("成分")
    if not statement or not statement.strip():
        raise ValidationError("补充说明不能为空")
    row = IngredientFeedback(
        tenant_id=tenant_id,
        user_id=user_id,
        ingredient_id=ingredient_id,
        statement=statement.strip()[:500],
        provenance_type="explicit_user_statement",
        source_message_id=source_message_id,
    )
    db.add(row)
    db.flush()
    mark_views_stale(db, tenant_id=tenant_id, user_id=user_id)
    audit.record(
        db,
        action="ingredient_feedback.created",
        actor_user_id=actor or user_id,
        tenant_id=tenant_id,
        entity_type="ingredient_feedback",
        entity_id=row.id,
        meta={"ingredient_id": ingredient_id},
    )
    return row


def combo_reasoning(
    db: Session,
    products: Sequence[OwnedProduct],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Combination suitability reasoning, every note backed by approved sources.

    Returns (notes, skipped). Products without ingredient sources are skipped and
    reported so they never silently participate.
    """
    notes: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    knowledge_by_product: dict[str, Any] = {}
    for product in products:
        if not product.catalog_product_id:
            skipped.append({"owned_product_id": product.id, "name": product.custom_name, "reason": "UNMATCHED_PRODUCT"})
            continue
        catalog = db.get(CatalogProduct, product.catalog_product_id)
        pk = knowledge.load_product_knowledge(db, catalog)
        if not pk.has_sources or not (pk.ingredients or pk.irritants):
            skipped.append(
                {
                    "owned_product_id": product.id,
                    "name": product.custom_name,
                    "reason": pk.error_code or "INGREDIENT_SOURCE_MISSING",
                    "message": pk.message or "该产品没有已审核的成分资料，不参与组合推理。",
                }
            )
            continue
        knowledge_by_product[product.id] = pk

    # 1) same active ingredient in 2+ usable products, supported by an approved caution
    ingredient_index: dict[str, list[tuple[OwnedProduct, Any, dict[str, Any]]]] = {}
    for product in products:
        pk = knowledge_by_product.get(product.id)
        if pk is None:
            continue
        for entry in pk.ingredients + pk.irritants:
            ingredient_index.setdefault(entry["inci"], []).append((product, pk, entry))
    for inci, entries in sorted(ingredient_index.items()):
        product_ids = sorted({p.id for p, _, _ in entries})
        if len(product_ids) < 2:
            continue
        citation_ids: list[str] = []
        caution_texts: list[str] = []
        for product, pk, _entry in entries:
            for chunk in pk.chunks:
                structured = chunk.structured or {}
                caution = structured.get("combination_caution")
                if caution and caution.get("inci") == inci:
                    caution_texts.append(caution.get("text") or chunk.text)
                    citation_ids.append(chunk.id)
        if not citation_ids:
            continue  # no approved source -> no claim at all
        notes.append(
            {
                "type": "shared_active",
                "ingredient_inci": inci,
                "owned_product_ids": product_ids,
                "product_names": sorted({p.custom_name for p, _, _ in entries if p.id in product_ids}),
                "text": (
                    f"这些产品含同类成分 {inci}。已审核资料说明："
                    + caution_texts[0].rstrip("。；;. ")
                    + "。系统不判定它们能否叠用，请自行选择保留、间隔或移除其中一件。"
                ),
                "options": ["keep", "space_out", "remove_one"],
                "citation_ids": sorted(set(citation_ids)),
                "decided_by_system": False,
            }
        )

    # 2) source stated interleave requirement
    for product in products:
        pk = knowledge_by_product.get(product.id)
        if pk is None:
            continue
        for chunk in pk.chunks:
            structured = chunk.structured or {}
            others = structured.get("interleave_with_inci") or []
            if not others:
                continue
            for other_inci in others:
                targets = [
                    p.id
                    for p in products
                    if p.id != product.id
                    and p.id in knowledge_by_product
                    and other_inci in {i["inci"] for i in knowledge_by_product[p.id].ingredients + knowledge_by_product[p.id].irritants}
                ]
                if not targets:
                    continue
                notes.append(
                    {
                        "type": "interleave",
                        "ingredient_inci": other_inci,
                        "owned_product_ids": sorted([product.id, *targets]),
                        "text": (
                            f"已审核资料要求「{product.custom_name}」避免与含 {other_inci} 的产品在同一时段叠加。"
                            + (chunk.text.strip() if chunk.text else "")
                        ),
                        "options": ["keep", "space_out", "remove_one"],
                        "citation_ids": [chunk.id],
                        "decided_by_system": False,
                    }
                )

    # 3) period separation hints (deterministic, from structured claims only)
    periods: dict[str, list[str]] = {}
    for product in products:
        pk = knowledge_by_product.get(product.id)
        if pk is None:
            continue
        for period in pk.period_hints:
            periods.setdefault(period, []).append(product.custom_name)
    if periods.get("evening") and periods.get("morning"):
        notes.append(
            {
                "type": "period_assignment",
                "text": (
                    "按已审核资料，部分产品仅限晚间使用、部分仅限晨间使用，因此计划按时间段分开安排："
                    f"晨间 {len(periods.get('morning', []))} 件，晚间 {len(periods.get('evening', []))} 件。"
                ),
                "owned_product_ids": [
                    p.id
                    for p in products
                    if p.id in knowledge_by_product and set(knowledge_by_product[p.id].period_hints) & {"morning", "evening"}
                ],
                "citation_ids": sorted(
                    {
                        chunk.id
                        for p in products
                        if p.id in knowledge_by_product
                        for chunk in knowledge_by_product[p.id].chunks
                        if (chunk.structured or {}).get("period")
                    }
                ),
                "options": [],
                "decided_by_system": True,
            }
        )
    return notes, skipped
