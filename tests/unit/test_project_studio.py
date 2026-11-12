"""Safety, completeness and persistence checks for GitHub AI Project Studio."""

import pytest
from sqlalchemy import select

from app.core import db as db_module
from app.integrations.github import GitHubError, normalize_repository_url, redact_content
from app.models import Project, ProjectRepository, ProjectStudioDraft
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
        summary="A verified summary.",
        headline="A case study.",
        brief={"overview": "Overview", "purpose": "Purpose", "users": "Users"},
        architecture=[{"title": "API", "body": "FastAPI routes."}],
        features=["Repository-backed feature"],
        tech_stack={"Backend": ["FastAPI"]},
        links={"github": "https://github.com/owner/demo", "live": "https://demo.example"},
        case_study={"problem": "Problem", "approach": "Approach", "results": ["Result"]},
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

        assert project.intro == "Overview"
        assert project.discover == "Problem"
        assert project.explore == "Approach"
        assert project.results == [{"label": "Verified outcome 1", "value": "Result"}]
        assert project.live_url == "https://demo.example"
        assert project.published is False
        assert project.studio_content["architecture"] == [
            {"title": "API", "body": "FastAPI routes."}
        ]


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
