"""Environment: location preferences, activities/trips and snapshots."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select

from ..environment import service as env_service
from ..models import City, TriggerRule
from ..services.clock import now as clock_now
from .deps import CurrentAuth, DbSession, SettingsDep
from .validators import to_utc

router = APIRouter()


class LocationRequest(BaseModel):
    city_id: str
    purpose: Literal["home", "travel", "unset"] = "home"
    provenance: Literal["manual", "device_precise"] = "manual"
    consent_ref: str | None = None
    expected_version: int | None = None


class ActivityCreate(BaseModel):
    _normalise = field_validator("starts_at", "ends_at", mode="after")(lambda v: to_utc(v))

    activity_type: Literal["outdoor", "trip"]
    title: str = Field(min_length=1, max_length=200)
    starts_at: datetime
    ends_at: datetime | None = None
    destination_city_id: str | None = None
    origin_city_id: str | None = None
    user_confirmed: bool = True
    notes: str | None = None


class ActivityPatch(BaseModel):
    _normalise = field_validator("starts_at", "ends_at", mode="after")(lambda v: to_utc(v))

    expected_version: int | None = None
    title: str | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    status: Literal["planned", "cancelled", "completed", "expired"] | None = None
    notes: str | None = None
    user_confirmed: bool | None = None
    destination_city_id: str | None = None


@router.get("/cities")
def list_cities(auth: CurrentAuth, db: DbSession, q: str | None = None) -> dict[str, Any]:
    rows = list(db.execute(select(City).order_by(City.city_id)).scalars())
    if q:
        rows = [c for c in rows if q in c.name_zh or q.lower() in c.name_en.lower()]
    return {
        "cities": [
            {
                "city_id": c.city_id,
                "name_zh": c.name_zh,
                "name_en": c.name_en,
                "country": c.country,
                "timezone": c.timezone,
                "latitude": c.latitude,
                "longitude": c.longitude,
                "forecast_days": c.forecast_days,
            }
            for c in rows
        ],
        "notice": "MVP 默认手动选择城市；精确定位是独立可选权限，不做持续轨迹跟踪。",
    }


@router.get("/location-preferences")
def get_location(auth: CurrentAuth, db: DbSession) -> dict[str, Any]:
    row = env_service.get_active_location(db, tenant_id=auth.tenant_id, user_id=auth.user_id)
    return {
        "location": env_service.serialize_location(row),
        "notice": "IP 不会被当作真实居住地；活动、目的地与长期城市分别存储。",
    }


@router.put("/location-preferences")
def put_location(payload: LocationRequest, auth: CurrentAuth, db: DbSession) -> dict[str, Any]:
    row = env_service.set_location(
        db,
        tenant_id=auth.tenant_id,
        user_id=auth.user_id,
        city_id=payload.city_id,
        purpose=payload.purpose,
        provenance=payload.provenance,
        consent_ref=payload.consent_ref,
        expected_version=payload.expected_version,
        actor=auth.user_id,
    )
    db.commit()
    return {"location": env_service.serialize_location(row), "notice": "已使用你选择的城市。"}


@router.get("/activities")
def list_activities(auth: CurrentAuth, db: DbSession) -> dict[str, Any]:
    rows = env_service.list_activities(db, tenant_id=auth.tenant_id, user_id=auth.user_id)
    return {
        "activities": [env_service.serialize_activity(a) for a in rows],
        "notice": "活动与行程均来自用户确认，不根据定位推断。",
    }


@router.post("/activities", status_code=201)
def create_activity(payload: ActivityCreate, auth: CurrentAuth, db: DbSession) -> dict[str, Any]:
    row = env_service.create_activity(
        db,
        tenant_id=auth.tenant_id,
        user_id=auth.user_id,
        actor=auth.user_id,
        **payload.model_dump(),
    )
    db.commit()
    return {"activity": env_service.serialize_activity(row), "notice": "已记录（以你的确认为准）。"}


@router.patch("/activities/{activity_id}")
def patch_activity(
    activity_id: str, payload: ActivityPatch, auth: CurrentAuth, db: DbSession
) -> dict[str, Any]:
    row = env_service.get_activity(
        db, tenant_id=auth.tenant_id, user_id=auth.user_id, activity_id=activity_id
    )
    changes = payload.model_dump(exclude_unset=True, exclude={"expected_version"})
    env_service.update_activity(
        db, row, expected_version=payload.expected_version, changes=changes, actor=auth.user_id
    )
    db.commit()
    return {
        "activity": env_service.serialize_activity(row),
        "notice": "取消活动会同时取消依赖它的待发消息。",
    }


@router.delete("/activities/{activity_id}")
def cancel_activity(activity_id: str, auth: CurrentAuth, db: DbSession) -> dict[str, Any]:
    row = env_service.get_activity(
        db, tenant_id=auth.tenant_id, user_id=auth.user_id, activity_id=activity_id
    )
    env_service.update_activity(
        db, row, expected_version=None, changes={"status": "cancelled"}, actor=auth.user_id
    )
    db.commit()
    return {"activity": env_service.serialize_activity(row), "cancelled": True}


@router.get("/environment")
def get_environment(
    auth: CurrentAuth,
    db: DbSession,
    settings: SettingsDep,
    city_id: str | None = Query(default=None),
) -> dict[str, Any]:
    if city_id:
        city = env_service.get_city(db, city_id)
        location = None
    else:
        location = env_service.get_active_location(db, tenant_id=auth.tenant_id, user_id=auth.user_id)
        if location is None:
            return {
                "available": False,
                "notice": "尚未选择城市，无法获取环境数据。",
                "current": None,
                "forecast": [],
            }
        city = env_service.get_city(db, location.city_id)
    payload = env_service.load_environment(
        db,
        city=city,
        settings=settings,
        tenant_id=auth.tenant_id,
        location_id=location.id if location else None,
    )
    payload["available"] = payload.get("current") is not None
    payload["location"] = env_service.serialize_location(location)
    payload["using_user_city"] = location is not None and city_id is None
    db.commit()
    return payload


@router.get("/trigger-rules")
def list_trigger_rules(auth: CurrentAuth, db: DbSession) -> dict[str, Any]:
    rows = list(db.execute(select(TriggerRule)).scalars())
    return {
        "rules": [
            {
                "service_type": r.service_type,
                "description": r.description,
                "conditions": r.conditions,
                "threshold_source": r.threshold_source,
                "approval_status": r.approval_status,
                "cooldown_minutes": r.cooldown_minutes,
                "min_interval_minutes": r.min_interval_minutes,
                "version": r.version,
                "notes": r.notes,
            }
            for r in rows
        ],
        "notice": "演示规则：阈值来源与审核状态逐条标注，不代表医学依据。",
    }


@router.get("/environment/forecast-for")
def forecast_for(
    auth: CurrentAuth,
    db: DbSession,
    settings: SettingsDep,
    city_id: str,
    date: str = Query(description="YYYY-MM-DD"),
) -> dict[str, Any]:
    city = env_service.get_city(db, city_id)
    payload = env_service.load_environment(
        db, city=city, settings=settings, tenant_id=auth.tenant_id, persist=False
    )
    try:
        target = datetime.fromisoformat(date).replace(tzinfo=timezone.utc)
    except ValueError:
        return {"found": False, "notice": "日期格式应为 YYYY-MM-DD"}
    day = env_service.forecast_day(payload, target)
    return {
        "found": day is not None,
        "day": day,
        "notice": "超出预报覆盖范围时返回未知，不伪造成 0 或用 mock 顶替。",
        "available_days": [d["valid_from"][:10] for d in payload.get("forecast", [])],
    }
