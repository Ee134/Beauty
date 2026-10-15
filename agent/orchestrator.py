"""Single orchestration agent + deterministic services.

Flow (spec 9.1):
  auth -> run_id + idempotency -> plan (intent + read-only tools + draft writes)
  -> execute tools -> execute draft writes (savepoint) -> compose -> validate
  -> one repair attempt -> persist messages and AgentRun -> standard output.

The model never approves writes. `accept_routine` / `submit_handoff` are only
reachable from the user-facing confirmation APIs.
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import AuthContext
from ..config import Settings, get_settings
from ..environment import service as env_service
from ..insights import service as insights_service
from ..knowledge import service as knowledge
from ..models import (
    AgentRun,
    CatalogProduct,
    Conversation,
    FollowUpTask,
    ImportBatch,
    MemoryRecord,
    Message,
    OwnedProduct,
    ReviewPrompt,
    RoutinePlan,
    ServiceTicket,
    UsageEvent,
)
from ..providers import notifications as notification_providers
from ..providers.model import get_model_provider, model_status
from ..schemas import turn as turn_schemas
from ..services import atlas as atlas_service
from ..services import audit
from ..services import cabinet as cabinet_service
from ..services import memory_service
from ..services import proactive as proactive_service
from ..services import routine_service
from ..services import tickets as ticket_service
from ..services import usage_events as usage_service
from ..services.clock import now as clock_now, snapshot as clock_snapshot
from ..services.errors import AppError, InvalidModelOutputError, ValidationError, not_found
from . import extraction, prompts, tools as tool_module
from .validation import sanitize_answer, validate_turn

MAX_EVIDENCE = 6


@dataclass
class TurnResult:
    output: dict[str, Any]
    run_id: str
    assistant_message_id: str | None
    user_message_id: str | None


def _hash(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
    ).hexdigest()


def _get_or_create_conversation(
    db: Session, *, tenant_id: str, user_id: str, conversation_id: str | None
) -> Conversation:
    if conversation_id:
        conv = db.get(Conversation, conversation_id)
        if conv is None or conv.tenant_id != tenant_id or conv.user_id != user_id:
            raise not_found("会话")
        return conv
    conv = Conversation(tenant_id=tenant_id, user_id=user_id, title="新对话")
    db.add(conv)
    db.flush()
    return conv


def _next_sequence(db: Session, conversation_id: str) -> int:
    rows = list(
        db.execute(
            select(Message.sequence).where(Message.conversation_id == conversation_id)
        ).scalars()
    )
    return (max(rows) + 1) if rows else 1


def _context_summary(db: Session, *, tenant_id: str, user_id: str) -> dict[str, Any]:
    context = memory_service.build_context(db, tenant_id=tenant_id, user_id=user_id)
    products = cabinet_service.list_owned(db, tenant_id=tenant_id, user_id=user_id)
    plan = db.execute(
        select(RoutinePlan).where(
            RoutinePlan.tenant_id == tenant_id,
            RoutinePlan.user_id == user_id,
            RoutinePlan.status == "active",
        )
    ).scalar_one_or_none()
    prompts = list(
        db.execute(
            select(ReviewPrompt).where(
                ReviewPrompt.tenant_id == tenant_id,
                ReviewPrompt.user_id == user_id,
                ReviewPrompt.status == "open",
            )
        ).scalars()
    )
    tickets = ticket_service.list_tickets(db, tenant_id=tenant_id, user_id=user_id)
    return {
        "preferences": context["preferences"],
        "pending_hypotheses": context["pending_hypotheses"],
        "unresolved_events": context["unresolved_events"],
        "recent_events": context["recent_events"][:5],
        "cabinet": [
            {
                "owned_product_id": p.id,
                "name": p.custom_name,
                "usage_status": p.usage_status,
                "lifecycle_status": p.lifecycle_status,
                "ingredient_source_status": p.ingredient_source_status,
                "review_flag": p.review_flag,
            }
            for p in products
        ],
        "active_plan": (
            {"plan_id": plan.id, "version": plan.version, "status": plan.status} if plan else None
        ),
        "open_review_prompts": [
            {"prompt_id": p.id, "question": p.question, "options": p.options, "owned_product_id": p.owned_product_id}
            for p in prompts
        ],
        "tickets": [
            {"ticket_id": t.id, "status": t.status, "adapter_mode": t.adapter_mode} for t in tickets[:5]
        ],
    }


def _recent_messages(db: Session, conversation_id: str) -> list[dict[str, Any]]:
    rows = list(
        db.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id, Message.redacted_at.is_(None))
            .order_by(Message.sequence.desc())
            .limit(8)
        ).scalars()
    )
    return [{"role": m.role, "content": m.content[:400]} for m in reversed(rows)]


# --- write request execution ---------------------------------------------


def _execute_write_requests(
    db: Session,
    *,
    tenant_id: str,
    user_id: str,
    requests: list[dict[str, Any]],
    message: str,
    source_message_id: str,
    settings: Settings,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    results: dict[str, Any] = {}
    events: list[dict[str, Any]] = []
    allowed = {
        "draft_routine",
        "draft_handoff",
        "record_usage_event",
        "create_followup",
        "draft_brand_feedback",
        "propose_proactive_service",
    }
    for request in requests:
        tool_name = request.get("tool")
        args = request.get("args") or {}
        if tool_name not in allowed:
            events.append({"tool": tool_name, "status": "rejected", "reason": "WRITE_TOOL_NOT_ALLOWED"})
            continue
        try:
            if tool_name == "draft_routine":
                draft = routine_service.generate_draft(
                    db,
                    tenant_id=tenant_id,
                    user_id=user_id,
                    actor=user_id,
                    trigger=str(args.get("trigger") or "chat_request"),
                )
                if draft.plan is None:
                    results["routine_draft"] = {
                        "error": "没有可用产品，无法生成计划草稿",
                        "questions": draft.questions,
                    }
                else:
                    results["routine_draft"] = {
                        "plan_id": draft.plan.id,
                        "version": draft.plan.version,
                        "status": draft.plan.status,
                        "step_count": len(draft.steps),
                        "diff_summary": (draft.plan.diff or {}).get("summary"),
                        "pending_count": len(draft.pending_products),
                        "combination_notes": draft.combination_notes,
                        "questions": draft.questions,
                        "uncertainties": draft.uncertainties,
                        "needs_review": draft.plan.needs_review,
                    }
                events.append({"tool": tool_name, "status": "ok"})
            elif tool_name == "record_usage_event":
                text = str(args.get("reported_text") or message)
                products = usage_service.resolve_products_from_text(
                    db, tenant_id=tenant_id, user_id=user_id, text=message
                )
                explicit_ids = [i for i in (args.get("owned_product_ids") or []) if i]
                owned_ids = [p.id for p in products] or explicit_ids
                occurred_at = None
                precision = str(args.get("time_precision") or "unknown")
                if args.get("occurred_at"):
                    try:
                        occurred_at = datetime.fromisoformat(str(args["occurred_at"]))
                    except ValueError:
                        occurred_at = None
                        precision = "unknown"
                event, prompt, guidance = usage_service.create_event(
                    db,
                    tenant_id=tenant_id,
                    user_id=user_id,
                    reported_text=text,
                    owned_product_ids=owned_ids,
                    occurred_at=occurred_at,
                    time_precision=precision,
                    event_type=args.get("event_type"),
                    source_message_id=source_message_id,
                )
                questions: list[dict[str, Any]] = []
                if not owned_ids:
                    questions.append(
                        {
                            "key": "usage_event.product",
                            "question": "你这次说的是哪一件产品？",
                            "why": "需要关联到具体产品实例才能更新计划与图鉴。",
                        }
                    )
                if event.occurred_at is None:
                    questions.append(
                        {
                            "key": "usage_event.time",
                            "question": "大约是什么时候使用的？（可以是「昨晚」这类模糊时间）",
                            "why": "发生时间会影响是否需要调整使用频率；不确定也可以先记为未知。",
                        }
                    )
                results["usage_event"] = {
                    "event_id": event.id,
                    "event_type": event.event_type,
                    "severity": event.severity,
                    "escalated": event.escalated,
                    "guidance": guidance,
                    "questions": questions[:2],
                    "review_prompt": (
                        {
                            "prompt_id": prompt.id,
                            "question": prompt.question,
                            "options": prompt.options,
                            "owned_product_id": prompt.owned_product_id,
                        }
                        if prompt
                        else None
                    ),
                }
                events.append({"tool": tool_name, "status": "ok"})
            elif tool_name == "draft_handoff":
                suggestion = ticket_service.suggest_records(db, tenant_id=tenant_id, user_id=user_id)
                record_ids = [i for i in (args.get("record_ids") or suggestion["default_selection"]) if i]
                ticket = ticket_service.draft_handoff(
                    db,
                    tenant_id=tenant_id,
                    user_id=user_id,
                    included_record_ids=record_ids,
                    request_text=str(args.get("request") or message),
                    actor=user_id,
                )
                results["handoff_draft"] = {
                    "ticket_id": ticket.id,
                    "status": ticket.status,
                    "version": ticket.version,
                    "included_record_ids": record_ids,
                    "candidates": suggestion["records"],
                }
                events.append({"tool": tool_name, "status": "ok"})
            elif tool_name == "create_followup":
                follow = FollowUpTask(
                    tenant_id=tenant_id,
                    user_id=user_id,
                    purpose=str(args.get("purpose") or "check_in"),
                    related_entity_id=args.get("related_entity_id"),
                    title=str(args.get("title") or "跟进提醒"),
                    detail=args.get("detail"),
                    scheduled_at=(
                        datetime.fromisoformat(str(args["scheduled_at"]))
                        if args.get("scheduled_at")
                        else clock_now(db) + timedelta(days=1)
                    ),
                    status="pending",
                    consent_ref=args.get("consent_ref"),
                )
                db.add(follow)
                db.flush()
                results["followup"] = {
                    "id": follow.id,
                    "title": follow.title,
                    "scheduled_at": follow.scheduled_at.isoformat() if follow.scheduled_at else None,
                }
                events.append({"tool": tool_name, "status": "ok"})
            elif tool_name == "draft_brand_feedback":
                category = str(args.get("category") or "feature_request")
                if category == "explicit_product_request":
                    explicitness = "explicit"
                else:
                    explicitness = "inferred"
                draft = insights_service.create_draft(
                    db,
                    tenant_id=tenant_id,
                    user_id=user_id,
                    category=category,
                    summary=str(args.get("text") or message)[:300],
                    evidence_refs=[{"type": "message", "id": source_message_id}],
                    explicitness=explicitness,
                    brand_scope=args.get("brand_scope"),
                    mode=settings.model_mode,
                )
                results["brand_draft"] = insights_service.serialize(draft)
                events.append({"tool": tool_name, "status": "ok"})
            elif tool_name == "propose_proactive_service":
                decision = proactive_service.decide(
                    db,
                    tenant_id=tenant_id,
                    user_id=user_id,
                    service_type=str(args.get("service_type") or "environment_checkin"),
                    event_id=str(args.get("trigger_id") or f"model:{source_message_id}"),
                    context_refs=args.get("context_refs") or [],
                    snapshot_id=args.get("snapshot_id"),
                    citation_ids=args.get("citation_ids") or [],
                    plan_version=proactive_service.active_plan_version(
                        db, tenant_id=tenant_id, user_id=user_id
                    ),
                    payload={
                        "activity_cancelled": False,
                        "snapshot_fresh": bool(args.get("snapshot_fresh")),
                        "owned_product_ids": [],
                        "paused_product_ids": proactive_service.paused_product_ids(
                            db, tenant_id=tenant_id, user_id=user_id
                        ),
                        "useful_after_quiet_hours": False,
                        "model_confidence_ok": False,
                    },
                    settings=settings,
                )
                results["proactive_proposal"] = {
                    "decision": decision,
                    "notice": "模型只能提出候选；发送由后端策略决定，当前不会直接发出。",
                }
                events.append({"tool": tool_name, "status": "ok"})
        except AppError as exc:
            results[tool_name] = {"error": exc.message, "code": exc.code}
            events.append({"tool": tool_name, "status": "error", "code": exc.code})
    return results, events


# --- cards ----------------------------------------------------------------


def _build_cards(
    db: Session,
    *,
    tenant_id: str,
    user_id: str,
    intent: str,
    tool_results: dict[str, Any],
    write_results: dict[str, Any],
    validation_citations: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []

    draft = write_results.get("routine_draft") or {}
    if draft.get("plan_id"):
        plan = db.get(RoutinePlan, draft["plan_id"])
        if plan is not None:
            if plan.status == "draft":
                cards.append(
                    {
                        "type": "routine_draft",
                        "entity_id": plan.id,
                        "version": plan.version,
                        "status": plan.status,
                        "step_count": draft.get("step_count", 0),
                        "diff_summary": draft.get("diff_summary"),
                        "pending_count": draft.get("pending_count", 0),
                        "combination_note_count": len(draft.get("combination_notes") or []),
                        "question_count": len(draft.get("questions") or []),
                    }
                )
            else:
                serialized = routine_service.serialize_plan(db, plan)
                cards.append(
                    {
                        "type": "routine_plan",
                        "entity_id": plan.id,
                        "version": plan.version,
                        "status": plan.status,
                        "steps": serialized["steps"],
                        "pending_products": serialized["pending_products"],
                        "combination_notes": serialized["combination_notes"],
                        "uncertainties": serialized["uncertainties"],
                    }
                )
        for note in draft.get("combination_notes") or []:
            cards.append(
                {
                    "type": "combination_note",
                    "entity_id": None,
                    "ingredient_inci": note.get("ingredient_inci"),
                    "text": note.get("text", ""),
                    "citation_ids": note.get("citation_ids") or [],
                    "options": note.get("options") or [],
                    "decided_by_system": bool(note.get("decided_by_system")),
                }
            )

    active = (tool_results.get("get_active_routine") or {}).get("active_plan")
    if active and not draft.get("plan_id"):
        cards.append(
            {
                "type": "routine_plan",
                "entity_id": active["id"],
                "version": active["version"],
                "status": active["status"],
                "steps": active["steps"],
                "pending_products": active["pending_products"],
                "combination_notes": active["combination_notes"],
                "uncertainties": active["uncertainties"],
            }
        )

    event = write_results.get("usage_event") or {}
    if event.get("event_id"):
        cards.append(
            {
                "type": "audit_summary",
                "entity_id": event["event_id"],
                "headline": "已记录为你报告的体验（非诊断结论）",
                "items": [
                    f"事件类型：{event.get('event_type')}",
                    f"严重程度标记：{event.get('severity')}",
                    event.get("guidance", {}).get("advice", ""),
                ],
            }
        )
        prompt = event.get("review_prompt")
        if prompt:
            cards.append(
                {
                    "type": "review_prompt",
                    "entity_id": prompt["prompt_id"],
                    "question": prompt["question"],
                    "options": prompt.get("options") or [],
                    "owned_product_id": prompt.get("owned_product_id"),
                    "plan_version": active["version"] if active else None,
                }
            )

    handoff = write_results.get("handoff_draft") or {}
    if handoff.get("ticket_id"):
        ticket = db.get(ServiceTicket, handoff["ticket_id"])
        if ticket is not None:
            cards.append(
                {
                    "type": "service_ticket",
                    "entity_id": ticket.id,
                    "status": ticket.status,
                    "adapter_mode": ticket.adapter_mode,
                    "next_action": ticket.next_action,
                    "notice": "草稿：确认后才会提交到本地演示工作台。",
                }
            )

    env = tool_results.get("get_environment") or {}
    if env.get("available") and intent in {"environment", "travel"}:
        current = env.get("current") or {}
        cards.append(
            {
                "type": "environment",
                "entity_id": current.get("id"),
                "city_name": env.get("city_name", ""),
                "city_id": env.get("city_id", ""),
                "quality": current.get("freshness", env.get("quality", "ok")),
                "mode": env.get("mode", "mock"),
                "kind": "current",
                "issued_at": current.get("issued_at"),
                "valid_to": current.get("valid_to"),
                "metrics": current.get("metrics") or {},
                "missing_fields": env.get("missing_fields") or [],
                "notice": env.get("notice"),
            }
        )

    atlas = tool_results.get("build_ingredient_atlas") or {}
    if atlas.get("cards") is not None and intent == "ingredient_atlas":
        cards.append(
            {
                "type": "ingredient_atlas",
                "entity_id": atlas.get("view_id"),
                "version": atlas.get("version"),
                "card_count": atlas.get("stats", {}).get("card_count", 0),
                "below_threshold_count": atlas.get("stats", {}).get("below_threshold_count", 0),
                "pending_count": atlas.get("stats", {}).get("pending_count", 0),
            }
        )
        for card in atlas.get("cards", [])[:5]:
            cards.append(
                {
                    "type": "ingredient",
                    "entity_id": card["ingredient_id"],
                    "inci_name": card["inci_name"],
                    "common_name": card["common_name"],
                    "data_status": card["data_status"],
                    "data_note": card.get("data_note"),
                }
            )

    status = (tool_results.get("get_service_status") or {})
    if intent == "service" and not handoff.get("ticket_id"):
        if status.get("tickets") is not None:
            cards.append(
                {
                    "type": "service_status",
                    "entity_id": None,
                    "ticket_id": status["tickets"][0]["ticket_id"] if status["tickets"] else None,
                    "status": status["tickets"][0]["status"] if status["tickets"] else None,
                    "found": bool(status["tickets"]),
                    "timeline_count": 0,
                    "next_action": status["tickets"][0].get("next_action") if status["tickets"] else None,
                }
            )
        elif status.get("found") is False:
            cards.append(
                {
                    "type": "service_status",
                    "entity_id": None,
                    "ticket_id": status.get("ticket_id"),
                    "status": None,
                    "found": False,
                    "timeline_count": 0,
                    "next_action": None,
                }
            )
        elif status.get("found"):
            cards.append(
                {
                    "type": "service_status",
                    "entity_id": status["ticket_id"],
                    "ticket_id": status["ticket_id"],
                    "status": status.get("status"),
                    "found": True,
                    "timeline_count": len(status.get("timeline") or []),
                    "next_action": status.get("next_action"),
                }
            )

    brand = write_results.get("brand_draft")
    if brand:
        cards.append(
            {
                "type": "audit_summary",
                "entity_id": brand["id"],
                "headline": "已生成内部需求草稿（未外发）",
                "items": [
                    f"类别：{brand['category_label']}",
                    f"明确程度：{'显式表达' if brand['explicitness'] == 'explicit' else '系统推测，需你确认'}",
                    "真实外发需要你单独同意分享范围，并由品牌运营审核。",
                ],
            }
        )

    return cards


def _flatten_strings(value: Any, *, limit: int = 400, cap: int = 2000) -> list[str]:
    """Yield every string in a tool result so injection scanning never truncates it away."""
    out: list[str] = []

    def walk(node: Any) -> None:
        if len(out) >= limit:
            return
        if isinstance(node, str):
            if node.strip():
                out.append(node[:cap])
        elif isinstance(node, dict):
            for item in node.values():
                walk(item)
        elif isinstance(node, (list, tuple, set)):
            for item in node:
                walk(item)

    walk(value)
    return out


def _pending_actions(
    db: Session, *, intent: str, write_results: dict[str, Any], tool_results: dict[str, Any]
) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    draft = write_results.get("routine_draft") or {}
    if draft.get("plan_id"):
        plan = db.get(RoutinePlan, draft["plan_id"])
        if plan is not None and plan.status == "draft":
            actions.append(
                {
                    "type": "accept_routine",
                    "entity_id": plan.id,
                    "expected_version": plan.version,
                    "label": "接受这份草稿（接受后成为当前版本）",
                }
            )
    handoff = write_results.get("handoff_draft") or {}
    if handoff.get("ticket_id"):
        ticket = db.get(ServiceTicket, handoff["ticket_id"])
        if ticket is not None and ticket.status == "draft":
            actions.append(
                {
                    "type": "submit_handoff",
                    "entity_id": ticket.id,
                    "expected_version": ticket.version,
                    "label": "确认提交到本地演示工作台",
                }
            )
    event = write_results.get("usage_event") or {}
    prompt = event.get("review_prompt")
    if prompt:
        actions.append(
            {
                "type": "review_routine",
                "entity_id": prompt["prompt_id"],
                "label": "复核是否暂停该步骤（暂停只会生成新草稿）",
            }
        )
    if intent == "import":
        actions.append(
            {
                "type": "confirm_import",
                "entity_id": None,
                "label": "打开导入页确认候选产品",
                "blocked_reason": "需要你先确认候选与数量",
            }
        )
    if intent == "ingredient_atlas":
        actions.append(
            {
                "type": "open_atlas",
                "entity_id": None,
                "label": "查看完整成分图鉴",
            }
        )
    return actions


# --- main entry -----------------------------------------------------------


def run_turn(
    db: Session,
    *,
    auth: AuthContext,
    message: str,
    conversation_id: str | None = None,
    idempotency_key: str | None = None,
    settings: Settings | None = None,
) -> TurnResult:
    settings = settings or get_settings()
    started = time.perf_counter()
    tenant_id, user_id = auth.tenant_id, auth.user_id
    message = (message or "").strip()
    if not message:
        raise ValidationError("消息不能为空")
    if idempotency_key:
        existing = db.execute(
            select(AgentRun).where(
                AgentRun.tenant_id == tenant_id,
                AgentRun.user_id == user_id,
                AgentRun.idempotency_key == idempotency_key,
            )
        ).scalar_one_or_none()
        if existing is not None and existing.response:
            return TurnResult(
                output=existing.response,
                run_id=existing.id,
                assistant_message_id=existing.message_id,
                user_message_id=None,
            )

    conversation = _get_or_create_conversation(
        db, tenant_id=tenant_id, user_id=user_id, conversation_id=conversation_id
    )
    sequence = _next_sequence(db, conversation.id)
    user_message = Message(
        tenant_id=tenant_id,
        user_id=user_id,
        conversation_id=conversation.id,
        role="user",
        content=message,
        sequence=sequence,
    )
    db.add(user_message)
    db.flush()
    conversation.last_message_at = clock_now(db)
    db.flush()

    run_id = str(uuid.uuid4())
    run = AgentRun(
        id=run_id,
        tenant_id=tenant_id,
        user_id=user_id,
        conversation_id=conversation.id,
        message_id=user_message.id,
        intent="general",
        model_mode=settings.model_mode,
        model_provider=settings.model_provider if settings.model_mode == "live" else "mock",
        model_name=settings.model_name or "mock-deterministic-v1",
        prompt_version=settings.prompt_version,
        idempotency_key=idempotency_key,
    )
    db.add(run)
    db.flush()

    provider = get_model_provider(settings)
    context = _context_summary(db, tenant_id=tenant_id, user_id=user_id)
    planner_payload = {
        "message": message,
        "context": context,
        "tools": tool_module.tool_schemas(),
        "conversation": _recent_messages(db, conversation.id),
        "mode": settings.model_mode,
        "notice": (
            "mock 模式：确定性 fixtures，不声称真实模型能力。"
            if settings.model_mode == "mock"
            else "live 模式。"
        ),
    }
    tool_events: list[dict[str, Any]] = []
    output: dict[str, Any]
    cards: list[dict[str, Any]] = []
    try:
        planner_response = provider.complete_json(
            system_prompt=prompts.PLANNER_PROMPT,
            user_payload=planner_payload,
            schema_name="PlannerOutput",
            schema={},
        )
        planner = turn_schemas.PlannerOutput.model_validate(planner_response.payload)
    except AppError:
        db.rollback()
        raise
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        raise InvalidModelOutputError(
            "意图解析输出不符合 schema。", details={"error": type(exc).__name__}
        ) from exc
    run.intent = planner.intent

    ctx = tool_module.ToolContext(
        db=db, tenant_id=tenant_id, user_id=user_id, settings=settings, run_id=run_id
    )
    tool_results: dict[str, Any] = {}
    tool_budget = settings.max_tool_calls_per_turn
    for request in planner.tool_requests[:tool_budget]:
        name = str(request.get("name") or "")
        args = request.get("args") or {}
        try:
            result = tool_module.execute(ctx, name, args)
            tool_results[name] = result
            tool_events.append({"tool": name, "args": args, "status": "ok"})
        except AppError as exc:
            tool_results[name] = {"error": exc.message, "code": exc.code}
            tool_events.append({"tool": name, "args": args, "status": "error", "code": exc.code})
    if len(planner.tool_requests) > tool_budget:
        tool_events.append(
            {"tool": "__budget__", "status": "truncated", "requested": len(planner.tool_requests)}
        )

    # explicit first-person preferences are written BEFORE drafts so the draft
    # already reflects them (e.g. “只想三步” produces a 3-step draft in one turn)
    pre_applied_keys: set[str] = set()
    memory_changes: list[dict[str, Any]] = []
    for proposal in extraction.extract_proposals(message):
        payload = dict(proposal)
        payload["source_message_id"] = user_message.id
        result = memory_service.propose(
            db, tenant_id=tenant_id, user_id=user_id, proposal=payload, actor=user_id
        )
        if result.status == "rejected" or result.record is None:
            continue
        pre_applied_keys.add(result.record.key)
        memory_changes.append(
            {
                "type": "pending" if result.status == "pending_confirmation" else "preference",
                "entity_id": result.record.id,
                "key": result.record.key,
                "value": result.record.value.get("value"),
                "status": result.status,
                "description": result.reason,
            }
        )

    write_results: dict[str, Any] = {}
    write_events: list[dict[str, Any]] = []
    repair_attempts = 0
    validation_errors: list[dict[str, Any]] = []
    compose_response = None
    savepoint = db.begin_nested()
    try:
        write_results, write_events = _execute_write_requests(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            requests=[w.model_dump() for w in getattr(planner, "write_requests", [])],
            message=message,
            source_message_id=user_message.id,
            settings=settings,
        )
        compose_payload = {
            "message": message,
            "intent": planner.intent,
            "context": context,
            "tool_results": tool_results,
            "write_results": write_results,
            "source_message_id": user_message.id,
            "settings_mode": settings.model_mode,
            "applied_preference_keys": sorted(pre_applied_keys),
            "conversation": _recent_messages(db, conversation.id),
        }
        compose_response = provider.complete_json(
            system_prompt=prompts.COMPOSER_PROMPT,
            user_payload=compose_payload,
            schema_name="ComposeOutput",
            schema={},
        )
        composed = turn_schemas.ComposeOutput.model_validate(compose_response.payload)
        retrieved_texts = _flatten_strings(
            {
                key: value
                for key, value in tool_results.items()
                if key
                in {
                    "search_knowledge",
                    "get_product_sources",
                    "get_user_context",
                    "list_owned_products",
                    "build_ingredient_atlas",
                    "get_ingredient_profile",
                    "get_environment",
                    "get_user_activities",
                }
            }
        )
        report = validate_turn(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            answer=composed.answer,
            citation_ids=composed.citation_ids,
            write_results=write_results,
            entity_refs={},
            retrieved_texts=retrieved_texts,
        )
        # One repair attempt, then explicit failure.
        if not report.ok:
            repair_attempts = 1
            validation_errors = report.errors
            compose_payload["validation_errors"] = report.errors
            compose_payload["repair_instruction"] = (
                "上一次输出未通过服务端校验：引用必须来自工具结果、实体必须属于当前用户、"
                "不得声称未发生的写入。请重新输出 JSON。"
            )
            compose_response = provider.complete_json(
                system_prompt=prompts.COMPOSER_PROMPT,
                user_payload=compose_payload,
                schema_name="ComposeOutput",
                schema={},
            )
            composed = turn_schemas.ComposeOutput.model_validate(compose_response.payload)
            report = validate_turn(
                db,
                tenant_id=tenant_id,
                user_id=user_id,
                answer=composed.answer,
                citation_ids=composed.citation_ids,
                write_results=write_results,
                entity_refs={},
                retrieved_texts=retrieved_texts,
            )
        if not report.ok:
            raise InvalidModelOutputError(
                "模型输出连续两次未通过服务端校验，已阻止返回对应建议。",
                details={"errors": report.errors},
            )
        savepoint.commit()
    except AppError:
        savepoint.rollback()
        raise
    except Exception as exc:  # noqa: BLE001
        savepoint.rollback()
        raise InvalidModelOutputError(
            "本轮生成失败，未写入任何草稿。", details={"error": type(exc).__name__}
        ) from exc

    assert compose_response is not None
    answer = sanitize_answer(composed.answer, write_results)

    # memory proposals are validated and written by the service, never by the model
    for proposal in composed.memory_proposals:
        if proposal.get("key") in pre_applied_keys:
            continue
        payload = dict(proposal)
        payload.setdefault("source_message_id", user_message.id)
        result = memory_service.propose(
            db, tenant_id=tenant_id, user_id=user_id, proposal=payload, actor=user_id
        )
        if result.status == "rejected":
            validation_errors.append(
                {"code": "MEMORY_PROPOSAL_REJECTED", "message": result.reason or "提议被拒绝"}
            )
            continue
        memory_changes.append(
            {
                "type": "pending" if result.status == "pending_confirmation" else "preference",
                "entity_id": result.record.id if result.record else None,
                "key": result.record.key if result.record else payload.get("key"),
                "value": result.record.value.get("value") if result.record else payload.get("value"),
                "status": result.status,
                "description": result.reason,
            }
        )

    cards = _build_cards(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        intent=planner.intent,
        tool_results=tool_results,
        write_results=write_results,
        validation_citations=report.citations,
    )
    if not report.ok:
        cards.append(
            {
                "type": "error",
                "entity_id": None,
                "code": "INVALID_MODEL_OUTPUT",
                "message": "部分建议未通过服务端校验，已被阻止。",
                "retryable": True,
                "manual_path": "可重试，或直接在美妆柜手动添加产品。",
            }
        )
    questions = [q.model_dump() for q in composed.questions][: settings.max_clarifying_questions]
    pending_actions = _pending_actions(
        db, intent=planner.intent, write_results=write_results, tool_results=tool_results
    )
    for question in (write_results.get("usage_event") or {}).get("questions") or []:
        if len(questions) >= settings.max_clarifying_questions:
            break
        if question["key"] not in {q["key"] for q in questions}:
            questions.append(question)
    for question in (write_results.get("routine_draft") or {}).get("questions") or []:
        if len(questions) >= settings.max_clarifying_questions:
            break
        if question["key"] not in {q["key"] for q in questions}:
            questions.append(question)

    latency_ms = int((time.perf_counter() - started) * 1000)
    clock = clock_snapshot(db)
    if latency_ms > settings.turn_budget_seconds * 1000:
        answer += "\n（提示：本轮耗时超过预算，结果仍然来自真实状态。）"

    output = {
        "run_id": run_id,
        "intent": planner.intent,
        "answer": answer,
        "questions": questions,
        "citations": report.citations,
        "cards": cards,
        "memory_changes": memory_changes,
        "pending_actions": pending_actions,
        "uncertainties": composed.uncertainties
        + (report.warnings if report.warnings else [])
        + ((write_results.get("routine_draft") or {}).get("uncertainties") or []),
        "mode": settings.model_mode,
        "model_unavailable": False,
        "validation_errors": validation_errors,
        "clock": clock.to_dict(),
        "tool_calls": tool_events + write_events,
        "model": {
            "provider": getattr(provider, "provider", "mock"),
            "name": getattr(provider, "name", "mock"),
            "latency_ms": compose_response.latency_ms,
            "usage": compose_response.usage,
            "repair_attempts": repair_attempts,
        },
    }

    assistant_message = Message(
        tenant_id=tenant_id,
        user_id=user_id,
        conversation_id=conversation.id,
        role="assistant",
        content=answer,
        sequence=sequence + 1,
        run_id=run_id,
        cards=cards,
        citations=report.citations,
    )
    db.add(assistant_message)
    db.flush()
    conversation.last_message_at = clock_now(db)

    run.tool_events = tool_events + write_events
    run.validation_result = report.to_dict() | {"repair_attempts": repair_attempts}
    run.latency_ms = latency_ms
    run.usage_metadata = {
        "planner": planner_response.usage,
        "composer": compose_response.usage,
        "tool_calls": len(tool_events),
        "write_requests": len(write_events),
    }
    run.repair_attempts = repair_attempts
    run.message_id = assistant_message.id
    run.response = output
    db.flush()

    audit.record(
        db,
        action="agent.turn",
        actor_user_id=user_id,
        tenant_id=tenant_id,
        entity_type="agent_run",
        entity_id=run_id,
        meta={
            "intent": planner.intent,
            "mode": settings.model_mode,
            "tool_calls": len(tool_events),
            "validation_ok": report.ok,
            "latency_ms": latency_ms,
        },
    )
    return TurnResult(
        output=output,
        run_id=run_id,
        assistant_message_id=assistant_message.id,
        user_message_id=user_message.id,
    )


def run_import_extraction(
    db: Session,
    *,
    auth: AuthContext,
    batch: ImportBatch,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Vision/OCR step for the import flow (mock fixtures or the live adapter)."""
    settings = settings or get_settings()
    from ..providers.vision import get_vision_provider

    provider = get_vision_provider(settings)
    result = provider.extract(db, batch=batch, settings=settings)
    return result
