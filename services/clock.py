"""Application clock.

A test/demo clock can shift `now()` so the demo script can walk day 1 / 5 / 10.
Whenever the clock is shifted the API marks responses with `clock.is_demo_time`
so a demo timestamp is never mistaken for a real one.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from ..models import SystemSetting

CLOCK_KEY = "clock_override"


@dataclass(frozen=True)
class ClockSnapshot:
    now: datetime
    mode: str  # real | demo
    offset_seconds: float
    fixed_at: datetime | None
    is_demo_time: bool
    label: str

    def to_dict(self) -> dict[str, object]:
        return {
            "now": self.now.isoformat(),
            "mode": self.mode,
            "offset_seconds": self.offset_seconds,
            "fixed_at": self.fixed_at.isoformat() if self.fixed_at else None,
            "is_demo_time": self.is_demo_time,
            "label": self.label,
        }


def read_override(session: Session) -> dict[str, object]:
    row = session.get(SystemSetting, CLOCK_KEY)
    if row is None:
        return {}
    return dict(row.value or {})


def _parse(value: object) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value))
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def snapshot(session: Session) -> ClockSnapshot:
    cfg = read_override(session)
    fixed = _parse(cfg.get("fixed_at"))
    offset = float(cfg.get("offset_seconds") or 0.0)
    base = datetime.now(timezone.utc)
    if fixed is not None:
        now = fixed + timedelta(seconds=offset)
        mode = "demo"
    elif offset:
        now = base + timedelta(seconds=offset)
        mode = "demo"
    else:
        now = base
        mode = "real"
    return ClockSnapshot(
        now=now,
        mode=mode,
        offset_seconds=offset,
        fixed_at=fixed,
        is_demo_time=mode == "demo",
        label=str(cfg.get("label") or ("演示时间" if mode == "demo" else "系统时间")),
    )


def now(session: Session) -> datetime:
    return snapshot(session).now


def set_override(
    session: Session,
    *,
    fixed_at: datetime | None = None,
    offset_hours: float | None = None,
    label: str | None = None,
    actor: str | None = None,
    clear: bool = False,
) -> ClockSnapshot:
    if clear:
        row = session.get(SystemSetting, CLOCK_KEY)
        if row is not None:
            session.delete(row)
            session.flush()
        return snapshot(session)
    payload: dict[str, object] = {}
    if fixed_at is not None:
        payload["fixed_at"] = fixed_at.isoformat()
    if label:
        payload["label"] = label
    existing = read_override(session)
    payload.setdefault("fixed_at", existing.get("fixed_at"))
    if offset_hours is not None:
        payload["offset_seconds"] = float(offset_hours) * 3600.0
    else:
        payload["offset_seconds"] = existing.get("offset_seconds", 0.0)
    payload.setdefault("label", "演示时间")
    row = session.get(SystemSetting, CLOCK_KEY)
    if row is None:
        row = SystemSetting(key=CLOCK_KEY, value=payload, updated_by=actor)
        session.add(row)
    else:
        row.value = payload
        row.updated_by = actor
    session.flush()
    return snapshot(session)


__all__ = ["ClockSnapshot", "snapshot", "now", "set_override", "read_override", "CLOCK_KEY"]
