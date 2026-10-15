"""Notification pipeline: preferences, subscriptions, decisions, messages, outbox."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TenantMixin, TimestampMixin, UTCDateTime, UUIDMixin, VersionMixin


class NotificationPreference(Base, UUIDMixin, TimestampMixin, VersionMixin, TenantMixin):
    __tablename__ = "notification_preferences"

    service_types: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    channels: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    daily_cap: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    quiet_hours_start: Mapped[str] = mapped_column(String(5), default="22:00", nullable=False)
    quiet_hours_end: Mapped[str] = mapped_column(String(5), default="08:00", nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Shanghai", nullable=False)
    consent_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    marketing_opt_in: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    external_push_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    muted_service_types: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)


class PushSubscription(Base, UUIDMixin, TimestampMixin, TenantMixin):
    __tablename__ = "push_subscriptions"

    device_id: Mapped[str] = mapped_column(String(64), nullable=False)
    platform: Mapped[str] = mapped_column(String(32), default="web", nullable=False)
    # Stored through the secure-storage adapter; never logged.
    endpoint_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    keys_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    # active | revoked | expired | failed
    status: Mapped[str] = mapped_column(String(16), default="active", nullable=False, index=True)
    granted_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(200), nullable=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class ProactiveDecision(Base, UUIDMixin, TimestampMixin, TenantMixin):
    __tablename__ = "proactive_decisions"

    event_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    service_type: Mapped[str] = mapped_column(String(40), nullable=False)
    # send | defer | suppress | ask
    outcome: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    reason_codes: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    context_refs: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    snapshot_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    rule_version: Mapped[str] = mapped_column(String(32), default="demo-v1", nullable=False)
    plan_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    citation_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    channel: Mapped[str | None] = mapped_column(String(24), nullable=True)
    mode: Mapped[str] = mapped_column(String(8), default="mock", nullable=False)
    score: Mapped[float | None] = mapped_column(nullable=True)
    defer_until: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class ServiceMessage(Base, UUIDMixin, TimestampMixin, TenantMixin):
    __tablename__ = "service_messages"

    decision_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    # service | marketing
    kind: Mapped[str] = mapped_column(String(16), default="service", nullable=False)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    source_refs: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    plan_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # draft | approved | queued | sent | expired | cancelled | read
    status: Mapped[str] = mapped_column(String(16), default="draft", nullable=False, index=True)
    read_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False, unique=True, index=True)


class NotificationOutbox(Base, UUIDMixin, TimestampMixin, TenantMixin):
    __tablename__ = "notification_outbox"

    message_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    channel: Mapped[str] = mapped_column(String(24), nullable=False)
    # user_id + event_id + service_type + rule_version + occurrence
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    next_attempt_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    # pending | processing | provider_accepted | failed | cancelled | expired
    status: Mapped[str] = mapped_column(String(24), default="pending", nullable=False, index=True)
    lease_owner: Mapped[str | None] = mapped_column(String(64), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(300), nullable=True)
    provider_message_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class NotificationDelivery(Base, UUIDMixin, TimestampMixin, TenantMixin):
    __tablename__ = "notification_deliveries"

    outbox_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    message_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    channel: Mapped[str] = mapped_column(String(24), nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    # pending | processing | provider_accepted | failed | cancelled | expired
    status: Mapped[str] = mapped_column(String(24), default="pending", nullable=False)
    provider_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    error: Mapped[str | None] = mapped_column(String(300), nullable=True)
    # Only recorded when the provider can actually verify a receipt.
    provider_confirmed_receipt: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class MessageFeedback(Base, UUIDMixin, TimestampMixin, TenantMixin):
    __tablename__ = "message_feedback"

    message_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    # read | adopt_intent | reject | later | not_helpful | mute_type
    action: Mapped[str] = mapped_column(String(24), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
