"""Proactive service decisions, messages and the transactional outbox.

Deterministic filtering happens first; the (model generated) service draft is
only a candidate. The backend decides send / defer / suppress / ask and records
auditable reason codes. A user closing the page does not stop this pipeline.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import Settings, get_settings
from ..knowledge import service as knowledge
from ..models import (
    Activity,
    FollowUpTask,
    NotificationOutbox,
    NotificationPreference,
    OwnedProduct,
    ProactiveDecision,
    PushSubscription,
    RoutinePlan,
    RoutineStep,
    ServiceMessage,
    TriggerRule,
)
from . import audit
from . import cabinet as cabinet_service
from .clock import now as clock_now
from .errors import ValidationError, not_found

OUTCOMES = {"send", "defer", "suppress", "ask"}
CHANNELS = {"in_app", "web_push"}
DEFAULT_SERVICE_TYPES = [
    "travel_support",
    "outdoor_support",
    "environment_checkin",
    "service_progress",
]


# --- preferences ----------------------------------------------------------


def get_preferences(db: Session, *, tenant_id: str, user_id: str, settings: Settings | None = None) -> NotificationPreference:
    settings = settings or get_settings()
    row = db.execute(
        select(NotificationPreference).where(
            NotificationPreference.tenant_id == tenant_id,
            NotificationPreference.user_id == user_id,
        )
    ).scalar_one_or_none()
    if row is None:
        start, end = settings.quiet_hours_range
        row = NotificationPreference(
            tenant_id=tenant_id,
            user_id=user_id,
            service_types=[],
            channels=["in_app"],
            daily_cap=settings.service_daily_cap,
            quiet_hours_start=start,
            quiet_hours_end=end,
            timezone=settings.app_timezone,
            consent_version=None,
            marketing_opt_in=False,
            external_push_enabled=False,
        )
        db.add(row)
        db.flush()
    return row


def serialize_preferences(row: NotificationPreference) -> dict[str, Any]:
    return {
        "service_types": list(row.service_types or []),
        "channels": list(row.channels or []),
        "daily_cap": row.daily_cap,
        "quiet_hours_start": row.quiet_hours_start,
        "quiet_hours_end": row.quiet_hours_end,
        "timezone": row.timezone,
        "consent_version": row.consent_version,
        "marketing_opt_in": row.marketing_opt_in,
        "external_push_enabled": row.external_push_enabled,
        "muted_service_types": list(row.muted_service_types or []),
        "version": row.version,
    }


def update_preferences(
    db: Session,
    row: NotificationPreference,
    *,
    changes: dict[str, Any],
    expected_version: int | None,
    actor: str | None = None,
) -> NotificationPreference:
    from .errors import VersionConflictError

    if expected_version is not None and row.version != expected_version:
        raise VersionConflictError(
            "通知偏好已更新，请刷新", details={"expected": expected_version, "actual": row.version}
        )
    allowed = {
        "service_types",
        "channels",
        "daily_cap",
        "quiet_hours_start",
        "quiet_hours_end",
        "timezone",
        "marketing_opt_in",
        "external_push_enabled",
        "muted_service_types",
        "consent_version",
    }
    unknown = set(changes) - allowed
    if unknown:
        raise ValidationError("不支持修改的字段：" + "、".join(sorted(unknown)))
    if "channels" in changes:
        bad = set(changes["channels"]) - CHANNELS
        if bad:
            raise ValidationError("未知渠道：" + "、".join(sorted(bad)))
        if "web_push" in changes["channels"] and not row.external_push_enabled and "external_push_enabled" not in changes:
            raise ValidationError("选择 web_push 渠道需要同时开启 external_push_enabled（独立授权）")
    if "daily_cap" in changes and not (0 <= int(changes["daily_cap"]) <= 10):
        raise ValidationError("daily_cap 需在 0–10 之间")
    for key, value in changes.items():
        setattr(row, key, value)
    row.version += 1
    db.flush()
    audit.record(
        db,
        action="notification.preferences_updated",
        actor_user_id=actor or row.user_id,
        tenant_id=row.tenant_id,
        entity_type="notification_preference",
        entity_id=row.id,
        meta={"fields": sorted(changes), "channels": row.channels, "service_types": row.service_types},
    )
    cancel_unauthorized_pending(db, preference=row)
    return row


def cancel_unauthorized_pending(db: Session, *, preference: NotificationPreference) -> int:
    """After a preference change, re-validate queued messages and cancel the ones
    that are no longer authorized (AC34)."""
    pending = list(
        db.execute(
            select(NotificationOutbox).where(
                NotificationOutbox.tenant_id == preference.tenant_id,
                NotificationOutbox.user_id == preference.user_id,
                NotificationOutbox.status.in_(["pending", "processing"]),
            )
        ).scalars()
    )
    cancelled = 0
    for item in pending:
        message = db.get(ServiceMessage, item.message_id)
        if message is None:
            item.status = "cancelled"
            cancelled += 1
            continue
        service_type = (message.payload or {}).get("service_type")
        allowed = service_type in (preference.service_types or [])
        if item.channel == "web_push" and not preference.external_push_enabled:
            allowed = False
        if not allowed:
            item.status = "cancelled"
            item.last_error = "AUTHORIZATION_REVOKED"
            message.status = "cancelled"
            cancelled += 1
    if cancelled:
        db.flush()
    return cancelled


# --- push subscriptions ---------------------------------------------------


def add_subscription(
    db: Session,
    *,
    tenant_id: str,
    user_id: str,
    endpoint: str,
    keys: dict[str, Any] | None = None,
    device_id: str = "web-default",
    platform: str = "web",
    actor: str | None = None,
) -> PushSubscription:
    from .crypto import encrypt

    if not endpoint:
        raise ValidationError("缺少订阅端点")
    existing = db.execute(
        select(PushSubscription).where(
            PushSubscription.tenant_id == tenant_id,
            PushSubscription.user_id == user_id,
            PushSubscription.device_id == device_id,
            PushSubscription.status == "active",
        )
    ).scalar_one_or_none()
    if existing is not None:
        existing.status = "revoked"
        existing.revoked_at = clock_now(db)
        db.flush()
    row = PushSubscription(
        tenant_id=tenant_id,
        user_id=user_id,
        device_id=device_id,
        platform=platform,
        endpoint_encrypted=encrypt(endpoint),
        keys_encrypted=encrypt(__import__("json").dumps(keys or {})) if keys else None,
        status="active",
        granted_at=clock_now(db),
        is_primary=True,
    )
    db.add(row)
    db.flush()
    audit.record(
        db,
        action="push.subscribed",
        actor_user_id=actor or user_id,
        tenant_id=tenant_id,
        entity_type="push_subscription",
        entity_id=row.id,
        meta={"platform": platform, "device_id": device_id},
    )
    return row


def revoke_subscription(
    db: Session, *, tenant_id: str, user_id: str, subscription_id: str | None = None, actor: str | None = None
) -> int:
    stmt = select(PushSubscription).where(
        PushSubscription.tenant_id == tenant_id,
        PushSubscription.user_id == user_id,
        PushSubscription.status == "active",
    )
    if subscription_id:
        stmt = stmt.where(PushSubscription.id == subscription_id)
    rows = list(db.execute(stmt).scalars())
    now = clock_now(db)
    for row in rows:
        row.status = "revoked"
        row.revoked_at = now
    db.flush()
    if rows:
        preference = get_preferences(db, tenant_id=tenant_id, user_id=user_id)
        preference.external_push_enabled = False
        preference.channels = [c for c in (preference.channels or []) if c != "web_push"]
        preference.version += 1
        db.flush()
        cancel_unauthorized_pending(db, preference=preference)
    audit.record(
        db,
        action="push.revoked",
        actor_user_id=actor or user_id,
        tenant_id=tenant_id,
        entity_type="push_subscription",
        entity_id=subscription_id,
        meta={"count": len(rows)},
    )
    return len(rows)


def active_subscription(db: Session, *, tenant_id: str, user_id: str) -> PushSubscription | None:
    return (
        db.execute(
            select(PushSubscription)
            .where(
                PushSubscription.tenant_id == tenant_id,
                PushSubscription.user_id == user_id,
                PushSubscription.status == "active",
            )
            .order_by(PushSubscription.created_at.desc())
        )
        .scalars()
        .first()
    )


# --- rules and decisions --------------------------------------------------


def get_rule(db: Session, service_type: str) -> TriggerRule | None:
    return (
        db.execute(
            select(TriggerRule)
            .where(TriggerRule.service_type == service_type, TriggerRule.is_active.is_(True))
            .order_by(TriggerRule.version.desc())
        )
        .scalars()
        .first()
    )


def quiet_hours_active(preference: NotificationPreference, moment: datetime) -> bool:
    """Quiet hours in the user's notification timezone, handling midnight wrap."""
    try:
        from zoneinfo import ZoneInfo

        local = moment.astimezone(ZoneInfo(preference.timezone or "Asia/Shanghai"))
    except Exception:  # noqa: BLE001
        local = moment
    start_h, start_m = (int(x) for x in (preference.quiet_hours_start or "22:00").split(":"))
    end_h, end_m = (int(x) for x in (preference.quiet_hours_end or "08:00").split(":"))
    minutes = local.hour * 60 + local.minute
    start = start_h * 60 + start_m
    end = end_h * 60 + end_m
    if start == end:
        return False
    if start < end:
        return start <= minutes < end
    return minutes >= start or minutes < end


