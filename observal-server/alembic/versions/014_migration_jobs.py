# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Add migration_jobs table for data migration tracking.

Revision ID: 011_migration_jobs
Revises: c680c63ced65
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSON, UUID

from alembic import op

revision = "011_migration_jobs"
down_revision = "c680c63ced65"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create PG enum types
    migration_operation = sa.Enum("export", "import", "validate", name="migration_operation")
    migration_scope = sa.Enum("postgres", "clickhouse", "both", name="migration_scope")
    migration_status = sa.Enum("queued", "running", "completed", "failed", name="migration_status")

    migration_operation.create(op.get_bind(), checkfirst=True)
    migration_scope.create(op.get_bind(), checkfirst=True)
    migration_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "migration_jobs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("operation_type", migration_operation, nullable=False),
        sa.Column("data_scope", migration_scope, nullable=False),
        sa.Column("status", migration_status, nullable=False, server_default="queued"),
        sa.Column("progress_phase", sa.String(50), nullable=True, server_default="queued"),
        sa.Column("progress_pct", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("progress_message", sa.Text(), nullable=True),
        sa.Column("progress_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("result_json", JSON(), nullable=True),
        sa.Column("artifacts_json", JSON(), nullable=True),
        sa.Column("artifact_dir", sa.Text(), nullable=True),
        sa.Column("schema_version", sa.String(64), nullable=True),
        sa.Column("org_id", UUID(as_uuid=True), nullable=True),
    )

    op.create_foreign_key(
        "fk_migration_jobs_created_by",
        "migration_jobs",
        "users",
        ["created_by"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_migration_jobs_status", "migration_jobs", ["status"])


def downgrade() -> None:
    op.drop_index("ix_migration_jobs_status", table_name="migration_jobs")
    op.drop_constraint("fk_migration_jobs_created_by", "migration_jobs", type_="foreignkey")
    op.drop_table("migration_jobs")

    # Drop enum types
    sa.Enum(name="migration_status").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="migration_scope").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="migration_operation").drop(op.get_bind(), checkfirst=True)
