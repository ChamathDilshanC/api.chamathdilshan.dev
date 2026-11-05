"""Secrets, hashes and signed short-lived cookies."""

import hashlib
import hmac
import logging
import secrets
from typing import Any

from itsdangerous import BadSignature, URLSafeTimedSerializer

from app.core.config import settings

log = logging.getLogger(__name__)

_ephemeral_secret: str | None = None


def session_secret() -> str:
    """SESSION_SECRET, or a per-process random one outside production."""
    global _ephemeral_secret
    if settings.SESSION_SECRET:
        return settings.SESSION_SECRET
    if settings.is_production:
        raise RuntimeError("SESSION_SECRET must be set in production")
    if _ephemeral_secret is None:
        log.warning("SESSION_SECRET is not set — using a random one; sessions end on restart")
        _ephemeral_secret = secrets.token_urlsafe(48)
    return _ephemeral_secret


def new_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_code() -> str:
    """Six random digits from the OS CSPRNG."""
    return f"{secrets.randbelow(1_000_000):06d}"


def code_hash(challenge_id: str, code: str) -> str:
    """Keyed hash of a one-time code, bound to its challenge."""
    msg = f"{challenge_id}:{code}".encode()
    return hmac.new(session_secret().encode(), msg, hashlib.sha256).hexdigest()


def _serializer(salt: str) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(session_secret(), salt=salt)


def seal(salt: str, value: dict[str, Any]) -> str:
    return _serializer(salt).dumps(value)


def unseal(salt: str, token: str | None, max_age: int) -> dict[str, Any] | None:
    if not token:
        return None
    try:
        value = _serializer(salt).loads(token, max_age=max_age)
    except BadSignature:
        return None
    return value if isinstance(value, dict) else None