def _sent_today(db: Session, *, tenant_id: str, user_id: str, now: datetime, timezone_name: str) -> int:
    try:
        from zoneinfo import ZoneInfo

        tz = ZoneInfo(timezone_name or "Asia/Shanghai")
    except Exception:  # noqa: BLE001
        tz = timezone.utc
    local_now = now.astimezone(tz)
    start_local = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    start_utc = start_local.astimezone(timezone.utc)
    rows = list(
        db.execute(
            select(ServiceMessage).where(
                ServiceMessage.tenant_id == tenant_id,
                ServiceMessage.user_id == user_id,
                ServiceMessage.status.in_(["sent", "read", "queued"]),
            )
        ).scalars()
    )
    return sum(1 for r in rows if r.created_at and r.created_at >= start_utc)


def _last_message_at(
    db: Session, *, tenant_id: str, user_id: str, service_type: str
) -> datetime | None:
    rows = list(
        db.execute(
            select(ServiceMessage)
            .where(
                ServiceMessage.tenant_id == tenant_id,
                ServiceMessage.user_id == user_id,
                ServiceMessage.status.in_(["sent", "read", "queued", "approved"]),
            )
            .order_by(ServiceMessage.created_at.desc())
        ).scalars()
    )
    for row in rows:
        if (row.payload or {}).get("service_type") == service_type:
            return row.created_at
    return None


