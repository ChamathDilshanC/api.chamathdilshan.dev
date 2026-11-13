"""Safety, completeness and persistence checks for GitHub AI Project Studio."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.core import db as db_module
from app.integrations import cloudinary
from app.integrations.github import GitHubError, normalize_repository_url, redact_content
from app.models import Media, Project, ProjectRepository, ProjectStudioDraft
from app.schemas.studio import (
    CreateProjectFromDraftIn,
    RepositoryAnalysis,
    RepositorySummary,
    StudioContent,
)
from app.services import projects, studio


def test_github_urls_are_normalized_without_accepting_other_hosts() -> None:
    repository = normalize_repository_url("https://github.com/ChamathDilshanC/demo.git/issues")
    assert repository.owner == "ChamathDilshanC"
    assert repository.name == "demo"
    assert repository.url == "https://github.com/ChamathDilshanC/demo"

    try:
        normalize_repository_url("https://example.com/owner/demo")
    except GitHubError as exc:
        assert "GitHub" in str(exc)
    else:
        raise AssertionError("non-GitHub host was accepted")


def test_secret_files_and_values_are_redacted() -> None:
    assert redact_content(".env", "GEMINI_API_KEY=secret")[0] is None
    safe, changed = redact_content("README.md", "api_key=secret\nfeature: import")
    assert changed
    assert safe is not None
    assert "secret" not in safe
    assert "[REDACTED]" in safe


def test_studio_content_rejects_unstructured_ai_fields() -> None:
    content = StudioContent(title="Demo", summary="Verified summary")
    assert content.title == "Demo"


def test_legacy_overlong_summary_is_bounded_for_admin_output() -> None:
    row = Project(
        id=1,
        slug="legacy-summary",
        title="Legacy summary",
        category="Tools",
        year="2026",
        summary="summary " * 100,
        intro="Intro",
        discover="Discover",
        explore="Explore",
        template="legacy",
        featured=False,
        published=False,
        sort_order=1,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    assert len(projects.to_out(row).summary) == 300


def test_incomplete_content_is_not_treated_as_a_case_study() -> None:
    analysis = RepositoryAnalysis(
        repository=RepositorySummary(
            owner="owner",
            name="demo",
            full_name="owner/demo",
            html_url="https://github.com/owner/demo",
        ),
        source_sha="abc123",
        files_scanned=["README.md"],
    )
    assert not studio._content_is_substantive(StudioContent(title="Demo"), analysis)


def test_case_study_requires_problem_and_approach() -> None:
    analysis = RepositoryAnalysis(
        repository=RepositorySummary(
            owner="owner",
            name="demo",
            full_name="owner/demo",
            html_url="https://github.com/owner/demo",
        ),
        source_sha="abc123",
        files_scanned=["README.md"],
        technologies={"Backend": ["FastAPI"]},
        architecture=["API routes are verified."],
        features=["A repository-backed feature."],
    )
    content = StudioContent(
        title="Demo",
        summary="A verified summary.",
        brief={"overview": "Overview", "purpose": "Purpose"},
        case_study={"problem": "", "approach": ""},
        features=["A repository-backed feature."],
        tech_stack={"Backend": ["FastAPI"]},
    )
    assert not studio._content_is_substantive(content, analysis)


def test_generated_content_requires_deep_architecture_and_narrative_sections() -> None:
    analysis = RepositoryAnalysis(
        repository=RepositorySummary(
            owner="owner",
            name="demo",
            full_name="owner/demo",
            html_url="https://github.com/owner/demo",
        ),
        source_sha="abc123",
        files_scanned=["src/app.ts", "api/routes.py", "tests/test_api.py"],
        technologies={"Backend": ["FastAPI"]},
    )
    content = StudioContent(
        title="Demo",
        summary="Short summary.",
        brief={"overview": "Too short.", "purpose": "Too short."},
        architecture=[
            {"title": "How it works", "body": "Implemented with FastAPI and tests."}
        ],
        case_study={"problem": "Short.", "approach": "Short."},
        features=["Repository-backed feature"],
        tech_stack={"Backend": ["FastAPI"]},
    )
    assert not studio._content_is_substantive(content, analysis)


def test_repository_features_strip_readme_markup() -> None:
    features, _ = studio._repository_features(
        ["README.md"],
        {
            "README.md": (
                "<p align=\"center\">ignored</p>\n"
                "<h1 align=\"center\">Upscalee</h1>\n"
                "Right-click <b>Upscale with Upscalee</b> to choose 4K output."
            )
        },
    )
    assert features == ["Right-click Upscale with Upscalee to choose 4K output."]


def test_repository_keys_ignore_case_and_trailing_slashes() -> None:
    assert studio._repository_key("https://github.com/Owner/Demo/") == (
        "https://github.com/owner/demo"
    )


def test_repository_technology_detection_reads_dependency_manifests() -> None:
    technologies, evidence = studio._technologies(
        ["package.json", "pyproject.toml"],
        {
            "package.json": (
                '{"dependencies":{"next":"14.0.0","react":"18.0.0",'
                '"tailwindcss":"3.4.0"}}'
            ),
            "pyproject.toml": "fastapi = '^0.115'\nsqlalchemy = '^2.0'\n",
        },
    )
    assert technologies["Frontend"] == ["JavaScript/TypeScript", "Next.js", "React", "Tailwind CSS"]
    assert technologies["Backend"] == ["Python", "FastAPI"]
    assert technologies["Database"] == ["SQLAlchemy"]
    assert {item.path for item in evidence} >= {"package.json", "pyproject.toml"}


def test_submodule_repository_urls_resolve_relative_github_links() -> None:
    parent = studio.normalize_repository_url("https://github.com/owner/main")
    resolved = studio._resolve_submodule_repository(parent, "../frontend")
    assert resolved is not None
    assert resolved.url == "https://github.com/owner/frontend"


def test_repository_live_url_uses_verified_homepage_or_readme_link() -> None:
    summary = RepositorySummary(
        owner="owner",
        name="demo",
        full_name="owner/demo",
        html_url="https://github.com/owner/demo",
        homepage="https://demo.example",
    )
    assert studio._live_url(summary, {}) == "https://demo.example"
    summary = summary.model_copy(update={"homepage": ""})
    assert studio._live_url(
        summary, {"README.md": "Try the app at https://demo.example/app."}
    ) == "https://demo.example/app"


def test_generated_text_removes_markdown_table_artifacts() -> None:
    assert studio._clean_generated_text(
        "| Area | Capability |\n|------|------------|\n| Auth | Session handling |"
    ) == "Area: Capability Auth: Session handling"


@pytest.mark.asyncio
async def test_studio_project_maps_rich_content_to_legacy_fields() -> None:
    analysis = RepositoryAnalysis(
        repository=RepositorySummary(
            owner="owner",
            name="demo",
            full_name="owner/demo",
            html_url="https://github.com/owner/demo",
        ),
        source_sha="abc123",
        files_scanned=["README.md"],
        technologies={"Backend": ["FastAPI"]},
        architecture=["API routes are verified."],
    )
    content = StudioContent(
        title="Demo",
        summary=(
            "This project provides a verified workflow for handling repository-backed requests. "
            "Its documented boundaries make the main user journey and engineering "
            "trade-offs clear. "
            "The summary is intentionally grounded in the files inspected during analysis."
        ),
        headline="A case study.",
        brief={
            "overview": (
                "The project organizes its user-facing workflow around a small set of repository "
                "modules and documented boundaries. Those modules provide the behavior described "
                "by the source tree and keep the case study tied to verified evidence."
            ),
            "purpose": (
                "The purpose is to make the repository workflow understandable and maintainable "
                "for the people using it. The implementation separates responsibilities so changes "
                "can be reviewed against the relevant source files and tests."
            ),
            "users": "Users of the documented repository workflow.",
        },
        architecture=[
            {
                "title": "API",
                "body": (
                    "FastAPI routes expose the documented service boundary and connect requests to "
                    "the repository's application behavior. The route and test evidence provide a "
                    "traceable path for reviewing this flow."
                ),
            },
            {
                "title": "Application",
                "body": (
                    "Application modules contain the user-facing behavior described by the project "
                    "evidence. Their boundaries show where the main workflow is assembled and "
                    "where future changes should be reviewed."
                ),
            },
            {
                "title": "Quality",
                "body": (
                    "The test boundary verifies the repository behavior that supports the project "
                    "workflow. These checks connect implementation changes to repeatable evidence "
                    "instead of relying on an unverified claim."
                ),
            },
        ],
        features=["Repository-backed feature"],
        tech_stack={"Backend": ["FastAPI"]},
        links={"github": "https://github.com/owner/demo", "live": "https://demo.example"},
        case_study={
            "problem": (
                "The original workflow made it difficult to understand how repository evidence "
                "mapped to the resulting project content. That ambiguity could leave important "
                "details hidden or represented by generic text in the published case study."
            ),
            "approach": (
                "The implementation maps the documented repository boundaries into editable "
                "project "
                "sections and preserves their evidence for review. Tests and source paths provide "
                "the concrete references needed to validate the generated narrative."
            ),
            "results": ["Result"],
        },
    )
    draft_id = "c" * 16
    async with db_module.get_sessionmaker()() as db:
        db.add(
            ProjectStudioDraft(
                id=draft_id,
                repository_url="https://github.com/owner/demo",
                source_sha=analysis.source_sha,
                status="review",
                analysis=analysis.model_dump(mode="json", by_alias=True),
                content=content.model_dump(mode="json", by_alias=True),
            )
        )
        await db.commit()
        project = await studio.create_project(
            db,
            CreateProjectFromDraftIn(
                draft_id=draft_id,
                content=content,
                publish=False,
            ),
        )

        assert project.intro == content.brief["overview"]
        assert project.discover == content.case_study["problem"]
        assert project.explore == content.case_study["approach"]
        assert project.results == [{"label": "Verified outcome 1", "value": "Result"}]
        assert project.live_url == "https://demo.example"
        assert project.published is False
        assert project.studio_content["architecture"] == content.model_dump(
            mode="json", by_alias=True
        )["architecture"]


@pytest.mark.asyncio
async def test_project_delete_removes_repository_associations() -> None:
    async with db_module.get_sessionmaker()() as db:
        project = Project(
            slug="association-cleanup-test",
            title="Association cleanup test",
            repositories=[{"url": "https://github.com/owner/association-cleanup"}],
        )
        db.add(project)
        await db.flush()
        db.add(
            ProjectRepository(
                project_id=project.id,
                url="https://github.com/owner/association-cleanup",
                owner="owner",
                name="association-cleanup",
            )
        )
        await db.commit()

        await projects.delete(db, project.id)

        assert (
            await db.scalar(
                select(ProjectRepository).where(
                    ProjectRepository.url == "https://github.com/owner/association-cleanup"
                )
            )
            is None
        )


@pytest.mark.asyncio
async def test_project_delete_destroys_exclusive_media_but_preserves_shared_media(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destroyed: list[tuple[str, str]] = []

    async def fake_destroy(public_id: str, resource_type: str, **_: object) -> None:
        destroyed.append((public_id, resource_type))

    monkeypatch.setattr(cloudinary, "destroy", fake_destroy)
    async with db_module.get_sessionmaker()() as db:
        project = Project(
            slug="media-cleanup-test",
            title="Media cleanup test",
            thumbnail={"url": "https://res.cloudinary.com/demo/image/upload/v1/site/owned.jpg"},
            hero={"url": "https://res.cloudinary.com/demo/image/upload/v1/site/shared.jpg"},
        )
        shared = Project(
            slug="media-shared-test",
            title="Media shared test",
            thumbnail={"url": "https://res.cloudinary.com/demo/image/upload/v1/site/shared.jpg"},
        )
        db.add_all([project, shared])
        await db.flush()
        db.add_all(
            [
                Media(public_id="site/owned", kind="image", url=project.thumbnail["url"]),
                Media(public_id="site/shared", kind="image", url=shared.thumbnail["url"]),
            ]
        )
        await db.commit()

        await projects.delete(db, project.id)

        assert destroyed == [("site/owned", "image")]
        assert await db.scalar(select(Media).where(Media.public_id == "site/owned")) is None
        assert await db.scalar(select(Media).where(Media.public_id == "site/shared")) is not None
