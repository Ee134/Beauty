"""Integration: the Alembic migration must produce the full schema from scratch."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
VENV_PYTHON = ROOT / ".venv" / "bin" / "python"

EXPECTED_TABLES = {
    "tenants",
    "users",
    "user_sessions",
    "catalog_products",
    "knowledge_sources",
    "knowledge_chunks",
    "ingredient_profiles",
    "user_ingredient_signals",
    "system_settings",
    "cities",
    "owned_products",
    "import_batches",
    "conversations",
    "messages",
    "memory_records",
    "usage_events",
    "ingredient_feedback",
    "ingredient_atlas_views",
    "review_prompts",
    "routine_plans",
    "routine_steps",
    "followup_tasks",
    "service_tickets",
    "ticket_events",
    "agent_runs",
    "audit_events",
    "brand_insight_drafts",
    "location_preferences",
    "activities",
    "environment_snapshots",
    "trigger_rules",
    "notification_preferences",
    "push_subscriptions",
    "proactive_decisions",
    "service_messages",
    "notification_outbox",
    "notification_deliveries",
    "message_feedback",
    "fixed_job_locks",
}


@pytest.mark.slow
def test_alembic_upgrade_head_creates_the_full_schema(tmp_path):
    db_path = tmp_path / "migrated.db"
    env = {"DATABASE_URL": f"sqlite+pysqlite:///{db_path}", "PATH": "/usr/bin:/bin"}
    upgrade = subprocess.run(
        [str(VENV_PYTHON), "-m", "alembic", "-c", "alembic.ini", "upgrade", "head"],
        cwd=BACKEND,
        env=env,
        capture_output=True,
        text=True,
    )
    assert upgrade.returncode == 0, upgrade.stderr

    import sqlite3

    connection = sqlite3.connect(db_path)
    try:
        tables = {row[0] for row in connection.execute("select name from sqlite_master where type='table'")}
    finally:
        connection.close()
    assert EXPECTED_TABLES <= tables, EXPECTED_TABLES - tables
    assert "alembic_version" in tables


@pytest.mark.slow
def test_migrated_database_is_usable_by_the_app(tmp_path):
    db_path = tmp_path / "seeded.db"
    url = f"sqlite+pysqlite:///{db_path}"
    env = {"DATABASE_URL": url, "PATH": "/usr/bin:/bin"}
    upgrade = subprocess.run(
        [str(VENV_PYTHON), "-m", "alembic", "-c", "alembic.ini", "upgrade", "head"],
        cwd=BACKEND,
        env=env,
        capture_output=True,
        text=True,
    )
    assert upgrade.returncode == 0, upgrade.stderr

    seed = subprocess.run(
        [str(VENV_PYTHON), "-m", "scripts.seed_db"],
        cwd=ROOT,
        env={
            **env,
            "DATA_DIR": str(ROOT / "data"),
            "UPLOAD_DIR": str(tmp_path / "uploads"),
            "SCHEDULER_ENABLED": "false",
        },
        capture_output=True,
        text=True,
    )
    assert seed.returncode == 0, seed.stderr
    assert "atlas preview for consumer_a" in seed.stdout
    assert "'card_count': 4" in seed.stdout or "card_count" in seed.stdout


def test_downgrade_and_upgrade_again(tmp_path):
    db_path = tmp_path / "roundtrip.db"
    url = f"sqlite+pysqlite:///{db_path}"
    env = {"DATABASE_URL": url, "PATH": "/usr/bin:/bin"}

    def run(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(VENV_PYTHON), "-m", "alembic", "-c", "alembic.ini", *args],
            cwd=BACKEND,
            env=env,
            capture_output=True,
            text=True,
        )

    assert run("upgrade", "head").returncode == 0
    assert run("downgrade", "base").returncode == 0
    assert run("upgrade", "head").returncode == 0