def decide(
    db: Session,
    *,
    tenant_id: str,
    user_id: str,
    service_type: str,
    event_id: str,
    context_refs: Sequence[str],
    snapshot_id: str | None,
    citation_ids: Sequence[str],
    plan_version: int | None,
    payload: dict[str, Any],
    expires_at: datetime | None = None,
    settings: Settings | None = None,
    extra_suppress_reasons: Sequence[str] = (),
) -> dict[str, Any]:
    """Deterministic gate. Returns the decision dict with reason codes."""
    settings = settings or get_settings()
    now = clock_now(db)
    preference = get_preferences(db, tenant_id=tenant_id, user_id=user_id, settings=settings)
    rule = get_rule(db, service_type)
    reasons: list[str] = []

    if service_type not in (preference.service_types or []):
        return _record_decision(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            service_type=service_type,
            event_id=event_id,
            outcome="suppress",
            reason_codes=["NO_USER_AUTHORIZATION"],
            context_refs=context_refs,
            snapshot_id=snapshot_id,
            citation_ids=citation_ids,
            plan_version=plan_version,
            expires_at=expires_at,
            channel=None,
        )
    reasons.append("USER_AUTHORIZED")

    if service_type in (preference.muted_service_types or []):
        return _record_decision(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            service_type=service_type,
            event_id=event_id,
            outcome="suppress",
            reason_codes=["SERVICE_TYPE_MUTED"],
            context_refs=context_refs,
            snapshot_id=snapshot_id,
            citation_ids=citation_ids,
            plan_version=plan_version,
            expires_at=expires_at,
            channel=None,
        )

    if extra_suppress_reasons:
        return _record_decision(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            service_type=service_type,
            event_id=event_id,
            outcome="suppress",
            reason_codes=list(extra_suppress_reasons),
            context_refs=context_refs,
            snapshot_id=snapshot_id,
            citation_ids=citation_ids,
            plan_version=plan_version,
            expires_at=expires_at,
            channel=None,
        )

    paused_ids_early = set(payload.get("paused_product_ids", []))
    if paused_ids_early & set(payload.get("owned_product_ids", [])):
        return _record_decision(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            service_type=service_type,
            event_id=event_id,
            outcome="suppress",
            reason_codes=["PRODUCT_PAUSED"],
            context_refs=context_refs,
            snapshot_id=snapshot_id,
            citation_ids=citation_ids,
            plan_version=plan_version,
            expires_at=expires_at,
            channel=None,
        )

    if payload.get("activity_cancelled"):
        return _record_decision(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            service_type=service_type,
            event_id=event_id,
            outcome="suppress",
            reason_codes=["ACTIVITY_CANCELLED"],
            context_refs=context_refs,
            snapshot_id=snapshot_id,
            citation_ids=citation_ids,
            plan_version=plan_version,
            expires_at=expires_at,
            channel=None,
        )

    if snapshot_id is None:
        return _record_decision(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            service_type=service_type,
            event_id=event_id,
            outcome="suppress",
            reason_codes=["ENVIRONMENT_UNAVAILABLE"],
            context_refs=context_refs,
            snapshot_id=snapshot_id,
            citation_ids=citation_ids,
            plan_version=plan_version,
            expires_at=expires_at,
            channel=None,
        )
    if not payload.get("snapshot_fresh", False):
        return _record_decision(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            service_type=service_type,
            event_id=event_id,
            outcome="suppress",
            reason_codes=["ENVIRONMENT_STALE"],
            context_refs=context_refs,
            snapshot_id=snapshot_id,
            citation_ids=citation_ids,
            plan_version=plan_version,
            expires_at=expires_at,
            channel=None,
        )
    reasons.append("FRESH_ENVIRONMENT")

    if not citation_ids:
        return _record_decision(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            service_type=service_type,
            event_id=event_id,
            outcome="suppress",
            reason_codes=["PRODUCT_SOURCE_MISSING"],
            context_refs=context_refs,
            snapshot_id=snapshot_id,
            citation_ids=citation_ids,
            plan_version=plan_version,
            expires_at=expires_at,
            channel=None,
        )
    validation = knowledge.validate_citations(db, citation_ids, require=True)
    if not validation.ok:
        return _record_decision(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            service_type=service_type,
            event_id=event_id,
            outcome="suppress",
            reason_codes=["CITATION_NOT_APPROVED"],
            context_refs=context_refs,
            snapshot_id=snapshot_id,
            citation_ids=citation_ids,
            plan_version=plan_version,
            expires_at=expires_at,
            channel=None,
        )
    reasons.append("PRODUCT_SOURCE_AVAILABLE")

    if expires_at is not None and expires_at <= now:
        return _record_decision(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            service_type=service_type,
            event_id=event_id,
            outcome="suppress",
            reason_codes=["EXPIRED"],
            context_refs=context_refs,
            snapshot_id=snapshot_id,
            citation_ids=citation_ids,
            plan_version=plan_version,
            expires_at=expires_at,
            channel=None,
        )

    existing = db.execute(
        select(ServiceMessage).where(
            ServiceMessage.tenant_id == tenant_id,
            ServiceMessage.user_id == user_id,
            ServiceMessage.idempotency_key
            == _idempotency_key(user_id, event_id, service_type, rule.version if rule else 1, 1),
        )
    ).scalar_one_or_none()
    if existing is not None:
        return _record_decision(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            service_type=service_type,
            event_id=event_id,
            outcome="suppress",
            reason_codes=["DUPLICATE_EVENT"],
            context_refs=context_refs,
            snapshot_id=snapshot_id,
            citation_ids=citation_ids,
            plan_version=plan_version,
            expires_at=expires_at,
            channel=None,
            message_id=existing.id,
        )

    last = _last_message_at(db, tenant_id=tenant_id, user_id=user_id, service_type=service_type)
    min_interval = rule.min_interval_minutes if rule else settings.service_min_interval_hours * 60
    if last is not None and (now - last) < timedelta(minutes=min_interval):
        return _record_decision(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            service_type=service_type,
            event_id=event_id,
            outcome="suppress",
            reason_codes=["COOLDOWN_ACTIVE"],
            context_refs=context_refs,
            snapshot_id=snapshot_id,
            citation_ids=citation_ids,
            plan_version=plan_version,
            expires_at=expires_at,
            channel=None,
        )

    if _sent_today(db, tenant_id=tenant_id, user_id=user_id, now=now, timezone_name=preference.timezone) >= (
        preference.daily_cap or 0
    ):
        return _record_decision(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            service_type=service_type,
            event_id=event_id,
            outcome="suppress",
            reason_codes=["DAILY_CAP_REACHED"],
            context_refs=context_refs,
            snapshot_id=snapshot_id,
            citation_ids=citation_ids,
            plan_version=plan_version,
            expires_at=expires_at,
            channel=None,
        )

    if quiet_hours_active(preference, now):
        still_useful = bool(payload.get("useful_after_quiet_hours", False))
        return _record_decision(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            service_type=service_type,
            event_id=event_id,
            outcome="defer" if still_useful else "suppress",
            reason_codes=["QUIET_HOURS"] + (["STILL_USEFUL_AFTER_DEFER"] if still_useful else ["NO_LONGER_USEFUL"]),
            context_refs=context_refs,
            snapshot_id=snapshot_id,
            citation_ids=citation_ids,
            plan_version=plan_version,
            expires_at=expires_at,
            channel=None,
            defer_until=_next_quiet_hours_end(preference, now),
        )

    channel = "in_app"
    if preference.external_push_enabled and "web_push" in (preference.channels or []):
        if active_subscription(db, tenant_id=tenant_id, user_id=user_id) is not None:
            channel = "web_push"
        else:
            reasons.append("PUSH_SUBSCRIPTION_MISSING_FALLBACK_IN_APP")
    return _record_decision(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        service_type=service_type,
        event_id=event_id,
        outcome="send" if payload.get("model_confidence_ok", True) else "ask",
        reason_codes=reasons + (["NEEDS_USER_CONFIRMATION"] if not payload.get("model_confidence_ok", True) else []),
        context_refs=context_refs,
        snapshot_id=snapshot_id,
        citation_ids=citation_ids,
        plan_version=plan_version,
        expires_at=expires_at,
        channel=channel,
    )


