"""Persist the provider selected for Studio generation."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_ai_provider_metadata"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("project_studio_drafts", sa.Column("provider", sa.String(30), nullable=True))
    op.add_column(
        "project_studio_drafts",
        sa.Column("provider_failures", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
    )


def downgrade() -> None:
    op.drop_column("project_studio_drafts", "provider_failures")
    op.drop_column("project_studio_drafts", "provider")
