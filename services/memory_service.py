"""Memory: user confirmed facts, explicit preferences, user reports and hypotheses.

Rules (spec section 7):
  * first person, explicit statements may be written as user_report / explicit_preference;
  * vague references, dates, causality and long term skin traits require confirmation;
  * model hypotheses are never promoted to confirmed facts;
  * forgetting removes the source text from context and invalidates derived content.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    Conversation,
    IngredientAtlasView,
    IngredientFeedback,
    MemoryRecord,
    Message,
    UsageEvent,
)
from . import audit
from .clock import now as clock_now
from .errors import ForbiddenError, ValidationError, not_found

# --- allowed schema -------------------------------------------------------

PREFERENCE_SCHEMA: dict[str, dict[str, Any]] = {
    "routine.max_steps": {"type": "int", "min": 1, "max": 10, "label": "每日常规步骤上限"},
    "routine.budget_monthly": {"type": "number", "min": 0, "max": 1_000_000, "label": "月度预算"},
    "routine.budget_currency": {"type": "enum", "values": ["CNY", "USD", "EUR"], "label": "预算币种"},
    "routine.preferred_period": {"type": "enum", "values": ["morning", "evening", "both"], "label": "偏好时段"},
    "routine.avoid_ingredients": {"type": "list_str", "label": "希望避免的成分"},
    "routine.prefer_simple": {"type": "bool", "label": "偏好精简流程"},
    "notification.channel_preference": {"type": "enum", "values": ["in_app", "web_push"], "label": "偏好渠道"},
    "travel.packing_preference": {"type": "str", "label": "出行携带偏好"},
    "environment.home_city": {"type": "str", "label": "常用城市"},
}

FACT_SCHEMA: dict[str, dict[str, Any]] = {
    "budget.monthly": {"type": "number", "min": 0, "max": 1_000_000, "label": "月度预算"},
    "skin.type_hint": {"type": "str", "requires_confirmation": True, "label": "肤质倾向（需确认）"},
    "product.avoid_ingredient": {"type": "list_str", "requires_confirmation": True, "label": "避免成分（需确认）"},
}

CONFIRM_REQUIRED_KEYS = {k for k, v in {**PREFERENCE_SCHEMA, **FACT_SCHEMA}.items() if v.get("requires_confirmation")}

ALLOWED_KINDS = {
    "confirmed_fact",
    "explicit_preference",
    "user_report",
    "model_hypothesis",
    "business_fact",
}

VAGUE_PATTERNS = [
    r"好多了",
    r"好一点",
    r"差不多",
    r"可能",
    r"好像",
    r"也许",
    r"应该是",
    r"也许是",
]
CAUSAL_PATTERNS = [r"是因为", r"导致", r"造成", r"过敏", r"引起"]
LONGTERM_SKIN_PATTERNS = [r"一直", r"天生", r"从来", r"多年", r"敏感肌", r"干性皮肤", r"油性皮肤"]


def _matches(patterns: Sequence[str], text: str) -> str | None:
    for pattern in patterns:
        if re.search(pattern, text or ""):
            return pattern
    return None


def validate_value(key: str, value: Any, schema: dict[str, dict[str, Any]]) -> Any:
    spec = schema.get(key)
    if spec is None:
        raise ValidationError(f"未知的记忆字段：{key}")
    kind = spec["type"]
    if kind == "int":
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValidationError(f"{key} 需要整数")
        if not (spec["min"] <= value <= spec["max"]):
            raise ValidationError(f"{key} 超出允许范围 {spec['min']}–{spec['max']}")
        return value
    if kind == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValidationError(f"{key} 需要数字")
        if not (spec["min"] <= float(value) <= spec["max"]):
            raise ValidationError(f"{key} 超出允许范围")
        return float(value)
    if kind == "enum":
        if value not in spec["values"]:
            raise ValidationError(f"{key} 只能是 {spec['values']}")
        return value
    if kind == "bool":
        if not isinstance(value, bool):
            raise ValidationError(f"{key} 需要布尔值")
        return value
    if kind == "str":
        if not isinstance(value, str) or not value.strip():
            raise ValidationError(f"{key} 需要非空文本")
        return value.strip()[:200]
    if kind == "list_str":
        if isinstance(value, str):
            value = [v.strip() for v in re.split(r"[、,，;；]", value) if v.strip()]
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            raise ValidationError(f"{key} 需要文本列表")
        return [v.strip()[:80] for v in value if v.strip()]
    raise ValidationError(f"{key} 类型未支持")


@dataclass
class ProposalResult:
    record: MemoryRecord | None
    status: str  # created | pending_confirmation | rejected
    reason: str | None = None
    requires_confirmation: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.record.id if self.record else None,
            "status": self.status,
            "reason": self.reason,
            "requires_confirmation": self.requires_confirmation,
            "kind": self.record.kind if self.record else None,
            "key": self.record.key if self.record else None,
            "value": self.record.value if self.record else None,
        }


def active_records(
    db: Session,
    *,
    tenant_id: str,
    user_id: str,
    kinds: Iterable[str] | None = None,
    keys: Iterable[str] | None = None,
) -> list[MemoryRecord]:
    stmt = select(MemoryRecord).where(
        MemoryRecord.tenant_id == tenant_id,
        MemoryRecord.user_id == user_id,
        MemoryRecord.status == "active",
    )
    if kinds:
        stmt = stmt.where(MemoryRecord.kind.in_(list(kinds)))
    if keys:
        stmt = stmt.where(MemoryRecord.key.in_(list(keys)))
    return list(db.execute(stmt.order_by(MemoryRecord.created_at)).scalars())


def get_active_value(db: Session, *, tenant_id: str, user_id: str, key: str) -> Any:
    rows = active_records(db, tenant_id=tenant_id, user_id=user_id, keys=[key])
    if not rows:
        return None
    return rows[-1].value.get("value")


def list_records(db: Session, *, tenant_id: str, user_id: str, include_history: bool = True) -> list[MemoryRecord]:
    stmt = select(MemoryRecord).where(
        MemoryRecord.tenant_id == tenant_id, MemoryRecord.user_id == user_id
    )
    if not include_history:
        stmt = stmt.where(MemoryRecord.status == "active")
    return list(db.execute(stmt.order_by(MemoryRecord.created_at)).scalars())


def get_record(db: Session, *, tenant_id: str, user_id: str, record_id: str) -> MemoryRecord:
    row = db.get(MemoryRecord, record_id)
    if row is None or row.tenant_id != tenant_id or row.user_id != user_id:
        raise not_found("记忆记录")
    return row


def _source_message(db: Session, *, tenant_id: str, user_id: str, message_id: str | None) -> Message | None:
    """Resolve a source message. A missing or foreign id is an opaque rejection,
    never a hint about whether the resource exists."""
    if not message_id:
        return None
    msg = db.get(Message, message_id)
    if msg is None or msg.tenant_id != tenant_id or msg.user_id != user_id:
        return None
    return msg


def _text_supports(text: str, key: str, value: Any) -> str | None:
    """Cheap deterministic support check. Returns a rejection reason or None."""
    if not text:
        return None
    if key in {"routine.max_steps"} and isinstance(value, int):
        from ..agent.extraction import supported_number_in_text

        if not supported_number_in_text(text, value):
            return "原文未出现该数值，需用户确认"
    if key in {"routine.budget_monthly", "budget.monthly"} and isinstance(value, (int, float)):
        digits = str(int(value))
        if digits not in re.sub(r"[,，]", "", text):
            return "原文未出现该预算数值，需用户确认"
    return None


def propose(
    db: Session,
    *,
    tenant_id: str,
    user_id: str,
    proposal: dict[str, Any],
    actor: str | None = None,
) -> ProposalResult:
    kind = proposal.get("kind")
    if kind not in ALLOWED_KINDS:
        return ProposalResult(None, "rejected", f"kind 非法：{kind}")
    if kind == "model_hypothesis":
        return ProposalResult(
            None, "rejected", "模型推测不能写入记忆；只能作为待确认假设展示"
        )
    key = proposal.get("key") or ""
    raw_value = proposal.get("value")
    schema = PREFERENCE_SCHEMA if kind == "explicit_preference" else FACT_SCHEMA
    if kind in {"confirmed_fact", "business_fact", "user_report"}:
        schema = {**PREFERENCE_SCHEMA, **FACT_SCHEMA}
    if key not in schema:
        return ProposalResult(None, "rejected", f"字段不在允许的 schema 内：{key}")
    try:
        value = validate_value(key, raw_value, schema)
    except ValidationError as exc:
        return ProposalResult(None, "rejected", exc.message)

    message = _source_message(
        db, tenant_id=tenant_id, user_id=user_id, message_id=proposal.get("source_message_id")
    )
    if message is None:
        return ProposalResult(None, "rejected", "缺少可核验的 source_message_id")
    if message.redacted_at is not None:
        return ProposalResult(None, "rejected", "来源消息已被删除，不能作为依据")

    text = message.content or ""
    support = _text_supports(text, key, value)
    needs_confirm = bool(proposal.get("requires_confirmation")) or key in CONFIRM_REQUIRED_KEYS
    reason = support
    if _matches(VAGUE_PATTERNS, text):
        needs_confirm = True
        reason = reason or "表述模糊（如“好多了”），需要先明确关联事件"
    if _matches(CAUSAL_PATTERNS, text):
        needs_confirm = True
        reason = reason or "涉及因果或过敏表述，必须由用户确认且不作为确诊"
    if _matches(LONGTERM_SKIN_PATTERNS, text):
        needs_confirm = True
        reason = reason or "长期肤质判断需要用户确认"

    status = "pending_confirmation" if needs_confirm else "active"
    supersedes_id = proposal.get("supersedes_id")
    if kind in {"explicit_preference", "confirmed_fact"} and not supersedes_id:
        existing = active_records(db, tenant_id=tenant_id, user_id=user_id, keys=[key])
        if existing:
            if all(r.value.get("value") == value for r in existing):
                return ProposalResult(existing[-1], "created", "与现有记忆一致，无需重复记录")
            if status == "active":
                supersedes_id = existing[-1].id
    record = MemoryRecord(
        tenant_id=tenant_id,
        user_id=user_id,
        kind=kind,
        key=key,
        value={"value": value, "label": schema[key].get("label", key)},
        provenance_type=proposal.get("provenance_type") or "explicit_user_statement",
        source_ref=message.id,
        source_excerpt=(text[:160] if text else None),
        occurred_at=proposal.get("occurred_at"),
        valid_from=clock_now(db),
        status=status,
        confidence=proposal.get("confidence"),
        supersedes_id=supersedes_id,
    )
    db.add(record)
    db.flush()
    if supersedes_id and status == "active":
        old = db.get(MemoryRecord, supersedes_id)
        if old is not None:
            old.status = "superseded"
            old.valid_to = clock_now(db)
            old.superseded_by_id = record.id
            db.flush()
    audit.record(
        db,
        action="memory.proposed",
        actor_user_id=actor or user_id,
        tenant_id=tenant_id,
        entity_type="memory_record",
        entity_id=record.id,
        meta={"kind": kind, "key": key, "status": status},
    )
    return ProposalResult(record, status, reason, status == "pending_confirmation")


def confirm(db: Session, record: MemoryRecord, *, value: Any | None = None) -> MemoryRecord:
    if value is not None:
        schema = {**PREFERENCE_SCHEMA, **FACT_SCHEMA}
        record.value = {"value": validate_value(record.key, value, schema), "label": record.value.get("label")}
    record.status = "active"
    record.valid_from = clock_now(db)
    db.flush()
    return record


def update_value(
    db: Session, record: MemoryRecord, *, value: Any, actor: str | None = None
) -> MemoryRecord:
    """Explicit correction: creates a new version and supersedes the old one."""
    schema = {**PREFERENCE_SCHEMA, **FACT_SCHEMA}
    validated = validate_value(record.key, value, schema)
    new = MemoryRecord(
        tenant_id=record.tenant_id,
        user_id=record.user_id,
        kind=record.kind,
        key=record.key,
        value={"value": validated, "label": record.value.get("label", record.key)},
        provenance_type="explicit_user_statement",
        source_ref=record.source_ref,
        source_excerpt=record.source_excerpt,
        valid_from=clock_now(db),
        status="active",
        supersedes_id=record.id,
    )
    db.add(new)
    db.flush()
    record.status = "superseded"
    record.valid_to = clock_now(db)
    record.superseded_by_id = new.id
    db.flush()
    audit.record(
        db,
        action="memory.corrected",
        actor_user_id=actor,
        tenant_id=record.tenant_id,
        entity_type="memory_record",
        entity_id=new.id,
        meta={"key": record.key, "supersedes": record.id},
    )
    return new


def invalidate_derived(db: Session, record: MemoryRecord, *, reason: str) -> dict[str, Any]:
    """Invalidate everything derived from a memory record (lineage based)."""
    affected: dict[str, Any] = {"usage_events": 0, "messages_redacted": 0, "atlas_stale": 0, "signals": 0}

    if record.source_ref:
        events = list(
            db.execute(
                select(UsageEvent).where(
                    UsageEvent.tenant_id == record.tenant_id,
                    UsageEvent.user_id == record.user_id,
                    UsageEvent.source_message_id == record.source_ref,
                )
            ).scalars()
        )
        if events:
            from . import atlas as atlas_service
            from . import usage_events as usage_service

            for event in events:
                usage_service.remove_event(db, event, reason=reason)
            affected["usage_events"] = len(events)
            affected["signals"] = atlas_service.invalidate_signals_for_events(db, events)

        messages = list(
            db.execute(
                select(Message).where(
                    Message.id == record.source_ref,
                    Message.tenant_id == record.tenant_id,
                    Message.user_id == record.user_id,
                )
            ).scalars()
        )
        for msg in messages:
            if msg.redacted_at is None:
                msg.redacted_at = clock_now(db)
                msg.redaction_scope = reason
                msg.content = "[该消息内容已按用户要求删除]"
                msg.cards = []
                msg.citations = []
                affected["messages_redacted"] += 1

    views = list(
        db.execute(
            select(IngredientAtlasView).where(
                IngredientAtlasView.tenant_id == record.tenant_id,
                IngredientAtlasView.user_id == record.user_id,
                IngredientAtlasView.status == "current",
            )
        ).scalars()
    )
    for view in views:
        view.status = "stale"
        affected["atlas_stale"] += 1
    db.flush()
    return affected


def delete_record(
    db: Session, record: MemoryRecord, *, actor: str | None = None, purge_source: bool = True
) -> dict[str, Any]:
    """Forget: remove the record, redact the source text and invalidate derived data."""
    affected = invalidate_derived(db, record, reason="user_forget") if purge_source else {}
    record.status = "deleted"
    record.value = {"value": None, "label": record.value.get("label", record.key), "deleted": True}
    record.source_excerpt = None
    record.valid_to = clock_now(db)
    db.flush()
    audit.record(
        db,
        action="memory.deleted",
        actor_user_id=actor,
        tenant_id=record.tenant_id,
        entity_type="memory_record",
        entity_id=record.id,
        meta={"key": record.key, "kind": record.kind, "derived": affected},
    )
    return affected


def delete_events_for_source_message(
    db: Session, *, tenant_id: str, user_id: str, message_id: str
) -> int:
    from . import usage_events as usage_service

    events = list(
        db.execute(
            select(UsageEvent).where(
                UsageEvent.tenant_id == tenant_id,
                UsageEvent.user_id == user_id,
                UsageEvent.source_message_id == message_id,
            )
        ).scalars()
    )
    for event in events:
        usage_service.remove_event(db, event, reason="user_forget")
    return len(events)


def build_context(
    db: Session,
    *,
    tenant_id: str,
    user_id: str,
    recent_event_days: int = 30,
) -> dict[str, Any]:
    """Minimal necessary context. Redacted messages never re-enter the model prompt."""
    preferences = [
        {
            "id": r.id,
            "key": r.key,
            "value": r.value.get("value"),
            "label": r.value.get("label"),
            "provenance": r.provenance_type,
            "source_ref": r.source_ref,
        }
        for r in active_records(
            db, tenant_id=tenant_id, user_id=user_id, kinds=["explicit_preference", "confirmed_fact"]
        )
    ]
    pending = [
        {
            "id": r.id,
            "key": r.key,
            "value": r.value.get("value"),
            "reason": r.provenance_type,
        }
        for r in active_records(
            db, tenant_id=tenant_id, user_id=user_id, kinds=["model_hypothesis"]
        )
    ]
    unresolved_events = list(
        db.execute(
            select(UsageEvent)
            .where(
                UsageEvent.tenant_id == tenant_id,
                UsageEvent.user_id == user_id,
                UsageEvent.invalidated_at.is_(None),
                UsageEvent.escalated.is_(True),
            )
            .order_by(UsageEvent.created_at.desc())
        ).scalars()
    )
    recent_events = list(
        db.execute(
            select(UsageEvent)
            .where(
                UsageEvent.tenant_id == tenant_id,
                UsageEvent.user_id == user_id,
                UsageEvent.invalidated_at.is_(None),
            )
            .order_by(UsageEvent.created_at.desc())
            .limit(10)
        ).scalars()
    )
    return {
        "preferences": preferences,
        "pending_hypotheses": pending,
        "unresolved_events": [
            {
                "id": e.id,
                "event_type": e.event_type,
                "reported_text": e.reported_text,
                "owned_product_ids": e.owned_product_ids,
                "occurred_at": e.occurred_at.isoformat() if e.occurred_at else None,
                "time_precision": e.time_precision,
                "severity": e.severity,
            }
            for e in unresolved_events
        ],
        "recent_events": [
            {
                "id": e.id,
                "event_type": e.event_type,
                "reported_text": e.reported_text,
                "owned_product_ids": e.owned_product_ids,
                "occurred_at": e.occurred_at.isoformat() if e.occurred_at else None,
                "time_precision": e.time_precision,
            }
            for e in recent_events
        ],
        "ingredient_feedback": [
            {"id": f.id, "ingredient_id": f.ingredient_id, "statement": f.statement}
            for f in db.execute(
                select(IngredientFeedback).where(
                    IngredientFeedback.tenant_id == tenant_id,
                    IngredientFeedback.user_id == user_id,
                    IngredientFeedback.status == "active",
                )
            ).scalars()
        ],
    }


def product_memories(db: Session, *, tenant_id: str, user_id: str, owned_product_id: str) -> list[MemoryRecord]:
    rows = list_records(db, tenant_id=tenant_id, user_id=user_id, include_history=True)
    return [
        r
        for r in rows
        if str(owned_product_id) in str(r.value) or str(owned_product_id) in (r.source_excerpt or "")
    ]


def conversation_messages(
    db: Session, *, tenant_id: str, user_id: str, conversation_id: str, limit: int = 20
) -> list[Message]:
    conv = db.get(Conversation, conversation_id)
    if conv is None or conv.tenant_id != tenant_id or conv.user_id != user_id:
        raise not_found("会话")
    rows = list(
        db.execute(
            select(Message)
            .where(
                Message.conversation_id == conversation_id,
                Message.redacted_at.is_(None),
            )
            .order_by(Message.sequence.desc())
            .limit(limit)
        ).scalars()
    )
    return list(reversed(rows))
