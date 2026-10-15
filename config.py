"""Application configuration.

Every externally visible switch is an environment variable documented in
`.env.example`. Secrets are read by the backend process only and are never
returned to the browser.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATA_DIR = REPO_ROOT / "data"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(REPO_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- app ---
    app_name: str = "BeautyCare MVP"
    app_env: str = Field(default="local", alias="APP_ENV")
    app_timezone: str = Field(default="Asia/Shanghai", alias="APP_TIMEZONE")
    api_prefix: str = "/api/v1"
    # demo shows the fixed server-side demo identities; deploy requires real auth.
    auth_mode: str = Field(default="demo", alias="AUTH_MODE")
    cors_origins: str = Field(
        default="http://localhost:5173,http://127.0.0.1:5173", alias="CORS_ORIGINS"
    )

    # --- storage ---
    database_url: str = Field(
        default=f"sqlite+pysqlite:///{REPO_ROOT / 'beautycare.db'}", alias="DATABASE_URL"
    )
    upload_dir: str = Field(default=str(REPO_ROOT / "var" / "uploads"), alias="UPLOAD_DIR")
    data_dir: str = Field(default=str(DEFAULT_DATA_DIR), alias="DATA_DIR")

    # --- model adapter ---
    model_mode: str = Field(default="mock", alias="MODEL_MODE")  # mock | live
    model_provider: str = Field(default="mock", alias="MODEL_PROVIDER")
    model_name: str = Field(default="", alias="MODEL_NAME")
    api_base: str = Field(default="", alias="API_BASE")
    api_key: str = Field(default="", alias="API_KEY")
    model_timeout_seconds: float = Field(default=30.0, alias="MODEL_TIMEOUT_SECONDS")
    turn_budget_seconds: float = Field(default=60.0, alias="TURN_BUDGET_SECONDS")
    max_tool_calls_per_turn: int = Field(default=6, alias="MAX_TOOL_CALLS_PER_TURN")
    max_clarifying_questions: int = Field(default=2, alias="MAX_CLARIFYING_QUESTIONS")
    prompt_version: str = Field(default="v1.2", alias="PROMPT_VERSION")

    # --- vision / OCR adapter ---
    vision_mode: str = Field(default="mock", alias="VISION_MODE")  # mock | live
    ocr_mode: str = Field(default="mock", alias="OCR_MODE")  # mock | live
    vision_provider: str = Field(default="mock", alias="VISION_PROVIDER")
    ocr_provider: str = Field(default="mock", alias="OCR_PROVIDER")

    # --- uploads ---
    max_upload_mb: int = Field(default=10, alias="MAX_UPLOAD_MB")
    max_upload_pixels: int = Field(default=25_000_000, alias="MAX_UPLOAD_PIXELS")
    import_retention_hours: int = Field(default=24, alias="IMPORT_RETENTION_HOURS")
    allowed_upload_types: tuple[str, ...] = ("image/jpeg", "image/png", "image/webp")

    # --- knowledge / atlas ---
    atlas_min_events: int = Field(default=3, alias="ATLAS_MIN_EVENTS")
    citation_strict: bool = Field(default=True, alias="CITATION_STRICT")
    # Only reviewed hosts may appear as external source links. The backend never
    # fetches a user supplied URL, so this list also documents what is trusted.
    allowed_source_domains: str = Field(
        default=(
            "pubchem.ncbi.nlm.nih.gov,www.cerave.com,theordinary.com,www.larocheposay.de,"
            "open-meteo.com,ec.europa.eu,local"
        ),
        alias="ALLOWED_SOURCE_DOMAINS",
    )

    # --- environment / weather ---
    weather_mode: str = Field(default="mock", alias="WEATHER_MODE")  # mock | live
    weather_provider: str = Field(default="mock", alias="WEATHER_PROVIDER")
    weather_api_key: str = Field(default="", alias="WEATHER_API_KEY")
    weather_api_base: str = Field(
        default="https://api.open-meteo.com/v1/forecast", alias="WEATHER_API_BASE"
    )
    weather_max_age_minutes: int = Field(default=60, alias="WEATHER_MAX_AGE_MINUTES")
    weather_forecast_max_age_minutes: int = Field(
        default=360, alias="WEATHER_FORECAST_MAX_AGE_MINUTES"
    )
    weather_timeout_seconds: float = Field(default=10.0, alias="WEATHER_TIMEOUT_SECONDS")

    # --- notifications ---
    notification_mode: str = Field(default="in_app", alias="NOTIFICATION_MODE")
    vapid_public_key: str = Field(default="", alias="VAPID_PUBLIC_KEY")
    vapid_private_key: str = Field(default="", alias="VAPID_PRIVATE_KEY")
    vapid_subject: str = Field(default="mailto:demo@example.invalid", alias="VAPID_SUBJECT")
    native_push_token_placeholder: str = Field(default="", alias="NATIVE_PUSH_TOKEN_PLACEHOLDER")
    quiet_hours: str = Field(default="22:00-08:00", alias="QUIET_HOURS")
    service_daily_cap: int = Field(default=1, alias="SERVICE_DAILY_CAP")
    service_min_interval_hours: int = Field(default=24, alias="SERVICE_MIN_INTERVAL_HOURS")

    # --- scheduler ---
    scheduler_enabled: bool = Field(default=True, alias="SCHEDULER_ENABLED")
    scheduler_interval_seconds: int = Field(default=60, alias="SCHEDULER_INTERVAL")
    scheduler_lease_seconds: int = Field(default=120, alias="SCHEDULER_LEASE_SECONDS")
    outbox_worker_id: str = Field(default="worker-local-1", alias="OUTBOX_WORKER_ID")

    # --- brand insights ---
    brand_min_cohort: int = Field(default=10, alias="BRAND_MIN_COHORT")

    # --- demo clock ---
    demo_clock_offset_hours: float = Field(default=0.0, alias="DEMO_CLOCK_OFFSET_HOURS")

    @field_validator("cors_origins")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip()

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def allowed_domain_list(self) -> list[str]:
        return [d.strip().lower() for d in self.allowed_source_domains.split(",") if d.strip()]

    @property
    def upload_path(self) -> Path:
        p = Path(self.upload_dir)
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def fixtures_path(self) -> Path:
        return Path(self.data_dir) / "fixtures"

    @property
    def is_live_model(self) -> bool:
        return self.model_mode == "live"

    @property
    def model_ready(self) -> bool:
        """Live mode without credentials is explicitly unavailable, never silently mocked."""
        if self.model_mode != "live":
            return True
        return bool(self.api_key and self.api_base and self.model_name)

    @property
    def quiet_hours_range(self) -> tuple[str, str]:
        raw = self.quiet_hours
        if "-" in raw:
            start, end = raw.split("-", 1)
            return start.strip(), end.strip()
        return "22:00", "08:00"


@lru_cache
def get_settings() -> Settings:
    return Settings()


def reset_settings_cache() -> None:
    get_settings.cache_clear()


def env_flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}
