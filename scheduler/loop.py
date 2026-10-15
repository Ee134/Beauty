"""Persistent scheduler.

Runs independently of any browser session: an asyncio loop inside the API
process (production would run it as a separate worker) plus an explicit tick
endpoint for tests and demos. Jobs already stored in the database survive a
restart, and the outbox idempotency key prevents duplicates after a restart.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import Settings, get_settings
from ..db import session_scope
from ..models import FixedJobLock, ImportBatch, NotificationPreference, User
from ..services import audit
from ..services import outbox as outbox_service
from ..services import proactive as proactive_service
from ..services import triggers as trigger_service
from ..services.clock import now as clock_now


def _scan_users(db: Session, settings: Settings) -> list[tuple[str, str]]:
    stmt = select(NotificationPreference)
    rows = list(db.execute(stmt).scalars())
    return [(row.tenant_id, row.user_id) for row in rows]


def expire_imports(db: Session, *, settings: Settings) -> int:
    """Screenshots are deleted after confirmation + retention window (configurable)."""
    from ..models import ImportBatch

    now = clock_now(db)
    rows = list(
        db.execute(
            select(ImportBatch).where(
                ImportBatch.file_deleted_at.is_(None), ImportBatch.storage_key.is_not(None)
            )
        ).scalars()
    )
    deleted = 0
    for batch in rows:
        anchor = batch.confirmed_at or batch.created_at
        cutoff = anchor + timedelta(hours=settings.import_retention_hours)
        if now < cutoff:
            continue
        path = settings.upload_path / os.path.basename(batch.storage_key or "")
        with contextlib.suppress(FileNotFoundError):
            path.unlink()
        batch.file_deleted_at = now
        batch.storage_key = None
        if batch.status not in {"confirmed", "failed"}:
            batch.status = "expired"
        deleted += 1
    if deleted:
        db.flush()
        audit.record(db, action="import.files_expired", actor_role="system", meta={"count": deleted})
    return deleted


def run_tick(
    db: Session,
    *,
    settings: Settings | None = None,
    worker_id: str | None = None,
    create_messages: bool = True,
) -> dict[str, Any]:
    settings = settings or get_settings()
    worker_id = worker_id or settings.outbox_worker_id
    started = clock_now(db)
    summary: dict[str, Any] = {
        "started_at": started.isoformat(),
        "users": 0,
        "decisions": [],
        "outbox": [],
        "expired_outbox": 0,
        "expired_imports": 0,
    }
    for tenant_id, user_id in _scan_users(db, settings):
        summary["users"] += 1
        decisions = trigger_service.evaluate_triggers(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            settings=settings,
            create_messages=create_messages,
        )
        summary["decisions"].extend(decisions)
    summary["expired_outbox"] = outbox_service.expire_stale(db, settings=settings)
    summary["outbox"] = outbox_service.process_outbox(db, worker_id=worker_id, settings=settings)
    summary["expired_imports"] = expire_imports(db, settings=settings)
    summary["finished_at"] = clock_now(db).isoformat()
    return summary


def acquire_tick_lock(db: Session, *, name: str = "scheduler", owner: str) -> bool:
    """A single row lock keeps one scheduler active per database."""
    lock = db.get(FixedJobLock, name)
    now = clock_now(db)
    if lock is None:
        db.add(FixedJobLock(name=name, owner=owner, locked_until=now + timedelta(seconds=90)))
        db.flush()
        return True
    if lock.locked_until is not None and lock.locked_until > now and lock.owner != owner:
        return False
    lock.owner = owner
    lock.locked_until = now + timedelta(seconds=90)
    db.flush()
    return True


class SchedulerLoop:
    def __init__(self, settings: Settings | None = None, worker_id: str | None = None) -> None:
        self.settings = settings or get_settings()
        self.worker_id = worker_id or f"loop-{os.getpid()}"
        self._task: asyncio.Task[None] | None = None
        self._stopping = asyncio.Event()
        self.last_tick: dict[str, Any] | None = None

    async def _run(self) -> None:
        while not self._stopping.is_set():
            try:
                with session_scope() as db:
                    if acquire_tick_lock(db, owner=self.worker_id):
                        self.last_tick = run_tick(
                            db, settings=self.settings, worker_id=self.worker_id
                        )
            except Exception as exc:  # noqa: BLE001 - the loop must survive
                self.last_tick = {"error": type(exc).__name__}
            try:
                await asyncio.wait_for(
                    self._stopping.wait(), timeout=self.settings.scheduler_interval_seconds
                )
            except asyncio.TimeoutError:
                continue

    def start(self) -> None:
        if not self.settings.scheduler_enabled:
            return
        if self._task is None or self._task.done():
            self._stopping.clear()
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        self._stopping.set()
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None


_loop: SchedulerLoop | None = None


def get_loop() -> SchedulerLoop:
    global _loop
    if _loop is None:
        _loop = SchedulerLoop()
    return _loop


def tick_once(db: Session, *, settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    return run_tick(db, settings=settings, worker_id="manual-tick")
