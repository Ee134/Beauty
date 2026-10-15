"""Real-network smoke test for the live weather adapter (WEATHER_MODE=live).

Usage:
    ./.venv/bin/python scripts/smoke_live_weather.py [CITY_ID ...]

Prints the raw provider result and the persisted snapshot fields so the README /
evaluation report can record an actual measured result instead of a claim.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.config import get_settings, reset_settings_cache  # noqa: E402
from app.db import reset_engine, session_scope  # noqa: E402
from app.environment import service as env_service  # noqa: E402
from app.models import Base, City  # noqa: E402
from app.providers.weather import OpenMeteoWeatherProvider  # noqa: E402
from sqlalchemy import select  # noqa: E402


def main() -> int:
    import os
    import tempfile

    city_ids = sys.argv[1:] or ["CN-GZ", "CN-BJ"]
    tmp = tempfile.mkdtemp()
    os.environ["DATABASE_URL"] = f"sqlite+pysqlite:///{tmp}/smoke.db"
    os.environ["UPLOAD_DIR"] = f"{tmp}/uploads"
    os.environ["DATA_DIR"] = str(ROOT / "data")
    os.environ["WEATHER_MODE"] = "live"
    reset_settings_cache()
    settings = get_settings()
    reset_engine(settings.database_url)
    from app.services import seed

    with session_scope() as db:
        Base.metadata.create_all(db.get_bind())
        if not seed.is_seeded(db):
            seed.seed_catalog(db, settings)
    print(f"WEATHER_MODE={settings.weather_mode} endpoint={settings.weather_api_base}")

    exit_code = 0
    for city_id in city_ids:
        with session_scope() as db:
            city = db.execute(select(City).where(City.city_id == city_id)).scalar_one_or_none()
            if city is None:
                print(f"[{city_id}] city not seeded; run scripts/seed_db.py first")
                continue
            provider = OpenMeteoWeatherProvider(settings)
            try:
                result = provider.fetch(db, city)
            except Exception as exc:  # noqa: BLE001
                print(f"[{city_id}] FAILED: {type(exc).__name__}: {exc}")
                exit_code = 1
                continue
            print(f"--- {city_id} {city.name_zh} (provider={result.provider} mode={result.mode})")
            print(f"    quality={result.quality} missing={result.missing_fields}")
            if result.current:
                print("    current:", json.dumps(result.current.metrics, ensure_ascii=False))
                print(
                    "    issued_at:",
                    result.current.issued_at.isoformat(),
                    "valid_to:",
                    result.current.valid_to.isoformat(),
                )
            for day in result.forecast:
                print(
                    "    forecast",
                    day.valid_from.date().isoformat(),
                    json.dumps(day.metrics, ensure_ascii=False),
                )
            # also exercise the service level path that persists the snapshot
            payload = env_service.load_environment(db, city=city, settings=settings, persist=True)
            print(
                "    persisted snapshot:",
                (payload.get("current") or {}).get("id"),
                "freshness:",
                (payload.get("current") or {}).get("freshness"),
            )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
