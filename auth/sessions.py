"""Server-side sessions and authorization.

The browser never sends a user_id. It sends an opaque bearer token that the
server resolves to a User row, and every query is scoped by that row.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime

from fastapi import Depends, Header, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..models import User, UserSession
from ..services import clock
from ..services.errors import ForbiddenError, UnauthorizedError


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def new_token() -> str:
    return "bc_" + secrets.token_urlsafe(32)


@dataclass
class AuthContext:
    user: User
    tenant_id: str
    session: UserSession
    token_hash: str

    @property
    def user_id(self) -> str:
        return self.user.id

    @property
    def role(self) -> str:
        return self.user.role

    @property
    def timezone(self) -> str:
        return self.user.timezone

    def is_staff(self) -> bool:
        return self.user.role in {"staff", "admin"}

    def is_brand(self) -> bool:
        return self.user.role in {"brand", "admin"}

    def require_staff(self) -> None:
        if not self.is_staff():
            raise ForbiddenError("需要客服角色权限")

    def require_brand(self) -> None:
        if not self.is_brand():
            raise ForbiddenError("需要品牌角色权限")


def create_session(
    db: Session,
    user: User,
    *,
    persona_code: str | None = None,
    label: str | None = None,
    kind: str = "demo",
) -> tuple[str, UserSession]:
    token = new_token()
    row = UserSession(
        user_id=user.id,
        token_hash=hash_token(token),
        kind=kind,
        persona_code=persona_code,
        label=label,
    )
    db.add(row)
    db.flush()
    return token, row


def resolve_token(db: Session, token: str) -> AuthContext:
    if not token:
        raise UnauthorizedError("缺少访问令牌")
    row = db.execute(
        select(UserSession).where(UserSession.token_hash == hash_token(token))
    ).scalar_one_or_none()
    if row is None or row.revoked_at is not None:
        raise UnauthorizedError("访问令牌无效或已撤销")
    user = db.get(User, row.user_id)
    if user is None or user.deleted_at is not None:
        raise UnauthorizedError("账号不可用")
    return AuthContext(user=user, tenant_id=user.tenant_id, session=row, token_hash=row.token_hash)


def _extract_token(request: Request, authorization: str | None, x_demo_token: str | None) -> str:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization.split(" ", 1)[1].strip()
    if x_demo_token:
        return x_demo_token.strip()
    cookie = request.cookies.get("bc_session")
    return cookie or ""


def get_auth(
    request: Request,
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
    x_demo_token: str | None = Header(default=None),
) -> AuthContext:
    token = _extract_token(request, authorization, x_demo_token)
    return resolve_token(db, token)


def optional_auth(
    request: Request,
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
    x_demo_token: str | None = Header(default=None),
) -> AuthContext | None:
    token = _extract_token(request, authorization, x_demo_token)
    if not token:
        return None
    try:
        return resolve_token(db, token)
    except UnauthorizedError:
        return None


def require_staff(auth: AuthContext = Depends(get_auth)) -> AuthContext:
    auth.require_staff()
    return auth


def require_brand(auth: AuthContext = Depends(get_auth)) -> AuthContext:
    auth.require_brand()
    return auth


def demo_login_allowed() -> bool:
    return get_settings().auth_mode == "demo"


def touch_session(db: Session, ctx: AuthContext) -> datetime:
    return clock.now(db)
