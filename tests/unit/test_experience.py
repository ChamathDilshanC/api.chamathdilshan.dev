"""Work experience: admin CRUD, validation and the public timeline."""

from typing import Any

from fastapi.testclient import TestClient


def role(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "title": "Software Engineer",
        "employmentType": "Full-time",
        "start": "2023-01",
        "end": None,
        "summary": "Built the platform.",
        "highlights": ["Shipped the API"],
        "skills": ["FastAPI", "Next.js"],
    }
    body.update(overrides)
    return body


def company(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "company": "Acme",
        "companyUrl": "https://acme.example",
        "location": "Colombo, Sri Lanka",
        "roles": [role()],
    }
    body.update(overrides)
    return body


def test_experience_admin_requires_a_session(client: TestClient) -> None:
    assert client.get("/api/admin/experience").status_code == 401
    assert client.post("/api/admin/experience", json=company()).status_code == 401


def test_experience_schema_drives_the_editor(signed_in: TestClient) -> None:
    schema = signed_in.get("/api/admin/schemas/experience").json()
    assert schema["required"] == ["company", "roles"]
    assert schema["properties"]["roles"]["minItems"] == 1
    fields = schema["$defs"]["ExperienceRoleIn"]["properties"]
    assert fields["start"]["format"] == "month"
    assert "Internship" in fields["employmentType"]["enum"]


def test_experience_crud_and_promotions(signed_in: TestClient) -> None:
    created = signed_in.post(
        "/api/admin/experience",
        json=company(
            roles=[
                role(title="Intern", employmentType="Internship", start="2022-06",
                     end="2022-12"),
                role(title="Senior Engineer", start="2024-07"),
                role(title="Engineer", start="2023-01", end="2024-06"),
            ]
        ),
    )
    assert created.status_code == 201, created.text
    body = created.json()
    # Stored newest first, so a promotion path reads top to bottom.
    assert [r["title"] for r in body["roles"]] == ["Senior Engineer", "Engineer", "Intern"]
    assert body["published"] is True

    updated = signed_in.put(
        f"/api/admin/experience/{body['id']}",
        json=company(company="Acme Labs", roles=body["roles"][:2]),
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["company"] == "Acme Labs"
    assert signed_in.get(f"/api/admin/experience/{body['id']}").json()["roles"][1]["title"] == (
        "Engineer"
    )

    assert signed_in.delete(f"/api/admin/experience/{body['id']}").status_code == 204
    assert signed_in.get(f"/api/admin/experience/{body['id']}").status_code == 404
    actions = [e["action"] for e in signed_in.get("/api/admin/audit-logs").json()]
    assert {"experience.create", "experience.update", "experience.delete"} <= set(actions)


def test_experience_validation(signed_in: TestClient) -> None:
    def post(body: dict[str, Any]) -> Any:
        return signed_in.post("/api/admin/experience", json=body)

    backwards = post(company(roles=[role(start="2024-05", end="2023-01")]))
    assert backwards.status_code == 422
    # Located on the field, so the admin form marks the End input itself.
    assert backwards.json()["detail"][0]["loc"][-3:] == ["roles", 0, "end"]
    assert post(company(roles=[])).status_code == 422
    assert post(company(roles=[role(start="2024-13")])).status_code == 422
    assert post(company(roles=[role(start="May 2024")])).status_code == 422
    assert post(company(roles=[role(employmentType="Volunteer")])).status_code == 422
    assert post(company(companyUrl="javascript:alert(1)")).status_code == 422
    assert post(company(logo="data:image/png;base64,AAAA")).status_code == 422
    assert post(company(author="someone")).status_code == 422


def test_public_timeline_orders_companies_and_hides_drafts(signed_in: TestClient) -> None:
    signed_in.post("/api/admin/experience", json=company(
        company="Old Co", roles=[role(start="2019-01", end="2021-03")]))
    signed_in.post("/api/admin/experience", json=company(
        company="Current Co", roles=[role(start="2023-04")]))
    signed_in.post("/api/admin/experience", json=company(
        company="Recent Co", roles=[role(start="2021-04", end="2023-03")]))
    signed_in.post("/api/admin/experience", json=company(
        company="Hidden Co", published=False, roles=[role(start="2024-01")]))

    timeline = signed_in.get("/api/experience")
    assert timeline.status_code == 200
    assert [c["company"] for c in timeline.json()] == ["Current Co", "Recent Co", "Old Co"]
    first = timeline.json()[0]
    assert set(first) == {"company", "companyUrl", "logo", "location", "roles"}
    assert first["roles"][0]["end"] is None
    assert [c["company"] for c in signed_in.get("/api/admin/experience").json()] == [
        "Hidden Co", "Current Co", "Recent Co", "Old Co"
    ]


def test_experience_logo_counts_as_media_in_use(signed_in: TestClient) -> None:
    from tests.unit.test_admin import _upload

    media = signed_in.post("/api/admin/media", json=_upload()).json()
    signed_in.post("/api/admin/experience", json=company(logo=media["url"]))
    blocked = signed_in.delete(f"/api/admin/media/{media['id']}")
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["usages"][0]["label"] == "Acme"


def test_experience_heading_is_an_editable_section(signed_in: TestClient) -> None:
    detail = signed_in.get("/api/admin/sections/about.experience").json()
    assert detail["data"]["title"] == "Experience"
    public = signed_in.get("/api/content").json()["sections"]
    assert public["about.experience"]["title"] == "Experience"
