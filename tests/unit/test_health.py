"""Smoke tests for the application entry point."""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_returns_ok() -> None:
    res = client.get("/api/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}


def test_health_is_never_cached() -> None:
    """The health endpoint must not be stored by any cache. (CACHING.md §15)"""
    res = client.get("/api/health")
    assert res.headers["cache-control"] == "private, no-store, max-age=0"
