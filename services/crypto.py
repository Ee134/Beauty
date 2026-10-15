"""Small crypto helper for subscription credentials.

The demo uses a deterministic local key derived from SECRET_KEY-equivalent
configuration so tokens are never stored in plain text nor written to logs.
Real deployments must supply a proper key management adapter.
"""

from __future__ import annotations

import base64
import hashlib
import os

from cryptography.fernet import Fernet  # type: ignore

from ..config import get_settings


def _key() -> bytes:
    settings = get_settings()
    seed = os.environ.get("STORAGE_ENCRYPTION_KEY") or f"beautycare-local::{settings.database_url}"
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


def encrypt(value: str) -> str:
    if value is None:
        return ""
    return Fernet(_key()).encrypt(value.encode("utf-8")).decode("ascii")


def decrypt(value: str) -> str:
    if not value:
        return ""
    return Fernet(_key()).decrypt(value.encode("ascii")).decode("utf-8")


def redact(value: str | None) -> str:
    """Never log full endpoints/tokens."""
    if not value:
        return "<empty>"
    return value[:12] + "…" + str(len(value))
