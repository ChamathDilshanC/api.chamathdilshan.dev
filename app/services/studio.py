"""Repository analysis and AI draft orchestration.

The analyzer is deterministic and bounded. Gemini only receives a compact,
evidence-labelled summary, never credentials, binary files, or an unbounded
repository dump.
"""

import re
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import flush_content
from app.core.config import settings
from app.integrations.ai_fallback import AIGeneration, generate_with_fallback
from app.integrations.github import (
    GitHubClient,
    GitHubError,
    normalize_repository_url,
    redact_content,
)
from app.models import Project, ProjectRepository, ProjectStudioDraft
from app.schemas.studio import (
    AnalyzeRepositoryIn,
    CreateProjectFromDraftIn,
    Evidence,
    GenerateDraftIn,
    RepositoryAnalysis,
    RepositoryAssociationOut,
    RepositoryPage,
    RepositorySummary,
    StudioContent,
    StudioDraftOut,
    SubmoduleEvidence,
    UpdateDraftIn,
)
from app.services.common import slugify, unique_slug

_GITMODULE = re.compile(
    r"^\s*\[submodule \"(?P<name>[^\"]+)\"\]\s*$|^\s*(?P<key>path|url)\s*=\s*(?P<value>.+?)\s*$",
    re.MULTILINE,
)
_TECH_RULES = {
    "Frontend": [
        ("package.json", "JavaScript/TypeScript"),
        ("next.config", "Next.js"),
        ("vite.config", "Vite"),
        ("src/", "Frontend"),
    ],
    "Backend": [
        ("pyproject.toml", "Python"),
        ("requirements.txt", "Python"),
        ("fastapi", "FastAPI"),
        ("pom.xml", "Java/Maven"),
        ("build.gradle", "Java/Gradle"),
    ],
    "Database": [
        ("alembic", "Alembic"),
        ("prisma", "Prisma"),
        ("schema.prisma", "Prisma"),
        ("supabase", "Supabase"),
    ],
    "DevOps": [
        ("dockerfile", "Docker"),
        (".github/workflows", "GitHub Actions"),
        ("terraform", "Terraform"),
        ("vercel.json", "Vercel"),
    ],
}


def _summary(item: dict[str, Any]) -> RepositorySummary:
    def as_dt(key: str) -> datetime | None:
        value = item.get(key)
        if not value:
            return None
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None

    owner = str(
        (item.get("owner") or {}).get("login") or str(item.get("full_name", "/")).split("/")[0]
    )
    name = str(item.get("name", ""))
    return RepositorySummary(
        owner=owner,
        name=name,
        full_name=str(item.get("full_name") or f"{owner}/{name}"),
        html_url=item.get("html_url") or f"https://github.com/{owner}/{name}",
        description=str(item.get("description") or ""),
        language=item.get("language"),
        visibility="private" if item.get("private") else "public",
        stars=int(item.get("stargazers_count") or 0),
        created_at=as_dt("created_at"),
        updated_at=as_dt("updated_at"),
        pushed_at=as_dt("pushed_at"),
        default_branch=str(item.get("default_branch") or "main"),
        fork=bool(item.get("fork")),
        archived=bool(item.get("archived")),
        has_readme=item.get("has_readme"),
    )


def _priority(path: str) -> tuple[int, str]:
    lower = path.lower()
    if lower in {"readme.md", "readme"}:
        return (0, path)
    if lower in {
        "package.json",
        "pyproject.toml",
        "requirements.txt",
        "pom.xml",
        "build.gradle",
        ".gitmodules",
    }:
        return (1, path)
    if lower.startswith(".github/") or lower.startswith("docs/"):
        return (2, path)
    if any(part in lower for part in ("docker", "vercel", "terraform", "alembic", "prisma")):
        return (3, path)
    return (4, path)


