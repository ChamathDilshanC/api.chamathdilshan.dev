"""Protected documents attached to work experience.

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON = sa.JSON().with_variant(JSONB(), "postgresql")


def upgrade() -> None:
    op.add_column(
        "experiences",
        sa.Column("documents", JSON, nullable=False, server_default=sa.text("'[]'")),
    )


def downgrade() -> None:
    op.drop_column("experiences", "documents")
