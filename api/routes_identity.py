"""Identity, health and demo personas."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from ..auth import create_session, demo_login_allowed
from ..config import get_settings
from ..models import User
from ..providers.model import model_status
from ..providers.notifications import channel_status
from ..services import cabinet as cabinet_service
from ..services import proactive as proactive_service
from ..services import routine_service
from ..services.errors import ForbiddenError
from .deps import ClockInfo, CurrentAuth, DbSession, SettingsDep

router = APIRouter()


class DemoSessionRequest(BaseModel):
    persona_code: str = Field(description="consumer_a / consumer_b / staff / brand")
    device_label: str | None = None


@router.get("/health")
def health(db: DbSession) -> dict[str, Any]:
    settings = get_settings()
    return {
        "status": "ok",
        "app": settings.app_name,
        "env": settings.app_env,
        "auth_mode": settings.auth_mode,
        "model": {
            "mode": settings.model_mode,
            "available": settings.model_ready,
            "is_mock": settings.model_mode == "mock",
        },
        "weather": {"mode": settings.weather_mode, "provider": settings.weather_provider},
        "notification": {"mode": settings.notification_mode},
        "scheduler": {
            "enabled": settings.scheduler_enabled,
            "interval_seconds": settings.scheduler_interval_seconds,
        },
        "notice": "无敏感信息的健康状态；不含密钥、路径或上传内容。",
    }


@router.get("/meta")
def meta(db: DbSession, settings: SettingsDep, clock: ClockInfo) -> dict[str, Any]:
    return {
        "model": model_status(settings),
        "channels": channel_status(settings),
        "clock": clock,
        "personas": [code for code in ("consumer_a", "consumer_b", "staff", "brand")],
        "demo_auth": demo_login_allowed(),
        "data_notice": (
            "本环境为演示环境：产品目录含虚构 DEMO SKU（is_demo=true）与 3 个带真实来源链接的真实 SKU；"
            "品牌需求与外发渠道均为本地模拟。"
        ),
        "app": {"name": settings.app_name, "timezone": settings.app_timezone},
    }


@router.post("/auth/demo-session")
def demo_session(payload: DemoSessionRequest, db: DbSession) -> dict[str, Any]:
    """Fixed server-side demo identity. Clearly marked; deployment needs real auth."""
    if not demo_login_allowed():
        raise ForbiddenError("当前 AUTH_MODE 不允许演示身份登录，请接入真实认证。")
    from ..services import seed

    spec = seed.PERSONAS.get(payload.persona_code)
    if spec is None:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "未知演示身份"})
    user = db.execute(select(User).where(User.email == spec["email"])).scalar_one_or_none()
    if user is None:
        raise HTTPException(
            status_code=409,
            detail={"code": "NOT_FOUND", "message": "演示身份尚未初始化，请先运行 seed 脚本。"},
        )
    token, session = create_session(
        db, user, persona_code=payload.persona_code, label=payload.device_label
    )
    db.commit()
    return {
        "token": token,
        "persona_code": payload.persona_code,
        "user": {
            "id": user.id,
            "display_name": user.display_name,
            "role": user.role,
            "timezone": user.timezone,
        },
        "notice": (
            "演示身份：由服务端固定映射，仅用于本地演示；"
            "前端不会也不能提交任意 user_id。"
        ),
    }


@router.get("/me")
def me(auth: CurrentAuth, db: DbSession, clock: ClockInfo) -> dict[str, Any]:
    settings = get_settings()
    products = cabinet_service.list_owned(db, tenant_id=auth.tenant_id, user_id=auth.user_id)
    plans = routine_service.list_plans(db, tenant_id=auth.tenant_id, user_id=auth.user_id)
    active = next((p for p in plans if p.status == "active"), None)
    preference = proactive_service.get_preferences(
        db, tenant_id=auth.tenant_id, user_id=auth.user_id
    )
    return {
        "user": {
            "id": auth.user_id,
            "display_name": auth.user.display_name,
            "email": auth.user.email,
            "role": auth.role,
            "timezone": auth.user.timezone,
            "consent_flags": auth.user.consent_flags,
            "is_demo": auth.user.is_demo,
        },
        "tenant_id": auth.tenant_id,
        "mode": {
            "model_mode": settings.model_mode,
            "model_available": settings.model_ready,
            "weather_mode": settings.weather_mode,
            "notification_mode": settings.notification_mode,
            "auth_mode": settings.auth_mode,
        },
        "counts": {
            "owned_products": len(products),
            "paused_products": sum(1 for p in products if p.usage_status != "active"),
            "plans": len(plans),
            "active_plan_version": active.version if active else None,
        },
        "notification": {
            "service_types": preference.service_types,
            "channels": preference.channels,
            "daily_cap": preference.daily_cap,
            "quiet_hours": [preference.quiet_hours_start, preference.quiet_hours_end],
            "timezone": preference.timezone,
        },
        "clock": clock,
        "notice": "演示环境：状态以服务器为准，跨设备共享。",
    }