def _select_files(tree: list[dict[str, Any]]) -> tuple[list[str], list[str]]:
    candidates: list[str] = []
    omitted: list[str] = []
    for entry in tree:
        path = str(entry.get("path", ""))
        if entry.get("type") == "commit":
            continue
        if entry.get("type") == "blob" and not any(
            part in path.lower()
            for part in (
                "node_modules/",
                ".next/",
                "dist/",
                "build/",
                "coverage/",
                "vendor/",
                ".venv/",
            )
        ):
            if SENSITIVE_PATH(path) or HIGH_SIGNAL_PATH(path):
                candidates.append(path)
            else:
                omitted.append(path)
    candidates.sort(key=_priority)
    return candidates[: settings.GITHUB_MAX_FILES], omitted + candidates[
        settings.GITHUB_MAX_FILES :
    ]


def SENSITIVE_PATH(path: str) -> bool:
    return bool(
        re.search(
            r"(^|/)(\.env(?:\.|$)|.*\.(pem|key|p12|pfx)$|id_rsa(?:\.|$)|.*credentials?.*)",
            path,
            re.I,
        )
    )


def HIGH_SIGNAL_PATH(path: str) -> bool:
    return bool(
        re.search(
            r"(?i)(readme|package\.json|lock|pyproject|requirements|poetry|pom\.xml|build\.gradle|docker|\.gitmodules|\.ya?ml|\.json$|\.(ts|tsx|js|jsx|py|java|go|rs)$)",
            path,
        )
    )


def _parse_submodules(text: str, tree: list[dict[str, Any]]) -> list[dict[str, Any]]:
    blocks: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("[submodule "):
            if current:
                blocks.append(current)
            current = {"name": line.split('"', 2)[1] if '"' in line else "submodule"}
        elif current and "=" in line:
            key, value = [part.strip() for part in line.split("=", 1)]
            if key in {"path", "url"}:
                current[key] = value
    if current:
        blocks.append(current)
    by_path = {
        str(item.get("path")): str(item.get("sha", ""))
        for item in tree
        if item.get("type") == "commit"
    }
    return [
        {
            "path": block.get("path", ""),
            "name": block.get("name", "submodule"),
            "url": block.get("url"),
            "sha": by_path.get(block.get("path", ""), "unknown"),
            "accessible": False,
            "role": "other",
        }
        for block in blocks
        if block.get("path")
    ]


def _technologies(
    paths: list[str], texts: dict[str, str]
) -> tuple[dict[str, list[str]], list[Evidence]]:
    result: dict[str, list[str]] = {}
    evidence: list[Evidence] = []
    joined_paths = "\n".join(paths).lower()
    joined_text = "\n".join(texts.values()).lower()
    for category, rules in _TECH_RULES.items():
        values: list[str] = []
        for marker, technology in rules:
            if marker.lower() in joined_paths or marker.lower() in joined_text:
                if technology not in values:
                    values.append(technology)
                    match_path = next(
                        (path for path in paths if marker.lower() in path.lower()),
                        paths[0] if paths else "repository tree",
                    )
                    evidence.append(
                        Evidence(
                            path=match_path,
                            claim=f"{technology} is present in the repository evidence.",
                            confidence="verified",
                        )
                    )
        if values:
            result[category] = values
    return result, evidence


