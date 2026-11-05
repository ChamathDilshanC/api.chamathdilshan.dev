"""Request guards shared by the auth and admin routers."""

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import get_db
from app.models import AdminSession
from app.security.sessions import client_ip, load_session

_UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}

DB = Annotated[AsyncSession, Depends(get_db)]


def require_trusted_origin(request: Request) -> None:
    """CSRF defence for state-changing requests (SECURITY.md §18).

    SameSite=Lax already keeps the session cookie off cross-site POSTs; this
    also rejects any request whose Origin is not the site itself.
    """
    if request.method not in _UNSAFE:
        return
    origin = request.headers.get("origin")
    if origin is None:
        referer = request.headers.get("referer", "")
        origin = "/".join(referer.split("/", 3)[:3]) if referer else None
    if origin is None or origin.rstrip("/") not in settings.cors_origins:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Request origin is not allowed.")


@dataclass(frozen=True)
class Admin:
    session: AdminSession
    ip: str

    @property
    def email(self) -> str:
        return self.session.email


async def require_admin(request: Request, db: DB) -> Admin:
    """Every /api/admin/* request: valid session cookie for the configured owner."""
    session = await load_session(db, request.cookies.get(settings.SESSION_COOKIE_NAME))
    if session is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Sign in to continue.")
    return Admin(session=session, ip=client_ip(request))


CurrentAdmin = Annotated[Admin, Depends(require_admin)]
