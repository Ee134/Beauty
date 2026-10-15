"""Privacy: full export and irreversible deletion of all business content.

Deletion covers conversation text, uploads, plans, memory, events, tickets,
follow ups, messages, subscriptions, locations, activities, atlas views and
signals, brand drafts and caches. Shared catalog rows and other users' data are
never deleted. Only a content free audit record remains.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..config import Settings, get_settings
from ..models import (
    Activity,
    AgentRun,
    BrandInsightDraft,
    Conversation,
    FollowUpTask,
    ImportBatch,
    IngredientAtlasView,
    IngredientFeedback,
    LocationPreference,
    MemoryRecord,
    Message,
    NotificationDelivery,
    NotificationOutbox,
    NotificationPreference,
    OwnedProduct,
    ProactiveDecision,
    PushSubscription,
    ReviewPrompt,
    RoutinePlan,
    RoutineStep,
    ServiceMessage,
    ServiceTicket,
    TicketEvent,
    UsageEvent,
    User,
    UserIngredientSignal,
    UserSession,
)
from . import audit
from .clock import now as clock_now

USER_SCOPED_MODELS = [
    OwnedProduct,
    ImportBatch,
    Conversation,
    Message,
    MemoryRecord,
    UsageEvent,
    IngredientFeedback,
    IngredientAtlasView,
    ReviewPrompt,
    RoutinePlan,
    FollowUpTask,
    ServiceTicket,
    AgentRun,
    LocationPreference,
    Activity,
    NotificationPreference,
    PushSubscription,
    ProactiveDecision,
    ServiceMessage,
    NotificationOutbox,
    NotificationDelivery,
    BrandInsightDraft,
]


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def export_user_data(db: Session, *, tenant_id: str, user_id: str) -> dict[str, Any]:
    user = db.get(User, user_id)
    if user is None or user.tenant_id != tenant_id:
        from .errors import not_found

        raise not_found("用户")
    from . import atlas as atlas_service
    from . import cabinet as cabinet_service
    from . import routine_service
    from . import tickets as ticket_service
    from . import usage_events as usage_service

    products = cabinet_service.list_owned(db, tenant_id=tenant_id, user_id=user_id, include_deleted=True)
    plans = routine_service.list_plans(db, tenant_id=tenant_id, user_id=user_id)
    messages = list(
        db.execute(
            select(Message)
            .where(Message.tenant_id == tenant_id, Message.user_id == user_id)
            .order_by(Message.created_at)
        ).scalars()
    )
    memories = list(
        db.execute(
            select(MemoryRecord).where(
                MemoryRecord.tenant_id == tenant_id, MemoryRecord.user_id == user_id
            )
        ).scalars()
    )
    events = usage_service.list_events(db, tenant_id=tenant_id, user_id=user_id, limit=10_000)
    tickets = ticket_service.list_tickets(db, tenant_id=tenant_id, user_id=user_id)
    activities = list(
        db.execute(
            select(Activity).where(Activity.tenant_id == tenant_id, Activity.user_id == user_id)
        ).scalars()
    )
    location = db.execute(
        select(LocationPreference).where(
            LocationPreference.tenant_id == tenant_id, LocationPreference.user_id == user_id
        )
    ).scalars().first()
    return {
        "exported_at": clock_now(db).isoformat(),
        "user": {
            "id": user.id,
            "email": user.email,
            "display_name": user.display_name,
            "timezone": user.timezone,
            "role": user.role,
            "consent_flags": user.consent_flags,
        },
        "owned_products": [cabinet_service.serialize(p) for p in products],
        "routine_plans": [routine_service.serialize_plan(db, p) for p in plans],
        "memories": [
            {
                "id": m.id,
                "kind": m.kind,
                "key": m.key,
                "value": m.value,
                "status": m.status,
                "provenance_type": m.provenance_type,
                "valid_from": _iso(m.valid_from),
                "valid_to": _iso(m.valid_to),
            }
            for m in memories
        ],
        "usage_events": [usage_service.serialize(e) for e in events],
        "conversations": [
            {
                "id": m.id,
                "role": m.role,
                "content": m.content,
                "sequence": m.sequence,
                "redacted": m.redacted_at is not None,
                "created_at": m.created_at.isoformat(),
            }
            for m in messages
        ],
        "tickets": [ticket_service.serialize_ticket(db, t) for t in tickets],
        "activities": [
            {
                "id": a.id,
                "type": a.activity_type,
                "title": a.title,
                "starts_at": a.starts_at.isoformat(),
                "status": a.status,
            }
            for a in activities
        ],
        "location": (
            {"city_id": location.city_id, "city_name": location.city_name, "provenance": location.provenance}
            if location
            else None
        ),
        "ingredient_atlas": atlas_service.build_payload(
            db, tenant_id=tenant_id, user_id=user_id, persist=False
        ),
        "notice": "导出包含你的业务数据与派生内容；演示数据已标注 is_demo。",
    }


def delete_user_data(
    db: Session, *, tenant_id: str, user_id: str, actor: str | None = None, settings: Settings | None = None
) -> dict[str, Any]:
    settings = settings or get_settings()
    counts: dict[str, int] = {}
    now = clock_now(db)

    # uploaded files
    batches = list(
        db.execute(
            select(ImportBatch).where(
                ImportBatch.tenant_id == tenant_id, ImportBatch.user_id == user_id
            )
        ).scalars()
    )
    files_removed = 0
    import os

    for batch in batches:
        if batch.storage_key:
            path = settings.upload_path / os.path.basename(batch.storage_key)
            try:
                path.unlink()
                files_removed += 1
            except FileNotFoundError:
                pass
    counts["uploaded_files"] = files_removed

    # child rows without tenant columns
    plans = list(
        db.execute(
            select(RoutinePlan.id).where(
                RoutinePlan.tenant_id == tenant_id, RoutinePlan.user_id == user_id
            )
        ).scalars()
    )
    if plans:
        db.execute(delete(RoutineStep).where(RoutineStep.plan_id.in_(plans)))
    tickets = list(
        db.execute(
            select(ServiceTicket.id).where(
                ServiceTicket.tenant_id == tenant_id, ServiceTicket.user_id == user_id
            )
        ).scalars()
    )
    if tickets:
        db.execute(delete(TicketEvent).where(TicketEvent.ticket_id.in_(tickets)))
    outbox = list(
        db.execute(
            select(NotificationOutbox.id).where(
                NotificationOutbox.tenant_id == tenant_id, NotificationOutbox.user_id == user_id
            )
        ).scalars()
    )
    if outbox:
        db.execute(delete(NotificationDelivery).where(NotificationDelivery.outbox_id.in_(outbox)))
    db.flush()

    for model in USER_SCOPED_MODELS:
        result = db.execute(
            delete(model).where(model.tenant_id == tenant_id, model.user_id == user_id)
        )
        counts[model.__tablename__] = result.rowcount or 0
    signals = db.execute(
        delete(UserIngredientSignal).where(
            UserIngredientSignal.tenant_id == tenant_id, UserIngredientSignal.user_id == user_id
        )
    )
    counts["user_ingredient_signals"] = signals.rowcount or 0
    sessions = db.execute(delete(UserSession).where(UserSession.user_id == user_id))
    counts["user_sessions"] = sessions.rowcount or 0
    db.flush()

    audit.record(
        db,
        action="privacy.deleted",
        actor_user_id=actor or user_id,
        tenant_id=tenant_id,
        entity_type="user",
        entity_id=user_id,
        meta={"counts": counts, "at": now.isoformat()},
    )
    return {
        "deleted": True,
        "counts": counts,
        "notice": (
            "已删除你的业务数据、上传文件与派生内容（含图鉴视图、信号、通知与行程）。"
            "共享产品目录和其他用户数据不受影响。"
            "MVP 不保留备份副本；删除立即在本地数据库生效，不可恢复。"
        ),
    }
