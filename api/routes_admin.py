"""Privacy endpoints, admin/demo controls (clock, weather scenario, scheduler tick)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, field_validator
from sqlalchemy import select

from ..models import NotificationOutbox, ProactiveDecision, ServiceMessage, SystemSetting
from ..scheduler import loop as scheduler_loop
from ..services import audit
from ..services import clock as clock_service
from ..services import privacy as privacy_service
from ..services import proactive as proactive_service
from ..services import triggers as trigger_service
from ..services.errors import ForbiddenError
from .deps import ClockInfo, CurrentAuth, DbSession, SettingsDep, StaffAuth
from .validators import to_utc

router = APIRouter()


@router.get("/privacy/export")
def export_data(auth: CurrentAuth, db: DbSession) -> dict[str, Any]:
    payload = privacy_service.export_user_data(db, tenant_id=auth.tenant_id, user_id=auth.user_id)
    db.commit()
    return payload


@router.delete("/privacy/account-data")
def delete_account_data(auth: CurrentAuth, db: DbSession, settings: SettingsDep) -> dict[str, Any]:
    result = privacy_service.delete_user_data(
        db, tenant_id=auth.tenant_id, user_id=auth.user_id, actor=auth.user_id, settings=settings
    )
    db.commit()
    return result


# --- demo / admin controls -------------------------------------------------


class ClockRequest(BaseModel):
    _normalise = field_validator("fixed_at", mode="after")(lambda v: to_utc(v))

    mode: str = "demo"  # real | demo
    fixed_at: datetime | None = None
    offset_hours: float | None = None
    label: str | None = None
    day: int | None = None


class WeatherScenarioRequest(BaseModel):
    name: str


def _require_staff_or_demo(auth: CurrentAuth) -> None:
    from ..config import get_settings

    if auth.is_staff():
        return
    if get_settings().auth_mode == "demo" and auth.user.is_demo:
        return
    raise ForbiddenError("需要客服角色或本地演示环境")


@router.get("/admin/clock")
def get_clock(auth: CurrentAuth, db: DbSession, clock: ClockInfo) -> dict[str, Any]:
    return {"clock": clock, "notice": "演示时间会被明确标记，不会被当作真实时间。"}


@router.post("/admin/clock")
def set_clock(payload: ClockRequest, auth: CurrentAuth, db: DbSession) -> dict[str, Any]:
    _require_staff_or_demo(auth)
    if payload.mode == "real":
        snapshot = clock_service.set_override(db, clear=True, actor=auth.user_id)
    else:
        now = clock_service.snapshot(db).now
        offset_hours = payload.offset_hours
        if payload.day is not None:
            offset_hours = float(payload.day - 1) * 24.0
        snapshot = clock_service.set_override(
            db,
            fixed_at=payload.fixed_at or (now if offset_hours is not None else None),
            offset_hours=offset_hours,
            label=payload.label or (f"演示第 {payload.day} 天" if payload.day else "演示时间"),
            actor=auth.user_id,
        )
    db.commit()
    return {"clock": snapshot.to_dict(), "notice": "已切换时钟；所有输出会标记 is_demo_time。"}


@router.get("/admin/weather-scenario")
def get_weather_scenario(auth: CurrentAuth, db: DbSession) -> dict[str, Any]:
    row = db.get(SystemSetting, "weather_scenario")
    from ..providers.weather import _profiles

    from ..config import get_settings

    settings = get_settings()
    scenarios = _profiles(settings)["scenarios"]
    return {
        "current": (row.value.get("name") if row and row.value else "default"),
        "available": sorted(scenarios.keys()),
        "description": {k: v.get("description") for k, v in scenarios.items()},
        "notice": "演示场景开关：用于验证缺失、过时、提供方失败与超覆盖范围的处理。",
    }


@router.post("/admin/weather-scenario")
def set_weather_scenario(
    payload: WeatherScenarioRequest, auth: CurrentAuth, db: DbSession
) -> dict[str, Any]:
    _require_staff_or_demo(auth)
    row = db.get(SystemSetting, "weather_scenario")
    if row is None:
        row = SystemSetting(key="weather_scenario", value={"name": payload.name}, updated_by=auth.user_id)
        db.add(row)
    else:
        row.value = {"name": payload.name}
        row.updated_by = auth.user_id
    db.flush()
    db.commit()
    return {"current": payload.name, "notice": "已设置演示天气场景。"}


@router.post("/admin/scheduler/tick")
def scheduler_tick(auth: CurrentAuth, db: DbSession, settings: SettingsDep) -> dict[str, Any]:
    _require_staff_or_demo(auth)
    summary = scheduler_loop.tick_once(db, settings=settings)
    db.commit()
    return {"summary": summary, "notice": "一次调度 tick；生产环境由常驻 worker 执行。"}


@router.get("/admin/scheduler/status")
def scheduler_status(auth: CurrentAuth, db: DbSession, settings: SettingsDep) -> dict[str, Any]:
    outbox = list(db.execute(select(NotificationOutbox)).scalars())
    by_status: dict[str, int] = {}
    for row in outbox:
        by_status[row.status] = by_status.get(row.status, 0) + 1
    loop = scheduler_loop.get_loop()
    return {
        "enabled": settings.scheduler_enabled,
        "interval_seconds": settings.scheduler_interval_seconds,
        "last_tick": loop.last_tick,
        "outbox": by_status,
        "notice": "调度任务持久化在数据库中，重启后继续处理，不依赖打开网页。",
    }


@router.get("/admin/proactive-decisions")
def proactive_decisions(auth: CurrentAuth, db: DbSession) -> dict[str, Any]:
    """Auditable decision log for the current user (suppression reasons included)."""
    rows = list(
        db.execute(
            select(ProactiveDecision)
            .where(
                ProactiveDecision.tenant_id == auth.tenant_id,
                ProactiveDecision.user_id == auth.user_id,
            )
            .order_by(ProactiveDecision.created_at.desc())
            .limit(50)
        ).scalars()
    )
    return {
        "decisions": [
            {
                "id": r.id,
                "event_id": r.event_id,
                "service_type": r.service_type,
                "outcome": r.outcome,
                "reason_codes": r.reason_codes,
                "context_refs": r.context_refs,
                "snapshot_id": r.snapshot_id,
                "rule_version": r.rule_version,
                "plan_version": r.plan_version,
                "citation_ids": r.citation_ids,
                "channel": r.channel,
                "mode": r.mode,
                "expires_at": r.expires_at.isoformat() if r.expires_at else None,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ],
        "notice": "抑制原因可审计；消费者界面无需展示内部评分。",
    }


@router.post("/admin/proactive/evaluate")
def evaluate_proactive(auth: CurrentAuth, db: DbSession, settings: SettingsDep) -> dict[str, Any]:
    _require_staff_or_demo(auth)
    decisions = trigger_service.evaluate_triggers(
        db, tenant_id=auth.tenant_id, user_id=auth.user_id, settings=settings, create_messages=True
    )
    db.commit()
    return {"decisions": decisions, "notice": "确定性筛选 + 后端决策；模型不直接触达渠道。"}


@router.get("/admin/audit")
def recent_audit(auth: StaffAuth, db: DbSession) -> dict[str, Any]:
    from ..models import AuditEvent

    rows = list(
        db.execute(
            select(AuditEvent)
            .where(AuditEvent.tenant_id == auth.tenant_id)
            .order_by(AuditEvent.created_at.desc())
            .limit(100)
        ).scalars()
    )
    return {
        "events": [
            {
                "id": r.id,
                "action": r.action,
                "actor_role": r.actor_role,
                "entity_type": r.entity_type,
                "entity_id": r.entity_id,
                "meta": r.meta,
                "at": r.created_at.isoformat(),
            }
            for r in rows
        ],
        "notice": "审计记录不包含原文、上传内容或联系方式。",
    }
