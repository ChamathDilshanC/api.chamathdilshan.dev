"""Owner sign-in: Google identity check, emailed code, session lifecycle."""

import base64
import json
import time
from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.integrations.google import GoogleAuthError, validate_id_token
from tests.conftest import OWNER, google_round_trip


def test_login_redirects_to_google_with_pkce_and_hint(client: TestClient) -> None:
    res = client.get("/api/auth/google/login", follow_redirects=False)
    assert res.status_code == 302
    location = res.headers["location"]
    assert location.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    assert "code_challenge_method=S256" in location
    assert "login_hint=chamathdilshan.dev%40gmail.com" in location
    assert "pf_oauth" in res.headers["set-cookie"]
    assert "httponly" in res.headers["set-cookie"].lower()


def test_login_without_google_config_explains(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", "")
    res = client.get("/api/auth/google/login", follow_redirects=False)
    assert res.headers["location"].endswith("/ChamathDilshanC/login?error=not_configured")


def test_callback_rejects_wrong_state(
    client: TestClient, google_identity: Callable[..., None]
) -> None:
    google_identity()
    client.get("/api/auth/google/login", follow_redirects=False)
    res = client.get("/api/auth/google/callback?code=abc&state=forged", follow_redirects=False)
    assert res.headers["location"].endswith("login?error=expired")


def test_other_google_accounts_are_refused(
    client: TestClient, sent_codes: list[str], google_identity: Callable[..., None]
) -> None:
    google_identity(email="someone.else@gmail.com")
    res = google_round_trip(client)
    assert res.headers["location"].endswith("login?error=forbidden")
    assert sent_codes == []


def test_unverified_owner_email_is_refused(
    client: TestClient, sent_codes: list[str], google_identity: Callable[..., None]
) -> None:
    google_identity(verified=False)
    res = google_round_trip(client)
    assert res.headers["location"].endswith("login?error=forbidden")
    assert sent_codes == []


def test_pinned_google_sub_must_match(
    client: TestClient,
    sent_codes: list[str],
    google_identity: Callable[..., None],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "ADMIN_GOOGLE_SUB", "999")
    google_identity(sub="1001")
    assert google_round_trip(client).headers["location"].endswith("login?error=forbidden")


def test_google_alone_is_not_a_session(
    client: TestClient, sent_codes: list[str], google_identity: Callable[..., None]
) -> None:
    google_identity()
    google_round_trip(client)
    assert len(sent_codes) == 1
    assert client.get("/api/auth/me").status_code == 401
    assert client.get("/api/admin/sections").status_code == 401


def test_code_completes_sign_in(signed_in: TestClient) -> None:
    me = signed_in.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["email"] == OWNER
    assert signed_in.get("/api/admin/sections").status_code == 200


def test_wrong_codes_are_capped(
    client: TestClient, sent_codes: list[str], google_identity: Callable[..., None]
) -> None:
    google_identity()
    google_round_trip(client)
    wrong = "000000" if sent_codes[-1] != "000000" else "111111"
    for _ in range(settings.OTP_MAX_ATTEMPTS):
        assert client.post("/api/auth/verify", json={"code": wrong}).status_code == 400
    # Even the right code is refused once the attempts are used up.
    res = client.post("/api/auth/verify", json={"code": sent_codes[-1]})
    assert res.status_code == 429


def test_code_works_once(
    client: TestClient, sent_codes: list[str], google_identity: Callable[..., None]
) -> None:
    google_identity()
    google_round_trip(client)
    challenge_cookie = client.cookies.get("pf_challenge")
    assert client.post("/api/auth/verify", json={"code": sent_codes[-1]}).status_code == 200
    client.cookies.set("pf_challenge", challenge_cookie or "", path="/api/auth")
    assert client.post("/api/auth/verify", json={"code": sent_codes[-1]}).status_code == 401


def test_verify_requires_trusted_origin(
    client: TestClient, sent_codes: list[str], google_identity: Callable[..., None]
) -> None:
    google_identity()
    google_round_trip(client)
    res = client.post(
        "/api/auth/verify", json={"code": sent_codes[-1]}, headers={"Origin": "https://evil.test"}
    )
    assert res.status_code == 403


def test_resend_has_a_cooldown(
    client: TestClient, sent_codes: list[str], google_identity: Callable[..., None]
) -> None:
    google_identity()
    google_round_trip(client)
    assert client.post("/api/auth/resend").status_code == 429
    assert len(sent_codes) == 1


def test_logout_revokes_the_session(signed_in: TestClient) -> None:
    token = signed_in.cookies.get(settings.SESSION_COOKIE_NAME)
    assert signed_in.post("/api/auth/logout").status_code == 200
    signed_in.cookies.set(settings.SESSION_COOKIE_NAME, token or "")
    assert signed_in.get("/api/auth/me").status_code == 401


def test_changing_admin_email_ends_existing_sessions(
    signed_in: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "ADMIN_EMAIL", "new.owner@gmail.com")
    assert signed_in.get("/api/admin/sections").status_code == 401


# --- ID token claims ----------------------------------------------------------


def _token(**claims: object) -> str:
    base = {
        "iss": "https://accounts.google.com",
        "aud": settings.GOOGLE_CLIENT_ID,
        "exp": int(time.time()) + 300,
        "nonce": "n-1",
        "sub": "1001",
        "email": "Chamathdilshan.dev@gmail.com",
        "email_verified": True,
    }
    base.update(claims)
    body = base64.urlsafe_b64encode(json.dumps(base).encode()).rstrip(b"=").decode()
    return f"header.{body}.signature"


def test_id_token_claims_are_checked() -> None:
    identity = validate_id_token(_token(), "n-1")
    assert identity.email == OWNER  # normalised to lower case
    for bad in (
        {"iss": "https://evil.test"},
        {"aud": "another-client"},
        {"exp": int(time.time()) - 3600},
        {"nonce": "other"},
    ):
        with pytest.raises(GoogleAuthError):
            validate_id_token(_token(**bad), "n-1")
