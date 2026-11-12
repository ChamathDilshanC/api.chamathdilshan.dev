"""Request / response models for projects, journal posts, skills, experience and media."""

from datetime import date, datetime
from typing import Annotated, Any, Literal, Self

from pydantic import Field, ValidationInfo, field_validator, model_validator

from app.schemas.common import (
    BrandIconUrl,
    CamelModel,
    Copy,
    ExternalUrl,
    ImageRef,
    ImageUrl,
    Line,
    MediaItem,
    Short,
    Slug,
    Stat,
    widget,
)

# --- projects -----------------------------------------------------------------


class ProjectIn(CamelModel):
    title: Annotated[str, Field(min_length=1, max_length=120)]
    slug: Slug | None = Field(
        default=None, description="Leave empty to create it from the title."
    )
    category: Short = ""
    year: Annotated[str, Field(max_length=10)] = ""
    summary: Line = Field(default="", description="One sentence shown in the case-study hero.")
    thumbnail: ImageRef | None = Field(
        default=None,
        title="Thumbnail",
        description="Card image used on the home page, the projects grid and testimonials.",
    )
    hero: MediaItem | None = Field(
        default=None,
        title="Hero media",
        description="Image or video behind the case-study title. Falls back to the thumbnail.",
    )
    intro: Copy = Field(default="", description="The large statement under “The Project”.")
    discover: Copy = ""
    explore: Copy = ""
    results: Annotated[list[Stat], Field(max_length=8)] = []
    gallery: Annotated[
        list[MediaItem],
        Field(
            max_length=40,
            description="Images and videos shown down the case study, in this order.",
            json_schema_extra=widget("gallery"),
        ),
    ] = []
    tech: Annotated[
        list[Annotated[str, Field(max_length=40)]],
        Field(max_length=30, title="Tech stack", json_schema_extra=widget("tags")),
    ] = []
    live_url: ExternalUrl | None = Field(default=None, title="Live site URL")
    repo_url: ExternalUrl | None = Field(default=None, title="Source code URL")
    template: Annotated[
        Literal[
            "legacy",
            "minimal-case-study",
            "editorial-technical-story",
            "product-showcase",
            "architecture-deep-dive",
            "opensource-showcase",
        ],
        Field(json_schema_extra=widget("project-template")),
    ] = "legacy"
    template_config: dict[str, Any] = {}
    studio_content: Annotated[
        dict[str, Any],
        Field(json_schema_extra=widget("project-content")),
    ] = {}
    seo: dict[str, Any] = {}
    repositories: list[dict[str, Any]] = []
    featured: bool = Field(default=True, description="Show in Selected Work on the home page.")
    published: bool = Field(default=False, description="Visible on the public site.")

    @model_validator(mode="after")
    def _publishable(self) -> Self:
        if self.published and self.thumbnail is None:
            raise ValueError("Add a thumbnail before publishing the project.")
        return self


class ProjectOut(ProjectIn):
    id: int
    slug: str
    sort_order: int
    created_at: datetime
    updated_at: datetime


class ProjectPublic(CamelModel):
    slug: str
    title: str
    category: str
    year: str
    summary: str
    thumbnail: ImageRef
    hero: MediaItem
    intro: str
    discover: str
    explore: str
    results: list[Stat]
    gallery: list[MediaItem]
    tech: list[str]
    live_url: str | None
    repo_url: str | None
    featured: bool
    template: str = "legacy"
    template_config: dict[str, Any] = {}
    studio_content: dict[str, Any] = {}
    seo: dict[str, Any] = {}
    repositories: list[dict[str, Any]] = []


# --- journal posts ------------------------------------------------------------


class PostSectionIn(CamelModel):
    title: Short
    paragraphs: Annotated[
        list[Annotated[str, Field(max_length=5000)]],
        Field(
            max_length=50,
            description="Separate paragraphs with an empty line.",
            json_schema_extra=widget("paragraphs"),
        ),
    ] = []
    images: Annotated[
        list[ImageRef],
        Field(max_length=2, description="One full-width image or two side by side."),
    ] = []
    videos: Annotated[
        list[MediaItem],
        Field(max_length=2, description="Videos shown after the section images."),
    ] = []

    @field_validator("videos")
    @classmethod
    def _videos_only(cls, value: list[MediaItem]) -> list[MediaItem]:
        if any(item.kind != "video" for item in value):
            raise ValueError("Section videos must have kind video.")
        return value


