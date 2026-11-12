"""Projects (case studies): admin CRUD, ordering and the public read model."""

from typing import Any

from sqlalchemy import delete as sqlalchemy_delete
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import flush_content, get_or_set, key
from app.models import Project, ProjectRepository
from app.schemas.entities import ProjectIn, ProjectOut, ProjectPublic
from app.services.common import dump, not_found, slugify, unique_slug
from app.services.media import delete_project_assets


def to_out(row: Project) -> ProjectOut:
    return ProjectOut.model_validate(
        {
            "id": row.id,
            "slug": row.slug,
            "title": row.title,
            "category": row.category,
            "year": row.year,
            "summary": row.summary,
            "thumbnail": row.thumbnail,
            "hero": row.hero,
            "intro": row.intro,
            "discover": row.discover,
            "explore": row.explore,
            "results": row.results or [],
            "gallery": row.gallery or [],
            "tech": row.tech or [],
            "liveUrl": row.live_url,
            "repoUrl": row.repo_url,
            "template": row.template,
            "templateConfig": row.template_config or {},
            "studioContent": row.studio_content or {},
            "seo": row.seo or {},
            "repositories": row.repositories or [],
            "featured": row.featured,
            "published": row.published,
            "sortOrder": row.sort_order,
            "createdAt": row.created_at,
            "updatedAt": row.updated_at,
        }
    )


def to_public(row: Project) -> dict[str, Any] | None:
    """Public shape. Projects without a thumbnail are never shown."""
    if not row.thumbnail:
        return None
    hero = row.hero or {"kind": "image", "url": row.thumbnail["url"],
                        "alt": row.thumbnail.get("alt", ""), "poster": None}
    model = ProjectPublic.model_validate(
        {
            "slug": row.slug,
            "title": row.title,
            "category": row.category,
            "year": row.year,
            "summary": row.summary,
            "thumbnail": row.thumbnail,
            "hero": hero,
            "intro": row.intro,
            "discover": row.discover,
            "explore": row.explore,
            "results": row.results or [],
            "gallery": row.gallery or [],
            "tech": row.tech or [],
            "liveUrl": row.live_url,
            "repoUrl": row.repo_url,
            "template": row.template,
            "templateConfig": row.template_config or {},
            "studioContent": row.studio_content or {},
            "seo": row.seo or {},
            "repositories": row.repositories or [],
            "featured": row.featured,
        }
    )
    result: dict[str, Any] = dump(model)
    return result


def _apply(row: Project, data: ProjectIn) -> None:
    row.title = data.title
    row.category = data.category
    row.year = data.year
    row.summary = data.summary
    row.thumbnail = dump(data.thumbnail)
    row.hero = dump(data.hero)
    row.intro = data.intro
    row.discover = data.discover
    row.explore = data.explore
    row.results = [dump(r) for r in data.results]
    row.gallery = [dump(g) for g in data.gallery]
    row.tech = list(dict.fromkeys(t for t in data.tech if t))
    row.live_url = data.live_url
    row.repo_url = data.repo_url
    row.template = data.template
    row.template_config = data.template_config
    row.studio_content = data.studio_content
    row.seo = data.seo
    row.repositories = data.repositories
    row.featured = data.featured
    row.published = data.published


async def _flush(*slugs: str) -> None:
    tags = ["projects", *(f"project:{s}" for s in slugs)]
    paths = ["/", "/projects", *(f"/projects/{s}" for s in slugs)]
    await flush_content(tags=tags, paths=paths)


async def list_admin(db: AsyncSession) -> list[ProjectOut]:
    rows = await db.scalars(select(Project).order_by(Project.sort_order, Project.id))
    return [to_out(r) for r in rows]


async def get(db: AsyncSession, project_id: int) -> Project:
    row = await db.get(Project, project_id)
    if row is None:
        raise not_found("Project")
    return row


async def create(db: AsyncSession, data: ProjectIn) -> ProjectOut:
    slug = await unique_slug(db, Project.slug, data.slug or slugify(data.title))
    last = await db.scalar(select(func.max(Project.sort_order)))
    row = Project(slug=slug, sort_order=(last or 0) + 1)
    _apply(row, data)
    db.add(row)
    await db.commit()
    await _flush(slug)
    return to_out(row)


async def update(db: AsyncSession, project_id: int, data: ProjectIn) -> ProjectOut:
    row = await get(db, project_id)
    old_slug = row.slug
    wanted = data.slug or old_slug
    if wanted != old_slug:
        row.slug = await unique_slug(db, Project.slug, wanted, exclude_id=row.id,
                                     id_column=Project.id)
    _apply(row, data)
    await db.commit()
    await _flush(old_slug, row.slug)
    return to_out(row)


async def delete(db: AsyncSession, project_id: int) -> str:
    row = await get(db, project_id)
    slug = row.slug
    await delete_project_assets(
        db,
        project_id,
        [row.thumbnail, row.hero, row.gallery],
    )
    await db.execute(
        sqlalchemy_delete(ProjectRepository).where(ProjectRepository.project_id == project_id)
    )
    await db.delete(row)
    await db.commit()
    await _flush(slug)
    return slug


async def reorder(db: AsyncSession, ids: list[int]) -> list[ProjectOut]:
    rows = {r.id: r for r in await db.scalars(select(Project))}
    for position, project_id in enumerate(ids, start=1):
        if project_id in rows:
            rows[project_id].sort_order = position
    await db.commit()
    await _flush()
    return await list_admin(db)


async def public_list(db: AsyncSession) -> list[dict[str, Any]]:
    async def load() -> list[dict[str, Any]]:
        rows = await db.scalars(
            select(Project).where(Project.published.is_(True))
            .order_by(Project.sort_order, Project.id)
        )
        return [p for p in (to_public(r) for r in rows) if p is not None]

    result: list[dict[str, Any]] = await get_or_set(
        key("projects", "list"), 600, ["projects"], load
    )
    return result


async def public_get(db: AsyncSession, slug: str) -> dict[str, Any] | None:
    async def load() -> dict[str, Any] | None:
        row = await db.scalar(
            select(Project).where(Project.slug == slug, Project.published.is_(True))
        )
        return to_public(row) if row else None

    result: dict[str, Any] | None = await get_or_set(
        key("project", slug), 3600, ["projects", f"project:{slug}"], load
    )
    return result
