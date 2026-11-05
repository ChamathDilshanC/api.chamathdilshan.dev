"""Unauthenticated, cacheable reads for the public site (CACHING.md §6)."""

import json
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Path, Request, Response, status

from app.core.http_cache import PUBLIC_CONTENT, apply_cache
from app.security.deps import DB
from app.services import experience, posts, projects, sections, skills

router = APIRouter()

SlugParam = Annotated[str, Path(max_length=120, pattern=r"^[a-z0-9-]+$")]


def _cached(request: Request, response: Response, payload: Any) -> Any:
    """Shared-cacheable response with an ETag; answers 304 when the client is current."""
    body = json.dumps(payload, separators=(",", ":"), default=str).encode()
    apply_cache(response, PUBLIC_CONTENT, body)
    etag = response.headers.get("etag")
    if etag and request.headers.get("if-none-match") == etag:
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers=dict(response.headers))
    return payload


@router.get("/content")
async def content(request: Request, response: Response, db: DB) -> Any:
    """Every editable section of the site, keyed by section name."""
    return _cached(request, response, await sections.public_content(db))


@router.get("/projects")
async def list_projects(request: Request, response: Response, db: DB) -> Any:
    return _cached(request, response, await projects.public_list(db))


@router.get("/projects/{slug}")
async def get_project(slug: SlugParam, request: Request, response: Response, db: DB) -> Any:
    project = await projects.public_get(db, slug)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Project not found.")
    return _cached(request, response, project)


@router.get("/posts")
async def list_posts(request: Request, response: Response, db: DB) -> Any:
    return _cached(request, response, await posts.public_list(db))


@router.get("/posts/{slug}")
async def get_post(slug: SlugParam, request: Request, response: Response, db: DB) -> Any:
    post = await posts.public_get(db, slug)
    if post is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Article not found.")
    return _cached(request, response, post)


@router.get("/skills")
async def list_skills(request: Request, response: Response, db: DB) -> Any:
    return _cached(request, response, await skills.public_list(db))


@router.get("/experience")
async def list_experience(request: Request, response: Response, db: DB) -> Any:
    """Companies with their roles, most recent first."""
    return _cached(request, response, await experience.public_list(db))
