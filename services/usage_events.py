"""Usage events: user reported experiences. Never a diagnosis, never causal proof."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import OwnedProduct, ReviewPrompt, RoutinePlan, RoutineStep, UsageEvent
from . import audit
from . import cabinet as cabinet_service
from .clock import now as clock_now
from .errors import ValidationError, not_found

MIN_NAME_MATCH = 3

EVENT_TYPES = {"positive", "negative", "neutral", "uncertain"}
TIME_PRECISION = {"unknown", "day", "exact", "approximate"}

NEGATIVE_PATTERNS = [
    r"刺痛",
    r"疼",
    r"红肿",
    r"发红",
    r"泛红",
    r"痒",
    r"瘙痒",
    r"脱皮",
    r"起皮",
    r"爆痘",
    r"闷痘",
    r"灼热",
    r"烧灼",
    r"过敏",
    r"不舒服",
    r"刺激",
    r"干燥紧绷",
]
POSITIVE_PATTERNS = [r"很舒服", r"不错", r"好用", r"变好", r"改善", r"挺润", r"满意", r"没有不适", r"舒服"]
SEVERE_PATTERNS = [r"很严重", r"非常严重", r"持续", r"好几天", r"越来越", r"大面积", r"肿", r"水泡", r"呼吸困难", r"眼睛"]
PERSISTENT_PATTERNS = [r"一直", r"持续", r"好几天", r"反复", r"越来越"]

CAUSAL_LANGUAGE = [r"过敏", r"导致", r"是因为", r"造成"]


def classify(text: str, explicit: str | None = None) -> str:
    if explicit in EVENT_TYPES:
        return explicit
    if any(re.search(p, text or "") for p in NEGATIVE_PATTERNS):
        return "negative"
    if any(re.search(p, text or "") for p in POSITIVE_PATTERNS):
        return "positive"
    return "uncertain"


def assess_severity(text: str) -> str:
    if any(re.search(p, text or "") for p in SEVERE_PATTERNS):
        return "severe"
    if any(re.search(p, text or "") for p in PERSISTENT_PATTERNS):
        return "persistent"
    return "mild"


def contains_causal_language(text: str) -> bool:
    return any(re.search(p, text or "") for p in CAUSAL_LANGUAGE)


def _validate_owned_ids(
    db: Session, *, tenant_id: str, user_id: str, owned_product_ids: Sequence[str]
) -> list[OwnedProduct]:
    products: list[OwnedProduct] = []
    for pid in owned_product_ids:
        product = db.get(OwnedProduct, pid)
        if (
            product is None
            or product.tenant_id != tenant_id
            or product.user_id != user_id
            or product.deleted_at is not None
        ):
            raise not_found("产品实例")
        products.append(product)
    return products


def create_event(
    db: Session,
    *,
    tenant_id: str,
    user_id: str,
    reported_text: str,
    owned_product_ids: Sequence[str] = (),
    occurred_at: datetime | None = None,
    time_precision: str | None = None,
    event_type: str | None = None,
    severity: str | None = None,
    source_message_id: str | None = None,
    source_conversation_id: str | None = None,
    actor: str | None = None,
) -> tuple[UsageEvent, ReviewPrompt | None, dict[str, Any]]:
    if not reported_text or not reported_text.strip():
        raise ValidationError("反馈内容不能为空")
    products = _validate_owned_ids(
        db, tenant_id=tenant_id, user_id=user_id, owned_product_ids=owned_product_ids
    )
    precision = time_precision or ("exact" if occurred_at else "unknown")
    if precision not in TIME_PRECISION:
        raise ValidationError(f"time_precision 非法：{precision}")
    if precision != "unknown" and occurred_at is None:
        raise ValidationError("指定了时间精度但未提供发生时间")
    kind = classify(reported_text, event_type)
    sev = severity or assess_severity(reported_text)
    snapshot: list[dict[str, Any]] = []
    for product in products:
        snapshot.append(
            {
                "owned_product_id": product.id,
                "catalog_product_id": product.catalog_product_id,
                "name": product.custom_name,
                "ingredients": list(product.key_actives or []),
                "ingredient_source_status": product.ingredient_source_status,
            }
        )
    event = UsageEvent(
        tenant_id=tenant_id,
        user_id=user_id,
        owned_product_ids=list(owned_product_ids),
        reported_text=reported_text.strip(),
        occurred_at=occurred_at,
        time_precision=precision,
        event_type=kind,
        provenance="user_report",
        severity=sev,
        source_message_id=source_message_id,
        source_conversation_id=source_conversation_id,
        ingredient_snapshot=snapshot,
        escalated=sev in {"severe", "persistent"},
    )
    db.add(event)
    db.flush()

    for product in products:
        if kind == "negative":
            product.review_flag = True
            product.review_note = f"用户在 {event.created_at.date().isoformat()} 报告过负面体验（用户报告，非确诊）"
        elif kind == "positive" and product.review_flag:
            product.review_note = (product.review_note or "") + "；此后有正面反馈"

    follow_up = _maybe_create_review_prompt(db, event=event, products=products)
    from . import atlas as atlas_service

    atlas_service.mark_views_stale(db, tenant_id=tenant_id, user_id=user_id)
    audit.record(
        db,
        action="usage_event.created",
        actor_user_id=actor or user_id,
        tenant_id=tenant_id,
        entity_type="usage_event",
        entity_id=event.id,
        meta={"event_type": kind, "severity": sev, "time_precision": precision},
    )
    guidance: dict[str, Any] = {
        "escalate": sev in {"severe", "persistent"},
        "advice": (
            "已记录为你报告的体验，不是诊断结论。建议暂停相关步骤并联系人工客服或专业人士进一步确认。"
            if sev in {"severe", "persistent"}
            else "已记录为你报告的体验，不是诊断结论。系统不会建议你继续试用来验证。"
        ),
        "do_not_retry_advice": "不建议为了让系统确认而继续使用可疑产品。",
    }
    return event, follow_up, guidance


def _active_plan(db: Session, *, tenant_id: str, user_id: str) -> RoutinePlan | None:
    return db.execute(
        select(RoutinePlan).where(
            RoutinePlan.tenant_id == tenant_id,
            RoutinePlan.user_id == user_id,
            RoutinePlan.status == "active",
        )
    ).scalar_one_or_none()


def _maybe_create_review_prompt(
    db: Session, *, event: UsageEvent, products: Sequence[OwnedProduct]
) -> ReviewPrompt | None:
    """Negative feedback never changes the plan by itself: it opens an explicit question."""
    if event.event_type != "negative" or not products:
        return None
    plan = _active_plan(db, tenant_id=event.tenant_id, user_id=event.user_id)
    if plan is None:
        return None
    steps = list(db.execute(select(RoutineStep).where(RoutineStep.plan_id == plan.id)).scalars())
    step_product_ids = {s.owned_product_id for s in steps if s.owned_product_id}
    target = next((p for p in products if p.id in step_product_ids), None)
    if target is None:
        return None
    existing = db.execute(
        select(ReviewPrompt).where(
            ReviewPrompt.tenant_id == event.tenant_id,
            ReviewPrompt.user_id == event.user_id,
            ReviewPrompt.plan_id == plan.id,
            ReviewPrompt.owned_product_id == target.id,
            ReviewPrompt.status == "open",
        )
    ).scalar_one_or_none()
    if existing is not None:
        existing.question = (
            f"你报告了「{target.custom_name}」的负面体验，是否要暂停该步骤？（此前已提出同一复核问题）"
        )
        db.flush()
        return existing
    prompt = ReviewPrompt(
        tenant_id=event.tenant_id,
        user_id=event.user_id,
        usage_event_id=event.id,
        plan_id=plan.id,
        owned_product_id=target.id,
        question=f"你报告了「{target.custom_name}」的负面体验，是否要暂停该步骤？",
        options=["pause", "keep", "adjust"],
        status="open",
    )
    db.add(prompt)
    db.flush()
    audit.record(
        db,
        action="review_prompt.created",
        actor_user_id=event.user_id,
        tenant_id=event.tenant_id,
        entity_type="review_prompt",
        entity_id=prompt.id,
        meta={"plan_id": plan.id, "owned_product_id": target.id},
    )
    return prompt


def list_events(
    db: Session, *, tenant_id: str, user_id: str, limit: int = 50
) -> list[UsageEvent]:
    return list(
        db.execute(
            select(UsageEvent)
            .where(
                UsageEvent.tenant_id == tenant_id,
                UsageEvent.user_id == user_id,
                UsageEvent.invalidated_at.is_(None),
            )
            .order_by(UsageEvent.created_at.desc())
            .limit(limit)
        ).scalars()
    )


def get_event(db: Session, *, tenant_id: str, user_id: str, event_id: str) -> UsageEvent:
    row = db.get(UsageEvent, event_id)
    if row is None or row.tenant_id != tenant_id or row.user_id != user_id:
        raise not_found("使用事件")
    return row


def remove_event(db: Session, event: UsageEvent, *, reason: str, actor: str | None = None) -> dict[str, Any]:
    """Hard delete a feedback event and invalidate everything derived from it."""
    from . import atlas as atlas_service

    affected = atlas_service.invalidate_signals_for_events(db, [event])
    prompts = list(
        db.execute(
            select(ReviewPrompt).where(
                ReviewPrompt.usage_event_id == event.id, ReviewPrompt.status == "open"
            )
        ).scalars()
    )
    for prompt in prompts:
        prompt.status = "dismissed"
        prompt.decision = "event_deleted"
        prompt.decision_note = "用户删除了对应反馈事件"
        prompt.resolved_at = clock_now(db)
    product_ids = list(event.owned_product_ids or [])
    db.delete(event)
    db.flush()
    for pid in product_ids:
        remaining = db.execute(
            select(UsageEvent).where(
                UsageEvent.tenant_id == event.tenant_id,
                UsageEvent.user_id == event.user_id,
                UsageEvent.invalidated_at.is_(None),
            )
        ).scalars()
        still_flagged = False
        for other in remaining:
            if pid in (other.owned_product_ids or []) and other.event_type == "negative":
                still_flagged = True
                break
        product = db.get(OwnedProduct, pid)
        if product is not None:
            product.review_flag = still_flagged
            if not still_flagged:
                product.review_note = None
    atlas_service.mark_views_stale(db, tenant_id=event.tenant_id, user_id=event.user_id)
    audit.record(
        db,
        action="usage_event.deleted",
        actor_user_id=actor,
        tenant_id=event.tenant_id,
        entity_type="usage_event",
        entity_id=event.id,
        meta={"reason": reason, "derived": affected},
    )
    return affected


def serialize(event: UsageEvent) -> dict[str, Any]:
    return {
        "id": event.id,
        "owned_product_ids": list(event.owned_product_ids or []),
        "reported_text": event.reported_text,
        "occurred_at": event.occurred_at.isoformat() if event.occurred_at else None,
        "time_precision": event.time_precision,
        "event_type": event.event_type,
        "provenance": event.provenance,
        "severity": event.severity,
        "escalated": event.escalated,
        "ingredient_snapshot": event.ingredient_snapshot,
        "source_message_id": event.source_message_id,
        "created_at": event.created_at.isoformat(),
        "disclaimer": "这是你报告的体验记录，不是诊断结论，也不代表因果关系。",
    }


def product_symbol(db: Session, product: OwnedProduct) -> dict[str, Any]:
    return {"id": product.id, "name": product.custom_name, "actives": list(product.key_actives or [])}


def resolve_products_from_text(
    db: Session, *, tenant_id: str, user_id: str, text: str
) -> list[OwnedProduct]:
    """Match cabinet products named in a user message.

    Users rarely type the full product name ("修护晚霜" instead of
    "澄泉修护晚霜"), so the longest shared suffix of at least three characters
    wins. Ties are returned together, and a tie at the minimum length is treated
    as too ambiguous to link automatically.
    """
    products = cabinet_service.list_owned(db, tenant_id=tenant_id, user_id=user_id)
    normalized = re.sub(r"\s+", "", text or "")
    if not normalized:
        return []
    scored: list[tuple[int, OwnedProduct]] = []
    for product in products:
        name = re.sub(r"\s+", "", product.custom_name)
        best = 0
        if name and name in normalized:
            best = len(name)
        else:
            for length in range(len(name), MIN_NAME_MATCH - 1, -1):
                if name[-length:] in normalized:
                    best = length
                    break
        for token in re.findall(r"[A-Za-z][A-Za-z0-9+\-]{2,}", text or ""):
            if token.lower() in product.custom_name.lower():
                best = max(best, len(token))
        if best >= MIN_NAME_MATCH:
            scored.append((best, product))
    if not scored:
        return []
    top = max(score for score, _ in scored)
    return [product for score, product in scored if score == top]


