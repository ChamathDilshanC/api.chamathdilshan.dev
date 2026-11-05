"""Journal posts: admin CRUD and the public read model."""

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import flush_content, get_or_set, key
from app.models import Post
from app.schemas.entities import PostIn, PostOut, PostPublic
from app.services.common import dump, not_found, slugify, unique_slug


def to_out(row: Post) -> PostOut:
    return PostOut.model_validate(
        {
            "id": row.id,
            "slug": row.slug,
            "title": row.title,
            "category": row.category,
            "date": row.date,
            "excerpt": row.excerpt,
            "cover": row.cover,
            "sections": row.sections or [],
            "published": row.published,
            "createdAt": row.created_at,
            "updatedAt": row.updated_at,
        }
    )


def to_public(row: Post) -> dict[str, Any] | None:
    if not row.cover:
        return None
    model = PostPublic.model_validate(
        {
            "slug": row.slug,
            "title": row.title,
            "category": row.category,
            "date": row.date,
            "excerpt": row.excerpt,
            "cover": row.cover,
            "sections": row.sections or [],
        }
    )
    result: dict[str, Any] = dump(model)
    return result


def _apply(row: Post, data: PostIn) -> None:
    row.title = data.title
    row.category = data.category
    row.date = data.date
    row.excerpt = data.excerpt
    row.cover = dump(data.cover)
    row.sections = [
        {**dump(s), "paragraphs": [p for p in s.paragraphs if p.strip()]} for s in data.sections
    ]
    row.published = data.published


async def _flush(*slugs: str) -> None:
    tags = ["blog", *(f"post:{s}" for s in slugs)]
    paths = ["/", "/about", "/blog", *(f"/blog/{s}" for s in slugs)]
    await flush_content(tags=tags, paths=paths)


async def list_admin(db: AsyncSession) -> list[PostOut]:
    rows = await db.scalars(select(Post).order_by(Post.date.desc(), Post.id.desc()))
    return [to_out(r) for r in rows]


async def get(db: AsyncSession, post_id: int) -> Post:
    row = await db.get(Post, post_id)
    if row is None:
        raise not_found("Article")
    return row


async def create(db: AsyncSession, data: PostIn) -> PostOut:
    slug = await unique_slug(db, Post.slug, data.slug or slugify(data.title))
    row = Post(slug=slug)
    _apply(row, data)
    db.add(row)
    await db.commit()
    await _flush(slug)
    return to_out(row)


async def update(db: AsyncSession, post_id: int, data: PostIn) -> PostOut:
    row = await get(db, post_id)
    old_slug = row.slug
    wanted = data.slug or old_slug
    if wanted != old_slug:
        row.slug = await unique_slug(db, Post.slug, wanted, exclude_id=row.id, id_column=Post.id)
    _apply(row, data)
    await db.commit()
    await _flush(old_slug, row.slug)
    return to_out(row)


async def delete(db: AsyncSession, post_id: int) -> str:
    row = await get(db, post_id)
    slug = row.slug
    await db.delete(row)
    await db.commit()
    await _flush(slug)
    return slug


async def public_list(db: AsyncSession) -> list[dict[str, Any]]:
    async def load() -> list[dict[str, Any]]:
        rows = await db.scalars(
            select(Post).where(Post.published.is_(True)).order_by(Post.date.desc(), Post.id.desc())
        )
        return [p for p in (to_public(r) for r in rows) if p is not None]

    result: list[dict[str, Any]] = await get_or_set(key("blog", "list"), 600, ["blog"], load)
    return result


async def public_get(db: AsyncSession, slug: str) -> dict[str, Any] | None:
    async def load() -> dict[str, Any] | None:
        row = await db.scalar(select(Post).where(Post.slug == slug, Post.published.is_(True)))
        return to_public(row) if row else None

    result: dict[str, Any] | None = await get_or_set(
        key("post", slug), 3600, ["blog", f"post:{slug}"], load
    )
    return result
