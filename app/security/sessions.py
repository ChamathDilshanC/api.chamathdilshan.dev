"""Server-side admin sessions."""

from datetime import timedelta

from fastapi import Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import utcnow
from app.models import AdminSession
from app.security.tokens import hash_token, new_token

_TOUCH_EVERY = timedelta(minutes=5)


def client_ip(request: Request) -> str:
    return (request.client.host if request.client else "")[:64]


async def create_session(
    db: AsyncSession, request: Request, *, email: str, name: str = "", picture: str = ""
) -> str:
    """Store a new session and return the raw token for the cookie."""
    token = new_token()
    now = utcnow()
    db.add(
        AdminSession(
            token_hash=hash_token(token),
            email=email,
            name=name,
            picture=picture,
            ip=client_ip(request),
            user_agent=request.headers.get("user-agent", "")[:500],
            created_at=now,
            last_seen_at=now,
            expires_at=now + timedelta(seconds=settings.SESSION_MAX_AGE),
        )
    )
    await db.commit()
    return token


async def load_session(db: AsyncSession, token: str | None) -> AdminSession | None:
    """The live session for a cookie token, or None. Re-checks the owner email every time."""
    if not token or len(token) > 200:
        return None
    session = await db.scalar(
        select(AdminSession).where(AdminSession.token_hash == hash_token(token))
    )
    now = utcnow()
    if (
        session is None
        or session.revoked_at is not None
        or session.expires_at <= now
        or not settings.admin_email
        or session.email != settings.admin_email
    ):
        return None
    if now - session.last_seen_at > _TOUCH_EVERY:
        session.last_seen_at = now
        await db.commit()
    return session


async def revoke_session(db: AsyncSession, token: str | None) -> None:
    if not token:
        return
    session = await db.scalar(
        select(AdminSession).where(AdminSession.token_hash == hash_token(token))
    )
    if session is not None and session.revoked_at is None:
        session.revoked_at = utcnow()
        await db.commit()


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        settings.SESSION_COOKIE_NAME,
        token,
        max_age=settings.SESSION_MAX_AGE,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(
        settings.SESSION_COOKIE_NAME,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )
