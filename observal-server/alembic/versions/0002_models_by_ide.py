"""Add agent_versions.models_by_ide JSONB column for per-IDE model overrides

Backs the per-IDE model picker. The author chooses default models per IDE at
build time; the codegen reads ``models_by_ide`` first and falls back to the
single ``model_name`` field (Claude Code legacy default) when an IDE has no
explicit override.

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-08
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Idempotent: ``main._ensure_columns`` also runs this on every startup so
    # fresh installs created via ``Base.metadata.create_all`` already have the
    # column. Use IF NOT EXISTS to avoid clobbering deployments that booted
    # the new code before the migration ran.
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {c["name"] for c in inspector.get_columns("agent_versions")}
    if "models_by_ide" not in columns:
        op.add_column(
            "agent_versions",
            sa.Column(
                "models_by_ide",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'{}'::jsonb"),
            ),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {c["name"] for c in inspector.get_columns("agent_versions")}
    if "models_by_ide" in columns:
        op.drop_column("agent_versions", "models_by_ide")