async def analyze(db: AsyncSession, data: AnalyzeRepositoryIn) -> ProjectStudioDraft:
    repository = normalize_repository_url(data.repository_url)
    client = GitHubClient()
    metadata = await client.repository(repository)
    summary = _summary(metadata)
    if summary.visibility == "private" and not data.privacy_consent:
        # Metadata-only analysis is explicitly supported without consent.
        tree: list[dict[str, Any]] = []
        source_sha = "metadata-only"
        warnings = [
            "Private repository contents were not read. Give explicit consent before "
            "sending contents to an external AI provider."
        ]
    else:
        tree = await client.tree(repository, summary.default_branch)
        source_sha = await client.latest_commit(repository, summary.default_branch)
        warnings = []
    paths, omitted = _select_files(tree)
    texts: dict[str, str] = {}
    redacted: list[str] = []
    media: list[dict[str, str]] = []
    if data.privacy_consent or summary.visibility == "public":
        for path in paths:
            if SENSITIVE_PATH(path):
                redacted.append(path)
                continue
            if re.search(r"(?i)\.(png|jpe?g|webp|gif|svg|mp4|webm)$", path):
                media.append(
                    {
                        "path": path,
                        "url": f"https://raw.githubusercontent.com/{repository.owner}/{repository.name}/{summary.default_branch}/{path}",
                    }
                )
                continue
            content = await client.file(repository, path, summary.default_branch)
            if content is None:
                continue
            safe, changed = redact_content(path, content)
            if safe is not None:
                texts[path] = safe[: settings.GITHUB_MAX_BYTES]
            if changed:
                redacted.append(path)
    submodules = _parse_submodules(texts.get(".gitmodules", ""), tree)
    technologies, evidence = _technologies(paths, texts)
    analysis = RepositoryAnalysis(
        repository=summary,
        source_sha=source_sha,
        files_scanned=list(texts) if texts else paths,
        omitted_files=omitted,
        truncated=bool(omitted),
        redacted_files=redacted,
        technologies=technologies,
        architecture=["Repository structure and high-signal configuration were inspected."],
        features=[],
        media=media[:40],
        submodules=[SubmoduleEvidence.model_validate(item) for item in submodules],
        evidence=evidence,
        warnings=warnings,
    )
    draft = ProjectStudioDraft(
        id=uuid.uuid4().hex,
        repository_url=repository.url,
        source_sha=source_sha,
        status="analyzed",
        analysis=analysis.model_dump(mode="json", by_alias=True),
        evidence=[item.model_dump(mode="json", by_alias=True) for item in evidence],
        privacy_consent=data.privacy_consent,
    )
    db.add(draft)
    await db.commit()
    await db.refresh(draft)
    return draft


async def list_repositories(
    db: AsyncSession,
    page: int,
    per_page: int,
    search: str,
    sort: str,
    visibility: str,
    include_forks: bool = True,
    include_archived: bool = True,
) -> RepositoryPage:
    items, total = await GitHubClient().list_repositories(
        page, per_page, search, sort, visibility, include_forks, include_archived
    )
    urls = [str(item.get("html_url", "")).rstrip("/") for item in items]
    imported: dict[str, tuple[int, str]] = {}
    if urls:
        rows = await db.scalars(select(Project))
        for row in rows:
            if row.repo_url:
                imported[str(row.repo_url).rstrip("/")] = (row.id, row.slug)
            for repository in row.repositories or []:
                if repository.get("url"):
                    imported[str(repository["url"]).rstrip("/")] = (row.id, row.slug)
    summaries = []
    for item in items:
        current = _summary(item)
        match = imported.get(str(current.html_url).rstrip("/"))
        summaries.append(
            current.model_copy(
                update={
                    "imported_project_id": match[0] if match else None,
                    "imported_project_slug": match[1] if match else None,
                }
            )
        )
    return RepositoryPage(
        items=summaries,
        page=page,
        per_page=per_page,
        has_next=len(items) >= per_page or (total is not None and page * per_page < total),
    )


def _content_from_analysis(analysis: RepositoryAnalysis) -> StudioContent:
    repo = analysis.repository
    tech = {key: values for key, values in analysis.technologies.items()}
    evidence = analysis.evidence
    return StudioContent(
        title=repo.name.replace("-", " ").replace("_", " ").title(),
        slug=slugify(repo.name),
        category=next(iter(tech), "Software project"),
        year=str((repo.updated_at or datetime.now(UTC)).year),
        headline=repo.description or f"A production project built in {repo.name}.",
        summary=repo.description
        or "A software project documented from verified repository evidence.",
        seo_description=repo.description[:155] if repo.description else "",
        keywords=[value for values in tech.values() for value in values][:12],
        brief={"overview": repo.description or "", "purpose": "", "users": ""},
        architecture=analysis.architecture
        and [{"title": "Repository architecture", "body": analysis.architecture[0]}]
        or [],
        features=analysis.features,
        tech_stack=tech,
        links={"github": str(repo.html_url)},
        case_study={
            "problem": "",
            "approach": analysis.architecture[0] if analysis.architecture else "",
            "results": [],
        },
        evidence=evidence,
    )


