"""Shared FastAPI dependencies."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header, Query
from sqlalchemy.orm import Session

from ..auth import AuthContext, get_auth, require_brand, require_staff
from ..config import Settings, get_settings
from ..db import get_db
from ..services.clock import snapshot

DbSession = Annotated[Session, Depends(get_db)]
CurrentAuth = Annotated[AuthContext, Depends(get_auth)]
StaffAuth = Annotated[AuthContext, Depends(require_staff)]
BrandAuth = Annotated[AuthContext, Depends(require_brand)]


def settings_dep() -> Settings:
    return get_settings()


SettingsDep = Annotated[Settings, Depends(settings_dep)]


def idempotency_key(
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> str | None:
    return idempotency_key


IdempotencyKey = Annotated[str | None, Depends(idempotency_key)]


def clock_info(db: DbSession) -> dict:
    return snapshot(db).to_dict()


ClockInfo = Annotated[dict, Depends(clock_info)]


def pagination(
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: Annotated[str | None, Query()] = None,
) -> tuple[int, str | None]:
    return limit, cursor


Pagination = Annotated[tuple[int, str | None], Depends(pagination)]
