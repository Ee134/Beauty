"""Service tickets, follow-ups, agent runs, audit, brand insight drafts."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TenantMixin, TimestampMixin, UTCDateTime, UUIDMixin, VersionMixin


class FollowUpTask(Base, UUIDMixin, TimestampMixin, TenantMixin):
    __tablename__ = "followup_tasks"

    # routine_review | check_in | service_progress | product_status
    purpose: Mapped[str] = mapped_column(String(40), nullable=False)
    related_entity_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    scheduled_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    # pending | sent | done | cancelled | expired
    status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False, index=True)
    consent_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class ServiceTicket(Base, UUIDMixin, TimestampMixin, VersionMixin, TenantMixin):
    __tablename__ = "service_tickets"

    # draft | submitted | awaiting_user | in_review | resolved | cancelled
    status: Mapped[str] = mapped_column(String(24), default="draft", nullable=False, index=True)
    summary: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    included_record_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    adapter_mode: Mapped[str] = mapped_column(String(24), default="local_demo", nullable=False)
    external_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    next_action: Mapped[str | None] = mapped_column(Text, nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    # Resolution is user confirmed, never inferred from staff status alone.
    user_confirmed_resolution: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    user_confirmed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    escalated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    escalation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class TicketEvent(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "ticket_events"

    ticket_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    actor_user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    actor_role: Mapped[str] = mapped_column(String(24), default="consumer", nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    from_status: Mapped[str | None] = mapped_column(String(24), nullable=True)
    to_status: Mapped[str | None] = mapped_column(String(24), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)


class AgentRun(Base, UUIDMixin, TimestampMixin, TenantMixin):
    __tablename__ = "agent_runs"

    conversation_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    message_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    intent: Mapped[str] = mapped_column(String(40), default="general", nullable=False)
    model_mode: Mapped[str] = mapped_column(String(16), default="mock", nullable=False)
    model_provider: Mapped[str] = mapped_column(String(40), default="mock", nullable=False)
    model_name: Mapped[str | None] = mapped_column(String(80), nullable=True)
    prompt_version: Mapped[str] = mapped_column(String(32), default="v1.2", nullable=False)
    tool_events: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    validation_result: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    usage_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    repair_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # Stored standard output, used to replay an idempotent turn.
    response: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)


class AuditEvent(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "audit_events"

    tenant_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    actor_user_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    actor_role: Mapped[str] = mapped_column(String(24), default="system", nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    entity_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    entity_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Deliberately content free: no raw uploads, no message text, no contact details.
    meta: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)


class BrandInsightDraft(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "brand_insight_drafts"

    tenant_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    user_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    # source_gap | service_gap | explicit_product_request | feature_request
    category: Mapped[str] = mapped_column(String(40), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_refs: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    # explicit | inferred
    explicitness: Mapped[str] = mapped_column(String(16), default="inferred", nullable=False)
    user_consent: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    consent_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # draft | pending_review | approved_for_share | rejected
    review_status: Mapped[str] = mapped_column(String(24), default="draft", nullable=False)
    mode: Mapped[str] = mapped_column(String(16), default="mock", nullable=False)
    brand_scope: Mapped[str | None] = mapped_column(String(120), nullable=True)
    occurrence_count: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    catalog_product_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
