"""Read-only agent tools.

The model may request these by name; the orchestrator validates the name and the
arguments against the schema, then executes at most `MAX_TOOL_CALLS_PER_TURN`.
Write tools are never executed from model output — they become draft-only write
requests handled by the orchestrator with server-side authorization.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import Settings, get_settings
from ..environment import service as env_service
from ..knowledge import service as knowledge
from ..models import (
    CatalogProduct,
    IngredientProfile,
    OwnedProduct,
    RoutinePlan,
    ServiceTicket,
    TicketEvent,
    UsageEvent,
)
from ..services import atlas as atlas_service
from ..services import cabinet as cabinet_service
from ..services import memory_service
from ..services import proactive as proactive_service
from ..services.clock import now as clock_now
from ..services.errors import AppError, ValidationError, not_found

READ_ONLY_TOOLS: dict[str, tuple[Callable[["ToolContext", dict[str, Any]], dict[str, Any]], dict[str, Any]]] = {}


@dataclass
class ToolContext:
    db: Session
    tenant_id: str
    user_id: str
    settings: Settings = field(default_factory=get_settings)
    run_id: str | None = None

    @property
    def now(self) -> datetime:
        return clock_now(self.db)


def tool(name: str, schema: dict[str, Any]) -> Callable[..., Any]:
    def decorator(fn: Callable[[ToolContext, dict[str, Any]], dict[str, Any]]) -> Callable[..., Any]:
        READ_ONLY_TOOLS[name] = (fn, schema)
        return fn

    return decorator


def tool_names() -> list[str]:
    return sorted(READ_ONLY_TOOLS)


def tool_schemas() -> list[dict[str, Any]]:
    return [{"name": name, "schema": schema} for name, (_fn, schema) in sorted(READ_ONLY_TOOLS.items())]


def execute(ctx: ToolContext, name: str, args: dict[str, Any]) -> dict[str, Any]:
    entry = READ_ONLY_TOOLS.get(name)
    if entry is None:
        raise ValidationError(f"未知工具：{name}")
    fn, schema = entry
    allowed = set((schema.get("properties") or {}).keys())
    unknown = set(args) - allowed
    if unknown:
        raise ValidationError("工具参数包含未允许的字段：" + "、".join(sorted(unknown)))
    return fn(ctx, args)


# --- tools ----------------------------------------------------------------


@tool(
    "get_user_context",
    {
        "description": "读取当前用户的有效偏好、未解决事件与近期反馈（最小必要上下文）。",
        "properties": {"entity_filters": {"type": "array", "items": {"type": "string"}}},
    },
)
def get_user_context(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    data = memory_service.build_context(ctx.db, tenant_id=ctx.tenant_id, user_id=ctx.user_id)
    products = cabinet_service.list_owned(ctx.db, tenant_id=ctx.tenant_id, user_id=ctx.user_id)
    data["cabinet"] = [
        {
            "owned_product_id": p.id,
            "name": p.custom_name,
            "usage_status": p.usage_status,
            "lifecycle_status": p.lifecycle_status,
            "ingredient_source_status": p.ingredient_source_status,
            "review_flag": p.review_flag,
        }
        for p in products
    ]
    return data


@tool(
    "search_catalog",
    {
        "description": "在共享目录中检索产品候选与匹配理由（不自动入柜）。",
        "properties": {
            "name": {"type": "string"},
            "region": {"type": "string"},
            "variant": {"type": "string"},
        },
    },
)
def search_catalog(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    name = str(args.get("name") or "")
    results = knowledge.match_catalog_products(ctx.db, name, limit=5)
    region = args.get("region")
    if region:
        results = [r for r in results if r["region"] == region]
    return {
        "query": name,
        "candidates": results,
        "notice": "候选需要用户确认后才会写入美妆柜。",
    }


@tool(
    "get_product_sources",
    {
        "description": "读取某目录产品版本的已批准资料与引用片段。",
        "properties": {"product_id": {"type": "string"}},
    },
)
def get_product_sources(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    product_id = str(args.get("product_id") or "")
    product = ctx.db.get(CatalogProduct, product_id)
    if product is None:
        raise not_found("目录产品")
    pk = knowledge.load_product_knowledge(ctx.db, product)
    citations = [knowledge.citation_for(chunk, source).to_dict() for chunk, source in
                 (pk.usage_instructions + pk.frequencies + pk.order_hints)]
    seen: dict[str, dict[str, Any]] = {}
    for citation in citations:
        seen.setdefault(citation["citation_id"], citation)
    return {
        "product_id": product.id,
        "name": product.name,
        "formula_version": product.formula_version,
        "has_approved_sources": pk.has_sources,
        "error_code": pk.error_code,
        "message": pk.message,
        "citations": list(seen.values()),
        "ingredient_citation_ids": sorted({i["citation_id"] for i in pk.ingredients + pk.irritants}),
    }


@tool(
    "list_owned_products",
    {
        "description": "列出当前用户的已购产品实例与状态。",
        "properties": {"filters": {"type": "object"}},
    },
)
def list_owned_products(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    filters = args.get("filters") or {}
    products = cabinet_service.list_owned(
        ctx.db,
        tenant_id=ctx.tenant_id,
        user_id=ctx.user_id,
        usage_status=filters.get("usage_status"),
    )
    return {"products": [cabinet_service.serialize(p) for p in products]}


@tool(
    "get_active_routine",
    {"description": "读取当前生效的计划版本。", "properties": {}},
)
def get_active_routine(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    from ..services import routine_service

    plan = ctx.db.execute(
        select(RoutinePlan).where(
            RoutinePlan.tenant_id == ctx.tenant_id,
            RoutinePlan.user_id == ctx.user_id,
            RoutinePlan.status == "active",
        )
    ).scalar_one_or_none()
    if plan is None:
        return {"active_plan": None, "notice": "当前没有生效中的计划。"}
    return {"active_plan": routine_service.serialize_plan(ctx.db, plan)}


@tool(
    "get_service_status",
    {
        "description": "查询工单真实状态与处理时间线（本地演示工作台或适配器）。",
        "properties": {"ticket_id": {"type": "string"}},
    },
)
def get_service_status(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    ticket_id = str(args.get("ticket_id") or "").strip()
    if not ticket_id:
        tickets = list(
            ctx.db.execute(
                select(ServiceTicket)
                .where(
                    ServiceTicket.tenant_id == ctx.tenant_id,
                    ServiceTicket.user_id == ctx.user_id,
                )
                .order_by(ServiceTicket.created_at.desc())
            ).scalars()
        )
        return {
            "tickets": [
                {
                    "ticket_id": t.id,
                    "external_id": t.external_id,
                    "status": t.status,
                    "adapter_mode": t.adapter_mode,
                    "next_action": t.next_action,
                    "timeline_count": len(
                        list(
                            ctx.db.execute(
                                select(TicketEvent.id).where(TicketEvent.ticket_id == t.id)
                            ).scalars()
                        )
                    ),
                    "created_at": t.created_at.isoformat(),
                }
                for t in tickets
            ],
            "notice": "只返回真实存在的本地工单。",
        }
    ticket = ctx.db.get(ServiceTicket, ticket_id)
    if ticket is None:
        ticket = ctx.db.execute(
            select(ServiceTicket).where(
                ServiceTicket.external_id == ticket_id,
                ServiceTicket.tenant_id == ctx.tenant_id,
                ServiceTicket.user_id == ctx.user_id,
            )
        ).scalar_one_or_none()
    if ticket is None or ticket.tenant_id != ctx.tenant_id or ticket.user_id != ctx.user_id:
        return {"found": False, "ticket_id": ticket_id, "notice": "未找到该工单，不推测进度。"}
    events = list(
        ctx.db.execute(
            select(TicketEvent).where(TicketEvent.ticket_id == ticket.id).order_by(TicketEvent.created_at)
        ).scalars()
    )
    return {
        "found": True,
        "ticket_id": ticket.id,
        "status": ticket.status,
        "adapter_mode": ticket.adapter_mode,
        "external_id": ticket.external_id,
        "next_action": ticket.next_action,
        "user_confirmed_resolution": ticket.user_confirmed_resolution,
        "timeline": [
            {
                "action": e.action,
                "from": e.from_status,
                "to": e.to_status,
                "note": e.note,
                "at": e.created_at.isoformat(),
                "actor_role": e.actor_role,
            }
            for e in events
        ],
        "notice": "状态来自本地演示工作台，不代表品牌已收到。",
    }


@tool(
    "extract_ingredients",
    {
        "description": "从该产品实例的已批准资料中提取成分（只返回有来源支持的成分）。",
        "properties": {"owned_product_id": {"type": "string"}},
    },
)
def extract_ingredients(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    owned_id = str(args.get("owned_product_id") or "")
    product = cabinet_service.get_owned(
        ctx.db, tenant_id=ctx.tenant_id, user_id=ctx.user_id, owned_id=owned_id
    )
    if not product.catalog_product_id:
        return {
            "owned_product_id": product.id,
            "actives": [],
            "irritants": [],
            "citation_ids": [],
            "status": "unmatched",
            "notice": "该产品未匹配目录，无法从已审核资料提取成分，也不猜测成分。",
        }
    info = cabinet_service.extract_product_ingredients(ctx.db, product.catalog_product_id)
    return {
        "owned_product_id": product.id,
        "name": product.custom_name,
        "actives": info["actives"],
        "irritants": info["irritants"],
        "citation_ids": info["citation_ids"],
        "status": product.ingredient_source_status,
        "notice": info.get("message"),
    }


@tool(
    "build_ingredient_atlas",
    {
        "description": "生成当前用户的成分图鉴草稿（不会自动展示或推送）。",
        "properties": {"min_events": {"type": "integer"}},
    },
)
def build_ingredient_atlas(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    min_events = int(args.get("min_events") or ctx.settings.atlas_min_events)
    payload = atlas_service.build_payload(
        ctx.db,
        tenant_id=ctx.tenant_id,
        user_id=ctx.user_id,
        min_events=min_events,
        persist=False,
    )
    return payload


@tool(
    "get_ingredient_profile",
    {
        "description": "返回已审核的成分功效/致敏性；无来源时返回 insufficient。",
        "properties": {"ingredient_name": {"type": "string"}},
    },
)
def get_ingredient_profile(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    name = (args.get("ingredient_name") or "").strip()
    if not name:
        raise ValidationError("ingredient_name 不能为空")
    row = ctx.db.execute(
        select(IngredientProfile).where(IngredientProfile.inci_name.ilike(name))
    ).scalar_one_or_none()
    if row is None:
        row = ctx.db.execute(
            select(IngredientProfile).where(IngredientProfile.common_name.ilike(name))
        ).scalar_one_or_none()
    if row is None:
        return {
            "found": False,
            "ingredient_name": name,
            "data_status": "insufficient",
            "notice": "暂无充分信息：系统中没有该成分的已审核来源。",
        }
    return {"found": True, **atlas_service.serialize_profile(ctx.db, row)}


@tool(
    "get_environment",
    {
        "description": "读取授权地点的标准环境快照，包含时效、单位与缺失字段。",
        "properties": {
            "location_id": {"type": "string"},
            "time_range": {"type": "object"},
        },
    },
)
def get_environment(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    location = env_service.get_active_location(ctx.db, tenant_id=ctx.tenant_id, user_id=ctx.user_id)
    if location is None:
        return {
            "available": False,
            "notice": "尚未设置城市，无法获取环境数据。",
        }
    city = env_service.get_city(ctx.db, location.city_id)
    payload = env_service.load_environment(
        ctx.db,
        city=city,
        settings=ctx.settings,
        tenant_id=ctx.tenant_id,
        location_id=location.id,
    )
    return {"available": payload.get("current") is not None, **payload}


@tool(
    "get_user_activities",
    {
        "description": "读取用户确认过的活动/行程；不推测户外状态。",
        "properties": {"time_range": {"type": "object"}},
    },
)
def get_user_activities(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    rows = env_service.list_activities(
        ctx.db, tenant_id=ctx.tenant_id, user_id=ctx.user_id, statuses=["planned", "cancelled"]
    )
    return {
        "activities": [env_service.serialize_activity(r) for r in rows],
        "notice": "仅包含用户确认过的活动；系统不会根据定位推断正在户外。",
    }


@tool(
    "search_knowledge",
    {
        "description": "词法检索已批准资料片段（BM25），可按产品与主张类型过滤。",
        "properties": {
            "query": {"type": "string"},
            "product_ids": {"type": "array", "items": {"type": "string"}},
            "claim_types": {"type": "array", "items": {"type": "string"}},
            "limit": {"type": "integer"},
        },
    },
)
def search_knowledge(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    return {
        "results": knowledge.search(
            ctx.db,
            str(args.get("query") or ""),
            product_ids=args.get("product_ids"),
            claim_types=args.get("claim_types"),
            limit=int(args.get("limit") or 5),
        )
    }


@tool(
    "get_notification_status",
    {"description": "读取通知偏好、渠道可用性与待发消息状态。", "properties": {}},
)
def get_notification_status(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    from ..providers.notifications import channel_status

    preference = proactive_service.get_preferences(
        ctx.db, tenant_id=ctx.tenant_id, user_id=ctx.user_id, settings=ctx.settings
    )
    messages, _cursor = proactive_service.list_messages(
        ctx.db, tenant_id=ctx.tenant_id, user_id=ctx.user_id, limit=5
    )
    return {
        "preferences": proactive_service.serialize_preferences(preference),
        "channels": channel_status(ctx.settings),
        "recent_messages": [proactive_service.serialize_message(ctx.db, m) for m in messages],
    }