def _next_quiet_hours_end(preference: NotificationPreference, now: datetime) -> datetime:
    try:
        from zoneinfo import ZoneInfo

        tz = ZoneInfo(preference.timezone or "Asia/Shanghai")
    except Exception:  # noqa: BLE001
        tz = timezone.utc
    local = now.astimezone(tz)
    end_h, end_m = (int(x) for x in (preference.quiet_hours_end or "08:00").split(":"))
    candidate = local.replace(hour=end_h, minute=end_m, second=0, microsecond=0)
    if candidate <= local:
        candidate = candidate + timedelta(days=1)
    return candidate.astimezone(timezone.utc)


def _idempotency_key(
    user_id: str, event_id: str, service_type: str, rule_version: int, occurrence: int
) -> str:
    return f"{user_id}:{event_id}:{service_type}:{rule_version}:{occurrence}"


def _record_decision(
    db: Session,
    *,
    tenant_id: str,
    user_id: str,
    service_type: str,
    event_id: str,
    outcome: str,
    reason_codes: list[str],
    context_refs: Sequence[str],
    snapshot_id: str | None,
    citation_ids: Sequence[str],
    plan_version: int | None,
    expires_at: datetime | None,
    channel: str | None,
    defer_until: datetime | None = None,
    message_id: str | None = None,
    mode: str = "mock",
) -> dict[str, Any]:
    if outcome not in OUTCOMES:
        raise ValidationError(f"未知决策结果：{outcome}")
    rule = get_rule(db, service_type)
    row = ProactiveDecision(
        tenant_id=tenant_id,
        user_id=user_id,
        event_id=event_id,
        service_type=service_type,
        outcome=outcome,
        reason_codes=reason_codes,
        context_refs=list(context_refs),
        snapshot_id=snapshot_id,
        rule_version=f"demo-v{rule.version if rule else 1}",
        plan_version=plan_version,
        citation_ids=list(citation_ids),
        expires_at=expires_at,
        channel=channel,
        mode=mode,
        defer_until=defer_until,
    )
    db.add(row)
    db.flush()
    return {
        "decision_id": row.id,
        "event_id": event_id,
        "service_type": service_type,
        "outcome": outcome,
        "reason_codes": reason_codes,
        "environment_snapshot_id": snapshot_id,
        "context_refs": list(context_refs),
        "plan_version": plan_version,
        "rule_version": row.rule_version,
        "citation_ids": list(citation_ids),
        "expires_at": expires_at.isoformat() if expires_at else None,
        "channel": channel,
        "mode": mode,
        "message_id": message_id,
        "defer_until": defer_until.isoformat() if defer_until else None,
    }


