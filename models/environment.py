"""Environment: locations, activities, snapshots, trigger rules."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TenantMixin, TimestampMixin, UTCDateTime, UUIDMixin, VersionMixin


class LocationPreference(Base, UUIDMixin, TimestampMixin, VersionMixin, TenantMixin):
    __tablename__ = "location_preferences"

    city_id: Mapped[str] = mapped_column(String(64), nullable=False)
    city_name: Mapped[str] = mapped_column(String(120), nullable=False)
    country: Mapped[str] = mapped_column(String(64), default="CN", nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Shanghai", nullable=False)
    latitude: Mapped[float] = mapped_column(nullable=False)
    longitude: Mapped[float] = mapped_column(nullable=False)
    # home | travel | unset
    purpose: Mapped[str] = mapped_column(String(24), default="home", nullable=False)
    # manual | device_precise (opt-in, one-shot)
    provenance: Mapped[str] = mapped_column(String(24), default="manual", nullable=False)
    consent_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class Activity(Base, UUIDMixin, TimestampMixin, VersionMixin, TenantMixin):
    __tablename__ = "activities"

    # outdoor | trip
    activity_type: Mapped[str] = mapped_column(String(24), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    starts_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    ends_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    destination_city_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    destination_city_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    destination_timezone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    origin_city_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # User confirmation is mandatory: the system never infers outdoor exposure.
    user_confirmed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # planned | cancelled | completed | expired
    status: Mapped[str] = mapped_column(String(24), default="planned", nullable=False, index=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    carry_notes: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    consent_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)


class EnvironmentSnapshot(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "environment_snapshots"

    # Public environment cache carries no user id and no feedback.
    tenant_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    location_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    city_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    # mock | live
    mode: Mapped[str] = mapped_column(String(8), default="mock", nullable=False)
    # current | forecast
    kind: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    issued_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    valid_from: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    valid_to: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Shanghai", nullable=False)
    units: Mapped[dict[str, str]] = mapped_column(JSON, default=dict, nullable=False)
    # Nullable metrics: unknown is never replaced by zero.
    metrics: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    # ok | partial | unavailable | stale
    quality: Mapped[str] = mapped_column(String(16), default="ok", nullable=False)
    missing_fields: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)


class TriggerRule(Base, UUIDMixin, TimestampMixin, VersionMixin):
    __tablename__ = "trigger_rules"

    service_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    conditions: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    # demo_rule | reviewed_business_rule | medical_guideline
    threshold_source: Mapped[str] = mapped_column(String(40), default="demo_rule", nullable=False)
    # demo | approved
    approval_status: Mapped[str] = mapped_column(String(16), default="demo", nullable=False)
    cooldown_minutes: Mapped[int] = mapped_column(Integer, default=1440, nullable=False)
    min_interval_minutes: Mapped[int] = mapped_column(Integer, default=1440, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
