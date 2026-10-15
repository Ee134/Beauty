"""Notifications: preferences, push subscriptions, inbox, follow ups and the brand console."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select

from ..insights import service as insights_service
from ..models import FollowUpTask, ServiceMessage
from ..providers.notifications import channel_status
from ..services import proactive as proactive_service
from ..services.errors import ValidationError, not_found
from .deps import BrandAuth, CurrentAuth, DbSession, SettingsDep
from .validators import to_utc

router = APIRouter()


class NotificationPreferencePatch(BaseModel):
    service_types: list[str] | None = None
    channels: list[str] | None = None
    daily_cap: int | None = Field(default=None, ge=0, le=10)
    quiet_hours_start: str | None = None
    quiet_hours_end: str | None = None
    timezone: str | None = None
    marketing_opt_in: bool | None = None
    external_push_enabled: bool | None = None
    muted_service_types: list[str] | None = None
    consent_version: str | None = None
    expected_version: int | None = None


class PushSubscriptionRequest(BaseModel):
    endpoint: str = Field(min_length=8)
    keys: dict[str, Any] | None = None
    device_id: str = "web-default"
    platform: str = "web"


class MessageFeedbackRequest(BaseModel):
    action: Literal["read", "adopt_intent", "reject", "later", "not_helpful", "mute_type"]
    note: str | None = None


class FollowUpCreate(BaseModel):
    _normalise = field_validator("scheduled_at", mode="after")(lambda v: to_utc(v))

    purpose: str = "check_in"
    title: str
    detail: str | None = None
    scheduled_at: datetime | None = None
    related_entity_id: str | None = None
    consent_ref: str | None = None


class FollowUpPatch(BaseModel):
    status: Literal["pending", "done", "cancelled"]


class BrandDraftRequest(BaseModel):
    category: Literal["source_gap", "service_gap", "explicit_product_request", "feature_request"]
    summary: str = Field(min_length=2, max_length=500)
    evidence_refs: list[dict[str, Any]] = Field(default_factory=list)
    explicitness: Literal["explicit", "inferred"] = "explicit"
    brand_scope: str | None = None


class BrandConsentRequest(BaseModel):
    granted: bool
    scope: str | None = None


@router.get("/notification-preferences")
def get_notification_preferences(
    auth: CurrentAuth, db: DbSession, settings: SettingsDep
) -> dict[str, Any]:
    row = proactive_service.get_preferences(
        db, tenant_id=auth.tenant_id, user_id=auth.user_id, settings=settings
    )
    db.commit()
    return {
        "preferences": proactive_service.serialize_preferences(row),
        "channels": channel_status(settings),
        "notice": "默认关闭外部推送；选择渠道与频率后才在授权范围内自动发送。",
    }


@router.put("/notification-preferences")
def update_notification_preferences(
    payload: NotificationPreferencePatch,
    auth: CurrentAuth,
    db: DbSession,
    settings: SettingsDep,
) -> dict[str, Any]:
    row = proactive_service.get_preferences(
        db, tenant_id=auth.tenant_id, user_id=auth.user_id, settings=settings
    )
    changes = payload.model_dump(exclude_unset=True, exclude={"expected_version"})
    proactive_service.update_preferences(
        db, row, changes=changes, expected_version=payload.expected_version, actor=auth.user_id
    )
    db.commit()
    return {
        "preferences": proactive_service.serialize_preferences(row),
        "notice": "撤销授权后，已排队但不再被授权的消息会在发送前取消。",
    }


@router.get("/push-subscriptions")
def list_subscriptions(auth: CurrentAuth, db: DbSession) -> dict[str, Any]:
    from ..models import PushSubscription

    rows = list(
        db.execute(
            select(PushSubscription).where(
                PushSubscription.tenant_id == auth.tenant_id,
                PushSubscription.user_id == auth.user_id,
            )
        ).scalars()
    )
    return {
        "subscriptions": [
            {
                "id": r.id,
                "device_id": r.device_id,
                "platform": r.platform,
                "status": r.status,
                "granted_at": r.granted_at.isoformat() if r.granted_at else None,
                "revoked_at": r.revoked_at.isoformat() if r.revoked_at else None,
            }
            for r in rows
        ],
        "notice": "订阅端点作为敏感凭据加密保存，不会返回浏览器，也不写入普通日志。",
    }


@router.post("/push-subscriptions", status_code=201)
def create_subscription(
    payload: PushSubscriptionRequest, auth: CurrentAuth, db: DbSession
) -> dict[str, Any]:
    row = proactive_service.add_subscription(
        db,
        tenant_id=auth.tenant_id,
        user_id=auth.user_id,
        endpoint=payload.endpoint,
        keys=payload.keys,
        device_id=payload.device_id,
        platform=payload.platform,
        actor=auth.user_id,
    )
    db.commit()
    return {
        "subscription": {"id": row.id, "device_id": row.device_id, "status": row.status, "platform": row.platform},
        "notice": "本地演示：不会向真实推送服务发送。",
    }


@router.delete("/push-subscriptions")
@router.delete("/push-subscriptions/{subscription_id}")
def revoke_subscription(
    auth: CurrentAuth, db: DbSession, subscription_id: str | None = None
) -> dict[str, Any]:
    count = proactive_service.revoke_subscription(
        db, tenant_id=auth.tenant_id, user_id=auth.user_id, subscription_id=subscription_id, actor=auth.user_id
    )
    db.commit()
    return {"revoked": count, "notice": "已撤销设备订阅并取消不再授权的待发消息。"}


@router.get("/messages")
def list_messages(
    auth: CurrentAuth,
    db: DbSession,
    limit: int = Query(default=20, ge=1, le=100),
    cursor: str | None = None,
) -> dict[str, Any]:
    rows, next_cursor = proactive_service.list_messages(
        db, tenant_id=auth.tenant_id, user_id=auth.user_id, limit=limit, cursor=cursor
    )
    return {
        "messages": [proactive_service.serialize_message(db, m) for m in rows],
        "next_cursor": next_cursor,
        "notice": "所有端共享同一 inbox，状态以服务器为准。",
    }


@router.post("/messages/{message_id}/feedback")
def message_feedback(
    message_id: str, payload: MessageFeedbackRequest, auth: CurrentAuth, db: DbSession
) -> dict[str, Any]:
    from ..models import MessageFeedback
    from ..services.clock import now as clock_now

    message = proactive_service.get_message(
        db, tenant_id=auth.tenant_id, user_id=auth.user_id, message_id=message_id
    )
    now = clock_now(db)
    if payload.action == "read" and message.read_at is None:
        message.read_at = now
        if message.status == "sent":
            message.status = "read"
    if payload.action == "mute_type":
        preference = proactive_service.get_preferences(
            db, tenant_id=auth.tenant_id, user_id=auth.user_id
        )
        service_type = (message.payload or {}).get("service_type")
        if service_type and service_type not in (preference.muted_service_types or []):
            preference.muted_service_types = [*(preference.muted_service_types or []), service_type]
            preference.version += 1
        message.status = "cancelled"
    db.add(
        MessageFeedback(
            tenant_id=auth.tenant_id,
            user_id=auth.user_id,
            message_id=message.id,
            action=payload.action,
            occurred_at=now,
            note=payload.note,
        )
    )
    db.flush()
    db.commit()
    return {
        "message": proactive_service.serialize_message(db, message),
        "notice": (
            "「采用」只记录你的意向，计划只有通过接受 API 才会生效；"
            "忽略或未读不会改变任何产品状态。"
        ),
    }


@router.get("/followups")
def list_followups(auth: CurrentAuth, db: DbSession) -> dict[str, Any]:
    rows = list(
        db.execute(
            select(FollowUpTask)
            .where(FollowUpTask.tenant_id == auth.tenant_id, FollowUpTask.user_id == auth.user_id)
            .order_by(FollowUpTask.created_at.desc())
        ).scalars()
    )
    return {
        "followups": [
            {
                "id": r.id,
                "purpose": r.purpose,
                "title": r.title,
                "detail": r.detail,
                "status": r.status,
                "scheduled_at": r.scheduled_at.isoformat() if r.scheduled_at else None,
                "related_entity_id": r.related_entity_id,
            }
            for r in rows
        ]
    }


@router.post("/followups", status_code=201)
def create_followup(payload: FollowUpCreate, auth: CurrentAuth, db: DbSession) -> dict[str, Any]:
    row = FollowUpTask(
        tenant_id=auth.tenant_id,
        user_id=auth.user_id,
        purpose=payload.purpose,
        title=payload.title,
        detail=payload.detail,
        scheduled_at=payload.scheduled_at,
        related_entity_id=payload.related_entity_id,
        status="pending",
        consent_ref=payload.consent_ref,
    )
    db.add(row)
    db.flush()
    db.commit()
    return {
        "followup": {"id": row.id, "title": row.title, "status": row.status},
        "notice": "跟进任务进入统一主动服务决策与通知管线。",
    }


@router.patch("/followups/{followup_id}")
def patch_followup(
    followup_id: str, payload: FollowUpPatch, auth: CurrentAuth, db: DbSession
) -> dict[str, Any]:
    row = db.get(FollowUpTask, followup_id)
    if row is None or row.tenant_id != auth.tenant_id or row.user_id != auth.user_id:
        raise not_found("跟进任务")
    row.status = payload.status
    if payload.status == "done":
        from ..services.clock import now as clock_now

        row.completed_at = clock_now(db)
    db.commit()
    return {"followup": {"id": row.id, "status": row.status}}


@router.post("/brand-feedback/drafts", status_code=201)
def create_brand_draft(
    payload: BrandDraftRequest, auth: CurrentAuth, db: DbSession, settings: SettingsDep
) -> dict[str, Any]:
    draft = insights_service.create_draft(
        db,
        tenant_id=auth.tenant_id,
        user_id=auth.user_id,
        category=payload.category,
        summary=payload.summary,
        evidence_refs=payload.evidence_refs,
        explicitness=payload.explicitness,
        brand_scope=payload.brand_scope,
        mode=settings.model_mode,
        actor=auth.user_id,
    )
    db.commit()
    return {
        "draft": insights_service.serialize(draft),
        "notice": "内部草稿：未外发。真实分享需要你确认分享范围。",
    }


@router.get("/brand-feedback/drafts")
def list_brand_drafts(auth: CurrentAuth, db: DbSession) -> dict[str, Any]:
    rows = insights_service.list_for_user(db, tenant_id=auth.tenant_id, user_id=auth.user_id)
    return {"drafts": [insights_service.serialize(r) for r in rows]}


@router.post("/brand-feedback/{draft_id}/consent")
def brand_feedback_consent(
    draft_id: str, payload: BrandConsentRequest, auth: CurrentAuth, db: DbSession
) -> dict[str, Any]:
    draft = insights_service.get_draft(db, tenant_id=auth.tenant_id, draft_id=draft_id, user_id=auth.user_id)
    insights_service.set_consent(
        db, draft=draft, granted=payload.granted, scope=payload.scope, actor=auth.user_id
    )
    db.commit()
    return {
        "draft": insights_service.serialize(draft),
        "notice": (
            "已同意分享范围，但仍需品牌运营审核后才会外发；"
            "本 MVP 不存在真实外发通道，品牌台只做演示汇总。"
            if payload.granted
            else "已撤回同意：停止未来分享并处理可删除数据；已发送的外部数据撤回取决于接收方能力。"
        ),
    }


@router.get("/brand/insights")
def brand_insights(auth: BrandAuth, db: DbSession, settings: SettingsDep) -> dict[str, Any]:
    return insights_service.aggregate(db, tenant_id=auth.tenant_id, settings=settings)


@router.get("/inbox/summary")
def inbox_summary(auth: CurrentAuth, db: DbSession, settings: SettingsDep) -> dict[str, Any]:
    messages, _cursor = proactive_service.list_messages(
        db, tenant_id=auth.tenant_id, user_id=auth.user_id, limit=10
    )
    unread = [m for m in messages if m.read_at is None and m.status in {"sent", "read"}]
    decisions = proactive_service.followup_due(
        db, tenant_id=auth.tenant_id, user_id=auth.user_id
    )
    return {
        "unread_count": len(unread),
        "messages": [proactive_service.serialize_message(db, m) for m in messages],
        "due_followups": [
            {"id": f.id, "title": f.title, "purpose": f.purpose} for f in decisions
        ],
        "channels": channel_status(settings),
    }
