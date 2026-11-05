"""Owner sign-in: Google OpenID Connect, then a one-time code emailed through Resend.

    /ChamathDilshanC/login ──► GET /api/auth/google/login ──► Google
    Google ──► GET /api/auth/google/callback ── identity is the owner? ── email code
           ──► /ChamathDilshanC/verify ──► POST /api/auth/verify ──► session cookie

Both factors are required: a stolen Google session alone cannot reach the
dashboard without the inbox, and the code alone is useless without Google.
"""

import logging
import secrets
import uuid
from datetime import timedelta
from typing import Annotated, Any
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import RedirectResponse
from pydantic import Field

from app.core.config import settings
from app.core.db import utcnow
from app.core.http_cache import no_store
from app.integrations.google import GoogleAuthError, build_auth_request, exchange_code
from app.integrations.resend import EmailError, send_login_code
from app.models import LoginChallenge
from app.schemas.common import CamelModel
from app.security.deps import DB, require_trusted_origin
from app.security.rate_limit import auth_limit
from app.security.sessions import (
    clear_session_cookie,
    client_ip,
    create_session,
    load_session,
    revoke_session,
    set_session_cookie,
)
from app.security.tokens import code_hash, new_code, seal, unseal
from app.services import audit

log = logging.getLogger(__name__)
router = APIRouter()

OAUTH_COOKIE = "pf_oauth"
CHALLENGE_COOKIE = "pf_challenge"
COOKIE_PATH = "/api/auth"
OAUTH_TTL = 600


def _set_cookie(response: Response, name: str, value: str, max_age: int) -> None:
    response.set_cookie(
        name, value, max_age=max_age, httponly=True, secure=settings.cookie_secure,
        samesite="lax", path=COOKIE_PATH,
    )


def _drop_cookie(response: Response, name: str) -> None:
    response.delete_cookie(
        name, httponly=True, secure=settings.cookie_secure, samesite="lax", path=COOKIE_PATH
    )


def _to_admin(path: str, **params: str) -> RedirectResponse:
    query = f"?{urlencode(params)}" if params else ""
    response = RedirectResponse(f"{settings.admin_url}/{path}{query}", status.HTTP_302_FOUND)
    no_store(response)
    return response


def _mask(email: str) -> str:
    name, _, domain = email.partition("@")
    return f"{name[:2]}{'•' * max(1, len(name) - 2)}@{domain}"


# --- Google -------------------------------------------------------------------


@router.get("/google/login", dependencies=[Depends(auth_limit)])
async def google_login() -> RedirectResponse:
    if not settings.google_configured:
        return _to_admin("login", error="not_configured")
    auth = build_auth_request()
    response = RedirectResponse(auth.url, status.HTTP_302_FOUND)
    no_store(response)
    _set_cookie(
        response,
        OAUTH_COOKIE,
        seal("oauth", {"state": auth.state, "nonce": auth.nonce, "verifier": auth.code_verifier}),
        OAUTH_TTL,
    )
    return response


@router.get("/google/callback", dependencies=[Depends(auth_limit)])
async def google_callback(
    request: Request,
    db: DB,
    code: Annotated[str | None, Query(max_length=2000)] = None,
    state: Annotated[str | None, Query(max_length=200)] = None,
    error: Annotated[str | None, Query(max_length=200)] = None,
) -> RedirectResponse:
    ip = client_ip(request)

    def fail(reason: str) -> RedirectResponse:
        response = _to_admin("login", error=reason)
        _drop_cookie(response, OAUTH_COOKIE)
        return response

    stored = unseal("oauth", request.cookies.get(OAUTH_COOKIE), OAUTH_TTL)
    if error:
        return fail("cancelled")
    if not stored or not state or not code or not secrets.compare_digest(state, stored["state"]):
        return fail("expired")

    try:
        identity = await exchange_code(code, stored["verifier"], stored["nonce"])
    except (GoogleAuthError, ValueError, OSError) as exc:  # any failure is a denial
        log.warning("google sign-in failed: %s", exc)
        return fail("google")

    owner = (
        identity.email_verified
        and bool(settings.admin_email)
        and secrets.compare_digest(identity.email, settings.admin_email)
        and (not settings.ADMIN_GOOGLE_SUB or identity.sub == settings.ADMIN_GOOGLE_SUB)
    )
    if not owner:
        await audit.record(db, "auth.denied", actor=identity.email, ip=ip,
                           detail={"sub": identity.sub})
        return fail("forbidden")

    challenge_id = uuid.uuid4().hex
    one_time = new_code()
    now = utcnow()
    db.add(
        LoginChallenge(
            id=challenge_id,
            email=identity.email,
            google_sub=identity.sub,
            code_hash=code_hash(challenge_id, one_time),
            expires_at=now + timedelta(seconds=settings.OTP_TTL_SECONDS),
            last_sent_at=now,
            ip=ip,
        )
    )
    await db.commit()

    try:
        await send_login_code(identity.email, one_time)
    except EmailError as exc:
        log.error("could not send sign-in code: %s", exc)
        return fail("email")

    await audit.record(db, "auth.code_sent", actor=identity.email, ip=ip)
    response = _to_admin("verify")
    _drop_cookie(response, OAUTH_COOKIE)
    _set_cookie(
        response,
        CHALLENGE_COOKIE,
        seal("challenge", {"id": challenge_id, "name": identity.name, "picture": identity.picture}),
        settings.OTP_TTL_SECONDS,
    )
    return response


