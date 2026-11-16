"""Smoke tests for the application entry point."""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_root_describes_the_api() -> None:
    res = client.get("/")
    assert res.status_code == 200
    body = res.json()
    assert body["name"] == "Chamath Dilshan API"
    assert body["description"]
    assert body["health"] == "/api/health"
    assert res.headers["cache-control"] == "private, no-store, max-age=0"


def test_health_returns_ok() -> None:
    res = client.get("/api/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}


def test_health_is_never_cached() -> None:
    """The health endpoint must not be stored by any cache. (CACHING.md §15)"""
    res = client.get("/api/health")
    assert res.headers["cache-control"] == "private, no-store, max-age=0"


def test_favicon_uses_the_brand_logo() -> None:
    res = client.get("/favicon.ico")
    assert res.status_code == 200
    assert res.headers["content-type"] == "image/png"
    assert res.content.startswith(b"\x89PNG\r\n\x1a\n")


def test_swagger_docs_reference_the_brand_favicon() -> None:
    res = client.get("/docs")
    assert res.status_code == 200
    assert 'rel="shortcut icon" href="/favicon.ico"' in res.text
