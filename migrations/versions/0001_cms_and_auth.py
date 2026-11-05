"""CMS content, media library, Google + email-code auth, audit log.

Revision ID: 0001
Revises:
Create Date: 2026-11-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON = sa.JSON().with_variant(JSONB(), "postgresql")
TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "sections",
        sa.Column("key", sa.String(64), nullable=False),
        sa.Column("data", JSON, nullable=False),
        sa.Column("updated_at", TS, nullable=False),
        sa.PrimaryKeyConstraint("key", name=op.f("pk_sections")),
    )

    op.create_table(
        "projects",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("slug", sa.String(80), nullable=False),
        sa.Column("title", sa.String(120), nullable=False),
        sa.Column("category", sa.String(80), nullable=False),
        sa.Column("year", sa.String(10), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("intro", sa.Text(), nullable=False),
        sa.Column("discover", sa.Text(), nullable=False),
        sa.Column("explore", sa.Text(), nullable=False),
        sa.Column("results", JSON, nullable=False),
        sa.Column("thumbnail", JSON, nullable=True),
        sa.Column("hero", JSON, nullable=True),
        sa.Column("gallery", JSON, nullable=False),
        sa.Column("tech", JSON, nullable=False),
        sa.Column("live_url", sa.String(500), nullable=True),
        sa.Column("repo_url", sa.String(500), nullable=True),
        sa.Column("featured", sa.Boolean(), nullable=False),
        sa.Column("published", sa.Boolean(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("updated_at", TS, nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_projects")),
    )
    op.create_index(op.f("ix_projects_slug"), "projects", ["slug"], unique=True)
    op.create_index(op.f("ix_projects_published"), "projects", ["published"])
    op.create_index(op.f("ix_projects_sort_order"), "projects", ["sort_order"])

    op.create_table(
        "posts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("slug", sa.String(120), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("category", sa.String(80), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("excerpt", sa.Text(), nullable=False),
        sa.Column("cover", JSON, nullable=True),
        sa.Column("sections", JSON, nullable=False),
        sa.Column("published", sa.Boolean(), nullable=False),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("updated_at", TS, nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_posts")),
    )
    op.create_index(op.f("ix_posts_slug"), "posts", ["slug"], unique=True)
    op.create_index(op.f("ix_posts_published"), "posts", ["published"])

    op.create_table(
        "skills",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(60), nullable=False),
        sa.Column("category", sa.String(60), nullable=False),
        sa.Column("icon", sa.String(1000), nullable=True),
        sa.Column("featured", sa.Boolean(), nullable=False),
        sa.Column("visible", sa.Boolean(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("updated_at", TS, nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_skills")),
    )
    op.create_index(op.f("ix_skills_sort_order"), "skills", ["sort_order"])

    op.create_table(
        "media",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("public_id", sa.String(300), nullable=False),
        sa.Column("kind", sa.String(10), nullable=False),
        sa.Column("url", sa.String(1000), nullable=False),
        sa.Column("format", sa.String(20), nullable=False),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("bytes", sa.Integer(), nullable=False),
        sa.Column("duration", sa.Float(), nullable=True),
        sa.Column("alt", sa.String(300), nullable=False),
        sa.Column("original_filename", sa.String(300), nullable=False),
        sa.Column("created_at", TS, nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_media")),
    )
    op.create_index(op.f("ix_media_public_id"), "media", ["public_id"], unique=True)
    op.create_index(op.f("ix_media_created_at"), "media", ["created_at"])

    op.create_table(
        "login_challenges",
        sa.Column("id", sa.String(64), nullable=False),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("google_sub", sa.String(64), nullable=False),
        sa.Column("code_hash", sa.String(128), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("sends", sa.Integer(), nullable=False),
        sa.Column("last_sent_at", TS, nullable=False),
        sa.Column("expires_at", TS, nullable=False),
        sa.Column("consumed_at", TS, nullable=True),
        sa.Column("ip", sa.String(64), nullable=False),
        sa.Column("created_at", TS, nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_login_challenges")),
    )

    op.create_table(
        "admin_sessions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("picture", sa.String(1000), nullable=False),
        sa.Column("ip", sa.String(64), nullable=False),
        sa.Column("user_agent", sa.String(500), nullable=False),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("last_seen_at", TS, nullable=False),
        sa.Column("expires_at", TS, nullable=False),
        sa.Column("revoked_at", TS, nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_admin_sessions")),
    )
    op.create_index(
        op.f("ix_admin_sessions_token_hash"), "admin_sessions", ["token_hash"], unique=True
    )

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("at", TS, nullable=False),
        sa.Column("actor", sa.String(320), nullable=False),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("target", sa.String(200), nullable=False),
        sa.Column("ip", sa.String(64), nullable=False),
        sa.Column("detail", JSON, nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_logs")),
    )
    op.create_index(op.f("ix_audit_logs_at"), "audit_logs", ["at"])
    op.create_index(op.f("ix_audit_logs_action"), "audit_logs", ["action"])


def downgrade() -> None:
    op.drop_table("audit_logs")
    op.drop_table("admin_sessions")
    op.drop_table("login_challenges")
    op.drop_table("media")
    op.drop_table("skills")
    op.drop_table("posts")
    op.drop_table("projects")
    op.drop_table("sections")
