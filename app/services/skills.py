"""Skills: admin CRUD, ordering and the public list."""

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import flush_content, get_or_set, key
from app.models import Skill
from app.schemas.entities import SkillIn, SkillOut, SkillPublic
from app.services.common import dump, not_found


def to_out(row: Skill) -> SkillOut:
    return SkillOut.model_validate(
        {
            "id": row.id,
            "name": row.name,
            "category": row.category,
            "icon": row.icon,
            "featured": row.featured,
            "visible": row.visible,
            "sortOrder": row.sort_order,
            "createdAt": row.created_at,
            "updatedAt": row.updated_at,
        }
    )


def _apply(row: Skill, data: SkillIn) -> None:
    row.name = data.name
    row.category = data.category
    row.icon = data.icon
    row.featured = data.featured
    row.visible = data.visible


async def _flush() -> None:
    await flush_content(tags=["skills"], paths=["/", "/about"])


async def list_admin(db: AsyncSession) -> list[SkillOut]:
    rows = await db.scalars(select(Skill).order_by(Skill.sort_order, Skill.id))
    return [to_out(r) for r in rows]


async def get(db: AsyncSession, skill_id: int) -> Skill:
    row = await db.get(Skill, skill_id)
    if row is None:
        raise not_found("Skill")
    return row


async def create(db: AsyncSession, data: SkillIn) -> SkillOut:
    last = await db.scalar(select(func.max(Skill.sort_order)))
    row = Skill(sort_order=(last or 0) + 1)
    _apply(row, data)
    db.add(row)
    await db.commit()
    await _flush()
    return to_out(row)


async def update(db: AsyncSession, skill_id: int, data: SkillIn) -> SkillOut:
    row = await get(db, skill_id)
    _apply(row, data)
    await db.commit()
    await _flush()
    return to_out(row)


async def delete(db: AsyncSession, skill_id: int) -> str:
    row = await get(db, skill_id)
    name = row.name
    await db.delete(row)
    await db.commit()
    await _flush()
    return name


async def reorder(db: AsyncSession, ids: list[int]) -> list[SkillOut]:
    rows = {r.id: r for r in await db.scalars(select(Skill))}
    for position, skill_id in enumerate(ids, start=1):
        if skill_id in rows:
            rows[skill_id].sort_order = position
    await db.commit()
    await _flush()
    return await list_admin(db)


async def public_list(db: AsyncSession) -> list[dict[str, Any]]:
    async def load() -> list[dict[str, Any]]:
        rows = await db.scalars(select(Skill).order_by(Skill.sort_order, Skill.id))
        return [
            dump(SkillPublic(name=r.name, category=r.category, icon=r.icon, featured=r.featured,
                             visible=r.visible))
            for r in rows
            if r.featured or r.visible
        ]

    result: list[dict[str, Any]] = await get_or_set(key("skills", "list"), 3600, ["skills"], load)
    return result
