"""Environment service: manual locations, activities/trips and environment snapshots."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import Settings, get_settings
from ..models import Activity, City, EnvironmentSnapshot, LocationPreference
from ..providers.weather import WeatherResult, get_weather_provider
from ..services import audit
from ..services.clock import now as clock_now
from ..services.errors import (
    EnvironmentUnavailableError,
    NotFoundError,
    ValidationError,
    not_found,
)

ACTIVITY_TYPES = {"outdoor", "trip"}
ACTIVITY_STATUS = {"planned", "cancelled", "completed", "expired"}


# --- locations ------------------------------------------------------------


def get_active_location(db: Session, *, tenant_id: str, user_id: str) -> LocationPreference | None:
    return (
        db.execute(
            select(LocationPreference)
            .where(
                LocationPreference.tenant_id == tenant_id,
                LocationPreference.user_id == user_id,
                LocationPreference.is_active.is_(True),
            )
            .order_by(LocationPreference.created_at.desc())
        )
        .scalars()
        .first()
    )


def set_location(
    db: Session,
    *,
    tenant_id: str,
    user_id: str,
    city_id: str,
    purpose: str = "home",
    provenance: str = "manual",
    consent_ref: str | None = None,
    expected_version: int | None = None,
    actor: str | None = None,
) -> LocationPreference:
    city = db.execute(select(City).where(City.city_id == city_id)).scalar_one_or_none()
    if city is None:
        raise ValidationError(f"未知城市：{city_id}")
    if provenance not in {"manual", "device_precise"}:
        raise ValidationError("provenance 只能是 manual / device_precise")
    if provenance == "device_precise" and not consent_ref:
        raise ValidationError("精确定位需要一次性的 consent_ref，且不做持续跟踪")
    existing = get_active_location(db, tenant_id=tenant_id, user_id=user_id)
    if existing is not None and expected_version is not None and existing.version != expected_version:
        from ..services.errors import VersionConflictError

        raise VersionConflictError(
            "地点偏好已更新，请刷新", details={"expected": expected_version, "actual": existing.version}
        )
    if (
        existing is not None
        and existing.city_id == city_id
        and existing.purpose == purpose
        and existing.provenance == provenance
    ):
        return existing
    if existing is not None:
        existing.is_active = False
        existing.version += 1
        db.flush()
    row = LocationPreference(
        tenant_id=tenant_id,
        user_id=user_id,
        city_id=city.city_id,
        city_name=city.name_zh,
        country=city.country,
        timezone=city.timezone,
        latitude=city.latitude,
        longitude=city.longitude,
        purpose=purpose,
        provenance=provenance,
        consent_ref=consent_ref,
        is_active=True,
        version=1,
    )
    db.add(row)
    db.flush()
    audit.record(
        db,
        action="location.updated",
        actor_user_id=actor or user_id,
        tenant_id=tenant_id,
        entity_type="location_preference",
        entity_id=row.id,
        meta={"city_id": city_id, "provenance": provenance, "purpose": purpose},
    )
    return row


def serialize_location(row: LocationPreference | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "id": row.id,
        "city_id": row.city_id,
        "city_name": row.city_name,
        "country": row.country,
        "timezone": row.timezone,
        "latitude": row.latitude,
        "longitude": row.longitude,
        "purpose": row.purpose,
        "provenance": row.provenance,
        "version": row.version,
        "updated_at": row.updated_at.isoformat(),
    }


# --- snapshots ------------------------------------------------------------


def staleness(snapshot: EnvironmentSnapshot, now: datetime, settings: Settings) -> str:
    if snapshot.quality in {"unavailable", "stale"}:
        return snapshot.quality
    age = (now - snapshot.issued_at).total_seconds() / 60.0
    limit = (
        settings.weather_max_age_minutes
        if snapshot.kind == "current"
        else settings.weather_forecast_max_age_minutes
    )
    if age > limit:
        return "stale"
    if snapshot.missing_fields:
        return "partial"
    return "ok"


def persist_snapshot(
    db: Session,
    draft: Any,
    *,
    tenant_id: str | None = None,
    location_id: str | None = None,
) -> EnvironmentSnapshot:
    """Store an environment snapshot in the **public** cache.

    The spec requires the shared environment cache to carry no user id and no
    feedback, so tenant/location are deliberately not written here. Which
    snapshot a decision used is recorded on ProactiveDecision instead.
    """
    row = EnvironmentSnapshot(
        tenant_id=None,
        location_id=None,
        city_id=draft.city_id,
        provider=draft.provider,
        mode=draft.mode,
        kind=draft.kind,
        issued_at=draft.issued_at,
        fetched_at=draft.fetched_at,
        valid_from=draft.valid_from,
        valid_to=draft.valid_to,
        timezone=draft.timezone,
        units=draft.units,
        metrics=draft.metrics,
        quality=draft.quality,
        missing_fields=draft.missing_fields,
        is_demo=draft.is_demo,
        error_code=draft.error_code,
    )
    db.add(row)
    db.flush()
    return row


def load_environment(
    db: Session,
    *,
    city: City,
    settings: Settings | None = None,
    scenario: str | None = None,
    persist: bool = True,
    tenant_id: str | None = None,
    location_id: str | None = None,
) -> dict[str, Any]:
    """Fetch environment data and report freshness honestly."""
    settings = settings or get_settings()
    provider = get_weather_provider(settings)
    result: WeatherResult = provider.fetch(db, city, scenario=scenario)
    now = clock_now(db)
    payload: dict[str, Any] = {
        "city_id": city.city_id,
        "city_name": city.name_zh,
        "timezone": city.timezone,
        "provider": result.provider,
        "mode": result.mode,
        "scenario": result.scenario,
        "quality": result.quality,
        "missing_fields": result.missing_fields,
        "fetched_at": now.isoformat(),
        "notice": result.notice,
        "is_demo": result.mode == "mock",
        "current": None,
        "forecast": [],
    }
    if result.error_code:
        payload["error_code"] = result.error_code
        payload["notice"] = result.notice or "环境数据暂不可用，相关环境触发已暂停。"
        return payload
    if result.current is not None:
        row = (
            persist_snapshot(db, result.current, tenant_id=tenant_id, location_id=location_id)
            if persist
            else None
        )
        status = staleness(row, now, settings) if row else result.quality
        payload["current"] = {
            **(row_snapshot_dict(row) if row else result.current.to_dict()),
            "freshness": status,
            "age_minutes": round((now - result.current.issued_at).total_seconds() / 60.0, 1),
            "max_age_minutes": settings.weather_max_age_minutes,
        }
        if status == "stale":
            payload["quality"] = "stale"
            payload["notice"] = "当前数据已过时（超过允许的缓存时间），环境触发暂停。"
    for draft in result.forecast:
        row = (
            persist_snapshot(db, draft, tenant_id=tenant_id, location_id=location_id)
            if persist
            else None
        )
        status = staleness(row, now, settings) if row else draft.quality
        payload["forecast"].append(
            {
                **(row_snapshot_dict(row) if row else draft.to_dict()),
                "freshness": status,
                "age_minutes": round((now - draft.issued_at).total_seconds() / 60.0, 1),
                "max_age_minutes": settings.weather_forecast_max_age_minutes,
            }
        )
    return payload


def row_snapshot_dict(row: EnvironmentSnapshot) -> dict[str, Any]:
    return {
        "id": row.id,
        "city_id": row.city_id,
        "provider": row.provider,
        "mode": row.mode,
        "kind": row.kind,
        "issued_at": row.issued_at.isoformat(),
        "fetched_at": row.fetched_at.isoformat(),
        "valid_from": row.valid_from.isoformat(),
        "valid_to": row.valid_to.isoformat(),
        "timezone": row.timezone,
        "units": row.units,
        "metrics": row.metrics,
        "quality": row.quality,
        "missing_fields": row.missing_fields,
        "is_demo": row.is_demo,
        "error_code": row.error_code,
    }


def forecast_day(payload: dict[str, Any], target_date: Any) -> dict[str, Any] | None:
    """Find the forecast covering a date. Returns None when not covered (unknown)."""
    for day in payload.get("forecast", []):
        start = datetime.fromisoformat(day["valid_from"])
        end = datetime.fromisoformat(day["valid_to"])
        moment = target_date
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        if start <= moment < end:
            return day
    return None


def get_city(db: Session, city_id: str) -> City:
    city = db.execute(select(City).where(City.city_id == city_id)).scalar_one_or_none()
    if city is None:
        raise not_found("城市")
    return city


# --- activities -----------------------------------------------------------


def create_activity(
    db: Session,
    *,
    tenant_id: str,
    user_id: str,
    activity_type: str,
    title: str,
    starts_at: datetime,
    ends_at: datetime | None = None,
    destination_city_id: str | None = None,
    origin_city_id: str | None = None,
    user_confirmed: bool = True,
    notes: str | None = None,
    consent_ref: str | None = None,
    actor: str | None = None,
) -> Activity:
    if activity_type not in ACTIVITY_TYPES:
        raise ValidationError("activity_type 只能是 outdoor / trip")
    if ends_at is not None and ends_at < starts_at:
        raise ValidationError("结束时间不能早于开始时间")
    destination_name = None
    destination_timezone = None
    if destination_city_id:
        city = get_city(db, destination_city_id)
        destination_name = city.name_zh
        destination_timezone = city.timezone
    row = Activity(
        tenant_id=tenant_id,
        user_id=user_id,
        activity_type=activity_type,
        title=title,
        starts_at=starts_at,
        ends_at=ends_at,
        destination_city_id=destination_city_id,
        destination_city_name=destination_name,
        destination_timezone=destination_timezone,
        origin_city_id=origin_city_id,
        user_confirmed=user_confirmed,
        status="planned",
        notes=notes,
        consent_ref=consent_ref,
    )
    db.add(row)
    db.flush()
    audit.record(
        db,
        action="activity.created",
        actor_user_id=actor or user_id,
        tenant_id=tenant_id,
        entity_type="activity",
        entity_id=row.id,
        meta={"type": activity_type, "destination": destination_city_id, "confirmed": user_confirmed},
    )
    return row


def list_activities(
    db: Session,
    *,
    tenant_id: str,
    user_id: str,
    statuses: Iterable[str] | None = None,
) -> list[Activity]:
    stmt = select(Activity).where(Activity.tenant_id == tenant_id, Activity.user_id == user_id)
    if statuses:
        stmt = stmt.where(Activity.status.in_(list(statuses)))
    return list(db.execute(stmt.order_by(Activity.starts_at)).scalars())


def get_activity(db: Session, *, tenant_id: str, user_id: str, activity_id: str) -> Activity:
    row = db.get(Activity, activity_id)
    if row is None or row.tenant_id != tenant_id or row.user_id != user_id:
        raise not_found("活动")
    return row


def update_activity(
    db: Session,
    row: Activity,
    *,
    expected_version: int | None,
    changes: dict[str, Any],
    actor: str | None = None,
) -> Activity:
    from ..services.errors import VersionConflictError

    if expected_version is not None and row.version != expected_version:
        raise VersionConflictError(
            "活动已更新，请刷新", details={"expected": expected_version, "actual": row.version}
        )
    allowed = {"title", "starts_at", "ends_at", "status", "notes", "user_confirmed", "destination_city_id"}
    unknown = set(changes) - allowed
    if unknown:
        raise ValidationError("不支持修改的字段：" + "、".join(sorted(unknown)))
    if "status" in changes and changes["status"] not in ACTIVITY_STATUS:
        raise ValidationError("status 非法")
    for key, value in changes.items():
        if key == "destination_city_id" and value:
            city = get_city(db, value)
            row.destination_city_name = city.name_zh
            row.destination_timezone = city.timezone
        setattr(row, key, value)
    row.version += 1
    db.flush()
    if changes.get("status") == "cancelled":
        from ..services import proactive as proactive_service

        proactive_service.cancel_pending_for_activity(db, activity=row, reason="activity_cancelled")
    audit.record(
        db,
        action="activity.updated",
        actor_user_id=actor or row.user_id,
        tenant_id=row.tenant_id,
        entity_type="activity",
        entity_id=row.id,
        meta={"fields": sorted(changes)},
    )
    return row


def serialize_activity(row: Activity) -> dict[str, Any]:
    return {
        "id": row.id,
        "activity_type": row.activity_type,
        "title": row.title,
        "starts_at": row.starts_at.isoformat(),
        "ends_at": row.ends_at.isoformat() if row.ends_at else None,
        "destination_city_id": row.destination_city_id,
        "destination_city_name": row.destination_city_name,
        "destination_timezone": row.destination_timezone,
        "origin_city_id": row.origin_city_id,
        "user_confirmed": row.user_confirmed,
        "status": row.status,
        "notes": row.notes,
        "version": row.version,
        "created_at": row.created_at.isoformat(),
    }


def upcoming_activities(
    db: Session, *, tenant_id: str, user_id: str, within_hours: float = 72
) -> list[Activity]:
    now = clock_now(db)
    limit = now + timedelta(hours=within_hours)
    rows = list_activities(db, tenant_id=tenant_id, user_id=user_id, statuses=["planned"])
    return [r for r in rows if r.user_confirmed and r.starts_at <= limit and r.starts_at >= now - timedelta(hours=24)]
