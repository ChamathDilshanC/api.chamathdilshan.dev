"""A small sliding-window rate limiter for the auth endpoints.

Per process and in memory: enough to blunt scripted guessing on a single-owner
site. The one-time-code attempt cap is enforced in the database regardless.
"""

import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request, status

from app.core.config import settings

_hits: dict[str, deque[float]] = defaultdict(deque)
enabled = True


def check(bucket: str, key: str, limit: int, window: float = 60.0) -> None:
    if not enabled:
        return
    now = time.monotonic()
    hits = _hits[f"{bucket}:{key}"]
    while hits and hits[0] <= now - window:
        hits.popleft()
    if len(hits) >= limit:
        retry = int(window - (now - hits[0])) + 1
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many attempts. Wait a minute and try again.",
            headers={"Retry-After": str(retry)},
        )
    hits.append(now)


def auth_limit(request: Request) -> None:
    """FastAPI dependency for the sign-in endpoints."""
    ip = request.client.host if request.client else "unknown"
    check("auth", ip, settings.RATE_LIMIT_AUTH_PER_MINUTE)


def reset() -> None:
    _hits.clear()
