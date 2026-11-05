"""Request / response models for projects, journal posts, skills and media."""

from datetime import date, datetime
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from app.schemas.common import (
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


class PostIn(CamelModel):
    title: Annotated[str, Field(min_length=1, max_length=200)]
    slug: Slug | None = Field(default=None, description="Leave empty to create it from the title.")
    category: Short = ""
    date: date
    excerpt: Line = ""
    cover: ImageRef | None = None
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


class PostPublic(CamelModel):
    slug: str
    title: str
    category: str
    date: date
    excerpt: str
    cover: ImageRef
    sections: list[PostSectionPublic]


# --- skills -------------------------------------------------------------------


class SkillIn(CamelModel):
    name: Annotated[str, Field(min_length=1, max_length=60)]
    category: Annotated[str, Field(max_length=60)] = Field(
        default="", description="e.g. Frontend, Backend, Cloud, Tools."
    )
    icon: ImageUrl | None = Field(default=None, description="Optional logo shown on the tile.")
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


# --- media --------------------------------------------------------------------


class MediaSignature(CamelModel):
    cloud_name: str
    api_key: str
    timestamp: int
    folder: str
    signature: str
    upload_url: str


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

