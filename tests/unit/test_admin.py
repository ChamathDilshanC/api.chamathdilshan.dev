"""Admin content management: authorization, validation and CRUD."""

from typing import Any

from fastapi.testclient import TestClient

from app.integrations import cloudinary

THUMB = {"url": "https://res.cloudinary.com/demo/image/upload/v1/site/a.jpg", "alt": "A"}


def project(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "title": "Aegis Zero",
        "category": "Security",
        "year": "2026",
        "summary": "Zero-trust identity.",
        "thumbnail": THUMB,
        "hero": {"kind": "video", "url": "https://res.cloudinary.com/demo/video/upload/v1/h.mp4",
                 "alt": "Demo", "poster": None},
        "gallery": [
            {"kind": "image", "url": THUMB["url"], "alt": "One"},
            {"kind": "video", "url": "https://res.cloudinary.com/demo/video/upload/v1/b.mp4",
             "alt": "Two"},
        ],
        "results": [{"label": "Latency", "value": "-40%"}],
        "tech": ["Next.js", "FastAPI", "Next.js"],
        "published": True,
    }
    body.update(overrides)
    return body


def test_admin_requires_a_session(client: TestClient) -> None:
    for path in ("/api/admin/sections", "/api/admin/projects", "/api/admin/media",
                 "/api/admin/overview"):
        assert client.get(path).status_code == 401


def test_admin_writes_require_trusted_origin(signed_in: TestClient) -> None:
    res = signed_in.post("/api/admin/skills", json={"name": "Go"},
                         headers={"Origin": "https://evil.test"})
    assert res.status_code == 403


def test_admin_responses_are_never_cached(signed_in: TestClient) -> None:
    res = signed_in.get("/api/admin/sections")
    assert res.headers["cache-control"] == "private, no-store, max-age=0"


# --- sections -----------------------------------------------------------------


def test_sections_list_every_editable_block(signed_in: TestClient) -> None:
    keys = {s["key"] for s in signed_in.get("/api/admin/sections").json()}
    assert {"site", "home.hero", "home.pricing", "page.contact", "about.stack"} <= keys


def test_section_detail_has_defaults_and_schema(signed_in: TestClient) -> None:
    detail = signed_in.get("/api/admin/sections/home.pricing").json()
    assert detail["data"]["plans"][0]["name"] == "Starter"
    assert detail["schema"]["properties"]["includedHeading"]["type"] == "string"


def test_section_save_validates_and_publishes(signed_in: TestClient) -> None:
    data = signed_in.get("/api/admin/sections/home.pricing").json()["data"]
    data["plans"][0]["price"] = "2499"
    saved = signed_in.put("/api/admin/sections/home.pricing", json=data)
    assert saved.status_code == 200, saved.text
    public = signed_in.get("/api/content").json()["sections"]["home.pricing"]
    assert public["plans"][0]["price"] == "2499"


def test_section_save_rejects_bad_input(signed_in: TestClient) -> None:
    data = signed_in.get("/api/admin/sections/home.hero").json()["data"]
    assert signed_in.put("/api/admin/sections/home.hero",
                         json={**data, "image": "javascript:alert(1)"}).status_code == 422
    assert signed_in.put("/api/admin/sections/home.hero",
                         json={**data, "unknown": 1}).status_code == 422
    assert signed_in.put("/api/admin/sections/nope", json={}).status_code == 404


# --- projects -----------------------------------------------------------------


def test_project_crud_and_public_visibility(signed_in: TestClient) -> None:
    created = signed_in.post("/api/admin/projects", json=project())
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["slug"] == "aegis-zero"
    assert body["tech"] == ["Next.js", "FastAPI"]  # duplicates dropped

    public = signed_in.get("/api/projects/aegis-zero").json()
    assert public["hero"]["kind"] == "video"
    assert len(public["gallery"]) == 2
    assert public["tech"] == ["Next.js", "FastAPI"]

    draft = signed_in.put(f"/api/admin/projects/{body['id']}", json=project(published=False))
    assert draft.status_code == 200
    assert signed_in.get("/api/projects/aegis-zero").status_code == 404

    assert signed_in.delete(f"/api/admin/projects/{body['id']}").status_code == 204
    assert signed_in.get(f"/api/admin/projects/{body['id']}").status_code == 404


def test_project_slugs_stay_unique(signed_in: TestClient) -> None:
    first = signed_in.post("/api/admin/projects", json=project()).json()
    second = signed_in.post("/api/admin/projects", json=project()).json()
    assert (first["slug"], second["slug"]) == ("aegis-zero", "aegis-zero-2")


