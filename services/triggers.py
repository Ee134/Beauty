"""Proactive trigger evaluation: candidate generation before the decision gate."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import Settings, get_settings
from ..environment import service as env_service
from ..knowledge import service as knowledge
from ..models import Activity, City, EnvironmentSnapshot, OwnedProduct, RoutinePlan
from ..services import cabinet as cabinet_service
from ..services import proactive as proactive_service
from ..services.clock import now as clock_now

LEAD_MINUTES = {"trip": 48 * 60, "outdoor": 120}


def _cabinet_with_sources(
    db: Session, *, tenant_id: str, user_id: str
) -> list[tuple[OwnedProduct, dict[str, Any]]]:
    out: list[tuple[OwnedProduct, dict[str, Any]]] = []
    for product in cabinet_service.list_owned(db, tenant_id=tenant_id, user_id=user_id):
        if product.usage_status != "active" or product.lifecycle_status in {"finished", "discarded"}:
            continue
        out.append((product, cabinet_service.extract_product_ingredients(db, product.catalog_product_id or "")))
    return out


def _citations_for_product(db: Session, owned: OwnedProduct) -> list[str]:
    if not owned.catalog_product_id:
        return []
    info = cabinet_service.extract_product_ingredients(db, owned.catalog_product_id)
    return list(info.get("citation_ids") or [])


def _usage_citations(db: Session, owned: OwnedProduct) -> list[str]:
    """Citations that support a *usage* statement for this product."""
    if not owned.catalog_product_id:
        return []
    from ..models import CatalogProduct

    pk = knowledge.load_product_knowledge(db, db.get(CatalogProduct, owned.catalog_product_id))
    return [chunk.id for chunk, _src in pk.usage_instructions]


def humidity_trend(
    db: Session,
    *,
    city_id: str,
    current_humidity: float | None,
    now: datetime,
    window_hours: float = 24.0,
) -> float | None:
    """Humidity drop against the newest snapshot older than the rule window.

    Comparing within the same window would let a single fetch mask a real trend,
    so the baseline is deliberately at least `window_hours` old. Without such a
    baseline the result is unknown (never assumed to be zero).
    """
    if current_humidity is None:
        return None
    cutoff = now - timedelta(hours=float(window_hours))
    rows = list(
        db.execute(
            select(EnvironmentSnapshot)
            .where(EnvironmentSnapshot.city_id == city_id, EnvironmentSnapshot.kind == "current")
            .order_by(EnvironmentSnapshot.issued_at.desc())
            .limit(50)
        ).scalars()
    )
    baseline = None
    for row in rows:
        if row.issued_at > cutoff:
            continue
        value = (row.metrics or {}).get("relative_humidity")
        if value is None:
            continue
        baseline = value
        break
    if baseline is None or baseline == 0:
        return None
    return round((baseline - current_humidity) / baseline * 100.0, 1)


def _sunscreen_product(
    db: Session, *, tenant_id: str, user_id: str
) -> tuple[OwnedProduct | None, list[str]]:
    from ..models import CatalogProduct

    for product, _info in _cabinet_with_sources(db, tenant_id=tenant_id, user_id=user_id):
        catalog = db.get(CatalogProduct, product.catalog_product_id) if product.catalog_product_id else None
        if catalog is not None and catalog.category == "sunscreen":
            citations = _usage_citations(db, product)
            if citations:
                return product, citations
    return None, []


def _paused_sunscreen_ids(db: Session, *, tenant_id: str, user_id: str) -> list[str]:
    from ..models import CatalogProduct

    out: list[str] = []
    for product in cabinet_service.list_owned(db, tenant_id=tenant_id, user_id=user_id):
        if product.usage_status == "active" and product.lifecycle_status not in {"finished", "discarded"}:
            continue
        catalog = db.get(CatalogProduct, product.catalog_product_id) if product.catalog_product_id else None
        if catalog is not None and catalog.category == "sunscreen":
            out.append(product.id)
    return out


def evaluate_triggers(
    db: Session,
    *,
    tenant_id: str,
    user_id: str,
    settings: Settings | None = None,
    create_messages: bool = True,
) -> list[dict[str, Any]]:
    settings = settings or get_settings()
    now = clock_now(db)
    preference = proactive_service.get_preferences(
        db, tenant_id=tenant_id, user_id=user_id, settings=settings
    )
    results: list[dict[str, Any]] = []
    activities = env_service.list_activities(
        db, tenant_id=tenant_id, user_id=user_id, statuses=["planned"]
    )
    location = env_service.get_active_location(db, tenant_id=tenant_id, user_id=user_id)
    paused = proactive_service.paused_product_ids(db, tenant_id=tenant_id, user_id=user_id)
    plan_version = proactive_service.active_plan_version(db, tenant_id=tenant_id, user_id=user_id)

    for activity in activities:
        if not activity.user_confirmed:
            continue
        if activity.activity_type == "trip":
            results.append(
                _travel_candidate(
                    db,
                    activity=activity,
                    tenant_id=tenant_id,
                    user_id=user_id,
                    settings=settings,
                    create_messages=create_messages,
                    paused=paused,
                    plan_version=plan_version,
                    now=now,
                )
            )
        elif activity.activity_type == "outdoor":
            results.append(
                _outdoor_candidate(
                    db,
                    activity=activity,
                    tenant_id=tenant_id,
                    user_id=user_id,
                    settings=settings,
                    create_messages=create_messages,
                    paused=paused,
                    plan_version=plan_version,
                    now=now,
                )
            )

    if location is not None and "environment_checkin" in (preference.service_types or []):
        results.append(
            _humidity_candidate(
                db,
                location=location,
                tenant_id=tenant_id,
                user_id=user_id,
                settings=settings,
                create_messages=create_messages,
                plan_version=plan_version,
                now=now,
            )
        )

    due = proactive_service.followup_due(db, tenant_id=tenant_id, user_id=user_id)
    for task in due:
        if task.purpose != "service_progress":
            continue
        decision = proactive_service.decide(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            service_type="service_progress",
            event_id=f"{task.id}:followup",
            context_refs=[task.related_entity_id or task.id],
            snapshot_id=None,
            citation_ids=[],
            plan_version=plan_version,
            payload={
                "activity_cancelled": False,
                "snapshot_fresh": True,
                "owned_product_ids": [],
                "paused_product_ids": paused,
                "useful_after_quiet_hours": False,
            },
            settings=settings,
        )
        # service_progress does not need environment or product citations
        if decision["outcome"] == "suppress" and set(decision["reason_codes"]) <= {
            "ENVIRONMENT_UNAVAILABLE",
            "PRODUCT_SOURCE_MISSING",
        }:
            decision = proactive_service.decide(
                db,
                tenant_id=tenant_id,
                user_id=user_id,
                service_type="service_progress",
                event_id=f"{task.id}:followup",
                context_refs=[task.related_entity_id or task.id],
                snapshot_id=None,
                citation_ids=[],
                plan_version=plan_version,
                payload={
                    "activity_cancelled": False,
                    "snapshot_fresh": True,
                    "owned_product_ids": [],
                    "paused_product_ids": [],
                    "useful_after_quiet_hours": False,
                    "skip_environment_check": True,
                },
                settings=settings,
            )
        results.append(decision)
    return [r for r in results if r is not None]


def _travel_candidate(
    db: Session,
    *,
    activity: Activity,
    tenant_id: str,
    user_id: str,
    settings: Settings,
    create_messages: bool,
    paused: list[str],
    plan_version: int | None,
    now: datetime,
) -> dict[str, Any]:
    rule = proactive_service.get_rule(db, "travel_support")
    lead_hours = float((rule.conditions or {}).get("lead_hours", 48)) if rule else 48
    hours_until = (activity.starts_at - now).total_seconds() / 3600.0
    context_refs = [activity.id]
    base_payload: dict[str, Any] = {
        "activity_cancelled": activity.status == "cancelled",
        "snapshot_fresh": False,
        "owned_product_ids": [],
        "paused_product_ids": paused,
        "useful_after_quiet_hours": True,
        "activity_id": activity.id,
    }
    if hours_until > lead_hours or hours_until < -24:
        return proactive_service.decide(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            service_type="travel_support",
            event_id=f"{activity.id}:trip",
            context_refs=context_refs,
            snapshot_id=None,
            citation_ids=[],
            plan_version=plan_version,
            payload={**base_payload, "snapshot_fresh": True},
            settings=settings,
        )
    city_id = activity.destination_city_id or (
        env_service.get_active_location(db, tenant_id=tenant_id, user_id=user_id).city_id
        if env_service.get_active_location(db, tenant_id=tenant_id, user_id=user_id)
        else None
    )
    if city_id is None:
        return proactive_service.decide(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            service_type="travel_support",
            event_id=f"{activity.id}:trip",
            context_refs=context_refs,
            snapshot_id=None,
            citation_ids=[],
            plan_version=plan_version,
            payload=base_payload,
            settings=settings,
        )
    city = env_service.get_city(db, city_id)
    env = env_service.load_environment(db, city=city, settings=settings, tenant_id=tenant_id)
    current = env.get("current")
    snapshot_id = current["id"] if current else None
    fresh = bool(current) and current.get("freshness") == "ok"

    checklist: list[dict[str, Any]] = []
    citation_ids: list[str] = []
    carry: list[str] = []
    for product, _info in _cabinet_with_sources(db, tenant_id=tenant_id, user_id=user_id):
        from ..models import CatalogProduct

        catalog = db.get(CatalogProduct, product.catalog_product_id) if product.catalog_product_id else None
        if catalog is None or catalog.category not in {"sunscreen", "moisturizer", "cleanser", "serum"}:
            continue
        cites = _usage_citations(db, product)
        if not cites:
            continue
        carry.append(product.custom_name)
        checklist.append(
            {
                "owned_product_id": product.id,
                "name": product.custom_name,
                "reason": "按该产品已审核资料携带（产品携带建议不等于两种产品可互换）",
                "citation_ids": cites,
            }
        )
        citation_ids.extend(cites)

    unknown_days: list[str] = []
    if activity.ends_at:
        cursor = activity.starts_at
        while cursor.date() <= activity.ends_at.date():
            if env_service.forecast_day(env, cursor) is None:
                unknown_days.append(cursor.date().isoformat())
            cursor = cursor + timedelta(days=1)

    payload = {
        **base_payload,
        "snapshot_fresh": fresh,
        "snapshot_missing_fields": (current or {}).get("missing_fields", []),
        "unknown_forecast_days": unknown_days,
        "carry_items": carry,
    }
    decision = proactive_service.decide(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        service_type="travel_support",
        event_id=f"{activity.id}:trip",
        context_refs=context_refs + [snapshot_id] if snapshot_id else context_refs,
        snapshot_id=snapshot_id,
        citation_ids=citation_ids,
        plan_version=plan_version,
        payload=payload,
        expires_at=activity.starts_at,
        settings=settings,
    )
    if create_messages and decision["outcome"] == "send":
        metrics = (current or {}).get("metrics", {})
        body = (
            f"你确认了行程「{activity.title}」，目的地 {city.name_zh} 当前 "
            f"{metrics.get('temperature_c', '未知')}°C、相对湿度 {metrics.get('relative_humidity', '未知')}%。"
            + ("预报未覆盖的日期标记为未知。" if unknown_days else "")
            + "以下携带清单纯粹来自产品已审核资料，产品之间不能互相替代。"
        )
        message = proactive_service.create_message(
            db,
            decision=decision,
            tenant_id=tenant_id,
            user_id=user_id,
            title="出行准备提醒（演示环境数据）",
            body=body,
            payload={**payload, "event_id": f"{activity.id}:trip", "checklist": checklist},
            source_refs=[],
            expires_at=activity.starts_at,
        )
        decision["message_id"] = message.id
        decision["message"] = proactive_service.serialize_message(db, message)
        decision["checklist"] = checklist
        decision["unknown_forecast_days"] = unknown_days
    return decision


def _outdoor_candidate(
    db: Session,
    *,
    activity: Activity,
    tenant_id: str,
    user_id: str,
    settings: Settings,
    create_messages: bool,
    paused: list[str],
    plan_version: int | None,
    now: datetime,
) -> dict[str, Any]:
    rule = proactive_service.get_rule(db, "outdoor_support")
    conditions = rule.conditions if rule else {}
    lead_minutes = float(conditions.get("lead_minutes", LEAD_MINUTES["outdoor"]))
    uv_threshold = float(conditions.get("uv_index_gte", 6))
    minutes_until = (activity.starts_at - now).total_seconds() / 60.0
    location = env_service.get_active_location(db, tenant_id=tenant_id, user_id=user_id)
    base_payload: dict[str, Any] = {
        "activity_cancelled": activity.status == "cancelled",
        "snapshot_fresh": False,
        "owned_product_ids": [],
        "paused_product_ids": paused,
        "useful_after_quiet_hours": True,
        "activity_id": activity.id,
    }
    if minutes_until > lead_minutes or minutes_until < -60:
        return proactive_service.decide(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            service_type="outdoor_support",
            event_id=f"{activity.id}:reminder",
            context_refs=[activity.id],
            snapshot_id=None,
            citation_ids=[],
            plan_version=plan_version,
            payload={**base_payload, "snapshot_fresh": True},
            settings=settings,
        )
    if location is None:
        return proactive_service.decide(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            service_type="outdoor_support",
            event_id=f"{activity.id}:reminder",
            context_refs=[activity.id],
            snapshot_id=None,
            citation_ids=[],
            plan_version=plan_version,
            payload=base_payload,
            settings=settings,
        )
    city = env_service.get_city(db, location.city_id)
    env = env_service.load_environment(db, city=city, settings=settings, tenant_id=tenant_id)
    current = env.get("current")
    snapshot_id = current["id"] if current else None
    fresh = bool(current) and current.get("freshness") == "ok"
    day = env_service.forecast_day(env, activity.starts_at) if snapshot_id else None
    uv_value = None
    if day and day.get("metrics"):
        uv_value = day["metrics"].get("uv_index_max")
    if uv_value is None and current:
        uv_value = (current.get("metrics") or {}).get("uv_index")

    product, citation_ids = _sunscreen_product(db, tenant_id=tenant_id, user_id=user_id)
    paused_sunscreen = _paused_sunscreen_ids(db, tenant_id=tenant_id, user_id=user_id)
    extra_reasons: list[str] = []
    if uv_value is None:
        extra_reasons = ["ENVIRONMENT_FIELD_MISSING"]
    elif uv_value < uv_threshold:
        extra_reasons = ["UV_BELOW_THRESHOLD"]
    elif product is None and not paused_sunscreen:
        extra_reasons = ["NO_PRODUCT_WITH_SOURCES"]
    payload = {
        **base_payload,
        "snapshot_fresh": fresh,
        "uv_index": uv_value,
        "uv_threshold": uv_threshold,
        "owned_product_ids": [product.id] if product else list(paused_sunscreen),
        "product_found": product is not None,
        "paused_product_ids": sorted(set(paused) | set(paused_sunscreen)),
    }
    if extra_reasons and not (paused_sunscreen and product is None):
        return proactive_service.decide(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            service_type="outdoor_support",
            event_id=f"{activity.id}:reminder",
            context_refs=[activity.id] + ([snapshot_id] if snapshot_id else []),
            snapshot_id=snapshot_id,
            citation_ids=citation_ids,
            plan_version=plan_version,
            payload=payload,
            settings=settings,
            extra_suppress_reasons=extra_reasons,
        )
    decision = proactive_service.decide(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        service_type="outdoor_support",
        event_id=f"{activity.id}:reminder",
        context_refs=[activity.id] + ([snapshot_id] if snapshot_id else []),
        snapshot_id=snapshot_id,
        citation_ids=citation_ids,
        plan_version=plan_version,
        payload=payload,
        expires_at=activity.starts_at,
        settings=settings,
    )
    if create_messages and decision["outcome"] == "send":
        if product is not None:
            body = (
                f"你确认的户外活动「{activity.title}」将在 {activity.starts_at.astimezone().strftime('%m-%d %H:%M')} 开始，"
                f"该时段紫外线指数预报为 {uv_value}（演示环境数据）。按「{product.custom_name}」的已审核资料："
                + next(
                    (
                        c.excerpt
                        for c in knowledge.resolve_citations(db, citation_ids)
                        if c.chunk_id == citation_ids[0]
                    ),
                    "请按产品资料使用。",
                )
            )
        else:
            body = (
                f"你确认的户外活动「{activity.title}」该时段紫外线指数预报为 {uv_value}。"
                "柜内暂时没有资料完整可引用的防晒产品，因此这里只提供一般性服务信息："
                "建议参考经审核的一般防护常识（遮阳、避开正午），不提供具体产品建议。"
            )
        message = proactive_service.create_message(
            db,
            decision=decision,
            tenant_id=tenant_id,
            user_id=user_id,
            title="户外活动提醒",
            body=body,
            payload={
                **payload,
                "event_id": f"{activity.id}:reminder",
                "uv_index": uv_value,
                "product_name": product.custom_name if product else None,
                "general_advice_only": product is None,
            },
            expires_at=activity.starts_at,
        )
        decision["message_id"] = message.id
        decision["message"] = proactive_service.serialize_message(db, message)
    return decision


def _humidity_candidate(
    db: Session,
    *,
    location: Any,
    tenant_id: str,
    user_id: str,
    settings: Settings,
    create_messages: bool,
    plan_version: int | None,
    now: datetime,
) -> dict[str, Any]:
    from ..models import UsageEvent

    rule = proactive_service.get_rule(db, "environment_checkin")
    threshold = float((rule.conditions or {}).get("humidity_drop_pct_gte", 15)) if rule else 15.0
    city = env_service.get_city(db, location.city_id)
    env = env_service.load_environment(db, city=city, settings=settings, tenant_id=tenant_id)
    current = env.get("current")
    snapshot_id = current["id"] if current else None
    fresh = bool(current) and current.get("freshness") == "ok"
    window_hours = float((rule.conditions or {}).get("window_hours", 24)) if rule else 24.0
    trend = humidity_trend(
        db,
        city_id=location.city_id,
        current_humidity=(current.get("metrics") or {}).get("relative_humidity") if current else None,
        now=now,
        window_hours=window_hours,
    )
    recent_events = list(
        db.execute(
            select(UsageEvent).where(
                UsageEvent.tenant_id == tenant_id,
                UsageEvent.user_id == user_id,
                UsageEvent.invalidated_at.is_(None),
            )
        ).scalars()
    )
    has_report = any(
        e.created_at and (now - e.created_at) < timedelta(days=7) and e.event_type in {"negative", "positive", "uncertain"}
        for e in recent_events
    )
    payload = {
        "activity_cancelled": False,
        "snapshot_fresh": fresh,
        "humidity_drop_pct": trend,
        "requires_user_report": True,
        "has_recent_report": has_report,
        "owned_product_ids": [],
        "paused_product_ids": [],
        "useful_after_quiet_hours": False,
        "model_confidence_ok": True,
    }
    citation_ids: list[str] = []
    extra_reasons: list[str] = []
    if not has_report:
        extra_reasons = ["NO_RECENT_USER_REPORT"]
    elif trend is None:
        extra_reasons = ["NO_ENVIRONMENT_TREND"]
    elif trend < threshold:
        extra_reasons = ["TREND_BELOW_THRESHOLD"]

    plan = (
        db.execute(
            select(RoutinePlan).where(
                RoutinePlan.tenant_id == tenant_id,
                RoutinePlan.user_id == user_id,
                RoutinePlan.status == "active",
            )
        )
        .scalars()
        .first()
    )
    if plan is not None:
        from ..models import RoutineStep

        steps = list(db.execute(select(RoutineStep).where(RoutineStep.plan_id == plan.id)).scalars())
        for step in steps:
            citation_ids.extend(step.citation_ids or [])
    payload["model_confidence_ok"] = True
    decision = proactive_service.decide(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        service_type="environment_checkin",
        event_id=f"{location.id}:humidity",
        context_refs=[location.id] + ([snapshot_id] if snapshot_id else []),
        snapshot_id=snapshot_id,
        citation_ids=sorted(set(citation_ids)),
        plan_version=plan_version,
        payload=payload,
        settings=settings,
        extra_suppress_reasons=extra_reasons,
    )
    decision["humidity_drop_pct"] = trend
    if create_messages and decision["outcome"] == "send":
        message = proactive_service.create_message(
            db,
            decision=decision,
            tenant_id=tenant_id,
            user_id=user_id,
            title="是否需要复核当前流程？",
            body=(
                f"{location.city_name} 的相对湿度在最近 24 小时下降了约 {trend}%，"
                "你也报告过近期体验。天气变化本身不能证明肤况变化，是否需要生成一份复核草稿看看？"
            ),
            payload={**payload, "event_id": f"{location.id}:humidity"},
        )
        decision["message_id"] = message.id
        decision["message"] = proactive_service.serialize_message(db, message)
    return decision