class PostIn(CamelModel):
    title: Annotated[str, Field(min_length=1, max_length=200)]
    slug: Slug | None = Field(default=None, description="Leave empty to create it from the title.")
    category: Short = ""
    date: date
    excerpt: Line = ""
    cover: MediaItem | None = None
    sections: Annotated[list[PostSectionIn], Field(max_length=40)] = []
    published: bool = False

    @model_validator(mode="after")
    def _publishable(self) -> Self:
        if self.published and self.cover is None:
            raise ValueError("Add a cover image before publishing the article.")
        return self


class PostOut(PostIn):
    id: int
    slug: str
    created_at: datetime
    updated_at: datetime


class PostSectionPublic(CamelModel):
    title: str
    paragraphs: list[str]
    images: list[ImageRef]
    videos: list[MediaItem] = []


class PostPublic(CamelModel):
    slug: str
    title: str
    category: str
    date: date
    excerpt: str
    cover: MediaItem
    sections: list[PostSectionPublic]


# --- skills -------------------------------------------------------------------


class SkillIn(CamelModel):
    name: Annotated[str, Field(min_length=1, max_length=60)]
    category: Annotated[str, Field(max_length=60)] = Field(
        default="", description="e.g. Frontend, Backend, Cloud, Tools."
    )
    icon: BrandIconUrl | None = Field(
        default=None,
        description="Shown under the name. Search theSVG by name, or paste any image URL.",
    )
    featured: bool = Field(
        default=True, description="Show in the scrolling strip on the home page."
    )
    visible: bool = Field(default=True, description="Show in the Stack grid on the about page.")


class SkillOut(SkillIn):
    id: int
    sort_order: int
    created_at: datetime
    updated_at: datetime


class SkillPublic(CamelModel):
    name: str
    category: str
    icon: str | None
    featured: bool
    visible: bool


# --- work experience ----------------------------------------------------------

EmploymentType = Literal[
    "Full-time", "Part-time", "Contract", "Freelance", "Internship", "Self-employed"
]
DocumentFormat = Literal["png"]
Month = Annotated[
    str,
    Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$", json_schema_extra={"format": "month"}),
]


class ExperienceDocumentIn(CamelModel):
    """A protected Cloudinary asset attached to one employer."""

    id: Annotated[str, Field(min_length=12, max_length=40, pattern=r"^[A-Za-z0-9_-]+$")]
    label: Annotated[str, Field(min_length=1, max_length=80)] = "Service letter"
    public_id: Annotated[
        str,
        Field(min_length=1, max_length=300, pattern=r"^[A-Za-z0-9_./-]+$"),
    ]
    version: Annotated[int, Field(ge=1)]
    resource_type: Literal["image", "raw"]
    format: DocumentFormat
    pages: Annotated[int, Field(ge=1, le=100)] = 1
    bytes: Annotated[int, Field(ge=1, le=15 * 1024 * 1024)]
    original_filename: Annotated[str, Field(min_length=1, max_length=300)]


class ExperienceDocumentPublic(CamelModel):
    id: str
    label: str
    format: str
    pages: int


class ExperienceRoleIn(CamelModel):
    """One position at a company. A promotion is a new role at the same company."""

    title: Annotated[str, Field(min_length=1, max_length=120)]
    employment_type: EmploymentType = "Full-time"
    start: Month = Field(title="Start month", description="When you started this role.")
    end: Month | None = Field(
        default=None, title="End month", description="Leave empty while you still hold this role."
    )
    summary: Copy = ""
    highlights: Annotated[
        list[Line], Field(max_length=10, description="Shown as a + list under the role.")
    ] = []
    skills: Annotated[
        list[Annotated[str, Field(max_length=40)]],
        Field(max_length=20, json_schema_extra=widget("tags")),
    ] = []

    @field_validator("end")
    @classmethod
    def _not_before_start(cls, end: str | None, info: ValidationInfo) -> str | None:
        start = info.data.get("start")
        if end is not None and isinstance(start, str) and end < start:
            raise ValueError("must not be before the start month")
        return end


