"""客服交接：草稿摘要、用户确认提交、本地演示工单与客服视图。

模拟提交只说明内容进入了本地演示工作台（adapter_mode=local_demo），
不得声称品牌方已收到；用户是否真正解决独立存储（user_confirmed_resolution）。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    MemoryRecord,
    OwnedProduct,
    ReviewPrompt,
    RoutinePlan,
    RoutineStep,
    ServiceTicket,
    TicketEvent,
    UsageEvent,
)
from . import audit
from . import cabinet as cabinet_service
from . import routine_service
from .clock import now as clock_now
from .errors import ValidationError, VersionConflictError, not_found

TICKET_STATUS = {
    "draft",
    "submitted",
    "awaiting_user",
    "in_review",
    "resolved",
    "cancelled",
}
STAFF_TRANSITIONS = {
    "submitted": {"in_review", "awaiting_user", "resolved", "cancelled"},
    "in_review": {"awaiting_user", "resolved", "cancelled"},
    "awaiting_user": {"in_review", "resolved", "cancelled"},
    "resolved": {"in_review"},
    "cancelled": set(),
    "draft": set(),
}


def _collect_products(db: Session, *, tenant_id: str, user_id: str, owned_ids: Sequence[str]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for owned_id in owned_ids:
        product = db.get(OwnedProduct, owned_id)
        if product is None or product.tenant_id != tenant_id or product.user_id != user_id:
            raise not_found("产品实例")
        out.append(
            {
                "owned_product_id": product.id,
                "name": product.custom_name,
                "usage_status": product.usage_status,
                "lifecycle_status": product.lifecycle_status,
                "review_flag": product.review_flag,
                "ingredient_source_status": product.ingredient_source_status,
                "key_actives": list(product.key_actives or []),
            }
        )
    return out


def build_summary(
    db: Session,
    *,
    tenant_id: str,
    user_id: str,
    included_record_ids: Iterable[str],
    request_text: str,
) -> dict[str, Any]:
    ids = [i for i in dict.fromkeys(included_record_ids) if i]
    events: list[UsageEvent] = []
    memories: list[MemoryRecord] = []
    owned_ids: list[str] = []
    for record_id in ids:
        event = db.get(UsageEvent, record_id)
        if event is not None and event.tenant_id == tenant_id and event.user_id == user_id:
            events.append(event)
            owned_ids.extend(event.owned_product_ids or [])
            continue
        memory = db.get(MemoryRecord, record_id)
        if memory is not None and memory.tenant_id == tenant_id and memory.user_id == user_id:
            memories.append(memory)
            continue
        product = db.get(OwnedProduct, record_id)
        if product is not None and product.tenant_id == tenant_id and product.user_id == user_id:
            owned_ids.append(product.id)
            continue
        raise not_found("记录")
    plan = db.execute(
        select(RoutinePlan).where(
            RoutinePlan.tenant_id == tenant_id,
            RoutinePlan.user_id == user_id,
            RoutinePlan.status == "active",
        )
    ).scalar_one_or_none()
    steps: list[RoutineStep] = []
    if plan is not None:
        steps = list(db.execute(select(RoutineStep).where(RoutineStep.plan_id == plan.id)).scalars())
    prompts = list(
        db.execute(
            select(ReviewPrompt).where(
                ReviewPrompt.tenant_id == tenant_id,
                ReviewPrompt.user_id == user_id,
                ReviewPrompt.status == "open",
            )
        ).scalars()
    )
    already_done = ["已保存使用反馈并生成复核询问" if prompts else "已保存当前计划版本"]
    summary = {
        "request": request_text,
        "products": _collect_products(db, tenant_id=tenant_id, user_id=user_id, owned_ids=owned_ids),
        "user_reports": [
            {
                "event_id": e.id,
                "event_type": e.event_type,
                "reported_text": e.reported_text,
                "occurred_at": e.occurred_at.isoformat() if e.occurred_at else None,
                "time_precision": e.time_precision,
                "severity": e.severity,
                "provenance": e.provenance,
            }
            for e in events
        ],
        "memory_records": [
            {"memory_id": m.id, "kind": m.kind, "key": m.key, "value": m.value.get("value"), "status": m.status}
            for m in memories
        ],
        "plan": (
            {
                "plan_id": plan.id,
                "version": plan.version,
                "step_count": len(steps),
                "steps": [
                    {"label": s.label, "period": s.period, "frequency": s.frequency, "review_flag": s.review_flag}
                    for s in steps
                ],
            }
            if plan
            else None
        ),
        "open_review_prompts": [
            {"prompt_id": p.id, "question": p.question, "options": p.options} for p in prompts
        ],
        "actions_already_taken": already_done,
        "awaiting_from_user": ["确认是否已解决", "补充发生时间或使用组合（如需要）"],
        "disclaimer": "以上内容来自你确认包含的记录，均为用户报告而非诊断结论。",
    }
    return summary


def draft_handoff(
    db: Session,
    *,
    tenant_id: str,
    user_id: str,
    included_record_ids: Sequence[str],
    request_text: str,
    actor: str | None = None,
) -> ServiceTicket:
    if not included_record_ids:
        raise ValidationError("请至少选择一条要包含的记录")
    summary = build_summary(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        included_record_ids=included_record_ids,
        request_text=request_text,
    )
    ticket = ServiceTicket(
        tenant_id=tenant_id,
        user_id=user_id,
        status="draft",
        summary=summary,
        included_record_ids=list(included_record_ids),
        adapter_mode="local_demo",
        next_action="等待用户预览确认",
    )
    db.add(ticket)
    db.flush()
    db.add(
        TicketEvent(
            ticket_id=ticket.id,
            actor_user_id=user_id,
            actor_role="consumer",
            action="draft_created",
            to_status="draft",
            note="用户预览草稿，尚未提交",
        )
    )
    db.flush()
    audit.record(
        db,
        action="handoff.draft_created",
        actor_user_id=actor or user_id,
        tenant_id=tenant_id,
        entity_type="service_ticket",
        entity_id=ticket.id,
        meta={"records": len(included_record_ids)},
    )
    return ticket


def submit_handoff(
    db: Session,
    *,
    ticket: ServiceTicket,
    expected_version: int | None,
    included_record_ids: Sequence[str] | None = None,
    actor: str | None = None,
) -> ServiceTicket:
    if ticket.status != "draft":
        raise VersionConflictError(
            "该交接草稿已被处理，请刷新查看当前工单状态。",
            details={"status": ticket.status, "ticket_id": ticket.id},
        )
    if expected_version is not None and ticket.version != expected_version:
        raise VersionConflictError(
            "工单版本不一致，请刷新", details={"expected": expected_version, "actual": ticket.version}
        )
    if included_record_ids is not None:
        ticket.included_record_ids = list(included_record_ids)
        ticket.summary = build_summary(
            db,
            tenant_id=ticket.tenant_id,
            user_id=ticket.user_id,
            included_record_ids=included_record_ids,
            request_text=ticket.summary.get("request", ""),
        )
    ticket.status = "submitted"
    ticket.submitted_at = clock_now(db)
    ticket.external_id = f"LOCAL-DEMO-{ticket.id[:8].upper()}"
    ticket.next_action = "本地演示工作台待处理"
    db.flush()
    db.add(
        TicketEvent(
            ticket_id=ticket.id,
            actor_user_id=ticket.user_id,
            actor_role="consumer",
            action="submitted",
            from_status="draft",
            to_status="submitted",
            note="用户确认提交，进入本地演示工作台（非品牌系统）",
        )
    )
    db.flush()
    audit.record(
        db,
        action="handoff.submitted",
        actor_user_id=actor or ticket.user_id,
        tenant_id=ticket.tenant_id,
        entity_type="service_ticket",
        entity_id=ticket.id,
        meta={"adapter_mode": ticket.adapter_mode, "external_id": ticket.external_id},
    )
    return ticket


def list_tickets(db: Session, *, tenant_id: str, user_id: str) -> list[ServiceTicket]:
    return list(
        db.execute(
            select(ServiceTicket)
            .where(ServiceTicket.tenant_id == tenant_id, ServiceTicket.user_id == user_id)
            .order_by(ServiceTicket.created_at.desc())
        ).scalars()
    )


def get_ticket(db: Session, *, tenant_id: str, user_id: str, ticket_id: str) -> ServiceTicket:
    row = db.get(ServiceTicket, ticket_id)
    if row is None or row.tenant_id != tenant_id or row.user_id != user_id:
        raise not_found("工单")
    return row


def ticket_timeline(db: Session, ticket_id: str) -> list[TicketEvent]:
    return list(
        db.execute(
            select(TicketEvent).where(TicketEvent.ticket_id == ticket_id).order_by(TicketEvent.created_at)
        ).scalars()
    )


def staff_update(
    db: Session,
    *,
    ticket: ServiceTicket,
    status: str,
    note: str | None,
    actor_user_id: str,
    actor_role: str = "staff",
) -> ServiceTicket:
    if status not in TICKET_STATUS:
        raise ValidationError(f"未知工单状态：{status}")
    allowed = STAFF_TRANSITIONS.get(ticket.status, set())
    if status != ticket.status and status not in allowed:
        raise ValidationError(f"不允许从 {ticket.status} 变更为 {status}")
    previous = ticket.status
    ticket.status = status
    if status == "resolved":
        ticket.resolved_at = clock_now(db)
        ticket.next_action = "等待用户确认是否已解决"
    elif status == "awaiting_user":
        ticket.next_action = "等待用户补充信息"
    elif status == "in_review":
        ticket.next_action = "客服处理中"
    elif status == "cancelled":
        ticket.next_action = None
    db.flush()
    db.add(
        TicketEvent(
            ticket_id=ticket.id,
            actor_user_id=actor_user_id,
            actor_role=actor_role,
            action="status_changed",
            from_status=previous,
            to_status=status,
            note=note,
        )
    )
    db.flush()
    audit.record(
        db,
        action="handoff.staff_updated",
        actor_user_id=actor_user_id,
        actor_role=actor_role,
        tenant_id=ticket.tenant_id,
        entity_type="service_ticket",
        entity_id=ticket.id,
        meta={"from": previous, "to": status},
    )
    return ticket


def confirm_resolution(
    db: Session, *, ticket: ServiceTicket, resolved: bool, note: str | None, actor: str | None
) -> ServiceTicket:
    ticket.user_confirmed_resolution = resolved
    ticket.user_confirmed_at = clock_now(db)
    if not resolved and ticket.status == "resolved":
        ticket.status = "in_review"
        ticket.next_action = "用户反馈未解决，重新处理"
    db.flush()
    db.add(
        TicketEvent(
            ticket_id=ticket.id,
            actor_user_id=actor or ticket.user_id,
            actor_role="consumer",
            action="user_confirmed_resolution" if resolved else "user_denied_resolution",
            note=note,
        )
    )
    db.flush()
    return ticket


def serialize_ticket(db: Session, ticket: ServiceTicket, *, include_timeline: bool = True) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": ticket.id,
        "status": ticket.status,
        "summary": ticket.summary,
        "included_record_ids": list(ticket.included_record_ids or []),
        "adapter_mode": ticket.adapter_mode,
        "external_id": ticket.external_id,
        "next_action": ticket.next_action,
        "submitted_at": ticket.submitted_at.isoformat() if ticket.submitted_at else None,
        "resolved_at": ticket.resolved_at.isoformat() if ticket.resolved_at else None,
        "user_confirmed_resolution": ticket.user_confirmed_resolution,
        "escalated": ticket.escalated,
        "version": ticket.version,
        "created_at": ticket.created_at.isoformat(),
        "notice": (
            "本地演示工作台：已提交到本机演示环境，未发送给任何品牌或外部客服系统。"
            if ticket.status != "draft"
            else "草稿：用户确认前不会提交。"
        ),
    }
    if include_timeline:
        payload["timeline"] = [
            {
                "id": e.id,
                "action": e.action,
                "from_status": e.from_status,
                "to_status": e.to_status,
                "note": e.note,
                "actor_role": e.actor_role,
                "at": e.created_at.isoformat(),
            }
            for e in ticket_timeline(db, ticket.id)
        ]
    return payload


def staff_queue(db: Session, *, tenant_id: str) -> list[ServiceTicket]:
    return list(
        db.execute(
            select(ServiceTicket)
            .where(ServiceTicket.tenant_id == tenant_id, ServiceTicket.status != "draft")
            .order_by(ServiceTicket.created_at.desc())
        ).scalars()
    )


def suggest_records(db: Session, *, tenant_id: str, user_id: str) -> dict[str, Any]:
    """Candidate records the user may choose to include in a handoff."""
    events = list(
        db.execute(
            select(UsageEvent)
            .where(
                UsageEvent.tenant_id == tenant_id,
                UsageEvent.user_id == user_id,
                UsageEvent.invalidated_at.is_(None),
            )
            .order_by(UsageEvent.created_at.desc())
            .limit(20)
        ).scalars()
    )
    products = cabinet_service.list_owned(db, tenant_id=tenant_id, user_id=user_id)
    memories = list(
        db.execute(
            select(MemoryRecord).where(
                MemoryRecord.tenant_id == tenant_id,
                MemoryRecord.user_id == user_id,
                MemoryRecord.status == "active",
            )
        ).scalars()
    )
    return {
        "records": [
            {
                "id": e.id,
                "type": "usage_event",
                "label": f"{e.event_type}：{e.reported_text[:40]}",
                "occurred_at": e.occurred_at.isoformat() if e.occurred_at else None,
            }
            for e in events
        ]
        + [
            {
                "id": m.id,
                "type": "memory_record",
                "label": f"{m.value.get('label') or m.key} = {m.value.get('value')}",
                "occurred_at": None,
            }
            for m in memories
        ]
        + [
            {
                "id": p.id,
                "type": "owned_product",
                "label": p.custom_name,
                "occurred_at": None,
            }
            for p in products
        ],
        "default_selection": [e.id for e in events[:3]] or [m.id for m in memories[:2]],
    }
