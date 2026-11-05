"""Work experience: one row per company, its roles as a JSON list.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON = sa.JSON().with_variant(JSONB(), "postgresql")
TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "experiences",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("company", sa.String(120), nullable=False),
        sa.Column("company_url", sa.String(500), nullable=True),
        sa.Column("logo", sa.String(1000), nullable=True),
        sa.Column("location", sa.String(120), nullable=False),
        sa.Column("roles", JSON, nullable=False),
        sa.Column("published", sa.Boolean(), nullable=False),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("updated_at", TS, nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_experiences")),
    )
    op.create_index(op.f("ix_experiences_published"), "experiences", ["published"])


def downgrade() -> None:
    op.drop_index(op.f("ix_experiences_published"), table_name="experiences")
    op.drop_table("experiences")