# --- messages and outbox --------------------------------------------------


def create_message(
    db: Session,
    *,
    decision: dict[str, Any],
    tenant_id: str,
    user_id: str,
    title: str,
    body: str,
    payload: dict[str, Any],
    source_refs: Sequence[dict[str, Any]] = (),
    occurrence: int = 1,
    kind: str = "service",
    expires_at: datetime | None = None,
) -> ServiceMessage:
    rule = get_rule(db, decision["service_type"])
    key = _idempotency_key(
        user_id, decision["event_id"], decision["service_type"], rule.version if rule else 1, occurrence
    )
    existing = db.execute(
        select(ServiceMessage).where(ServiceMessage.idempotency_key == key)
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    message = ServiceMessage(
        tenant_id=tenant_id,
        user_id=user_id,
        decision_id=decision.get("decision_id"),
        kind=kind,
        title=title,
        body=body,
        payload={**payload, "service_type": decision["service_type"]},
        source_refs=list(source_refs),
        plan_version=decision.get("plan_version"),
        status="approved" if decision["outcome"] == "send" else "draft",
        expires_at=expires_at,
        idempotency_key=key,
    )
    db.add(message)
    db.flush()
    if decision["outcome"] != "send":
        return message
    channel = decision.get("channel") or "in_app"
    now = clock_now(db)
    outbox = NotificationOutbox(
        tenant_id=tenant_id,
        user_id=user_id,
        message_id=message.id,
        channel=channel,
        idempotency_key=f"{key}:{channel}",
        attempts=0,
        next_attempt_at=now,
        status="pending",
        expires_at=expires_at,
    )
    db.add(outbox)
    message.status = "queued"
    db.flush()
    audit.record(
        db,
        action="proactive.message_queued",
        actor_user_id=user_id,
        tenant_id=tenant_id,
        entity_type="service_message",
        entity_id=message.id,
        meta={
            "service_type": decision["service_type"],
            "channel": channel,
            "reason_codes": decision["reason_codes"],
        },
    )
    return message


def enqueue_outbox(
    db: Session,
    *,
    tenant_id: str,
    user_id: str,
    message: ServiceMessage,
    channel: str = "in_app",
    occurrence: int = 1,
) -> NotificationOutbox:
    rule = get_rule(db, (message.payload or {}).get("service_type", ""))
    key = _idempotency_key(
        user_id,
        (message.payload or {}).get("event_id", message.id),
        (message.payload or {}).get("service_type", "unknown"),
        rule.version if rule else 1,
        occurrence,
    )
    existing = db.execute(
        select(NotificationOutbox).where(NotificationOutbox.idempotency_key == f"{key}:{channel}")
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    now = clock_now(db)
    row = NotificationOutbox(
        tenant_id=tenant_id,
        user_id=user_id,
        message_id=message.id,
        channel=channel,
        idempotency_key=f"{key}:{channel}",
        next_attempt_at=now,
        status="pending",
        expires_at=message.expires_at,
    )
    db.add(row)
    db.flush()
    return row


def cancel_pending_for_activity(db: Session, *, activity: Activity, reason: str) -> int:
    rows = list(
        db.execute(
            select(NotificationOutbox).where(
                NotificationOutbox.tenant_id == activity.tenant_id,
                NotificationOutbox.user_id == activity.user_id,
                NotificationOutbox.status.in_(["pending", "processing"]),
            )
        ).scalars()
    )
    cancelled = 0
    for item in rows:
        message = db.get(ServiceMessage, item.message_id)
        if message is None:
            continue
        refs = (message.payload or {}).get("context_refs") or []
        if activity.id in refs or activity.id == (message.payload or {}).get("activity_id"):
            item.status = "cancelled"
            item.last_error = reason
            message.status = "cancelled"
            cancelled += 1
    if cancelled:
        db.flush()
        audit.record(
            db,
            action="proactive.pending_cancelled",
            actor_user_id=activity.user_id,
            tenant_id=activity.tenant_id,
            entity_type="activity",
            entity_id=activity.id,
            meta={"reason": reason, "count": cancelled},
        )
    return cancelled


def list_messages(
    db: Session, *, tenant_id: str, user_id: str, limit: int = 30, cursor: str | None = None
) -> tuple[list[ServiceMessage], str | None]:
    stmt = select(ServiceMessage).where(
        ServiceMessage.tenant_id == tenant_id,
        ServiceMessage.user_id == user_id,
        ServiceMessage.status.in_(["sent", "read", "queued", "approved", "cancelled", "expired"]),
    )
    if cursor:
        anchor = db.get(ServiceMessage, cursor)
        if anchor is not None:
            stmt = stmt.where(ServiceMessage.created_at < anchor.created_at)
    rows = list(db.execute(stmt.order_by(ServiceMessage.created_at.desc()).limit(limit + 1)).scalars())
    next_cursor = rows[limit].id if len(rows) > limit else None
    return rows[:limit], next_cursor


def serialize_message(db: Session, message: ServiceMessage) -> dict[str, Any]:
    decision = db.get(ProactiveDecision, message.decision_id) if message.decision_id else None
    return {
        "id": message.id,
        "kind": message.kind,
        "title": message.title,
        "body": message.body,
        "payload": message.payload,
        "source_refs": message.source_refs,
        "plan_version": message.plan_version,
        "status": message.status,
        "read_at": message.read_at.isoformat() if message.read_at else None,
        "expires_at": message.expires_at.isoformat() if message.expires_at else None,
        "created_at": message.created_at.isoformat(),
        "reason_codes": list(decision.reason_codes) if decision else [],
        "decision_outcome": decision.outcome if decision else None,
        "mode": decision.mode if decision else "mock",
        "deep_link": f"/inbox?message={message.id}",
        "notice": "服务提醒由后端策略发出；点击“采用”只记录意向，不自动接受计划。",
    }


def get_message(db: Session, *, tenant_id: str, user_id: str, message_id: str) -> ServiceMessage:
    row = db.get(ServiceMessage, message_id)
    if row is None or row.tenant_id != tenant_id or row.user_id != user_id:
        raise not_found("服务消息")
    return row


def paused_product_ids(db: Session, *, tenant_id: str, user_id: str) -> list[str]:
    products = cabinet_service.list_owned(db, tenant_id=tenant_id, user_id=user_id)
    return [p.id for p in products if p.usage_status != "active" or p.lifecycle_status in {"finished", "discarded"}]


def active_plan_version(db: Session, *, tenant_id: str, user_id: str) -> int | None:
    plan = (
        db.execute(
            select(RoutinePlan).where(
                RoutinePlan.tenant_id == tenant_id,
                RoutinePlan.user_id == user_id,
                RoutinePlan.status == "active",
            )
        )
        .scalars()
        .first()
    )
    return plan.version if plan else None


def followup_due(db: Session, *, tenant_id: str, user_id: str) -> list[FollowUpTask]:
    now = clock_now(db)
    rows = list(
        db.execute(
            select(FollowUpTask).where(
                FollowUpTask.tenant_id == tenant_id,
                FollowUpTask.user_id == user_id,
                FollowUpTask.status == "pending",
            )
        ).scalars()
    )
    return [r for r in rows if r.scheduled_at is None or r.scheduled_at <= now]
