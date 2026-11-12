"""GitHub AI Project Studio workflow and repository associations.

Revision ID: 0004
Revises: 0003
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON = sa.JSON().with_variant(JSONB(), "postgresql")
TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.add_column(
        "projects", sa.Column("template", sa.String(40), nullable=False, server_default="legacy")
    )
    op.add_column(
        "projects",
        sa.Column("template_config", JSON, nullable=False, server_default=sa.text("'{}'")),
    )
    op.add_column(
        "projects",
        sa.Column("studio_content", JSON, nullable=False, server_default=sa.text("'{}'")),
    )
    op.add_column(
        "projects", sa.Column("seo", JSON, nullable=False, server_default=sa.text("'{}'"))
    )
    op.add_column(
        "projects", sa.Column("repositories", JSON, nullable=False, server_default=sa.text("'[]'"))
    )
    op.create_table(
        "project_studio_drafts",
        sa.Column("id", sa.String(64), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=True),
        sa.Column("repository_url", sa.String(500), nullable=False),
        sa.Column("source_sha", sa.String(64), nullable=True),
        sa.Column("status", sa.String(30), nullable=False, server_default="analyzed"),
        sa.Column("analysis", JSON, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("content", JSON, nullable=True),
        sa.Column("evidence", JSON, nullable=False, server_default=sa.text("'[]'")),
        sa.Column("template", sa.String(40), nullable=False, server_default="minimal-case-study"),
        sa.Column("media_layout", sa.String(40), nullable=False, server_default="cinematic-hero"),
        sa.Column("privacy_consent", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("model", sa.String(120), nullable=True),
        sa.Column("token_usage", JSON, nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("updated_at", TS, nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_project_studio_drafts")),
    )
    op.create_index(
        op.f("ix_project_studio_drafts_project_id"), "project_studio_drafts", ["project_id"]
    )
    op.create_index(
        op.f("ix_project_studio_drafts_repository_url"), "project_studio_drafts", ["repository_url"]
    )
    op.create_index(op.f("ix_project_studio_drafts_status"), "project_studio_drafts", ["status"])

    op.create_table(
        "project_repositories",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("url", sa.String(500), nullable=False),
        sa.Column("owner", sa.String(120), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("role", sa.String(40), nullable=False, server_default="other"),
        sa.Column("primary", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("visibility", sa.String(20), nullable=False, server_default="public"),
        sa.Column("metadata", JSON, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("submodules", JSON, nullable=False, server_default=sa.text("'[]'")),
        sa.Column("source_sha", sa.String(64), nullable=True),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("updated_at", TS, nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_project_repositories")),
        sa.UniqueConstraint("project_id", "url", name="uq_project_repositories_project_url"),
    )
    op.create_index(
        op.f("ix_project_repositories_project_id"), "project_repositories", ["project_id"]
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_project_repositories_project_id"), table_name="project_repositories")
    op.drop_table("project_repositories")
    op.drop_index(op.f("ix_project_studio_drafts_status"), table_name="project_studio_drafts")
    op.drop_index(
        op.f("ix_project_studio_drafts_repository_url"), table_name="project_studio_drafts"
    )
    op.drop_index(op.f("ix_project_studio_drafts_project_id"), table_name="project_studio_drafts")
    op.drop_table("project_studio_drafts")
    op.drop_column("projects", "repositories")
    op.drop_column("projects", "seo")
    op.drop_column("projects", "studio_content")
    op.drop_column("projects", "template_config")
    op.drop_column("projects", "template")
