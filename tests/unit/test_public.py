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


def test_unknown_project_is_404(client: TestClient) -> None:
    assert client.get("/api/projects/does-not-exist").status_code == 404
    assert client.get("/api/projects/Bad Slug!").status_code in (404, 422)


def test_empty_collections(client: TestClient) -> None:
    assert client.get("/api/projects").json() == []
    assert client.get("/api/posts").json() == []
    assert client.get("/api/skills").json() == []
