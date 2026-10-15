"""Routine plans and steps."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TenantMixin, TimestampMixin, UTCDateTime, UUIDMixin


class RoutinePlan(Base, UUIDMixin, TimestampMixin, TenantMixin):
    __tablename__ = "routine_plans"
    # At most one active plan per user, enforced by the database (AC07).
    __table_args__ = (
        Index(
            "uq_active_routine_per_user",
            "tenant_id",
            "user_id",
            unique=True,
            sqlite_where=text("status = 'active'"),
            postgresql_where=text("status = 'active'"),
        ),
    )

    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    # draft | active | superseded | rejected | stale
    status: Mapped[str] = mapped_column(String(16), default="draft", nullable=False, index=True)
    parent_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    base_profile_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    input_snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    reasons: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    diff: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    pending_products: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    combination_notes: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    review_notes: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    uncertainties: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    trigger: Mapped[str] = mapped_column(String(40), default="user_request", nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    superseded_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    rejected_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    needs_review_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    model_mode: Mapped[str] = mapped_column(String(16), default="mock", nullable=False)


class RoutineStep(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "routine_steps"

    plan_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("routine_plans.id"), index=True, nullable=False
    )
    # morning | evening | weekly | as_needed
    period: Mapped[str] = mapped_column(String(16), nullable=False)
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    owned_product_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    catalog_product_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    instruction: Mapped[str] = mapped_column(Text, nullable=False)
    frequency: Mapped[str | None] = mapped_column(String(200), nullable=True)
    basis: Mapped[str] = mapped_column(String(400), nullable=False)
    citation_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    review_flag: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_general_advice: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