async def _ai_generate(analysis: RepositoryAnalysis) -> AIGeneration:
    return await generate_with_fallback(analysis)


def _studio_content(result: AIGeneration, analysis: RepositoryAnalysis) -> StudioContent:
    """Convert provider output while retaining only deterministic provenance."""
    payload = result.content.model_dump(mode="json", by_alias=True)
    tech_groups = payload.pop("techStack", [])
    payload["techStack"] = {
        str(item["category"]): list(item["technologies"])
        for item in tech_groups
        if item.get("category")
    }
    payload["evidence"] = [
        item.model_dump(mode="json", by_alias=True) for item in analysis.evidence
    ]
    payload["slug"] = slugify(str(payload.get("slug") or payload.get("title") or "project"))
    payload.setdefault("links", {})["github"] = str(analysis.repository.html_url)
    return StudioContent.model_validate(payload)


def draft_out(row: ProjectStudioDraft) -> StudioDraftOut:
    return StudioDraftOut(
        id=row.id,
        project_id=row.project_id,
        repository_url=row.repository_url,
        source_sha=row.source_sha,
        status=row.status,
        analysis=RepositoryAnalysis.model_validate(row.analysis),
        content=StudioContent.model_validate(row.content) if row.content else None,
        evidence=[Evidence.model_validate(item) for item in row.evidence or []],
        template=row.template,
        media_layout=row.media_layout,
        privacy_consent=row.privacy_consent,
        provider=row.provider,
        model=row.model,
        provider_failures=row.provider_failures or [],
        token_usage=row.token_usage,
        error=row.error,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


async def generate(db: AsyncSession, data: GenerateDraftIn) -> ProjectStudioDraft:
    row = await db.get(ProjectStudioDraft, data.draft_id)
    if row is None:
        raise GitHubError("Studio draft not found.", 404)
    analysis = RepositoryAnalysis.model_validate(row.analysis)
    if analysis.repository.visibility == "private" and not (
        data.privacy_consent or row.privacy_consent
    ):
        raise GitHubError(
            "Explicit consent is required before sending private repository evidence to Gemini.",
            428,
        )
    if row.status == "generating":
        raise GitHubError(
            "Generation is already in progress for this draft. Retry after it finishes.",
            409,
            code="generation_in_progress",
        )
    row.status = "generating"
    row.error = None
    await db.commit()
    # The request can wait on an external provider for tens of seconds. The
    # committed status lets this session release its DB connection before that
    # wait; the row is reloaded for the short result transaction below.
    await db.close()
    try:
        result = await _ai_generate(analysis)
    except GitHubError as exc:
        failed = await db.get(ProjectStudioDraft, data.draft_id)
        if failed is not None:
            failed.status = "failed"
            failed.error = str(exc)
            await db.commit()
        raise
    row = await db.get(ProjectStudioDraft, data.draft_id)
    if row is None:
        raise GitHubError("Studio draft disappeared during generation.", 409, code="draft_lost")
    content = _studio_content(result, analysis)
    row.content = content.model_dump(mode="json", by_alias=True)
    row.status = "review"
    row.provider = getattr(result, "provider", "gemini")
    row.model = getattr(result, "model", settings.GEMINI_MODEL)
    row.provider_failures = [failure.__dict__ for failure in getattr(result, "failures", [])]
    row.token_usage = result.token_usage
    row.privacy_consent = row.privacy_consent or data.privacy_consent
    await db.commit()
    await db.refresh(row)
    return row


async def update_draft(db: AsyncSession, draft_id: str, data: UpdateDraftIn) -> ProjectStudioDraft:
    row = await db.get(ProjectStudioDraft, draft_id)
    if row is None:
        raise GitHubError("Studio draft not found.", 404)
    row.content = data.content.model_dump(mode="json", by_alias=True)
    row.template = data.template
    row.media_layout = data.media_layout
    row.status = "review"
    await db.commit()
    await db.refresh(row)
    return row


async def create_project(db: AsyncSession, data: CreateProjectFromDraftIn) -> Project:
    draft = await db.get(ProjectStudioDraft, data.draft_id)
    if draft is None:
        raise GitHubError("Studio draft not found.", 404)
    content = data.content
    analysis = RepositoryAnalysis.model_validate(draft.analysis)
    media = [
        {"kind": "image", "url": item["url"], "alt": item.get("path", content.title)}
        for item in data.media
        if item.get("url", "").startswith("https://")
    ]
    slug = await unique_slug(db, Project.slug, content.slug or slugify(content.title))
    row = Project(
        slug=slug,
        sort_order=1,
        title=content.title,
        category=content.category,
        year=content.year,
        summary=content.summary,
        intro=content.brief.get("overview", ""),
        discover=content.brief.get("purpose", ""),
        explore=content.brief.get("users", ""),
        results=[],
        thumbnail=media[0] if media else None,
        hero=media[0] if media else None,
        gallery=media,
        tech=[value for values in content.tech_stack.values() for value in values],
        live_url=None,
        repo_url=content.links.get("github"),
        featured=False,
        published=data.publish and bool(media),
        template=data.template,
        template_config={"mediaLayout": data.media_layout},
        studio_content=content.model_dump(mode="json", by_alias=True),
        seo={"description": content.seo_description, "keywords": content.keywords},
        repositories=[
            {
                "url": str(analysis.repository.html_url),
                "name": analysis.repository.name,
                "owner": analysis.repository.owner,
                "role": data.repository_roles.get(str(analysis.repository.html_url), "primary"),
                "primary": True,
                "visibility": analysis.repository.visibility,
                "language": analysis.repository.language,
                "stars": analysis.repository.stars,
            }
        ],
    )
    db.add(row)
    await db.flush()
    repo = analysis.repository
    db.add(
        ProjectRepository(
            project_id=row.id,
            url=str(repo.html_url),
            owner=repo.owner,
            name=repo.name,
            role=data.repository_roles.get(str(repo.html_url), "primary"),
            primary=True,
            visibility=repo.visibility,
            repo_metadata=repo.model_dump(mode="json", by_alias=True),
            submodules=[
                item.model_dump(mode="json", by_alias=True) for item in analysis.submodules
            ],
            source_sha=draft.source_sha,
        )
    )
    draft.project_id = row.id
    draft.content = content.model_dump(mode="json", by_alias=True)
    draft.template = data.template
    draft.media_layout = data.media_layout
    draft.status = "published" if data.publish else "saved"
    await db.commit()
    await db.refresh(row)
    await flush_content(
        tags=["projects", f"project:{row.slug}"],
        paths=["/", "/projects", f"/projects/{row.slug}"],
    )
    return row


async def associations(db: AsyncSession, project_id: int) -> list[RepositoryAssociationOut]:
    rows = await db.scalars(
        select(ProjectRepository)
        .where(ProjectRepository.project_id == project_id)
        .order_by(ProjectRepository.primary.desc(), ProjectRepository.id)
    )
    return [
        RepositoryAssociationOut(
            id=row.id,
            project_id=row.project_id,
            url=row.url,
            owner=row.owner,
            name=row.name,
            role=row.role,
            primary=row.primary,
            visibility=row.visibility,
            metadata=row.repo_metadata,
            submodules=[SubmoduleEvidence.model_validate(item) for item in row.submodules or []],
            source_sha=row.source_sha,
        )
        for row in rows
    ]
