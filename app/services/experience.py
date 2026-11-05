"""Work experience: admin CRUD and the public timeline.

Order is never stored. Roles run newest first and companies by their most
recent role (current ones on top), so the timeline stays right as roles are
added or ended.
"""

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import flush_content, get_or_set, key
from app.models import Experience
from app.schemas.entities import ExperienceIn, ExperienceOut, ExperiencePublic, ExperienceRoleIn
from app.services.common import dump, not_found

# Sorts after any real "YYYY-MM", so a role without an end month counts as current.
_PRESENT = "9999-12"


def _role_key(role: dict[str, Any]) -> tuple[str, str]:
    return role.get("start") or "", role.get("end") or _PRESENT


def _company_key(row: Experience) -> tuple[str, str, int]:
    roles = row.roles or []
    latest_end = max((r.get("end") or _PRESENT for r in roles), default="")
    latest_start = max((r.get("start") or "" for r in roles), default="")
    return latest_end, latest_start, row.id


def _ordered(rows: list[Experience]) -> list[Experience]:
    return sorted(rows, key=_company_key, reverse=True)


def _roles(roles: list[ExperienceRoleIn]) -> list[dict[str, Any]]:
    return sorted((dump(r) for r in roles), key=_role_key, reverse=True)


def to_out(row: Experience) -> ExperienceOut:
    return ExperienceOut.model_validate(
        {
            "id": row.id,
            "company": row.company,
            "companyUrl": row.company_url,
            "logo": row.logo,
            "location": row.location,
            "roles": row.roles,
            "published": row.published,
            "createdAt": row.created_at,
            "updatedAt": row.updated_at,
        }
    )


def _apply(row: Experience, data: ExperienceIn) -> None:
    row.company = data.company
    row.company_url = data.company_url
    row.logo = data.logo
    row.location = data.location
    row.roles = _roles(data.roles)
    row.published = data.published


async def _flush() -> None:
    await flush_content(tags=["experience"], paths=["/about"])


async def list_admin(db: AsyncSession) -> list[ExperienceOut]:
    rows = list(await db.scalars(select(Experience)))
    return [to_out(r) for r in _ordered(rows)]


async def get(db: AsyncSession, experience_id: int) -> Experience:
    row = await db.get(Experience, experience_id)
    if row is None:
        raise not_found("Experience")
    return row


async def create(db: AsyncSession, data: ExperienceIn) -> ExperienceOut:
    row = Experience()
    _apply(row, data)
    db.add(row)
    await db.commit()
    await _flush()
    return to_out(row)


async def update(db: AsyncSession, experience_id: int, data: ExperienceIn) -> ExperienceOut:
    row = await get(db, experience_id)
    _apply(row, data)
    await db.commit()
    await _flush()
    return to_out(row)


async def delete(db: AsyncSession, experience_id: int) -> str:
    row = await get(db, experience_id)
    company = row.company
    await db.delete(row)
    await db.commit()
    await _flush()
    return company


async def public_list(db: AsyncSession) -> list[dict[str, Any]]:
    async def load() -> list[dict[str, Any]]:
        rows = list(await db.scalars(select(Experience).where(Experience.published.is_(True))))
        return [
            dump(
                ExperiencePublic(
                    company=r.company,
                    company_url=r.company_url,
                    logo=r.logo,
                    location=r.location,
                    roles=sorted(r.roles or [], key=_role_key, reverse=True),
                )
            )
            for r in _ordered(rows)
            if r.roles
        ]

    result: list[dict[str, Any]] = await get_or_set(
        key("experience", "list"), 3600, ["experience"], load
    )
    return result
