"""Memory records and usage events (user reports)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field, field_validator

from ..services import atlas as atlas_service
from ..services import memory_service
from ..services import usage_events as usage_service
from ..services.errors import ValidationError
from .deps import CurrentAuth, DbSession
from .validators import to_utc

router = APIRouter()


class MemoryUpdate(BaseModel):
    value: Any = None
    expected_version: int | None = None


class MemoryConfirm(BaseModel):
    value: Any = None


class UsageEventCreate(BaseModel):
    _normalise = field_validator("occurred_at", mode="after")(lambda v: to_utc(v))

    reported_text: str = Field(min_length=1, max_length=2000)
    owned_product_ids: list[str] = Field(default_factory=list)
    occurred_at: datetime | None = None
    time_precision: Literal["unknown", "day", "exact", "approximate"] = "unknown"
    event_type: Literal["positive", "negative", "neutral", "uncertain"] | None = None


def _serialize(record) -> dict[str, Any]:
    return {
        "id": record.id,
        "kind": record.kind,
        "key": record.key,
        "value": record.value.get("value"),
        "label": record.value.get("label"),
        "provenance_type": record.provenance_type,
        "source_ref": record.source_ref,
        "source_excerpt": record.source_excerpt,
        "occurred_at": record.occurred_at.isoformat() if record.occurred_at else None,
        "valid_from": record.valid_from.isoformat() if record.valid_from else None,
        "valid_to": record.valid_to.isoformat() if record.valid_to else None,
        "status": record.status,
        "confidence": record.confidence,
        "supersedes_id": record.supersedes_id,
        "superseded_by_id": record.superseded_by_id,
        "version": record.version,
        "created_at": record.created_at.isoformat(),
        "is_current": record.status == "active",
    }


@router.get("/memories")
def list_memories(
    auth: CurrentAuth,
    db: DbSession,
    include_history: bool = Query(default=True),
    kind: list[str] | None = Query(default=None),
) -> dict[str, Any]:
    rows = memory_service.list_records(
        db, tenant_id=auth.tenant_id, user_id=auth.user_id, include_history=include_history
    )
    if kind:
        rows = [r for r in rows if r.kind in kind]
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(row.kind, []).append(_serialize(row))
    return {
        "records": [_serialize(r) for r in rows],
        "grouped": grouped,
        "notice": (
            "历史版本仍可查看，但只有 status=active 的记录参与当前上下文；"
            "模型推测只以 pending 形式存在，不会成为已确认事实。"
        ),
    }


@router.patch("/memories/{memory_id}")
def update_memory(
    memory_id: str, payload: MemoryUpdate, auth: CurrentAuth, db: DbSession
) -> dict[str, Any]:
    record = memory_service.get_record(
        db, tenant_id=auth.tenant_id, user_id=auth.user_id, record_id=memory_id
    )
    if record.status == "pending_confirmation":
        updated = memory_service.confirm(db, record, value=payload.value)
        db.commit()
        return {"record": _serialize(updated), "notice": "已确认该待确认记录。"}
    updated = memory_service.update_value(db, record, value=payload.value, actor=auth.user_id)
    db.commit()
    return {
        "record": _serialize(updated),
        "superseded": _serialize(record),
        "notice": "已生成新版本；旧值只在历史中显示，不再作为当前值。",
    }


@router.get("/memories/{memory_id}")
def get_memory(memory_id: str, auth: CurrentAuth, db: DbSession) -> dict[str, Any]:
    record = memory_service.get_record(
        db, tenant_id=auth.tenant_id, user_id=auth.user_id, record_id=memory_id
    )
    return {"record": _serialize(record), "lineage": _lineage(db, record)}


def _lineage(db: DbSession, record) -> list[dict[str, Any]]:
    chain: list[dict[str, Any]] = []
    cursor = record
    seen: set[str] = set()
    while cursor is not None and cursor.id not in seen:
        seen.add(cursor.id)
        chain.append({"id": cursor.id, "status": cursor.status, "value": cursor.value.get("value")})
        cursor = db.get(type(record), cursor.supersedes_id) if cursor.supersedes_id else None
    return chain


@router.delete("/memories/{memory_id}")
def delete_memory(memory_id: str, auth: CurrentAuth, db: DbSession) -> dict[str, Any]:
    record = memory_service.get_record(
        db, tenant_id=auth.tenant_id, user_id=auth.user_id, record_id=memory_id
    )
    affected = memory_service.delete_record(db, record, actor=auth.user_id)
    db.commit()
    return {
        "deleted": True,
        "id": memory_id,
        "derived_invalidated": affected,
        "notice": (
            "已删除该记忆，并同步遮盖关联原文、失效派生摘要与图鉴信号；"
            "删除后的内容不会再进入 Agent 上下文，重启后仍保持。"
        ),
    }


@router.get("/usage-events")
def list_usage_events(auth: CurrentAuth, db: DbSession) -> dict[str, Any]:
    rows = usage_service.list_events(db, tenant_id=auth.tenant_id, user_id=auth.user_id)
    return {
        "events": [usage_service.serialize(e) for e in rows],
        "notice": "这些是你报告的体验记录，不是诊断结论，也不代表因果关系。",
    }


@router.post("/usage-events", status_code=201)
def create_usage_event(
    payload: UsageEventCreate, auth: CurrentAuth, db: DbSession
) -> dict[str, Any]:
    if payload.time_precision != "unknown" and payload.occurred_at is None:
        raise ValidationError("指定了时间精度但未提供发生时间")
    event, prompt, guidance = usage_service.create_event(
        db,
        tenant_id=auth.tenant_id,
        user_id=auth.user_id,
        reported_text=payload.reported_text,
        owned_product_ids=payload.owned_product_ids,
        occurred_at=payload.occurred_at,
        time_precision=payload.time_precision,
        event_type=payload.event_type,
        actor=auth.user_id,
    )
    db.commit()
    return {
        "event": usage_service.serialize(event),
        "review_prompt": (
            {
                "id": prompt.id,
                "question": prompt.question,
                "options": prompt.options,
                "owned_product_id": prompt.owned_product_id,
                "plan_id": prompt.plan_id,
            }
            if prompt
            else None
        ),
        "guidance": guidance,
        "notice": "反馈不会自动修改计划；如涉及计划内产品，会生成复核询问等待你选择。",
    }


@router.delete("/usage-events/{event_id}")
def delete_usage_event(event_id: str, auth: CurrentAuth, db: DbSession) -> dict[str, Any]:
    event = usage_service.get_event(db, tenant_id=auth.tenant_id, user_id=auth.user_id, event_id=event_id)
    invalidated = usage_service.remove_event(db, event, reason="user_forget", actor=auth.user_id)
    db.commit()
    return {
        "deleted": True,
        "id": event_id,
        "derived_invalidated": {
            "signals": invalidated,
            "atlas_views_marked_stale": 1,
            "review_prompts_dismissed": True,
        },
        "notice": "依赖该事件的成分信号已失效，图鉴将在下次查看时重新生成。",
    }


@router.get("/ingredient-feedback")
def list_ingredient_feedback(auth: CurrentAuth, db: DbSession) -> dict[str, Any]:
    from sqlalchemy import select

    from ..models import IngredientFeedback

    rows = list(
        db.execute(
            select(IngredientFeedback).where(
                IngredientFeedback.tenant_id == auth.tenant_id,
                IngredientFeedback.user_id == auth.user_id,
                IngredientFeedback.status == "active",
            )
        ).scalars()
    )
    return {
        "records": [
            {
                "id": r.id,
                "ingredient_id": r.ingredient_id,
                "statement": r.statement,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ]
    }


@router.get("/ingredient-feedback/{record_id}")
def get_ingredient_feedback(record_id: str, auth: CurrentAuth, db: DbSession) -> dict[str, Any]:
    from ..models import IngredientFeedback

    row = db.get(IngredientFeedback, record_id)
    if row is None or row.tenant_id != auth.tenant_id or row.user_id != auth.user_id:
        from ..services.errors import not_found

        raise not_found("成分补充说明")
    return {
        "id": row.id,
        "ingredient_id": row.ingredient_id,
        "statement": row.statement,
        "profile": atlas_service.get_ingredient(db, row.ingredient_id),
    }


@router.delete("/ingredient-feedback/{record_id}")
def delete_ingredient_feedback(record_id: str, auth: CurrentAuth, db: DbSession) -> dict[str, Any]:
    from ..models import IngredientFeedback

    row = db.get(IngredientFeedback, record_id)
    if row is None or row.tenant_id != auth.tenant_id or row.user_id != auth.user_id:
        from ..services.errors import not_found

        raise not_found("成分补充说明")
    row.status = "deleted"
    atlas_service.mark_views_stale(db, tenant_id=auth.tenant_id, user_id=auth.user_id)
    db.commit()
    return {"deleted": True, "id": record_id}
