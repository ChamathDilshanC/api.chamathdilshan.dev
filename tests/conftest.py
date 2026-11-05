"""Shared fixtures: a fresh SQLite database per test and helpers to sign in."""

import asyncio
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

import app.models  # noqa: F401 — registers tables
from app.api.auth import routes as auth_routes
from app.core import db as db_module
from app.core.config import settings
from app.integrations.google import GoogleIdentity
from app.main import app
from app.security import rate_limit

ORIGIN = "http://localhost:3000"
OWNER = "chamathdilshan.dev@gmail.com"


@pytest.fixture(autouse=True)
def _settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "APP_ENV", "test")
    monkeypatch.setattr(settings, "CACHE_ENABLED", False)
    monkeypatch.setattr(settings, "CACHE_REVALIDATE_SECRET", "")
    monkeypatch.setattr(settings, "ALLOWED_ORIGINS", ORIGIN)
    monkeypatch.setattr(settings, "NEXT_APP_URL", ORIGIN)
    monkeypatch.setattr(settings, "ADMIN_EMAIL", OWNER)
    monkeypatch.setattr(settings, "ADMIN_GOOGLE_SUB", "")
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", "client-id.apps.googleusercontent.com")
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_SECRET", "test-client-secret")
    monkeypatch.setattr(settings, "SESSION_SECRET", "test-session-secret-value")
    monkeypatch.setattr(settings, "CLOUDINARY_CLOUD_NAME", "demo")
    monkeypatch.setattr(settings, "CLOUDINARY_API_KEY", "1234")
    monkeypatch.setattr(settings, "CLOUDINARY_API_SECRET", "test-cloudinary-secret")
    monkeypatch.setattr(settings, "CLOUDINARY_SIGNATURE_ALGORITHM", "sha1")
    rate_limit.reset()


@pytest.fixture(autouse=True)
def database(tmp_path: Path) -> Iterator[None]:
    url = f"sqlite+aiosqlite:///{(tmp_path / 'test.db').as_posix()}"
    engine = create_async_engine(url, poolclass=NullPool)

    async def create() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(db_module.Base.metadata.create_all)

    asyncio.run(create())
    db_module.use_engine(engine)
    yield
    asyncio.run(engine.dispose())


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app, headers={"Origin": ORIGIN}) as c:
        yield c


@pytest.fixture
def sent_codes(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Captures the one-time codes instead of emailing them."""
    codes: list[str] = []

    async def fake_send(to: str, code: str) -> None:
        codes.append(code)

    monkeypatch.setattr(auth_routes, "send_login_code", fake_send)
    return codes


@pytest.fixture
def google_identity(monkeypatch: pytest.MonkeyPatch) -> Callable[..., None]:
    """Make the Google code exchange return the given identity."""

    def use(email: str = OWNER, verified: bool = True, sub: str = "1001") -> None:
        async def fake_exchange(code: str, verifier: str, nonce: str) -> GoogleIdentity:
            return GoogleIdentity(sub=sub, email=email, email_verified=verified,
                                  name="Chamath", picture="")

        monkeypatch.setattr(auth_routes, "exchange_code", fake_exchange)

    return use


def google_round_trip(client: TestClient) -> Any:
    """Start the Google flow and come back through the callback with the right state."""
    start = client.get("/api/auth/google/login", follow_redirects=False)
    assert start.status_code == 302
    state = start.headers["location"].split("state=", 1)[1].split("&", 1)[0]
    return client.get(
        f"/api/auth/google/callback?code=abc&state={state}", follow_redirects=False
    )


@pytest.fixture
def signed_in(
    client: TestClient, sent_codes: list[str], google_identity: Callable[..., None]
) -> TestClient:
    google_identity()
    res = google_round_trip(client)
    assert res.headers["location"].endswith("/ChamathDilshanC/verify")
    ok = client.post("/api/auth/verify", json={"code": sent_codes[-1]})
    assert ok.status_code == 200, ok.text
    return client
