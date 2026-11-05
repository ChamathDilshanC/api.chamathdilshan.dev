"""Owner-only content management. Every route requires a live admin session and,
for writes, a trusted Origin (SECURITY.md §8, §18). Nothing here is cacheable."""

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Response, status
from pydantic import ValidationError
from sqlalchemy import func, select

from app.core.config import settings
from app.core.http_cache import no_store
from app.models import Media, Post, Project, Skill
from app.schemas.common import CamelModel
from app.schemas.entities import (
    AuditOut,
    ExperienceIn,
    ExperienceOut,
    MediaOut,
    MediaRegister,
    MediaSignature,
    MediaUpdate,
    PostIn,
    PostOut,
    ProjectIn,
    ProjectOut,
    ReorderIn,
    SectionDetail,
    SectionSummary,
    SkillIn,
    SkillOut,
)
from app.security.deps import DB, CurrentAdmin, require_admin, require_trusted_origin
from app.services import audit, experience, media, posts, projects, sections, skills


def _private(response: Response) -> None:
    no_store(response)


router = APIRouter(
    dependencies=[
        Depends(require_admin),
        Depends(require_trusted_origin),
        Depends(_private),
    ]
)

SCHEMAS: dict[str, type[CamelModel]] = {
    "project": ProjectIn,
    "post": PostIn,
    "skill": SkillIn,
    "experience": ExperienceIn,
}


# --- overview -----------------------------------------------------------------


@router.get("/overview")
async def overview(db: DB) -> dict[str, Any]:
    async def count(model: Any, *where: Any) -> int:
        return int(await db.scalar(select(func.count()).select_from(model).where(*where)) or 0)

    logs = await audit.recent(db, 12)
    return {
        "projects": await count(Project),
        "projectsPublished": await count(Project, Project.published.is_(True)),
        "posts": await count(Post),
        "postsPublished": await count(Post, Post.published.is_(True)),
        "skills": await count(Skill),
        "media": await count(Media),
        "mediaConfigured": settings.cloudinary_configured,
        "recent": [AuditOut.model_validate(r, from_attributes=True).model_dump(by_alias=True,
                                                                               mode="json")
                   for r in logs],
    }


@router.get("/audit-logs", response_model=list[AuditOut])
async def audit_logs(db: DB, limit: Annotated[int, Query(ge=1, le=500)] = 100) -> Any:
    return [AuditOut.model_validate(r, from_attributes=True) for r in await audit.recent(db, limit)]


@router.get("/schemas/{name}")
async def schema(name: Literal["project", "post", "skill", "experience"]) -> dict[str, Any]:
    """JSON Schema the admin renders its editors from."""
    result: dict[str, Any] = SCHEMAS[name].model_json_schema(by_alias=True)
    return result


# --- sections -----------------------------------------------------------------


@router.get("/sections", response_model=list[SectionSummary])
async def list_sections(db: DB) -> Any:
    return await sections.list_sections(db)


@router.get("/sections/{key}", response_model=SectionDetail)
async def get_section(key: str, db: DB) -> Any:
    return await sections.get_section(db, key)


@router.put("/sections/{key}", response_model=SectionDetail)
async def save_section(
    key: str, admin: CurrentAdmin, db: DB, data: Annotated[dict[str, Any], Body()]
) -> Any:
    try:
        result = await sections.save_section(db, key, data)
    except ValidationError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=exc.errors(include_url=False, include_context=False, include_input=False),
        ) from exc
    await audit.record(db, "section.update", actor=admin.email, target=key, ip=admin.ip)
    return result


# --- projects -----------------------------------------------------------------


@router.get("/projects", response_model=list[ProjectOut])
async def list_projects(db: DB) -> Any:
    return await projects.list_admin(db)


@router.get("/projects/{project_id}", response_model=ProjectOut)
async def get_project(project_id: int, db: DB) -> Any:
    return projects.to_out(await projects.get(db, project_id))


@router.post("/projects", response_model=ProjectOut, status_code=status.HTTP_201_CREATED)
async def create_project(data: ProjectIn, admin: CurrentAdmin, db: DB) -> Any:
    result = await projects.create(db, data)
    await audit.record(db, "project.create", actor=admin.email, target=result.slug, ip=admin.ip)
    return result


@router.put("/projects/{project_id}", response_model=ProjectOut)
async def update_project(project_id: int, data: ProjectIn, admin: CurrentAdmin, db: DB) -> Any:
    result = await projects.update(db, project_id, data)
    await audit.record(db, "project.update", actor=admin.email, target=result.slug, ip=admin.ip)
    return result


