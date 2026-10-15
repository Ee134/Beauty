"""Identity, catalog and reviewed-knowledge tables."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin, UTCDateTime, UUIDMixin, VersionMixin


class Tenant(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "tenants"

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), default="demo", nullable=False)


class User(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "users"

    tenant_id: Mapped[str] = mapped_column(String(36), ForeignKey("tenants.id"), index=True)
    email: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    # consumer | staff | brand
    role: Mapped[str] = mapped_column(String(32), default="consumer", nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Shanghai", nullable=False)
    locale: Mapped[str] = mapped_column(String(16), default="zh-CN", nullable=False)
    # Notification / privacy consents, e.g. {"service_reminders": true, "marketing": false}
    consent_flags: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class UserSession(Base, UUIDMixin, TimestampMixin):
    """Server side session. Client sends the opaque token, never a user_id."""

    __tablename__ = "user_sessions"

    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, index=True)
    # demo | password | oidc
    kind: Mapped[str] = mapped_column(String(32), default="demo", nullable=False)
    persona_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    label: Mapped[str | None] = mapped_column(String(120), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class CatalogProduct(Base, UUIDMixin, TimestampMixin, VersionMixin):
    """Shared read-only catalog. Not user data, never deleted by the privacy endpoint."""

    __tablename__ = "catalog_products"

    brand: Mapped[str] = mapped_column(String(120), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    region: Mapped[str] = mapped_column(String(32), default="CN", nullable=False)
    variant: Mapped[str | None] = mapped_column(String(120), nullable=True)
    formula_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    size: Mapped[str | None] = mapped_column(String(64), nullable=True)
    aliases: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    # demo_fictional | real_verified | real_unverified
    verification_status: Mapped[str] = mapped_column(String(32), default="demo_fictional")
    is_demo: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Cached, source backed ingredient view for the product version (see knowledge service)
    ingredient_summary: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)


class KnowledgeSource(Base, UUIDMixin, TimestampMixin, VersionMixin):
    __tablename__ = "knowledge_sources"

    catalog_product_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("catalog_products.id"), index=True, nullable=True
    )
    # official_packaging | official_page | reviewed_brand | reviewed_third_party
    # | demo_authored | science_database | reviewed_dermatology
    source_type: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    publisher: Mapped[str | None] = mapped_column(String(200), nullable=True)
    url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    file_ref: Mapped[str | None] = mapped_column(String(300), nullable=True)
    region: Mapped[str] = mapped_column(String(32), default="CN", nullable=False)
    applies_to_variant: Mapped[str | None] = mapped_column(String(120), nullable=True)
    retrieved_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    # pending | approved | revoked
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False, index=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    approval_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    conflict_group: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class KnowledgeChunk(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "knowledge_chunks"

    source_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("knowledge_sources.id"), index=True, nullable=False
    )
    catalog_product_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    locator: Mapped[str | None] = mapped_column(String(200), nullable=True)
    heading: Mapped[str | None] = mapped_column(String(300), nullable=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    # claim types: usage_instruction | frequency | ingredient | effect | irritancy
    # | order_dependency | storage | life_extension
    claim_types: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    # Machine readable claims copied verbatim from the reviewed source, e.g.
    # {"ingredients": [{"inci": "Niacinamide", "role": "active", "period": "any"}],
    #  "frequency": "每日一次", "order_hint": "after_cleanser"}
    # Only read from approved sources; nothing here is inferred by the model.
    structured: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class IngredientProfile(Base, UUIDMixin, TimestampMixin, VersionMixin):
    __tablename__ = "ingredient_profiles"

    inci_name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    common_name: Mapped[str] = mapped_column(String(200), nullable=False)
    # [{"text": ..., "source_id": ..., "reviewed_at": ...}]
    known_effects: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    # none | low | moderate | high | unknown
    irritant_level: Mapped[str] = mapped_column(String(32), default="unknown", nullable=False)
    irritant_notes: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    # reviewed life-scenario extensions; each entry must carry an approved source_id
    life_extensions: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    source_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    # approved | pending | pending_review | insufficient
    approval_status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False, index=True)
    conflict_flag: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    conflict_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    categories: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    # Nullable ordering hint used by combination reasoning (e.g. spf last)
    typical_period: Mapped[str | None] = mapped_column(String(32), nullable=True)


class UserIngredientSignal(Base, UUIDMixin, TimestampMixin):
    """Derived per-user statistic. Only a signal, never causal evidence."""

    __tablename__ = "user_ingredient_signals"

    tenant_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    user_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    ingredient_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("ingredient_profiles.id"), index=True, nullable=False
    )
    # positive | negative
    signal_type: Mapped[str] = mapped_column(String(16), nullable=False)
    event_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_occurred_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    contributing_event_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    computed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    invalidated_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    invalidation_reason: Mapped[str | None] = mapped_column(String(120), nullable=True)


class SystemSetting(Base, TimestampMixin):
    """Internal mutable settings such as the demo clock. Never user scoped."""

    __tablename__ = "system_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    updated_by: Mapped[str | None] = mapped_column(String(36), nullable=True)


class City(Base, UUIDMixin, TimestampMixin):
    """Reviewed location catalog for manual city selection (no device tracking)."""

    __tablename__ = "cities"

    city_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    name_zh: Mapped[str] = mapped_column(String(120), nullable=False)
    name_en: Mapped[str] = mapped_column(String(120), nullable=False)
    country: Mapped[str] = mapped_column(String(64), nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    forecast_days: Mapped[int] = mapped_column(Integer, default=3, nullable=False)


class FixedJobLock(Base, TimestampMixin):
    """Single-row lease used to keep one scheduler active per database."""

    __tablename__ = "fixed_job_locks"

    name: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner: Mapped[str | None] = mapped_column(String(64), nullable=True)
    locked_until: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
