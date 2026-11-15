"""Editable site sections: read with defaults, validate, save, invalidate."""

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import flush_content, get_or_set, key
from app.core.config import settings
from app.core.db import utcnow
from app.models import Section
from app.schemas.entities import SectionDetail, SectionSummary
from app.schemas.sections import SECTIONS
from app.services.common import dump, not_found

SEED_FILE = Path(__file__).resolve().parent.parent / "seed" / "content.json"
PUBLIC_PATHS = ["/", "/about", "/projects", "/blog", "/contact"]


@lru_cache
def seed() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(SEED_FILE.read_text(encoding="utf-8"))
    return data


def default_section(key_: str) -> dict[str, Any]:
    """The seed content for a section, so a fresh database still renders and edits."""
    value = seed().get("sections", {}).get(key_)
    return dict(value) if isinstance(value, dict) else {}


def _read_data(key_: str, data: dict[str, Any]) -> dict[str, Any]:
    # Normalize legacy Toolbox photos without changing stored data on a read.
    if key_ == "about.toolbox":
        result: dict[str, Any] = dump(SECTIONS[key_].model.model_validate(data))
        return result
    return data


async def _stored(db: AsyncSession) -> dict[str, Section]:
    rows = await db.scalars(select(Section))
    return {row.key: row for row in rows}


async def list_sections(db: AsyncSession) -> list[SectionSummary]:
    stored = await _stored(db)
    return [
        SectionSummary(
            key=spec.key,
            title=spec.title,
            group=spec.group,
            description=spec.description,
            updated_at=stored[spec.key].updated_at if spec.key in stored else None,
        )
        for spec in SECTIONS.values()
    ]


async def get_section(db: AsyncSession, key_: str) -> SectionDetail:
    spec = SECTIONS.get(key_)
    if spec is None:
        raise not_found("Section")
    row = await db.get(Section, key_)
    return SectionDetail(
        key=spec.key,
        title=spec.title,
        group=spec.group,
        description=spec.description,
        updated_at=row.updated_at if row else None,
        data=_read_data(key_, row.data if row else default_section(key_)),
        schema_=spec.model.model_json_schema(by_alias=True),
    )


async def save_section(db: AsyncSession, key_: str, data: dict[str, Any]) -> SectionDetail:
    """Validate against the section model and store. Raises pydantic.ValidationError."""
    spec = SECTIONS.get(key_)
    if spec is None:
        raise not_found("Section")
    clean = dump(spec.model.model_validate(data))
    row = await db.get(Section, key_)
    if row is None:
        db.add(Section(key=key_, data=clean, updated_at=utcnow()))
    else:
        row.data = clean
        row.updated_at = utcnow()
    await db.commit()
    await flush_content(tags=["content"], paths=PUBLIC_PATHS)
    return await get_section(db, key_)


async def public_content(db: AsyncSession) -> dict[str, Any]:
    async def load() -> dict[str, Any]:
        stored = await _stored(db)
        sections: dict[str, Any] = {}
        for spec in SECTIONS.values():
            row = stored.get(spec.key)
            sections[spec.key] = _read_data(
                spec.key, row.data if row else default_section(spec.key)
            )
        return {"sections": sections}

    result: dict[str, Any] = await get_or_set(key("content", "all"), 3600, ["content"], load)
    sections = result.get("sections", {})
    site = sections.get("site", {})
    return {
        "sections": {
            **sections,
            "site": {**site, "email": settings.PUBLIC_CONTACT_EMAIL},
        }
    }

