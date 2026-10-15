"""Weather / environment providers.

`mock` uses a clearly labelled fixture set (mode=mock, is_demo=true).
`live` calls the fixed Open-Meteo endpoint configured in WEATHER_API_BASE; the
model never builds an arbitrary URL, so SSRF is not possible through the agent.
Missing or expired data is reported as missing/expired — never silently mocked.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx

from ..config import Settings, get_settings
from ..models import City
from ..services.clock import now as clock_now
from ..services.errors import EnvironmentUnavailableError

UNITS = {
    "temperature": "°C",
    "relative_humidity": "%",
    "wind_speed": "m/s",
    "uv_index": "index",
    "precipitation": "mm",
}

METRIC_KEYS = (
    "temperature_c",
    "relative_humidity",
    "wind_speed_ms",
    "uv_index",
    "precipitation_mm",
    "condition",
)


@dataclass
class SnapshotDraft:
    city_id: str
    provider: str
    mode: str
    kind: str
    issued_at: datetime
    fetched_at: datetime
    valid_from: datetime
    valid_to: datetime
    timezone: str
    metrics: dict[str, Any]
    quality: str
    missing_fields: list[str] = field(default_factory=list)
    is_demo: bool = True
    error_code: str | None = None

    @property
    def units(self) -> dict[str, str]:
        return UNITS

    def to_dict(self) -> dict[str, Any]:
        return {
            "city_id": self.city_id,
            "provider": self.provider,
            "mode": self.mode,
            "kind": self.kind,
            "issued_at": self.issued_at.isoformat(),
            "fetched_at": self.fetched_at.isoformat(),
            "valid_from": self.valid_from.isoformat(),
            "valid_to": self.valid_to.isoformat(),
            "timezone": self.timezone,
            "units": UNITS,
            "metrics": self.metrics,
            "quality": self.quality,
            "missing_fields": self.missing_fields,
            "is_demo": self.is_demo,
            "error_code": self.error_code,
        }


@dataclass
class WeatherResult:
    provider: str
    mode: str
    current: SnapshotDraft | None
    forecast: list[SnapshotDraft]
    quality: str
    missing_fields: list[str]
    error_code: str | None = None
    notice: str | None = None
    scenario: str = "default"


def _profiles(settings: Settings) -> dict[str, Any]:
    path = Path(settings.fixtures_path) / "weather" / "profiles.json"
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


class MockWeatherProvider:
    name = "mock"
    mode = "mock"

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def scenario(self, db: Any) -> str:
        from ..models import SystemSetting

        row = db.get(SystemSetting, "weather_scenario")
        if row and row.value:
            return str(row.value.get("name") or "default")
        return "default"

    def fetch(self, db: Any, city: City, *, scenario: str | None = None) -> WeatherResult:
        doc = _profiles(self.settings)
        scenario_name = scenario or self.scenario(db)
        scenario = doc["scenarios"].get(scenario_name) or doc["scenarios"]["default"]
        profile = doc["profiles"].get(
            next(
                (
                    c["profile"]
                    for c in _cities(self.settings)
                    if c["city_id"] == city.city_id
                ),
                "humid_subtropical",
            ),
            doc["profiles"]["humid_subtropical"],
        )
        now = clock_now(db)
        issued = now + timedelta(minutes=float(scenario.get("issued_offset_minutes", 0) or 0))
        if scenario.get("fail"):
            return WeatherResult(
                provider=self.name,
                mode=self.mode,
                current=None,
                forecast=[],
                quality="unavailable",
                missing_fields=list(scenario.get("missing_fields", [])),
                error_code="PROVIDER_ERROR",
                notice="演示场景：天气提供方失败。系统不会用 mock 数据伪装成实时数据。",
                scenario=scenario_name,
            )
        drop = set(scenario.get("drop_fields", []))
        humidity_multiplier = float(scenario.get("humidity_multiplier", 1.0) or 1.0)
        uv_multiplier = float(scenario.get("uv_multiplier", 1.0) or 1.0)

        current_metrics = dict(profile["current"])
        if "relative_humidity" in current_metrics:
            current_metrics["relative_humidity"] = round(
                current_metrics["relative_humidity"] * humidity_multiplier
            )
        if "uv_index" in current_metrics:
            current_metrics["uv_index"] = round(current_metrics["uv_index"] * uv_multiplier)
        missing: list[str] = []
        for key in list(current_metrics):
            if key in drop:
                current_metrics[key] = None
                missing.append(key)
        if scenario.get("quality") == "partial" and not missing:
            missing = list(scenario.get("missing_fields", []))

        current = SnapshotDraft(
            city_id=city.city_id,
            provider=self.name,
            mode=self.mode,
            kind="current",
            issued_at=issued,
            fetched_at=now,
            valid_from=issued,
            valid_to=issued + timedelta(minutes=self.settings.weather_max_age_minutes),
            timezone=city.timezone,
            metrics=current_metrics,
            quality=scenario.get("quality", "ok"),
            missing_fields=missing,
            is_demo=True,
        )

        forecast: list[SnapshotDraft] = []
        forecast_days = int(scenario.get("forecast_days_override") or city.forecast_days)
        daily = profile["daily"]
        for offset in range(max(forecast_days, 0)):
            if offset >= len(daily):
                break
            day = dict(daily[offset])
            day["relative_humidity"] = round(
                day.get("relative_humidity", 0) * humidity_multiplier
            )
            day["uv_index_max"] = round(day.get("uv_index_max", 0) * uv_multiplier)
            day_missing: list[str] = []
            for key in list(day):
                if key in drop:
                    day[key] = None
                    day_missing.append(key)
            start = (now + timedelta(days=offset)).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            forecast.append(
                SnapshotDraft(
                    city_id=city.city_id,
                    provider=self.name,
                    mode=self.mode,
                    kind="forecast",
                    issued_at=issued,
                    fetched_at=now,
                    valid_from=start,
                    valid_to=start + timedelta(days=1),
                    timezone=city.timezone,
                    metrics=day,
                    quality=scenario.get("quality", "ok"),
                    missing_fields=day_missing,
                    is_demo=True,
                )
            )
        quality = scenario.get("quality", "ok")
        if scenario_name == "beyond_coverage":
            quality = "partial"
        notice = None
        if quality == "stale":
            notice = "演示场景：数据已过时，环境触发已暂停。"
        elif quality == "partial":
            notice = "演示场景：部分字段缺失，缺失字段显示为未知（不会用 0 代替）。"
        return WeatherResult(
            provider=self.name,
            mode=self.mode,
            current=current,
            forecast=forecast,
            quality=quality,
            missing_fields=missing,
            notice=notice,
            scenario=scenario_name,
        )


class OpenMeteoWeatherProvider:
    """Real provider. Requires no key; the endpoint is fixed by configuration."""

    name = "open-meteo"
    mode = "live"

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def _get(self, city: City) -> dict[str, Any]:
        params = {
            "latitude": city.latitude,
            "longitude": city.longitude,
            "current": "temperature_2m,relative_humidity_2m,wind_speed_10m,precipitation,weather_code",
            "hourly": "uv_index",
            "daily": "temperature_2m_max,temperature_2m_min,relative_humidity_2m_mean,uv_index_max,precipitation_sum,weather_code",
            "timezone": city.timezone,
            "wind_speed_unit": "ms",
            "forecast_days": min(max(city.forecast_days, 1), 16),
        }
        if self.settings.weather_api_key:
            params["apikey"] = self.settings.weather_api_key
        try:
            with httpx.Client(timeout=self.settings.weather_timeout_seconds) as client:
                response = client.get(self.settings.weather_api_base, params=params)
                response.raise_for_status()
                return response.json()
        except Exception as exc:  # noqa: BLE001
            raise EnvironmentUnavailableError(
                "天气提供方不可用，未获取到实时/预报数据。",
                details={"provider": self.name, "error": type(exc).__name__},
            ) from exc

    def fetch(self, db: Any, city: City, *, scenario: str | None = None) -> WeatherResult:
        payload = self._get(city)
        now = clock_now(db)
        current_raw = payload.get("current") or {}
        daily_raw = payload.get("daily") or {}
        hourly_raw = payload.get("hourly") or {}
        missing: list[str] = []

        def pick(source: dict[str, Any], key: str) -> Any:
            value = source.get(key)
            if value is None:
                missing.append(key)
            return value

        uv_now = None
        times = hourly_raw.get("time") or []
        uvs = hourly_raw.get("uv_index") or []
        for ts, uv in zip(times, uvs):
            try:
                moment = datetime.fromisoformat(ts).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
            if moment <= now:
                uv_now = uv
        if uv_now is None:
            missing.append("uv_index")

        metrics = {
            "temperature_c": pick(current_raw, "temperature_2m"),
            "relative_humidity": pick(current_raw, "relative_humidity_2m"),
            "wind_speed_ms": pick(current_raw, "wind_speed_10m"),
            "precipitation_mm": pick(current_raw, "precipitation"),
            "uv_index": uv_now,
            "condition": str(pick(current_raw, "weather_code")),
        }
        current = SnapshotDraft(
            city_id=city.city_id,
            provider=self.name,
            mode=self.mode,
            kind="current",
            issued_at=now,
            fetched_at=now,
            valid_from=now,
            valid_to=now + timedelta(minutes=self.settings.weather_max_age_minutes),
            timezone=city.timezone,
            metrics=metrics,
            quality="partial" if missing else "ok",
            missing_fields=sorted(set(missing)),
            is_demo=False,
        )
        forecast: list[SnapshotDraft] = []
        days = daily_raw.get("time") or []
        for idx, day in enumerate(days):
            day_metrics = {
                "temperature_max_c": (daily_raw.get("temperature_2m_max") or [None] * len(days))[idx],
                "temperature_min_c": (daily_raw.get("temperature_2m_min") or [None] * len(days))[idx],
                "relative_humidity": (daily_raw.get("relative_humidity_2m_mean") or [None] * len(days))[idx],
                "uv_index_max": (daily_raw.get("uv_index_max") or [None] * len(days))[idx],
                "precipitation_mm": (daily_raw.get("precipitation_sum") or [None] * len(days))[idx],
                "condition": str((daily_raw.get("weather_code") or [None] * len(days))[idx]),
            }
            start = datetime.fromisoformat(day).replace(tzinfo=timezone.utc)
            forecast.append(
                SnapshotDraft(
                    city_id=city.city_id,
                    provider=self.name,
                    mode=self.mode,
                    kind="forecast",
                    issued_at=now,
                    fetched_at=now,
                    valid_from=start,
                    valid_to=start + timedelta(days=1),
                    timezone=city.timezone,
                    metrics=day_metrics,
                    quality="ok",
                    missing_fields=[],
                    is_demo=False,
                )
            )
        return WeatherResult(
            provider=self.name,
            mode=self.mode,
            current=current,
            forecast=forecast,
            quality=current.quality,
            missing_fields=current.missing_fields,
            error_code=None,
            notice=None,
            scenario="live",
        )


def _cities(settings: Settings) -> list[dict[str, Any]]:
    path = Path(settings.data_dir) / "sources" / "cities.json"
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)["cities"]


def get_weather_provider(settings: Settings | None = None) -> Any:
    settings = settings or get_settings()
    if settings.weather_mode == "live":
        return OpenMeteoWeatherProvider(settings)
    return MockWeatherProvider(settings)
