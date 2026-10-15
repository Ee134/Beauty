"""Unit tests: quiet hours, the demo clock, crypto and model mode honesty."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.services import clock as clock_service  # noqa: E402
from app.services import proactive as proactive_service  # noqa: E402


def _preference(**kwargs):
    from app.models import NotificationPreference

    base = dict(
        tenant_id="t",
        user_id="u",
        service_types=["travel_support"],
        channels=["in_app"],
        daily_cap=1,
        quiet_hours_start="22:00",
        quiet_hours_end="08:00",
        timezone="Asia/Shanghai",
    )
    base.update(kwargs)
    return NotificationPreference(**base)


@pytest.mark.parametrize(
    "hour,expected",
    [(23, True), (2, True), (7, True), (8, False), (12, False), (21, False), (22, True)],
)
def test_quiet_hours_wrap_across_midnight(hour, expected):
    preference = _preference()
    moment = datetime(2026, 3, 1, hour, 30, tzinfo=ZoneInfo("Asia/Shanghai")).astimezone(timezone.utc)
    assert proactive_service.quiet_hours_active(preference, moment) is expected


def test_quiet_hours_respect_the_configured_timezone():
    preference = _preference(timezone="UTC", quiet_hours_start="01:00", quiet_hours_end="05:00")
    moment = datetime(2026, 3, 1, 3, 0, tzinfo=timezone.utc)
    assert proactive_service.quiet_hours_active(preference, moment) is True
    moment_utc_afternoon = datetime(2026, 3, 1, 14, 0, tzinfo=timezone.utc)
    assert proactive_service.quiet_hours_active(preference, moment_utc_afternoon) is False


def test_equal_quiet_hours_bounds_disable_the_window():
    preference = _preference(quiet_hours_start="00:00", quiet_hours_end="00:00")
    assert proactive_service.quiet_hours_active(preference, datetime.now(timezone.utc)) is False


def test_defer_until_lands_after_the_quiet_window():
    preference = _preference()
    now = datetime(2026, 3, 1, 15, 0, tzinfo=timezone.utc)  # 23:00 in Shanghai
    target = proactive_service._next_quiet_hours_end(preference, now)
    local = target.astimezone(ZoneInfo("Asia/Shanghai"))
    assert (local.hour, local.minute) == (8, 0)
    assert target > now


def test_idempotency_key_is_stable_and_complete():
    key1 = proactive_service._idempotency_key("user", "event", "travel_support", 2, 1)
    key2 = proactive_service._idempotency_key("user", "event", "travel_support", 2, 1)
    key3 = proactive_service._idempotency_key("user", "event", "travel_support", 3, 1)
    assert key1 == key2
    assert key1 != key3
    assert key1.split(":") == ["user", "event", "travel_support", "2", "1"]


def test_demo_clock_marks_shifted_time(db):
    before = clock_service.snapshot(db)
    assert before.is_demo_time is False
    assert before.mode == "real"

    shifted = clock_service.set_override(db, offset_hours=48, label="演示第 3 天", actor="test")
    assert shifted.is_demo_time is True
    assert shifted.label == "演示第 3 天"
    assert shifted.now > before.now
    assert abs((shifted.now - before.now).total_seconds() - 48 * 3600) < 5

    cleared = clock_service.set_override(db, clear=True)
    assert cleared.is_demo_time is False
    assert cleared.mode == "real"


def test_crypto_roundtrip_and_redaction():
    from app.services import crypto

    secret = "https://push.example.invalid/very-secret-endpoint-token"
    encrypted = crypto.encrypt(secret)
    assert secret not in encrypted
    assert crypto.decrypt(encrypted) == secret
    redacted = crypto.redact(secret)
    assert "very-secret" not in redacted
    assert len(redacted) < len(secret)


def test_live_mode_without_credentials_is_unavailable(monkeypatch):
    from app.config import Settings, reset_settings_cache
    from app.providers.model import model_status

    settings = Settings(
        MODEL_MODE="live", MODEL_PROVIDER="openai_compatible", MODEL_NAME="", API_BASE="", API_KEY=""
    )
    status = model_status(settings)
    assert status["mode"] == "live"
    assert status["available"] is False
    assert "不可用" in status["notice"]

    configured = Settings(
        MODEL_MODE="live",
        MODEL_PROVIDER="openai_compatible",
        MODEL_NAME="some-model",
        API_BASE="https://example.invalid/v1",
        API_KEY="secret-key",
    )
    status = model_status(configured)
    assert status["available"] is True
    assert "secret-key" not in str(status)


def test_mock_status_is_explicitly_labelled():
    from app.config import Settings
    from app.providers.model import model_status

    status = model_status(Settings(MODEL_MODE="mock"))
    assert status["is_mock"] is True
    assert "确定性 fixtures" in status["notice"]


def test_notification_channel_status_is_honest():
    from app.config import Settings
    from app.providers.notifications import channel_status

    status = channel_status(Settings(NOTIFICATION_MODE="in_app"))
    assert status["in_app"]["available"] is True
    assert status["web_push"]["available"] is False
    assert status["native_push"]["available"] is False
    assert "未交付原生客户端" in status["native_push"]["notice"]


def test_citation_strict_allowed_domains_configuration():
    from app.config import Settings

    settings = Settings(ALLOWED_SOURCE_DOMAINS="a.com,b.org , c.cn")
    assert settings.allowed_domain_list == ["a.com", "b.org", "c.cn"]
    assert settings.quiet_hours_range == ("22:00", "08:00")


def test_quiet_hours_handle_dst_transitions():
    """22:00–08:00 local must hold on both sides of a DST switch."""
    preference = _preference(
        timezone="America/New_York", quiet_hours_start="22:00", quiet_hours_end="08:00"
    )
    # 2026-03-08 is the US spring-forward date; 2026-11-01 the fall-back date.
    before_dst = datetime(2026, 3, 7, 23, 30, tzinfo=ZoneInfo("America/New_York"))
    after_dst = datetime(2026, 3, 9, 23, 30, tzinfo=ZoneInfo("America/New_York"))
    autumn = datetime(2026, 11, 1, 6, 30, tzinfo=ZoneInfo("America/New_York"))
    daytime = datetime(2026, 3, 9, 13, 0, tzinfo=ZoneInfo("America/New_York"))
    assert proactive_service.quiet_hours_active(preference, before_dst.astimezone(timezone.utc))
    assert proactive_service.quiet_hours_active(preference, after_dst.astimezone(timezone.utc))
    assert proactive_service.quiet_hours_active(preference, autumn.astimezone(timezone.utc))
    assert not proactive_service.quiet_hours_active(preference, daytime.astimezone(timezone.utc))


def test_defer_target_is_computed_in_the_user_timezone():
    preference = _preference(timezone="America/New_York", quiet_hours_end="08:00")
    now = datetime(2026, 3, 9, 3, 0, tzinfo=timezone.utc)  # 23:00 in New York (EDT)
    target = proactive_service._next_quiet_hours_end(preference, now)
    local = target.astimezone(ZoneInfo("America/New_York"))
    assert (local.hour, local.minute) == (8, 0)
    assert local.date() > now.astimezone(ZoneInfo("America/New_York")).date()


def test_mock_push_channel_is_labelled_and_never_claims_receipt(monkeypatch):
    """Web Push without credentials runs as an explicit mock channel."""
    from app.config import Settings
    from app.providers import notifications as providers

    settings = Settings(NOTIFICATION_MODE="mock_push", VAPID_PUBLIC_KEY="", VAPID_PRIVATE_KEY="")
    provider = providers.get_provider("web_push", settings)
    assert provider.mode == "mock"

    class _Message:
        id = "0123456789abcdef"
        title = "户外活动提醒"
        body = "该时段紫外线指数预报为 7（演示环境数据）"
        payload = {"service_type": "outdoor_support"}

    class _Subscription:
        endpoint_encrypted = "irrelevant"

    accepted = provider.deliver(_Message(), _Subscription())
    assert accepted.status == "provider_accepted"
    assert accepted.provider_confirmed_receipt is False
    assert "不代表设备已收到" in (accepted.notice or "")

    missing = provider.deliver(_Message(), None)
    assert missing.status == "failed"
    assert missing.error == "NO_ACTIVE_SUBSCRIPTION"

    status = providers.channel_status(settings)
    assert status["web_push"]["available"] is True
    assert status["web_push"]["mode"] == "mock"
    assert status["native_push"]["available"] is False
