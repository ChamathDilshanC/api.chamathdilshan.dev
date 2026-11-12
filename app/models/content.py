"""Content tables: editable site sections, projects, journal posts, skills, work experience
and media."""

from datetime import date, datetime
from typing import Any

from sqlalchemy import Boolean, Date, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, JSONType, UTCDateTime, utcnow


class Section(Base):
    """One editable block of the public site, stored as a validated JSON document.

    The shape of `data` is defined per key in app/schemas/sections.py.
    """

    __tablename__ = "sections"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    data: Mapped[dict[str, Any]] = mapped_column(JSONType, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    slug: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(120))
    category: Mapped[str] = mapped_column(String(80), default="")
    year: Mapped[str] = mapped_column(String(10), default="")
    summary: Mapped[str] = mapped_column(Text, default="")
    intro: Mapped[str] = mapped_column(Text, default="")
    discover: Mapped[str] = mapped_column(Text, default="")
    explore: Mapped[str] = mapped_column(Text, default="")
    results: Mapped[list[dict[str, Any]]] = mapped_column(JSONType, default=list)
    # {url, alt} — the card image used in grids and lists.
    thumbnail: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)
    # {kind: image|video, url, alt, poster} — the case-study hero.
    hero: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)
    # [{kind, url, alt, poster}, …] — images and videos for the case study.
    gallery: Mapped[list[dict[str, Any]]] = mapped_column(JSONType, default=list)
    tech: Mapped[list[str]] = mapped_column(JSONType, default=list)
    live_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    repo_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    template: Mapped[str] = mapped_column(String(40), default="legacy")
    template_config: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    studio_content: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    seo: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    repositories: Mapped[list[dict[str, Any]]] = mapped_column(JSONType, default=list)
    featured: Mapped[bool] = mapped_column(Boolean, default=True)
    published: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class ProjectStudioDraft(Base):
    """Durable GitHub-to-portfolio workflow state.

    Draft JSON is intentionally separate from the legacy project columns so an
    incomplete import cannot alter an existing published project.
    """

    __tablename__ = "project_studio_drafts"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    repository_url: Mapped[str] = mapped_column(String(500), index=True)
    source_sha: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="analyzed", index=True)
    analysis: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    content: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSONType, default=list)
    template: Mapped[str] = mapped_column(String(40), default="minimal-case-study")
    media_layout: Mapped[str] = mapped_column(String(40), default="cinematic-hero")
    privacy_consent: Mapped[bool] = mapped_column(Boolean, default=False)
    model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    token_usage: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class ProjectRepository(Base):
    """A normalized repository association for one portfolio project."""

    __tablename__ = "project_repositories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(Integer, index=True)
    url: Mapped[str] = mapped_column(String(500))
    owner: Mapped[str] = mapped_column(String(120))
    name: Mapped[str] = mapped_column(String(120))
    role: Mapped[str] = mapped_column(String(40), default="other")
    primary: Mapped[bool] = mapped_column(Boolean, default=False)
    visibility: Mapped[str] = mapped_column(String(20), default="public")
    repo_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JSONType, default=dict)
    submodules: Mapped[list[dict[str, Any]]] = mapped_column(JSONType, default=list)
    source_sha: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class Post(Base):
    __tablename__ = "posts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    slug: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(80), default="")
    date: Mapped[date] = mapped_column(Date)
    excerpt: Mapped[str] = mapped_column(Text, default="")
    cover: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)
    # [{title, paragraphs: [...], images: [{url, alt}]}]
    sections: Mapped[list[dict[str, Any]]] = mapped_column(JSONType, default=list)
    published: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class Skill(Base):
    __tablename__ = "skills"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(60))
    category: Mapped[str] = mapped_column(String(60), default="")
    icon: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    # Shown in the scrolling strip on the home page.
    featured: Mapped[bool] = mapped_column(Boolean, default=True)
    # Shown in the Stack grid on the about page.
    visible: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class Experience(Base):
    """One employer on the about page, with every role held there (LinkedIn style).

    Roles live in a JSON list because they are always read and edited together
    with their company. The public order is derived from the role dates.
    """

    __tablename__ = "experiences"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    company: Mapped[str] = mapped_column(String(120))
    company_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    logo: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    location: Mapped[str] = mapped_column(String(120), default="")
    # [{title, employmentType, start: "YYYY-MM", end: "YYYY-MM" | null, summary,
    #   highlights: [...], skills: [...]}, …]
    roles: Mapped[list[dict[str, Any]]] = mapped_column(JSONType, default=list)
    # Protected Cloudinary references. Public responses expose only display metadata;
    # file bytes are delivered through a validated, no-store API endpoint.
    documents: Mapped[list[dict[str, Any]]] = mapped_column(JSONType, default=list)
    published: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class Media(Base):
    """An asset uploaded to Cloudinary. The file itself lives on Cloudinary's CDN."""

    __tablename__ = "media"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    public_id: Mapped[str] = mapped_column(String(300), unique=True, index=True)
    kind: Mapped[str] = mapped_column(String(10))  # image | video
    url: Mapped[str] = mapped_column(String(1000))
    format: Mapped[str] = mapped_column(String(20), default="")
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bytes: Mapped[int] = mapped_column(Integer, default=0)
    duration: Mapped[float | None] = mapped_column(Float, nullable=True)
    alt: Mapped[str] = mapped_column(String(300), default="")
    original_filename: Mapped[str] = mapped_column(String(300), default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