def test_project_needs_a_thumbnail_to_publish(signed_in: TestClient) -> None:
    res = signed_in.post("/api/admin/projects", json=project(thumbnail=None))
    assert res.status_code == 422
    draft = signed_in.post("/api/admin/projects", json=project(thumbnail=None, published=False))
    assert draft.status_code == 201


def test_project_hero_falls_back_to_thumbnail(signed_in: TestClient) -> None:
    signed_in.post("/api/admin/projects", json=project(hero=None))
    public = signed_in.get("/api/projects/aegis-zero").json()
    assert public["hero"] == {"kind": "image", "url": THUMB["url"], "alt": "A", "poster": None}


def test_project_reorder(signed_in: TestClient) -> None:
    a = signed_in.post("/api/admin/projects", json=project(title="A")).json()
    b = signed_in.post("/api/admin/projects", json=project(title="B")).json()
    signed_in.post("/api/admin/projects/reorder", json={"ids": [b["id"], a["id"]]})
    assert [p["slug"] for p in signed_in.get("/api/projects").json()] == ["b", "a"]


# --- skills -------------------------------------------------------------------


def test_skill_crud(signed_in: TestClient) -> None:
    made = signed_in.post("/api/admin/skills", json={"name": "Go", "category": "Backend"})
    assert made.status_code == 201
    skill_id = made.json()["id"]
    signed_in.put(f"/api/admin/skills/{skill_id}",
                  json={"name": "Go", "category": "Backend", "featured": False})
    public = signed_in.get("/api/skills").json()
    assert public == [{"name": "Go", "category": "Backend", "icon": None, "featured": False,
                       "visible": True}]
    assert signed_in.delete(f"/api/admin/skills/{skill_id}").status_code == 204
    assert signed_in.get("/api/skills").json() == []


# --- media --------------------------------------------------------------------


def _upload(public_id: str = "chamathdilshan.dev/shot") -> dict[str, Any]:
    version = 1730000000
    return {
        "publicId": public_id,
        "version": version,
        "signature": cloudinary.sign({"public_id": public_id, "version": version}),
        "resourceType": "image",
        "format": "jpg",
        "secureUrl": f"https://res.cloudinary.com/demo/image/upload/v{version}/{public_id}.jpg",
        "width": 1600,
        "height": 900,
        "bytes": 12345,
    }


def test_media_sign_returns_upload_params(signed_in: TestClient) -> None:
    sig = signed_in.post("/api/admin/media/sign").json()
    assert sig["uploadUrl"] == "https://api.cloudinary.com/v1_1/demo/auto/upload"
    assert sig["signature"] == cloudinary.sign({"folder": sig["folder"],
                                                "timestamp": sig["timestamp"]})


def test_media_register_checks_cloudinary_signature(signed_in: TestClient) -> None:
    forged = {**_upload(), "signature": "0" * 40}
    assert signed_in.post("/api/admin/media", json=forged).status_code == 400
    other_account = {**_upload(), "secureUrl": "https://res.cloudinary.com/other/x.jpg"}
    assert signed_in.post("/api/admin/media", json=other_account).status_code == 400
    ok = signed_in.post("/api/admin/media", json=_upload())
    assert ok.status_code == 201, ok.text
    assert signed_in.get("/api/admin/media").json()[0]["publicId"] == "chamathdilshan.dev/shot"


def test_media_in_use_is_protected(signed_in: TestClient, monkeypatch: Any) -> None:
    deleted: list[str] = []

    async def fake_destroy(public_id: str, resource_type: str) -> None:
        deleted.append(public_id)

    monkeypatch.setattr(cloudinary, "destroy", fake_destroy)
    media = signed_in.post("/api/admin/media", json=_upload()).json()
    signed_in.post("/api/admin/projects", json=project(thumbnail={"url": media["url"],
                                                                  "alt": ""}))
    blocked = signed_in.delete(f"/api/admin/media/{media['id']}")
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["usages"][0]["label"] == "Aegis Zero"
    assert signed_in.delete(f"/api/admin/media/{media['id']}?force=true").status_code == 204
    assert deleted == ["chamathdilshan.dev/shot"]


def test_cloudinary_signature_matches_documented_example(monkeypatch: Any) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "CLOUDINARY_API_SECRET", "abcd")
    params = {"eager": "w_400,h_300,c_pad|w_260,h_200,c_crop", "public_id": "sample_image",
              "timestamp": 1315060510}
    assert cloudinary.sign(params) == "bfd09f95f331f558cbd1320e67aa8d488770583e"


def test_video_poster_url() -> None:
    url = "https://res.cloudinary.com/demo/video/upload/v12/site/clip.mp4"
    assert cloudinary.video_poster(url) == (
        "https://res.cloudinary.com/demo/video/upload/so_0/v12/site/clip.jpg"
    )
