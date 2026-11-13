"""Repository analysis and AI draft orchestration.

The analyzer is deterministic and bounded. Gemini only receives a compact,
evidence-labelled summary, never credentials, binary files, or an unbounded
repository dump.
"""

import html
import re
import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import HttpUrl
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import flush_content
from app.core.config import settings
from app.integrations.ai_fallback import AIGeneration, generate_with_fallback
from app.integrations.github import (
    GitHubClient,
    GitHubError,
    GitHubRepository,
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
from app.services.projects import cms_summary

_GITMODULE = re.compile(
    r"^\s*\[submodule \"(?P<name>[^\"]+)\"\]\s*$|^\s*(?P<key>path|url)\s*=\s*(?P<value>.+?)\s*$",
    re.MULTILINE,
)
_TECH_RULES = {
    "Frontend": [
        ("package.json", "JavaScript/TypeScript"),
        ("next.config", "Next.js"),
        ("vite.config", "Vite"),
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
_DEPENDENCY_RULES = (
    (r'"next"\s*:', "Frontend", "Next.js"),
    (r'"react"\s*:', "Frontend", "React"),
    (r'"(?:typescript|@types/node)"\s*:', "Frontend", "TypeScript"),
    (r'"vite"\s*:', "Frontend", "Vite"),
    (r'"(?:tailwindcss|@tailwindcss/)', "Frontend", "Tailwind CSS"),
    (r"(?i)\bfastapi\b", "Backend", "FastAPI"),
    (r"(?i)\bdjango\b", "Backend", "Django"),
    (r"(?i)\bflask\b", "Backend", "Flask"),
    (r"(?i)\bsqlalchemy\b", "Database", "SQLAlchemy"),
    (r"(?i)\balembic\b", "Database", "Alembic"),
    (r"(?i)(?:@aws-sdk/|['\"]boto3['\"])", "Cloud", "AWS SDK"),
    (r"(?i)<targetframework[^>]*>net", "Backend", ".NET"),
    (r"(?i)<packagereference[^>]+include=['\"]avalonia", "Frontend", "Avalonia"),
    (r"(?i)\bffmpeg\b", "Media", "FFmpeg"),
    (r"(?i)\b(cargo\.toml|rustc|rust-lang)\b", "Languages", "Rust"),
    (r"(?i)^module\s+", "Languages", "Go"),
)


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
        html_url=HttpUrl(str(item.get("html_url") or f"https://github.com/{owner}/{name}")),
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
        homepage=str(item.get("homepage") or ""),
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
    for pattern, category, technology in _DEPENDENCY_RULES:
        dependency_path: str | None = next(
            (path for path, text in texts.items() if re.search(pattern, text, re.I | re.M)),
            next((path for path in paths if re.search(pattern, path, re.I | re.M)), None),
        )
        if dependency_path:
            values = result.setdefault(category, [])
            if technology not in values:
                values.append(technology)
                evidence.append(
                    Evidence(
                        path=dependency_path,
                        claim=f"{technology} is present in the repository evidence.",
                        confidence="verified",
                    )
                )
    return result, evidence


def _merge_technologies(
    target: dict[str, list[str]], additions: dict[str, list[str]]
) -> None:
    for category, values in additions.items():
        current = target.setdefault(category, [])
        for value in values:
            if value not in current:
                current.append(value)


def _live_url(summary: RepositorySummary, texts: dict[str, str]) -> str:
    homepage = summary.homepage.strip()
    if homepage.startswith(("http://", "https://")) and "github.com" not in homepage.lower():
        return homepage
    for text in texts.values():
        for candidate in re.findall(r"https?://[^\s)>\"]+", text):
            candidate = str(candidate)
            candidate = candidate.rstrip(".,;")
            lower = candidate.lower()
            if "github.com" not in lower and "shields.io" not in lower:
                return candidate
    return ""


def _clean_generated_text(value: str) -> str:
    lines: list[str] = []
    for raw_line in value.splitlines():
        line = raw_line.strip()
        if not line or re.fullmatch(r"\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?", line):
            continue
        if "|" in line:
            cells = [cell.strip() for cell in line.strip("|").split("|") if cell.strip()]
            line = ": ".join(cells)
        line = re.sub(r"^\s*#{1,6}\s*", "", line)
        line = re.sub(r"[*_`]+", "", line)
        line = re.sub(r"\s+", " ", line).strip()
        if line:
            lines.append(line)
    return " ".join(lines)


def _sanitize_studio_payload(value: Any) -> Any:
    if isinstance(value, str):
        return _clean_generated_text(value)
    if isinstance(value, list):
        return [_sanitize_studio_payload(item) for item in value]
    if isinstance(value, dict):
        return {key: _sanitize_studio_payload(item) for key, item in value.items()}
    return value


def _submodule_role(path: str, name: str) -> str:
    value = f"{path} {name}".lower()
    if any(token in value for token in ("frontend", "client", "web", "ui")):
        return "frontend"
    if any(token in value for token in ("backend", "server", "api", "service")):
        return "backend"
    return "other"


def _resolve_submodule_repository(
    parent: GitHubRepository, url: str | None
) -> GitHubRepository | None:
    if not url:
        return None
    value = url.strip()
    if value.startswith("git@github.com:"):
        value = f"https://github.com/{value.removeprefix('git@github.com:')}"
    elif value.startswith("../"):
        value = f"https://github.com/{parent.owner}/{value.removeprefix('../')}"
    elif not value.startswith(("http://", "https://")):
        value = f"https://github.com/{parent.owner}/{value}"
    try:
        return normalize_repository_url(value)
    except GitHubError:
        return None


def _repository_features(
    paths: list[str], texts: dict[str, str]
) -> tuple[list[str], list[Evidence]]:
    """Extract conservative feature evidence for the AI prompt and fallback draft."""
    features: list[str] = []
    evidence: list[Evidence] = []
    readme_path = next((path for path in texts if path.lower() in {"readme", "readme.md"}), None)
    if readme_path:
        readme_lines = texts[readme_path].splitlines()
        for index, line in enumerate(readme_lines):
            if re.match(r"^\s*<(?:p|img|h[1-6]|br)\b", line, re.I):
                continue
            next_line = readme_lines[index + 1].strip() if index + 1 < len(readme_lines) else ""
            if "|" in line and re.fullmatch(
                r"\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?", next_line
            ):
                continue
            value = re.sub(r"^\s*[-*]\s+", "", line).strip()
            if re.fullmatch(r"\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?", value):
                continue
            if "|" in value:
                cells = [cell.strip() for cell in value.strip("|").split("|") if cell.strip()]
                value = ": ".join(cells)
            value = html.unescape(re.sub(r"<[^>]+>", "", value))
            value = re.sub(r"[*_`]+", "", value)
            value = re.sub(r"\s+", " ", value).strip()
            if (
                value
                and len(value) >= 12
                and len(value) <= 180
                and not value.startswith("#")
                and not re.match(r"(?i)^(installation|getting started|usage|license)\b", value)
                and value not in features
            ):
                features.append(value)
                evidence.append(
                    Evidence(
                        path=readme_path,
                        claim=f"README documents: {value}",
                        confidence="verified",
                    )
                )
            if len(features) == 8:
                break
    if not features:
        for path in paths:
            if re.search(r"(?i)(auth|api|dashboard|checkout|search|upload|middleware|route)", path):
                feature = f"{path.rsplit('/', 1)[-1]} is implemented in the repository."
                features.append(feature)
                evidence.append(Evidence(path=path, claim=feature, confidence="inferred"))
            if len(features) == 5:
                break
    return features, evidence


def _repository_architecture(
    paths: list[str], texts: dict[str, str], technologies: dict[str, list[str]]
) -> list[str]:
    """Build architecture evidence from repository boundaries, not README prose."""
    layers = (
        ("Application surface", r"(^|/)(app|src|pages|routes|components|frontend|client)(/|$)"),
        (
            "Domain and data",
            r"(^|/)(api|server|services|models|database|db|schema|migrations)(/|$)",
        ),
        (
            "Delivery and quality",
            r"(^|/)(\.github|tests?|specs?|docker|infra|terraform|scripts?)(/|$)",
        ),
    )
    architecture: list[str] = []
    for label, pattern in layers:
        matches = [path for path in paths if re.search(pattern, path, re.I)]
        if not matches:
            continue
        examples = ", ".join(matches[:6])
        architecture.append(
            f"{label} is represented by {examples}. "
            f"This boundary shows where the repository keeps {label.lower()} responsibilities "
            "and gives the implementation path to follow when tracing the project flow."
        )
    if len(architecture) < 3:
        remaining = [path for path in paths if path not in "\n".join(architecture)]
        for index, chunk in enumerate(
            [remaining[:6], remaining[6:12], remaining[12:18]], start=1
        ):
            if chunk:
                architecture.append(
                    f"Repository boundary {index} is represented by {', '.join(chunk)}. "
                    "These high-signal files provide the concrete source locations needed "
                    "to trace how this part of the project is assembled."
                )
            if len(architecture) == 3:
                break
    if len(architecture) < 3:
        technology_summary = ", ".join(
            f"{category}: {', '.join(values)}"
            for category, values in technologies.items()
        )
        architecture.append(
            "Verified technology boundaries include "
            f"{technology_summary or 'the scanned repository files'}. "
            "These detected boundaries are the available evidence for the implementation flow; "
            "unsupported runtime details must remain unclaimed."
        )
    return architecture[:6]


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
    features, feature_evidence = _repository_features(paths, texts)
    evidence.extend(feature_evidence)
    architecture = _repository_architecture(paths, texts, technologies)
    live_url = _live_url(summary, texts)
    if not data.include_submodules:
        submodules = []
    for submodule in submodules[:4]:
        submodule["role"] = _submodule_role(
            str(submodule.get("path", "")), str(submodule.get("name", ""))
        )
        submodule_repository = _resolve_submodule_repository(
            repository, submodule.get("url")
        )
        if not submodule_repository or not submodule.get("sha"):
            warnings.append(
                f"Submodule {submodule.get('path', 'unknown')} has no accessible GitHub URL."
            )
            continue
        try:
            submodule_metadata = await client.repository(submodule_repository)
            submodule_summary = _summary(submodule_metadata)
            submodule_tree = await client.tree(
                submodule_repository, str(submodule.get("sha"))
            )
            submodule_paths, _ = _select_files(submodule_tree)
            submodule_texts: dict[str, str] = {}
            for submodule_path in submodule_paths:
                if SENSITIVE_PATH(submodule_path):
                    continue
                content = await client.file(
                    submodule_repository, submodule_path, str(submodule.get("sha"))
                )
                if content is None:
                    continue
                safe, _ = redact_content(submodule_path, content)
                if safe is not None:
                    submodule_texts[submodule_path] = safe[: settings.GITHUB_MAX_BYTES]
            submodule_technologies, submodule_evidence = _technologies(
                submodule_paths, submodule_texts
            )
            _merge_technologies(technologies, submodule_technologies)
            for item in submodule_evidence:
                item.path = f"{submodule['path']}/{item.path}"
            evidence.extend(submodule_evidence)
            submodule["accessible"] = True
            submodule["url"] = submodule_repository.url
            submodule["source_sha"] = str(submodule.get("sha"))
            submodule["technologies"] = submodule_technologies
            submodule_stack = ", ".join(
                submodule_technologies.get("Frontend", [])
                + submodule_technologies.get("Backend", [])
            ) or "the linked source tree"
            architecture.append(
                f"The {submodule['role']} boundary is provided by the "
                f"{submodule['name']} submodule at {submodule['path']}. "
                f"Its verified repository evidence includes {submodule_stack}, "
                f"which is assembled into the {summary.name} repository at commit "
                f"{submodule['sha'][:12]}."
            )
            if not live_url:
                live_url = _live_url(submodule_summary, submodule_texts)
        except GitHubError as exc:
            warnings.append(
                f"Submodule {submodule.get('path', 'unknown')} could not be analyzed: {exc}"
            )
    analysis = RepositoryAnalysis(
        repository=summary,
        source_sha=source_sha,
        files_scanned=list(texts) if texts else paths,
        omitted_files=omitted,
        truncated=bool(omitted),
        redacted_files=redacted,
        technologies=technologies,
        architecture=architecture,
        features=features,
        media=media[:40],
        submodules=[SubmoduleEvidence.model_validate(item) for item in submodules],
        evidence=evidence,
        warnings=warnings,
        live_url=live_url,
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
        architecture=[
            {"title": f"Architecture boundary {index}", "body": item}
            for index, item in enumerate(analysis.architecture, start=1)
        ],
        features=analysis.features,
        tech_stack=tech,
        links={"github": str(repo.html_url), "live": analysis.live_url},
        case_study={
            "problem": "",
            "approach": " ".join(analysis.architecture[:3]),
            "results": [],
        },
        evidence=evidence,
    )


async def _ai_generate(analysis: RepositoryAnalysis) -> AIGeneration:
    return await generate_with_fallback(analysis)


def _studio_content(result: AIGeneration, analysis: RepositoryAnalysis) -> StudioContent:
    """Convert provider output while retaining only deterministic provenance."""
    payload = _sanitize_studio_payload(
        result.content.model_dump(mode="json", by_alias=True)
    )
    tech_groups = payload.pop("techStack", [])
    generated_technologies = {
        str(item["category"]): [
            value for value in item["technologies"] if str(value).strip().lower() != "frontend"
        ]
        for item in tech_groups
        if item.get("category")
    }
    payload["evidence"] = [
        item.model_dump(mode="json", by_alias=True) for item in analysis.evidence
    ]
    # Provider output is authoritative where it contains substantive content,
    # while deterministic repository evidence prevents a metadata-only draft.
    payload["features"] = payload.get("features") or analysis.features
    payload["architecture"] = payload.get("architecture") or [
        {"title": f"Architecture boundary {index}", "body": item}
        for index, item in enumerate(analysis.architecture, start=1)
    ]
    _merge_technologies(generated_technologies, analysis.technologies)
    payload["techStack"] = generated_technologies
    payload["slug"] = slugify(str(payload.get("slug") or payload.get("title") or "project"))
    payload.setdefault("links", {})["github"] = str(analysis.repository.html_url)
    payload["links"]["live"] = (
        str(payload["links"].get("live") or analysis.live_url or analysis.repository.homepage)
    )
    return StudioContent.model_validate(payload)


def _content_is_substantive(content: StudioContent, analysis: RepositoryAnalysis) -> bool:
    """Reject syntactically valid provider responses that cannot be reviewed."""
    def has_depth(value: object, minimum_words: int = 24) -> bool:
        words = re.findall(r"\b[\w'-]+\b", str(value or ""))
        return len(words) >= minimum_words and len(str(value or "").strip()) >= 130

    brief = content.brief
    case_study = content.case_study
    architecture = [
        item
        for item in content.architecture
        if str(item.get("title", "")).strip() and has_depth(item.get("body", ""), 18)
    ]
    return (
        has_depth(content.summary)
        and has_depth(brief.get("overview", ""))
        and has_depth(brief.get("purpose", ""))
        and has_depth(case_study.get("problem", ""))
        and has_depth(case_study.get("approach", ""))
        and len(architecture) >= 3
        and bool(content.tech_stack or analysis.technologies)
        and bool(
            content.features or content.architecture or analysis.features or analysis.architecture
        )
    )


def _repository_key(value: object) -> str:
    return str(value or "").strip().rstrip("/").lower()


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
    if not _content_is_substantive(content, analysis):
        row.status = "incomplete"
        row.error = (
            "The provider returned an incomplete project case study. "
            "Regenerate the missing sections."
        )
        await db.commit()
        raise GitHubError(row.error, 502, code="incomplete_draft")
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
    row.content = _sanitize_studio_payload(data.content.model_dump(mode="json", by_alias=True))
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
    if draft.status not in {"review", "saved"}:
        raise GitHubError(
            "Review a complete Studio draft before creating a project.",
            409,
            code="draft_not_ready",
        )
    content = StudioContent.model_validate(
        _sanitize_studio_payload(data.content.model_dump(mode="json", by_alias=True))
    )
    analysis = RepositoryAnalysis.model_validate(draft.analysis)
    if not _content_is_substantive(content, analysis):
        raise GitHubError(
            "The Studio draft is incomplete. Add three-line overview, purpose, problem, "
            "approach, and at least three evidence-backed architecture sections.",
            422,
            code="incomplete_draft",
        )
    repository_url = str(analysis.repository.html_url).rstrip("/")
    repository_key = _repository_key(repository_url)
    associations = list(
        await db.scalars(
            select(ProjectRepository).where(ProjectRepository.url.ilike(repository_url))
        )
    )
    project_ids = set(await db.scalars(select(Project.id)))
    orphan_associations = [
        association
        for association in associations
        if association.project_id not in project_ids
    ]
    for association in orphan_associations:
        await db.delete(association)
    if orphan_associations:
        await db.flush()
    existing = next(
        (
            association
            for association in associations
            if association.project_id in project_ids
        ),
        None,
    )
    legacy_projects = await db.scalars(select(Project))
    legacy_match = next(
        (
            project
            for project in legacy_projects
            if _repository_key(project.repo_url) == repository_key
            or any(
                _repository_key(repository.get("url")) == repository_key
                for repository in project.repositories or []
            )
        ),
        None,
    )
    if existing is not None or legacy_match is not None:
        associated_name = (
            legacy_match.title
            if legacy_match is not None
            else f"project #{existing.project_id}" if existing is not None else "another project"
        )
        raise GitHubError(
            f"This repository is already associated with {associated_name}. "
            "Delete that project completely before importing it again.",
            409,
            code="duplicate_repository",
        )
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
        summary=cms_summary(content.summary),
        intro=content.brief.get("overview") or content.headline or content.summary,
        discover=content.case_study.get("problem") or content.brief.get("purpose", ""),
        explore=content.case_study.get("approach") or content.brief.get("users", ""),
        results=[
            {"label": f"Verified outcome {index}", "value": value}
            for index, value in enumerate(
                content.case_study.get("results", [])
                if isinstance(content.case_study.get("results", []), list)
                else [],
                start=1,
            )
        ],
        thumbnail=media[0] if media else None,
        hero=media[0] if media else None,
        gallery=media,
        tech=[value for values in content.tech_stack.values() for value in values],
        live_url=content.links.get("live") or None,
        repo_url=content.links.get("github"),
        featured=False,
        published=bool(data.publish and media),
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
        ]
        + [
            {
                "url": str(item.url),
                "name": item.name,
                "owner": (
                    str(item.url).rstrip("/").split("/")[-2]
                    if len(str(item.url).rstrip("/").split("/")) >= 2
                    else item.name
                ),
                "role": item.role,
                "primary": False,
                "visibility": "public",
                "language": None,
                "stars": 0,
                "submodulePath": item.path,
            }
            for item in analysis.submodules
            if item.url
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