class ExperienceIn(CamelModel):
    company: Annotated[str, Field(min_length=1, max_length=120)]
    company_url: ExternalUrl | None = Field(default=None, title="Company website")
    logo: ImageUrl | None = Field(default=None, description="Optional logo, shown small.")
    location: Short = Field(default="", description="e.g. Colombo, Sri Lanka · Hybrid")
    roles: Annotated[
        list[ExperienceRoleIn],
        Field(
            min_length=1,
            max_length=20,
            description=(
                "Every position you held here. They are shown newest first and joined "
                "by a line, so a promotion reads as one path."
            ),
        ),
    ]
    documents: Annotated[
        list[ExperienceDocumentIn],
        Field(
            max_length=20,
            description=(
                "Protected PNG service letters, employment letters and certificates. "
                "Visitors see one labelled view-only button for each document."
            ),
            json_schema_extra=widget("documents"),
        ),
    ] = []
    published: bool = Field(default=True, description="Show on the about page.")

    @model_validator(mode="after")
    def _unique_documents(self) -> Self:
        ids = [document.id for document in self.documents]
        public_ids = [document.public_id for document in self.documents]
        if len(ids) != len(set(ids)) or len(public_ids) != len(set(public_ids)):
            raise ValueError("Each attached document must be unique.")
        return self


class ExperienceOut(ExperienceIn):
    id: int
    created_at: datetime
    updated_at: datetime


class ExperienceRolePublic(CamelModel):
    title: str
    employment_type: str
    start: str
    end: str | None
    summary: str
    highlights: list[str]
    skills: list[str]


class ExperiencePublic(CamelModel):
    id: int
    company: str
    company_url: str | None
    logo: str | None
    location: str
    roles: list[ExperienceRolePublic]
    documents: list[ExperienceDocumentPublic] = []


class ExperienceDocumentSignature(CamelModel):
    cloud_name: str
    api_key: str
    timestamp: int
    folder: str
    signature: str
    upload_url: str
    delivery_type: Literal["authenticated"]


class ExperienceDocumentRegister(CamelModel):
    """Authenticated Cloudinary upload response forwarded by the admin browser."""

    public_id: Annotated[str, Field(max_length=300)]
    version: Annotated[int, Field(ge=1)]
    signature: Annotated[str, Field(max_length=128)]
    resource_type: Literal["image", "raw"]
    delivery_type: Literal["authenticated"]
    format: DocumentFormat
    secure_url: Annotated[str, Field(max_length=1000)]
    pages: Annotated[int, Field(ge=1, le=100)] = 1
    bytes: Annotated[int, Field(ge=1, le=15 * 1024 * 1024)]
    original_filename: Annotated[str, Field(min_length=1, max_length=300)]


# --- media --------------------------------------------------------------------


class MediaSignature(CamelModel):
    cloud_name: str
    api_key: str
    timestamp: int
    folder: str
    signature: str
    upload_url: str


class MediaSignIn(CamelModel):
    """Optional path below the configured Cloudinary root folder."""

    folder: Annotated[str | None, Field(max_length=120)] = None


class MediaRegister(CamelModel):
    """The Cloudinary upload response, forwarded by the browser after a direct upload."""

    public_id: Annotated[str, Field(max_length=300)]
    version: int
    signature: Annotated[str, Field(max_length=128)]
    resource_type: Literal["image", "video"]
    format: Annotated[str, Field(max_length=20)] = ""
    secure_url: Annotated[str, Field(max_length=1000)]
    width: int | None = None
    height: int | None = None
    bytes: int = 0
    duration: float | None = None
    original_filename: Annotated[str, Field(max_length=300)] = ""
    alt: Line = ""


class MediaUpdate(CamelModel):
    alt: Line


class MediaOut(CamelModel):
    id: int
    public_id: str
    kind: Literal["image", "video"]
    url: str
    poster: str | None
    format: str
    width: int | None
    height: int | None
    bytes: int
    duration: float | None
    alt: str
    original_filename: str
    created_at: datetime


class MediaOrganizeOut(CamelModel):
    moved: int
    skipped: int
    shared: int
    failed: list[str]


# --- shared admin responses ---------------------------------------------------


class ReorderIn(CamelModel):
    ids: Annotated[list[int], Field(max_length=500)]


class AuditOut(CamelModel):
    id: int
    at: datetime
    actor: str
    action: str
    target: str
    ip: str


class SectionSummary(CamelModel):
    key: str
    title: str
    group: str
    description: str
    updated_at: datetime | None


class SectionDetail(SectionSummary):
    data: dict[str, object]
    schema_: dict[str, object] = Field(alias="schema")


class MediaUsage(CamelModel):
    where: str
    label: str
