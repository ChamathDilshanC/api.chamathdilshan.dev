"""Typed contracts for the GitHub AI Project Studio."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field, HttpUrl, model_validator

from app.schemas.common import CamelModel, Slug


class RepositorySummary(CamelModel):
    owner: str
    name: str
    full_name: str
    html_url: HttpUrl
    description: str = ""
    language: str | None = None
    visibility: Literal["public", "private"] = "public"
    stars: int = Field(default=0, ge=0)
    created_at: datetime | None = None
    updated_at: datetime | None = None
    pushed_at: datetime | None = None
    default_branch: str = "main"
    fork: bool = False
    archived: bool = False
    has_readme: bool | None = None
    imported_project_id: int | None = None
    imported_project_slug: str | None = None


class RepositoryPage(CamelModel):
    items: list[RepositorySummary]
    page: int = Field(ge=1)
    per_page: int = Field(ge=1, le=100)
    has_next: bool
    rate_limit_remaining: int | None = None


class SubmoduleEvidence(CamelModel):
    path: str
    name: str
    url: str | None = None
    sha: str
    accessible: bool = False
    role: str = "other"


class Evidence(CamelModel):
    path: str
    claim: str
    confidence: Literal["verified", "inferred", "unknown"] = "verified"
    sha: str | None = None


class RepositoryAnalysis(CamelModel):
    repository: RepositorySummary
    source_sha: str
    files_scanned: list[str]
    omitted_files: list[str] = []
    truncated: bool = False
    redacted_files: list[str] = []
    technologies: dict[str, list[str]] = {}
    architecture: list[str] = []
    features: list[str] = []
    media: list[dict[str, str]] = []
    submodules: list[SubmoduleEvidence] = []
    evidence: list[Evidence] = []
    warnings: list[str] = []


class GeminiBrief(CamelModel):
    overview: str = ""
    purpose: str = ""
    users: str = ""


class GeminiArchitecture(CamelModel):
    title: str = ""
    body: str = ""


class GeminiLinks(CamelModel):
    github: str = ""
    live: str = ""


class GeminiCaseStudy(CamelModel):
    problem: str = ""
    approach: str = ""
    results: list[str] = []


class GeminiTechGroup(CamelModel):
    """Provider-safe representation of one technology category."""

    category: str = ""
    technologies: list[str] = []


class GeminiDraft(CamelModel):
    """Small, provider-compatible response schema used for Gemini structured output.

    Evidence is deliberately excluded: it is copied from the deterministic GitHub
    analysis so the model cannot manufacture provenance.
    """

    title: Annotated[str, Field(min_length=1, max_length=120)]
    slug: str = ""
    category: str = ""
    year: str = ""
    headline: str = ""
    summary: str = ""
    seo_description: str = ""
    keywords: list[str] = []
    brief: GeminiBrief = Field(default_factory=GeminiBrief)
    architecture: list[GeminiArchitecture] = Field(default_factory=list)
    features: list[str] = Field(default_factory=list)
    tech_stack: list[GeminiTechGroup] = Field(default_factory=list)
    ai_usage: list[str] = Field(default_factory=list)
    links: GeminiLinks = Field(default_factory=GeminiLinks)
    case_study: GeminiCaseStudy = Field(default_factory=GeminiCaseStudy)


class StudioContent(CamelModel):
    title: Annotated[str, Field(min_length=1, max_length=120)]
    slug: Slug | None = None
    category: str = ""
    year: str = ""
    headline: str = ""
    summary: str = ""
    seo_description: str = ""
    keywords: list[str] = []
    brief: dict[str, str] = {}
    architecture: list[dict[str, str]] = []
    features: list[str] = []
    tech_stack: dict[str, list[str]] = {}
    ai_usage: list[str] = []
    links: dict[str, str] = {}
    case_study: dict[str, str | list[str]] = {}
    evidence: list[Evidence] = []


class AnalyzeRepositoryIn(CamelModel):
    repository_url: str = Field(min_length=1, max_length=500)
    privacy_consent: bool = False


class GenerateDraftIn(CamelModel):
    draft_id: str = Field(min_length=16, max_length=64)
    privacy_consent: bool = False


class UpdateDraftIn(CamelModel):
    content: StudioContent
    template: str = Field(default="minimal-case-study", max_length=40)
    media_layout: str = Field(default="cinematic-hero", max_length=40)


class CreateProjectFromDraftIn(CamelModel):
    draft_id: str = Field(min_length=16, max_length=64)
    content: StudioContent
    template: str = Field(default="minimal-case-study", max_length=40)
    media_layout: str = Field(default="cinematic-hero", max_length=40)
    publish: bool = False
    repository_roles: dict[str, str] = {}
    media: list[dict[str, str]] = []

    @model_validator(mode="after")
    def _drafts_never_publish_unreviewed(self) -> "CreateProjectFromDraftIn":
        # The API still requires an explicit publish flag; the UI defaults false.
        return self


class StudioDraftOut(CamelModel):
    id: str
    project_id: int | None
    repository_url: str
    source_sha: str | None
    status: str
    analysis: RepositoryAnalysis
    content: StudioContent | None
    evidence: list[Evidence]
    template: str
    media_layout: str
    privacy_consent: bool
    provider: str | None
    model: str | None
    provider_failures: list[dict[str, str]]
    token_usage: dict[str, int] | None
    error: str | None
    created_at: datetime
    updated_at: datetime


class RepositoryAssociationOut(CamelModel):
    id: int
    project_id: int
    url: str
    owner: str
    name: str
    role: str
    primary: bool
    visibility: str
    metadata: dict[str, object]
    submodules: list[SubmoduleEvidence]
    source_sha: str | None
