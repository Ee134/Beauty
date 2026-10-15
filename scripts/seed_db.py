"""Seed the local database with catalog, sources, demo users and demo history.

Usage:
    ./.venv/bin/python -m scripts.seed_db            # seed if empty
    ./.venv/bin/python -m scripts.seed_db --force    # wipe user data tables first
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.config import get_settings  # noqa: E402
from app.db import get_engine, session_scope  # noqa: E402
from app.models import Base  # noqa: E402
from app.services import atlas as atlas_service  # noqa: E402
from app.services import seed  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed the BeautyCare demo database")
    parser.add_argument("--force", action="store_true", help="drop and recreate all tables first")
    args = parser.parse_args()

    settings = get_settings()
    print(f"database   : {settings.database_url}")
    print(f"data dir   : {settings.data_dir}")
    print(f"upload dir : {settings.upload_path}")
    print(f"model mode : {settings.model_mode}")

    engine = get_engine()
    if args.force:
        print("dropping all tables…")
        Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)

    with session_scope() as db:
        if seed.is_seeded(db):
            print("demo data already present — nothing to do (use --force to reset)")
            return 0
        result = seed.seed_all(db, settings)
        print("\nseeded personas:")
        for code, info in result["personas"].items():
            print(f"  {code:12s} {info['role']:9s} {info['email']}")
        print(f"\ncatalog products: {len(result['catalog'])} (demo + real)")
        if "consumer_a" in result:
            print(f"consumer_a active plan v{result['consumer_a']['plan_version']}")
            print(f"consumer_a usage events: {len(result['consumer_a']['events'])}")
        user_a = result["personas"]["consumer_a"]["user_id"]
        tenant_a = result["tenant_id"]
        payload = atlas_service.build_payload(
            db, tenant_id=tenant_a, user_id=user_a, min_events=settings.atlas_min_events
        )
        print(f"atlas preview for consumer_a: {payload['stats']}")
    print("\nCreate a local session token with:")
    print('  curl -s -X POST http://127.0.0.1:8000/api/v1/auth/demo-session \\')
    print('       -H "Content-Type: application/json" -d \'{"persona_code":"consumer_a"}\'')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
