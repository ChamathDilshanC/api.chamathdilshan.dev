"""Content tables: editable site sections, projects, journal posts, skills and media."""

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
    featured: Mapped[bool] = mapped_column(Boolean, default=True)
    published: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, index=True)
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
