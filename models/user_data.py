"""User owned data: cabinet, imports, conversation, memory, events, atlas views."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TenantMixin, TimestampMixin, UTCDateTime, UUIDMixin, VersionMixin


class ImportBatch(Base, UUIDMixin, TimestampMixin, TenantMixin):
    __tablename__ = "import_batches"

    file_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    storage_key: Mapped[str | None] = mapped_column(String(300), nullable=True)
    original_filename: Mapped[str | None] = mapped_column(String(300), nullable=True)
    mime_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    byte_size: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # uploaded | processing | ready | confirmed | failed | expired
    status: Mapped[str] = mapped_column(String(32), default="uploaded", nullable=False, index=True)
    candidates: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    provider_mode: Mapped[str] = mapped_column(String(16), default="mock", nullable=False)
    extractor: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    file_deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    created_owned_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)


class OwnedProduct(Base, UUIDMixin, TimestampMixin, VersionMixin, TenantMixin):
    __tablename__ = "owned_products"

    catalog_product_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("catalog_products.id"), nullable=True, index=True
    )
    custom_name: Mapped[str] = mapped_column(String(200), nullable=False)
    # matched | low_confidence | custom
    match_status: Mapped[str] = mapped_column(String(32), default="custom", nullable=False)
    purchase_date: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    opened_date: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    expiry_date: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    # packaging | user_confirmed | pao_derived | unknown
    expiry_source: Mapped[str] = mapped_column(String(32), default="unknown", nullable=False)
    pao_months: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # unopened | opened | finished | discarded | unknown
    lifecycle_status: Mapped[str] = mapped_column(String(32), default="unknown", nullable=False)
    # active | paused | unknown
    usage_status: Mapped[str] = mapped_column(String(32), default="unknown", nullable=False)
    size: Mapped[str | None] = mapped_column(String(64), nullable=True)
    key_actives: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    irritant_flags: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    ingredient_source_status: Mapped[str] = mapped_column(
        String(32), default="unknown", nullable=False
    )
    review_flag: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    import_batch_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    provenance: Mapped[str] = mapped_column(String(32), default="manual", nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class Conversation(Base, UUIDMixin, TimestampMixin, TenantMixin):
    __tablename__ = "conversations"

    title: Mapped[str] = mapped_column(String(200), default="新对话", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="open", nullable=False)
    last_message_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class Message(Base, UUIDMixin, TimestampMixin, TenantMixin):
    __tablename__ = "messages"

    conversation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("conversations.id"), index=True, nullable=False
    )
    # user | assistant | system
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    run_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    cards: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    citations: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    # Set when the content was redacted / soft deleted. Redacted messages never
    # re-enter agent context.
    redacted_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    redaction_scope: Mapped[str | None] = mapped_column(String(64), nullable=True)


class MemoryRecord(Base, UUIDMixin, TimestampMixin, VersionMixin, TenantMixin):
    __tablename__ = "memory_records"

    # confirmed_fact | explicit_preference | user_report | model_hypothesis | business_fact
    kind: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    key: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    value: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    # explicit_user_statement | user_report_event | model_inference | business_tool
    provenance_type: Mapped[str] = mapped_column(String(40), nullable=False)
    source_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
    occurred_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    valid_from: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    valid_to: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    # active | superseded | pending_confirmation | deleted
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False, index=True)
    confidence: Mapped[float | None] = mapped_column(nullable=True)
    supersedes_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    superseded_by_id: Mapped[str | None] = mapped_column(String(36), nullable=True)


class UsageEvent(Base, UUIDMixin, TimestampMixin, TenantMixin):
    __tablename__ = "usage_events"

    owned_product_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    reported_text: Mapped[str] = mapped_column(Text, nullable=False)
    occurred_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    time_precision: Mapped[str] = mapped_column(String(16), default="unknown", nullable=False)
    # positive | negative | neutral | uncertain
    event_type: Mapped[str] = mapped_column(String(16), default="uncertain", nullable=False, index=True)
    provenance: Mapped[str] = mapped_column(String(32), default="user_report", nullable=False)
    severity: Mapped[str] = mapped_column(String(16), default="unknown", nullable=False)
    source_message_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    source_conversation_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    ingredient_snapshot: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    escalated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Soft invalidation on delete: the row is removed on explicit forget, but
    # derived records keep a tombstone id list for lineage checks.
    invalidated_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class IngredientFeedback(Base, UUIDMixin, TimestampMixin, TenantMixin):
    __tablename__ = "ingredient_feedback"

    ingredient_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    statement: Mapped[str] = mapped_column(Text, nullable=False)
    # explicit_user_statement | user_report
    provenance_type: Mapped[str] = mapped_column(String(40), default="explicit_user_statement")
    source_message_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)


class IngredientAtlasView(Base, UUIDMixin, TimestampMixin, TenantMixin):
    __tablename__ = "ingredient_atlas_views"

    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    min_events: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    signal_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    generated_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    # current | stale
    status: Mapped[str] = mapped_column(String(16), default="current", nullable=False)


class ReviewPrompt(Base, UUIDMixin, TimestampMixin, TenantMixin):
    """Explicit routine review question created by a feedback event (never automatic)."""

    __tablename__ = "review_prompts"

    usage_event_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    plan_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    owned_product_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    options: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    # open | resolved | dismissed
    status: Mapped[str] = mapped_column(String(32), default="open", nullable=False, index=True)
    decision: Mapped[str | None] = mapped_column(String(32), nullable=True)
    decision_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    resulting_plan_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
