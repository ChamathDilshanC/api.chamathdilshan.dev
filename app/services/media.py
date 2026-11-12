"""Media library: records of assets uploaded straight to Cloudinary."""

import json
import re
from typing import Any, cast

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.integrations import cloudinary
from app.models import Experience, Media, Post, Project, Section, Skill
from app.schemas.entities import MediaOrganizeOut, MediaOut, MediaRegister, MediaUsage
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


def signature(subfolder: str | None = None) -> dict[str, object]:
    _require_configured()
    try:
        return cloudinary.upload_signature(subfolder)
    except cloudinary.CloudinaryError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


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


async def delete_project_assets(db: AsyncSession, project_id: int, assets: object) -> None:
    """Destroy media owned exclusively by a project before deleting the project."""
    encoded_assets = json.dumps(assets, default=str)
    if not encoded_assets:
        return

    for row in await db.scalars(select(Media)):
        if row.public_id not in encoded_assets and row.url not in encoded_assets:
            continue
        used_elsewhere = [
            usage for usage in await usages(db, row)
            if usage.where != f"project:{project_id}"
        ]
        if used_elsewhere:
            continue
        if settings.cloudinary_configured:
            try:
                await cloudinary.destroy(row.public_id, row.kind)
            except cloudinary.CloudinaryError as exc:
                raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
        await db.delete(row)


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


def _folder_part(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]+", "-", value).strip("-_")[:80] or "unknown"


def _replace(value: object, old_url: str, new_url: str, old_id: str, new_id: str) -> object:
    if isinstance(value, str):
        return value.replace(old_url, new_url).replace(old_id, new_id)
    if isinstance(value, list):
        return [_replace(item, old_url, new_url, old_id, new_id) for item in value]
    if isinstance(value, dict):
        return {
            key: _replace(item, old_url, new_url, old_id, new_id)
            for key, item in value.items()
        }
    return value


async def _references(db: AsyncSession, row: Media) -> list[str]:
    refs: list[str] = []
    for section in await db.scalars(select(Section)):
        if row.public_id in json.dumps(section.data, default=str):
            refs.append(f"sections/{_folder_part(section.key)}")
    for project in await db.scalars(select(Project)):
        if row.public_id in json.dumps(
            [project.thumbnail, project.hero, project.gallery],
            default=str,
        ):
            refs.append(f"projects/{project.id}")
    for post in await db.scalars(select(Post)):
        if row.public_id in json.dumps([post.cover, post.sections], default=str):
            refs.append(f"journal/{post.id}")
    for skill in await db.scalars(select(Skill)):
        if skill.icon and row.public_id in skill.icon:
            refs.append(f"skills/{skill.id}")
    for job in await db.scalars(select(Experience)):
        if job.logo and row.public_id in job.logo:
            refs.append(f"experience/{job.id}")
    return refs


async def organize(db: AsyncSession) -> MediaOrganizeOut:
    """Move registered Cloudinary assets into folders based on their content usage."""
    _require_configured()
    moved = skipped = shared = 0
    failed: list[str] = []
    rows = list(await db.scalars(select(Media).order_by(Media.id)))
    for row in rows:
        refs = await _references(db, row)
        if not refs:
            target_folder = "unassigned"
        elif len(refs) > 1:
            target_folder = "shared"
            shared += 1
        else:
            target_folder = refs[0]
        basename = _folder_part(row.public_id.rsplit("/", 1)[-1])
        target = f"{settings.CLOUDINARY_FOLDER.rstrip('/')}/{target_folder}/{basename}-{row.id}"
        if row.public_id == target:
            skipped += 1
            continue
        try:
            result = await cloudinary.rename(row.public_id, target, row.kind)
        except cloudinary.CloudinaryError as exc:
            failed.append(f"{row.id}: {exc}")
            continue
        old_id, old_url = row.public_id, row.url
        new_url = str(result["secure_url"])
        row.public_id = target
        row.url = new_url
        for section_model in (await db.scalars(select(Section))).all():
            section_model.data = cast(
                dict[str, Any],
                _replace(section_model.data, old_url, new_url, old_id, target),
            )
        for project_model in (await db.scalars(select(Project))).all():
            project_model.thumbnail = cast(
                dict[str, Any] | None,
                _replace(project_model.thumbnail, old_url, new_url, old_id, target),
            )
            project_model.hero = cast(
                dict[str, Any] | None,
                _replace(project_model.hero, old_url, new_url, old_id, target),
            )
            project_model.gallery = cast(
                list[dict[str, Any]],
                _replace(project_model.gallery, old_url, new_url, old_id, target),
            )
        for post_model in (await db.scalars(select(Post))).all():
            post_model.cover = cast(
                dict[str, Any] | None,
                _replace(post_model.cover, old_url, new_url, old_id, target),
            )
            post_model.sections = cast(
                list[dict[str, Any]],
                _replace(post_model.sections, old_url, new_url, old_id, target),
            )
        for skill_model in (await db.scalars(select(Skill))).all():
            skill_model.icon = cast(
                str | None,
                _replace(skill_model.icon, old_url, new_url, old_id, target),
            )
        for experience_model in (await db.scalars(select(Experience))).all():
            experience_model.logo = cast(
                str | None,
                _replace(experience_model.logo, old_url, new_url, old_id, target),
            )
        moved += 1
    await db.commit()
    return MediaOrganizeOut(moved=moved, skipped=skipped, shared=shared, failed=failed)
