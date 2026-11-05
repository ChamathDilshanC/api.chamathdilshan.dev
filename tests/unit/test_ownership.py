"""Single-owner content model.

The project has exactly one Core Author, `chamathdilshanc`, and the CMS keeps
no author records at all: no table, schema or seed entry carries an author, so
no API call, admin form, seed run or migration can create a second Core
Author. The signed-in admin account is recorded only as the actor in the audit
log. These tests keep it that way.
"""

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.db import Base
from app.schemas.entities import PostIn, ProjectIn, SkillIn
from app.schemas.sections import SECTIONS
from app.services.sections import SEED_FILE


def _keys(value: Any) -> set[str]:
    """Every dict key anywhere inside a JSON-like value."""
    if isinstance(value, dict):
        return set(value) | {k for v in value.values() for k in _keys(v)}
    if isinstance(value, list):
        return {k for v in value for k in _keys(v)}
    return set()


def _authorish(keys: set[str]) -> list[str]:
    return sorted(k for k in keys if "author" in k.lower())


def test_no_table_stores_an_author() -> None:
    columns = [f"{t.name}.{c.name}" for t in Base.metadata.tables.values() for c in t.columns]
    assert [c for c in columns if "author" in c.lower()] == []


def test_no_write_schema_has_an_author_field() -> None:
    models = [ProjectIn, PostIn, SkillIn, *(spec.model for spec in SECTIONS.values())]
    for model in models:
        schema = model.model_json_schema(by_alias=True)
        properties = {
            name
            for definition in [schema, *schema.get("$defs", {}).values()]
            for name in definition.get("properties", {})
        }
        assert _authorish(properties) == [], model.__name__


def test_seed_creates_no_authors() -> None:
    data = json.loads(SEED_FILE.read_text(encoding="utf-8"))
    assert _authorish(_keys(data)) == []


@pytest.mark.parametrize("field", ["author", "coreAuthor", "authors"])
def test_api_rejects_author_fields(signed_in: TestClient, field: str) -> None:
    other = "someone-else"
    project = signed_in.post("/api/admin/projects", json={"title": "X", field: other})
    assert project.status_code == 422
    post = signed_in.post("/api/admin/posts", json={"title": "X", "date": "2026-01-01",
                                                    field: other})
    assert post.status_code == 422
    skill = signed_in.post("/api/admin/skills", json={"name": "Go", field: other})
    assert skill.status_code == 422
    site = signed_in.get("/api/admin/sections/site").json()["data"]
    section = signed_in.put("/api/admin/sections/site", json={**site, field: other})
    assert section.status_code == 422