# --- one-time code ------------------------------------------------------------


class VerifyIn(CamelModel):
    code: Annotated[str, Field(pattern=r"^\d{6}$")]


async def _challenge(request: Request, db: DB) -> tuple[LoginChallenge, dict[str, Any]]:
    sealed = unseal("challenge", request.cookies.get(CHALLENGE_COOKIE), settings.OTP_TTL_SECONDS)
    row = await db.get(LoginChallenge, sealed["id"]) if sealed else None
    if sealed is None or row is None or row.consumed_at is not None or row.expires_at <= utcnow():
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            detail="This sign-in has expired. Continue with Google again.",
        )
    return row, sealed


@router.get("/challenge")
async def challenge_status(request: Request, response: Response, db: DB) -> dict[str, Any]:
    """What the verify page shows: where the code went and when it can be resent."""
    no_store(response)
    row, _ = await _challenge(request, db)
    cooldown = row.last_sent_at + timedelta(seconds=settings.OTP_RESEND_COOLDOWN_SECONDS)
    return {
        "email": _mask(row.email),
        "expiresAt": row.expires_at.isoformat(),
        "resendAt": cooldown.isoformat(),
        "resendsLeft": max(0, settings.OTP_MAX_SENDS - row.sends),
        "attemptsLeft": max(0, settings.OTP_MAX_ATTEMPTS - row.attempts),
    }


@router.post(
    "/verify", dependencies=[Depends(require_trusted_origin), Depends(auth_limit)]
)
async def verify(body: VerifyIn, request: Request, response: Response, db: DB) -> dict[str, str]:
    no_store(response)
    row, sealed = await _challenge(request, db)
    ip = client_ip(request)

    if row.attempts >= settings.OTP_MAX_ATTEMPTS:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many wrong codes. Continue with Google again.",
        )
    row.attempts += 1
    await db.commit()

    if not secrets.compare_digest(code_hash(row.id, body.code), row.code_hash):
        await audit.record(db, "auth.code_failed", actor=row.email, ip=ip)
        left = settings.OTP_MAX_ATTEMPTS - row.attempts
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail=f"That code is not right. {left} attempt{'s' if left != 1 else ''} left."
            if left > 0
            else "That code is not right. Continue with Google again.",
        )

    row.consumed_at = utcnow()
    await db.commit()
    token = await create_session(
        db, request, email=row.email, name=str(sealed.get("name", "")),
        picture=str(sealed.get("picture", "")),
    )
    set_session_cookie(response, token)
    _drop_cookie(response, CHALLENGE_COOKIE)
    await audit.record(db, "auth.login", actor=row.email, ip=ip)
    return {"email": row.email, "name": str(sealed.get("name", ""))}


@router.post(
    "/resend", dependencies=[Depends(require_trusted_origin), Depends(auth_limit)]
)
async def resend(request: Request, response: Response, db: DB) -> dict[str, Any]:
    no_store(response)
    row, _ = await _challenge(request, db)
    now = utcnow()
    if row.sends >= settings.OTP_MAX_SENDS:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            detail="No more codes for this sign-in. Continue with Google again.",
        )
    wait = row.last_sent_at + timedelta(seconds=settings.OTP_RESEND_COOLDOWN_SECONDS) - now
    if wait.total_seconds() > 0:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Wait {int(wait.total_seconds()) + 1} seconds before asking for a new code.",
        )

    one_time = new_code()
    row.code_hash = code_hash(row.id, one_time)
    row.sends += 1
    row.attempts = 0
    row.last_sent_at = now
    row.expires_at = now + timedelta(seconds=settings.OTP_TTL_SECONDS)
    await db.commit()
    try:
        await send_login_code(row.email, one_time)
    except EmailError as exc:
        log.error("could not resend sign-in code: %s", exc)
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, detail="The email could not be sent. Try again shortly."
        ) from exc
    await audit.record(db, "auth.code_resent", actor=row.email, ip=client_ip(request))
    return await challenge_status(request, response, db)


# --- session ------------------------------------------------------------------


@router.get("/me")
async def me(request: Request, response: Response, db: DB) -> dict[str, str]:
    no_store(response)
    session = await load_session(db, request.cookies.get(settings.SESSION_COOKIE_NAME))
    if session is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Not signed in.")
    return {
        "email": session.email,
        "name": session.name,
        "picture": session.picture,
        "expiresAt": session.expires_at.isoformat(),
    }


@router.post("/logout", dependencies=[Depends(require_trusted_origin)])
async def logout(request: Request, response: Response, db: DB) -> dict[str, bool]:
    no_store(response)
    token = request.cookies.get(settings.SESSION_COOKIE_NAME)
    session = await load_session(db, token)
    await revoke_session(db, token)
    clear_session_cookie(response)
    if session is not None:
        await audit.record(db, "auth.logout", actor=session.email, ip=client_ip(request))
    return {"ok": True}


@router.get("/status")
async def auth_status(response: Response) -> dict[str, bool]:
    """Lets the login page explain a missing configuration instead of failing silently."""
    no_store(response)
    return {"google": settings.google_configured}
