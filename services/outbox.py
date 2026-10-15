"""Transactional outbox worker.

Guarantees implemented (spec 22.2):
  * outbox rows are written in the same transaction as the message;
  * the idempotency key is user_id + event_id + service_type + rule_version + occurrence;
  * retries reuse the same message and delivery rows, exponential backoff, max 3 attempts;
  * a lease prevents two workers from consuming the same row;
  * a message that is no longer authorized is cancelled before sending;
  * `provider_accepted` never means delivered or read.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import Settings, get_settings
from ..models import (
    Activity,
    NotificationDelivery,
    NotificationOutbox,
    NotificationPreference,
    ServiceMessage,
)
from ..providers import notifications as notification_providers
from . import audit
from . import proactive as proactive_service
from .clock import now as clock_now

BACKOFF_MINUTES = [1, 5, 15]


def claim(
    db: Session, *, worker_id: str, settings: Settings, limit: int = 20
) -> list[NotificationOutbox]:
    now = clock_now(db)
    lease_until = now + timedelta(seconds=settings.scheduler_lease_seconds)
    rows = list(
        db.execute(
            select(NotificationOutbox).where(
                NotificationOutbox.status.in_(["pending", "processing"]),
                NotificationOutbox.attempts < NotificationOutbox.max_attempts,
            )
        ).scalars()
    )
    claimed: list[NotificationOutbox] = []
    for row in rows:
        if row.status == "processing":
            if row.lease_expires_at is not None and row.lease_expires_at > now:
                continue  # another worker holds a valid lease
        elif row.next_attempt_at > now:
            continue
        row.status = "processing"
        row.lease_owner = worker_id
        row.lease_expires_at = lease_until
        claimed.append(row)
        if len(claimed) >= limit:
            break
    db.flush()
    return claimed


def process_outbox(
    db: Session,
    *,
    worker_id: str | None = None,
    settings: Settings | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    settings = settings or get_settings()
    worker_id = worker_id or settings.outbox_worker_id
    now = clock_now(db)
    results: list[dict[str, Any]] = []
    for item in claim(db, worker_id=worker_id, settings=settings, limit=limit):
        message = db.get(ServiceMessage, item.message_id)
        if message is None:
            item.status = "cancelled"
            item.last_error = "MESSAGE_MISSING"
            results.append({"outbox_id": item.id, "status": "cancelled", "reason": "MESSAGE_MISSING"})
            continue
        if message.status == "cancelled" or item.expires_at is not None and item.expires_at <= now:
            item.status = "expired" if message.status != "cancelled" else "cancelled"
            item.last_error = "EXPIRED" if message.status != "cancelled" else "CANCELLED"
            message.status = "expired" if item.last_error == "EXPIRED" else "cancelled"
            results.append({"outbox_id": item.id, "status": item.status, "reason": item.last_error})
            continue

        preference = proactive_service.get_preferences(
            db, tenant_id=item.tenant_id, user_id=item.user_id, settings=settings
        )
        service_type = (message.payload or {}).get("service_type")
        activity_id = (message.payload or {}).get("activity_id")
        if activity_id:
            activity = db.get(Activity, activity_id)
            if activity is not None and (
                activity.status == "cancelled" or not activity.user_confirmed
            ):
                item.status = "cancelled"
                item.last_error = "ACTIVITY_CANCELLED"
                message.status = "cancelled"
                results.append({"outbox_id": item.id, "status": "cancelled", "reason": "ACTIVITY_CANCELLED"})
                continue
        if service_type not in (preference.service_types or []):
            item.status = "cancelled"
            item.last_error = "AUTHORIZATION_REVOKED"
            message.status = "cancelled"
            results.append({"outbox_id": item.id, "status": "cancelled", "reason": "AUTHORIZATION_REVOKED"})
            continue
        if item.channel == "web_push" and not preference.external_push_enabled:
            item.status = "cancelled"
            item.last_error = "CHANNEL_DISABLED"
            results.append({"outbox_id": item.id, "status": "cancelled", "reason": "CHANNEL_DISABLED"})
            continue

        subscription = (
            proactive_service.active_subscription(db, tenant_id=item.tenant_id, user_id=item.user_id)
            if item.channel == "web_push"
            else None
        )
        try:
            provider = notification_providers.get_provider(item.channel, settings)
            outcome = provider.deliver(message, subscription)
        except Exception as exc:  # noqa: BLE001
            outcome = notification_providers.DeliveryResult(
                status="failed", error=type(exc).__name__
            )

        item.attempts += 1
        delivery = NotificationDelivery(
            tenant_id=item.tenant_id,
            user_id=item.user_id,
            outbox_id=item.id,
            message_id=message.id,
            channel=item.channel,
            attempt=item.attempts,
            status=outcome.status,
            provider_id=outcome.provider_id,
            error=outcome.error,
            provider_confirmed_receipt=outcome.provider_confirmed_receipt,
        )
        db.add(delivery)
        if outcome.status == "provider_accepted":
            item.status = "provider_accepted"
            item.provider_message_id = outcome.provider_id
            item.last_error = None
            item.lease_owner = None
            item.lease_expires_at = None
            message.status = "sent"
        else:
            item.last_error = outcome.error or "UNKNOWN"
            item.lease_owner = None
            item.lease_expires_at = None
            if item.expires_at is not None and item.expires_at <= now:
                item.status = "expired"
            elif item.attempts >= item.max_attempts:
                item.status = "failed"
            else:
                item.status = "pending"
                backoff = BACKOFF_MINUTES[min(item.attempts - 1, len(BACKOFF_MINUTES) - 1)]
                item.next_attempt_at = now + timedelta(minutes=backoff)
        db.flush()
        results.append(
            {
                "outbox_id": item.id,
                "message_id": message.id,
                "channel": item.channel,
                "status": item.status,
                "delivery_status": outcome.status,
                "attempts": item.attempts,
                "provider_confirmed_receipt": outcome.provider_confirmed_receipt,
                "notice": outcome.notice,
            }
        )
    if results:
        audit.record(
            db,
            action="outbox.processed",
            actor_role="system",
            meta={"count": len(results), "worker": worker_id},
        )
    return results


def expire_stale(db: Session, *, settings: Settings | None = None) -> int:
    settings = settings or get_settings()
    now = clock_now(db)
    changed = 0
    rows = list(
        db.execute(
            select(NotificationOutbox).where(
                NotificationOutbox.status.in_(["pending", "processing"]),
            )
        ).scalars()
    )
    for row in rows:
        if row.expires_at is not None and row.expires_at <= now:
            row.status = "expired"
            row.last_error = "EXPIRED"
            message = db.get(ServiceMessage, row.message_id)
            if message is not None and message.status in {"queued", "approved", "draft"}:
                message.status = "expired"
            changed += 1
    if changed:
        db.flush()
    return changed
