"""Request level normalisation helpers.

Clients in different timezones may send naive datetimes (for example an
`<input type="datetime-local">`). The API must interpret them as UTC instead of
crashing on an aware/naive comparison, so every datetime field is normalised at
the edge, in one place.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def to_utc(value: Any) -> Any:
    if value is None or not isinstance(value, datetime):
        return value
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
