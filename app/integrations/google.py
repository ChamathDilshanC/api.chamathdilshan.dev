"""Google OpenID Connect: authorization URL, code exchange and ID-token checks."""

import base64
import hashlib
import json
import secrets
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import httpx

from app.core.config import settings

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"  # noqa: S105 — an endpoint, not a secret
ISSUERS = {"accounts.google.com", "https://accounts.google.com"}


class GoogleAuthError(Exception):
    """The Google response could not be trusted. The message is safe to log, not to show."""


@dataclass(frozen=True)
class GoogleIdentity:
    sub: str
    email: str
    email_verified: bool
    name: str
    picture: str


@dataclass(frozen=True)
class AuthRequest:
    url: str
    state: str
    nonce: str
    code_verifier: str


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def build_auth_request() -> AuthRequest:
    """A fresh state, nonce and PKCE pair, and the URL that starts the Google sign-in."""
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    code_verifier = secrets.token_urlsafe(64)
    challenge = _b64url(hashlib.sha256(code_verifier.encode()).digest())

    params = {
        "client_id": settings.GOOGLE_CLIENT_ID,
        "redirect_uri": settings.GOOGLE_OAUTH_REDIRECT_URI,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "nonce": nonce,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "prompt": "select_account",
        "access_type": "online",
    }
    if settings.admin_email:
        params["login_hint"] = settings.admin_email
    return AuthRequest(f"{AUTH_URL}?{urlencode(params)}", state, nonce, code_verifier)


def _decode_jwt_payload(token: str) -> dict[str, Any]:
    try:
        _, payload, _ = token.split(".")
        padded = payload + "=" * (-len(payload) % 4)
        data = json.loads(base64.urlsafe_b64decode(padded))
    except (ValueError, json.JSONDecodeError) as exc:
        raise GoogleAuthError("malformed id_token") from exc
    if not isinstance(data, dict):
        raise GoogleAuthError("malformed id_token payload")
    return data


def validate_id_token(id_token: str, nonce: str) -> GoogleIdentity:
    """Check the claims of an ID token received straight from Google's token endpoint.

    The token comes back over a TLS connection this server opened to Google, so
    per OpenID Connect Core §3.1.3.7 TLS server validation stands in for the
    signature check. Every claim that binds it to this sign-in is still checked.
    """
    claims = _decode_jwt_payload(id_token)
    if claims.get("iss") not in ISSUERS:
        raise GoogleAuthError("unexpected issuer")
    aud = claims.get("aud")
    if aud != settings.GOOGLE_CLIENT_ID and not (
        isinstance(aud, list) and settings.GOOGLE_CLIENT_ID in aud
    ):
        raise GoogleAuthError("token issued for another client")
    if not isinstance(claims.get("exp"), int | float) or claims["exp"] < time.time() - 60:
        raise GoogleAuthError("token expired")
    if not secrets.compare_digest(str(claims.get("nonce", "")), nonce):
        raise GoogleAuthError("nonce mismatch")

    email = str(claims.get("email", "")).strip().lower()
    sub = str(claims.get("sub", ""))
    if not email or not sub:
        raise GoogleAuthError("token has no email or subject")
    return GoogleIdentity(
        sub=sub,
        email=email,
        email_verified=claims.get("email_verified") is True,
        name=str(claims.get("name", ""))[:200],
        picture=str(claims.get("picture", ""))[:1000],
    )


async def exchange_code(code: str, code_verifier: str, nonce: str) -> GoogleIdentity:
    async with httpx.AsyncClient(timeout=10.0) as client:
        res = await client.post(
            TOKEN_URL,
            data={
                "code": code,
                "client_id": settings.GOOGLE_CLIENT_ID,
                "client_secret": settings.GOOGLE_CLIENT_SECRET,
                "redirect_uri": settings.GOOGLE_OAUTH_REDIRECT_URI,
                "grant_type": "authorization_code",
                "code_verifier": code_verifier,
            },
            headers={"Accept": "application/json"},
        )
    if res.status_code != 200:
        raise GoogleAuthError(f"token exchange failed with {res.status_code}")
    id_token = res.json().get("id_token")
    if not isinstance(id_token, str):
        raise GoogleAuthError("no id_token in token response")
    return validate_id_token(id_token, nonce)