@router.delete("/projects/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(project_id: int, admin: CurrentAdmin, db: DB) -> None:
    slug = await projects.delete(db, project_id)
    await audit.record(db, "project.delete", actor=admin.email, target=slug, ip=admin.ip)


@router.post("/projects/reorder", response_model=list[ProjectOut])
async def reorder_projects(data: ReorderIn, admin: CurrentAdmin, db: DB) -> Any:
    result = await projects.reorder(db, data.ids)
    await audit.record(db, "project.reorder", actor=admin.email, ip=admin.ip)
    return result


# --- journal posts ------------------------------------------------------------


@router.get("/posts", response_model=list[PostOut])
async def list_posts(db: DB) -> Any:
    return await posts.list_admin(db)


@router.get("/posts/{post_id}", response_model=PostOut)
async def get_post(post_id: int, db: DB) -> Any:
    return posts.to_out(await posts.get(db, post_id))


@router.post("/posts", response_model=PostOut, status_code=status.HTTP_201_CREATED)
async def create_post(data: PostIn, admin: CurrentAdmin, db: DB) -> Any:
    result = await posts.create(db, data)
    await audit.record(db, "post.create", actor=admin.email, target=result.slug, ip=admin.ip)
    return result


@router.put("/posts/{post_id}", response_model=PostOut)
async def update_post(post_id: int, data: PostIn, admin: CurrentAdmin, db: DB) -> Any:
    result = await posts.update(db, post_id, data)
    await audit.record(db, "post.update", actor=admin.email, target=result.slug, ip=admin.ip)
    return result


@router.delete("/posts/{post_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_post(post_id: int, admin: CurrentAdmin, db: DB) -> None:
    slug = await posts.delete(db, post_id)
    await audit.record(db, "post.delete", actor=admin.email, target=slug, ip=admin.ip)


# --- work experience ----------------------------------------------------------


@router.get("/experience", response_model=list[ExperienceOut])
async def list_experience(db: DB) -> Any:
    return await experience.list_admin(db)


@router.get("/experience/{experience_id}", response_model=ExperienceOut)
async def get_experience(experience_id: int, db: DB) -> Any:
    return experience.to_out(await experience.get(db, experience_id))


@router.post("/experience", response_model=ExperienceOut, status_code=status.HTTP_201_CREATED)
async def create_experience(data: ExperienceIn, admin: CurrentAdmin, db: DB) -> Any:
    result = await experience.create(db, data)
    await audit.record(db, "experience.create", actor=admin.email, target=result.company,
                       ip=admin.ip)
    return result


@router.put("/experience/{experience_id}", response_model=ExperienceOut)
async def update_experience(
    experience_id: int, data: ExperienceIn, admin: CurrentAdmin, db: DB
) -> Any:
    result = await experience.update(db, experience_id, data)
    await audit.record(db, "experience.update", actor=admin.email, target=result.company,
                       ip=admin.ip)
    return result


@router.delete("/experience/{experience_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_experience(experience_id: int, admin: CurrentAdmin, db: DB) -> None:
    company = await experience.delete(db, experience_id)
    await audit.record(db, "experience.delete", actor=admin.email, target=company, ip=admin.ip)


# --- skills -------------------------------------------------------------------


@router.get("/skills", response_model=list[SkillOut])
async def list_skills(db: DB) -> Any:
    return await skills.list_admin(db)


@router.post("/skills", response_model=SkillOut, status_code=status.HTTP_201_CREATED)
async def create_skill(data: SkillIn, admin: CurrentAdmin, db: DB) -> Any:
    result = await skills.create(db, data)
    await audit.record(db, "skill.create", actor=admin.email, target=result.name, ip=admin.ip)
    return result


@router.put("/skills/{skill_id}", response_model=SkillOut)
async def update_skill(skill_id: int, data: SkillIn, admin: CurrentAdmin, db: DB) -> Any:
    result = await skills.update(db, skill_id, data)
    await audit.record(db, "skill.update", actor=admin.email, target=result.name, ip=admin.ip)
    return result


@router.delete("/skills/{skill_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_skill(skill_id: int, admin: CurrentAdmin, db: DB) -> None:
    name = await skills.delete(db, skill_id)
    await audit.record(db, "skill.delete", actor=admin.email, target=name, ip=admin.ip)


@router.post("/skills/reorder", response_model=list[SkillOut])
async def reorder_skills(data: ReorderIn, admin: CurrentAdmin, db: DB) -> Any:
    result = await skills.reorder(db, data.ids)
    await audit.record(db, "skill.reorder", actor=admin.email, ip=admin.ip)
    return result


# --- media --------------------------------------------------------------------


@router.post("/media/sign", response_model=MediaSignature)
async def sign_upload() -> Any:
    """Short-lived signature for one direct browser → Cloudinary upload."""
    return media.signature()


@router.post("/media", response_model=MediaOut, status_code=status.HTTP_201_CREATED)
async def register_media(data: MediaRegister, admin: CurrentAdmin, db: DB) -> Any:
    result = await media.register(db, data)
    await audit.record(db, "media.upload", actor=admin.email, target=result.public_id,
                       ip=admin.ip)
    return result


@router.get("/media", response_model=list[MediaOut])
async def list_media(
    db: DB, kind: Annotated[Literal["image", "video"] | None, Query()] = None
) -> Any:
    return await media.list_media(db, kind)


@router.patch("/media/{media_id}", response_model=MediaOut)
async def update_media(media_id: int, data: MediaUpdate, db: DB) -> Any:
    return await media.update_alt(db, media_id, data.alt)


@router.get("/media/{media_id}/usages")
async def media_usages(media_id: int, db: DB) -> Any:
    row = await media.get(db, media_id)
    return [u.model_dump(by_alias=True) for u in await media.usages(db, row)]


@router.delete("/media/{media_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_media(
    media_id: int, admin: CurrentAdmin, db: DB, force: Annotated[bool, Query()] = False
) -> None:
    row = await media.delete(db, media_id, force=force)
    await audit.record(db, "media.delete", actor=admin.email, target=row.public_id, ip=admin.ip)
