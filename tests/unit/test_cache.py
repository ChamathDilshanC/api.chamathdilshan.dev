import httpx
import pytest

from app.core import cache
from app.core.config import settings


class _Response:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code

    @property
    def is_error(self) -> bool:
        return self.status_code >= 400

    def raise_for_status(self) -> None:
        if self.is_error:
            request = httpx.Request("POST", "https://www.chamathdilshan.com/api/revalidate")
            response = httpx.Response(self.status_code, request=request)
            raise httpx.HTTPStatusError("revalidation rejected", request=request, response=response)


class _Client:
    def __init__(self, response: _Response) -> None:
        self.response = response
        self.request: tuple[str, dict[str, str], dict[str, list[str]]] | None = None

    async def __aenter__(self) -> "_Client":
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def post(
        self,
        url: str,
        *,
        headers: dict[str, str],
        json: dict[str, list[str]],
    ) -> _Response:
        self.request = (url, headers, json)
        return self.response


@pytest.mark.asyncio
async def test_frontend_revalidation_posts_project_tags_and_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _Client(_Response(200))
    monkeypatch.setattr(settings, "CACHE_REVALIDATE_SECRET", "test-secret")
    monkeypatch.setattr(settings, "NEXT_APP_URL", "https://www.chamathdilshan.com")
    monkeypatch.setattr(cache.httpx, "AsyncClient", lambda timeout, follow_redirects: client)

    await cache.revalidate_frontend(
        ["projects", "project:cap-it-screen-recorder"], ["/", "/projects"]
    )

    assert client.request == (
        "https://www.chamathdilshan.com/api/revalidate",
        {"x-revalidate-secret": "test-secret"},
        {"tags": ["projects", "project:cap-it-screen-recorder"], "paths": ["/", "/projects"]},
    )


@pytest.mark.asyncio
async def test_frontend_revalidation_rejection_does_not_fail_admin_mutation(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    client = _Client(_Response(403))
    monkeypatch.setattr(settings, "CACHE_REVALIDATE_SECRET", "test-secret")
    monkeypatch.setattr(cache.httpx, "AsyncClient", lambda timeout, follow_redirects: client)

    with caplog.at_level("ERROR", logger="app.core.cache"):
        await cache.revalidate_frontend(["projects"], ["/", "/projects"])

    assert "HTTP 403" in caplog.text
