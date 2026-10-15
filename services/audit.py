"""Audit log. Content free by design: no uploads, no message text, no contacts."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from ..models import AuditEvent


def record(
    db: Session,
    *,
    action: str,
    actor_user_id: str | None = None,
    actor_role: str = "system",
    tenant_id: str | None = None,
    entity_type: str | None = None,
    entity_id: str | None = None,
    meta: dict[str, Any] | None = None,
) -> AuditEvent:
    row = AuditEvent(
        action=action,
        actor_user_id=actor_user_id,
        actor_role=actor_role,
        tenant_id=tenant_id,
        entity_type=entity_type,
        entity_id=entity_id,
        meta=meta or {},
    )
    db.add(row)
    db.flush()
    return row
