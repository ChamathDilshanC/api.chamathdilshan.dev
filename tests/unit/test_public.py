"""Public read API: defaults, caching headers and conditional requests."""

from fastapi.testclient import TestClient

from app.schemas.sections import SECTIONS


def test_content_serves_every_section_with_defaults(client: TestClient) -> None:
    res = client.get("/api/content")
    assert res.status_code == 200
    sections = res.json()["sections"]
    assert set(sections) == set(SECTIONS)
    assert sections["site"]["wordmark"] == "CHAMATH"


def test_seed_defaults_are_valid_for_every_section() -> None:
    from app.services.sections import default_section

    for key, spec in SECTIONS.items():
        spec.model.model_validate(default_section(key))


def test_public_reads_are_shared_cacheable_with_etag(client: TestClient) -> None:
    res = client.get("/api/content")
    assert res.headers["cache-control"].startswith("public, s-maxage=300")
    etag = res.headers["etag"]
    again = client.get("/api/content", headers={"If-None-Match": etag})
    assert again.status_code == 304


def test_public_reads_are_cached_by_vercels_cdn(client: TestClient) -> None:
    # Keep public reads at the edge so a cold Vercel function does not delay
    # every visitor. Admin edits become visible after the short edge TTL.
    for path in ("/api/content", "/api/projects", "/api/posts", "/api/skills",
                 "/api/experience"):
        res = client.get(path)
        assert res.headers["vercel-cdn-cache-control"].startswith("public, s-maxage=300"), path
        assert res.headers["cache-control"].startswith("public, s-maxage=300"), path
        again = client.get(path, headers={"If-None-Match": res.headers["etag"]})
        assert again.status_code == 304
        assert again.headers["vercel-cdn-cache-control"].startswith("public, s-maxage=300"), path


def test_private_and_immutable_policies_leave_vercels_cdn_alone() -> None:
    from fastapi import Response

    from app.core.http_cache import IMMUTABLE, PRIVATE, apply_cache

    for policy in (PRIVATE, IMMUTABLE):
        response = Response()
        apply_cache(response, policy)
        assert "vercel-cdn-cache-control" not in response.headers


def test_unknown_project_is_404(client: TestClient) -> None:
    assert client.get("/api/projects/does-not-exist").status_code == 404
    assert client.get("/api/projects/Bad Slug!").status_code in (404, 422)


def test_empty_collections(client: TestClient) -> None:
    assert client.get("/api/projects").json() == []
    assert client.get("/api/posts").json() == []
    assert client.get("/api/skills").json() == []
    assert client.get("/api/experience").json() == []
