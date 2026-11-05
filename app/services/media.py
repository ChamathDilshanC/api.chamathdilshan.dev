"""Media library: records of assets uploaded straight to Cloudinary."""

import json

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.integrations import cloudinary
from app.models import Experience, Media, Post, Project, Section, Skill
from app.schemas.entities import MediaOut, MediaRegister, MediaUsage
from app.schemas.sections import SECTIONS
from app.services.common import not_found


def to_out(row: Media) -> MediaOut:
    return MediaOut.model_validate(
        {
            "id": row.id,
            "publicId": row.public_id,
            "kind": row.kind,
            "url": row.url,
            "poster": cloudinary.video_poster(row.url) if row.kind == "video" else None,
            "format": row.format,
            "width": row.width,
            "height": row.height,
            "bytes": row.bytes,
            "duration": row.duration,
            "alt": row.alt,
            "originalFilename": row.original_filename,
            "createdAt": row.created_at,
        }
    )


def _require_configured() -> None:
    if not settings.cloudinary_configured:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Cloudinary is not configured. Set the CLOUDINARY_* variables on the API.",
        )


def signature() -> dict[str, object]:
    _require_configured()
    return cloudinary.upload_signature()


async def register(db: AsyncSession, data: MediaRegister) -> MediaOut:
    """Record an upload after proving Cloudinary produced it for this account."""
    _require_configured()
    if not cloudinary.verify_upload_response(data.public_id, data.version, data.signature):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Upload signature is invalid.")
    if not data.secure_url.startswith(cloudinary.delivery_prefix()):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Upload URL is not this account.")

    existing = await db.scalar(select(Media).where(Media.public_id == data.public_id))
    if existing is not None:
        return to_out(existing)

    row = Media(
        public_id=data.public_id,
        kind=data.resource_type,
        url=data.secure_url,
        format=data.format,
        width=data.width,
        height=data.height,
        bytes=data.bytes,
        duration=data.duration,
        alt=data.alt,
        original_filename=data.original_filename,
    )
    db.add(row)
    await db.commit()
    return to_out(row)


async def list_media(db: AsyncSession, kind: str | None = None) -> list[MediaOut]:
    query = select(Media).order_by(Media.created_at.desc(), Media.id.desc())
    if kind in {"image", "video"}:
        query = query.where(Media.kind == kind)
    return [to_out(r) for r in await db.scalars(query)]


async def get(db: AsyncSession, media_id: int) -> Media:
    row = await db.get(Media, media_id)
    if row is None:
        raise not_found("File")
    return row


async def update_alt(db: AsyncSession, media_id: int, alt: str) -> MediaOut:
    row = await get(db, media_id)
    row.alt = alt
    await db.commit()
    return to_out(row)


async def usages(db: AsyncSession, row: Media) -> list[MediaUsage]:
    """Everywhere the asset is referenced, so it is not deleted out from under the site."""
    needle = row.public_id
    found: list[MediaUsage] = []

    def uses(value: object) -> bool:
        return needle in json.dumps(value, default=str)

    for section in await db.scalars(select(Section)):
        if uses(section.data):
            spec = SECTIONS.get(section.key)
            found.append(MediaUsage(where=f"section:{section.key}",
                                    label=spec.title if spec else section.key))
    for project in await db.scalars(select(Project)):
        if uses([project.thumbnail, project.hero, project.gallery]):
            found.append(MediaUsage(where=f"project:{project.id}", label=project.title))
    for post in await db.scalars(select(Post)):
        if uses([post.cover, post.sections]):
            found.append(MediaUsage(where=f"post:{post.id}", label=post.title))
    for skill in await db.scalars(select(Skill)):
        if skill.icon and needle in skill.icon:
            found.append(MediaUsage(where=f"skill:{skill.id}", label=skill.name))
    for job in await db.scalars(select(Experience)):
        if job.logo and needle in job.logo:
            found.append(MediaUsage(where=f"experience:{job.id}", label=job.company))
    return found


async def delete(db: AsyncSession, media_id: int, *, force: bool) -> Media:
    row = await get(db, media_id)
    if not force:
        used = await usages(db, row)
        if used:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail={
                    "message": "This file is still used on the site.",
                    "usages": [u.model_dump(by_alias=True) for u in used],
                },
            )
    if settings.cloudinary_configured:
        try:
            await cloudinary.destroy(row.public_id, row.kind)
        except cloudinary.CloudinaryError as exc:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    await db.delete(row)
    await db.commit()
    return row
