"""Toolbox logos use their own section and the existing brand icon picker."""

import asyncio
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.db import get_sessionmaker
from app.models import Section
from app.schemas.sections import ToolboxItem

LOGO = "https://thesvg.org/icons/docker/default.svg"


def test_toolbox_schema_uses_the_brand_picker(signed_in: TestClient) -> None:
    detail = signed_in.get("/api/admin/sections/about.toolbox").json()
    logo = detail["schema"]["$defs"]["ToolboxItem"]["properties"]["image"]
    assert logo["title"] == "Logo"
    assert "brand-icon" in [part.get("widget") for part in logo["anyOf"]]


def test_toolbox_add_reorder_remove_and_clear_logo(signed_in: TestClient) -> None:
    signed_in.post("/api/admin/skills", json={"name": "Separate skill"})
    tools: dict[str, Any] = {
        "title": "Toolbox",
        "aside": "Everyday tools",
        "items": [
            {"name": "Docker", "role": "Containers", "image": LOGO},
            {"name": "Figma", "role": "Design", "image": None},
        ],
    }
    saved = signed_in.put("/api/admin/sections/about.toolbox", json=tools)
    assert saved.status_code == 200, saved.text
    public = signed_in.get("/api/content").json()["sections"]["about.toolbox"]
    assert public == tools
    tools["items"].reverse()
    tools["items"][1]["image"] = None
    assert signed_in.put("/api/admin/sections/about.toolbox", json=tools).status_code == 200
    public = signed_in.get("/api/content").json()["sections"]["about.toolbox"]
    assert [item["name"] for item in public["items"]] == ["Figma", "Docker"]
    assert public["items"][1]["image"] is None
    tools["items"] = []
    assert signed_in.put("/api/admin/sections/about.toolbox", json=tools).status_code == 200
    assert signed_in.get("/api/content").json()["sections"]["about.toolbox"]["items"] == []
    assert signed_in.get("/api/admin/skills").json()[0]["name"] == "Separate skill"


def test_legacy_placeholder_is_normalized_without_writing_on_read(signed_in: TestClient) -> None:
    old_photo = "/images/placeholders/team-3.jpg"

    async def insert_legacy() -> None:
        async with get_sessionmaker()() as db:
            db.add(
                Section(
                    key="about.toolbox",
                    data={
                        "title": "My toolbox",
                        "aside": "Daily",
                        "items": [{"name": "Docker", "role": "Containers", "image": old_photo}],
                    },
                )
            )
            await db.commit()

    asyncio.run(insert_legacy())
    admin = signed_in.get("/api/admin/sections/about.toolbox").json()["data"]
    public = signed_in.get("/api/content").json()["sections"]["about.toolbox"]
    assert admin["items"][0]["image"] == LOGO
    assert public == admin

    async def read_raw() -> str:
        async with get_sessionmaker()() as db:
            row = await db.get(Section, "about.toolbox")
            assert row is not None
            return str(row.data["items"][0]["image"])

    assert asyncio.run(read_raw()) == old_photo


@pytest.mark.parametrize(
    "url", ["javascript:alert(1)", "data:image/svg+xml,<svg/>", "//evil.test/a.svg"]
)
def test_toolbox_rejects_unsafe_logos(url: str) -> None:
    with pytest.raises(ValidationError):
        ToolboxItem(name="Tool", role="Test", image=url)


def test_unknown_legacy_photo_falls_back_and_custom_logos_are_preserved() -> None:
    assert (
        ToolboxItem(name="Other", role="Test", image="/images/placeholders/old.jpg").image is None
    )
    custom = "https://cdn.example.com/logo.svg"
    assert ToolboxItem(name="Other", role="Test", image=custom).image == custom
