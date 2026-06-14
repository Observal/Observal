# SPDX-FileCopyrightText: 2026 Swathi Saravanan <ss4522@cornell.edu>
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Self-learning loop: candidate artifacts + verification state

Adds the DB schema that the auto-candidate-generation / verification /
promotion modules build on:

- 3 new agentstatus enum values for the candidate lifecycle:
  pending_review, verification_failed, verification_inconclusive
- agent_versions.verification_result (JSON) + source_report_id (UUID)
- candidate_artifacts table (the versioned candidate store)
- the observal-auto-candidate system user (owns auto-generated versions;
  we never attribute auto-candidates to a real user)

Revision ID: 0008
Revises: 0007
Create Date: 2026-06-11
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

# Fixed identity for the system user that owns auto-generated candidate versions.
# Kept in sync with services constant SYSTEM_AUTO_CANDIDATE_USER_ID.
SYSTEM_USER_ID = "0a0a0a0a-0000-4000-8000-00000000a0c1"
SYSTEM_USER_EMAIL = "observal-auto-candidate@system.local"
SYSTEM_USER_NAME = "Observal Auto Candidate"

_NEW_STATUSES = ("pending_review", "verification_failed", "verification_inconclusive")


def upgrade() -> None:
    # 1. Extend the agentstatus enum. ADD VALUE cannot run in the migration's
    #    transaction if the value is used in the same tx; we don't use them here,
    #    but use an autocommit block to be safe across PG versions.
    with op.get_context().autocommit_block():
        for val in _NEW_STATUSES:
            op.execute(f"ALTER TYPE agentstatus ADD VALUE IF NOT EXISTS '{val}'")

    # 2. agent_versions: verification artifacts + provenance link.
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    av_cols = {c["name"] for c in inspector.get_columns("agent_versions")}
    if "verification_result" not in av_cols:
        op.add_column("agent_versions", sa.Column("verification_result", postgresql.JSON(), nullable=True))
    if "source_report_id" not in av_cols:
        op.add_column("agent_versions", sa.Column("source_report_id", postgresql.UUID(as_uuid=True), nullable=True))

    # 3. candidate_artifacts: the versioned candidate store. Never edited in
    #    place; every change is a new row.
    if "candidate_artifacts" not in inspector.get_table_names():
        op.create_table(
            "candidate_artifacts",
            sa.Column(
                "id",
                postgresql.UUID(as_uuid=True),
                primary_key=True,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("source_report_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("artifact_type", sa.String(32), nullable=False),  # cursor_rule|prompt_edit|tool_config_change
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("source_suggestions", postgresql.JSON(), nullable=False, server_default="[]"),
            sa.Column("motivating_session_ids", postgresql.JSON(), nullable=False, server_default="[]"),
            sa.Column("provenance", postgresql.JSON(), nullable=True),
            # pending | verification_failed | verification_inconclusive | promoted
            sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
            sa.Column("verification_result", postgresql.JSON(), nullable=True),
            sa.Column("promoted_version_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["source_report_id"], ["insight_reports.id"], ondelete="SET NULL"),
        )
        op.create_index("ix_candidate_artifacts_agent_id", "candidate_artifacts", ["agent_id"])
        op.create_index("ix_candidate_artifacts_status", "candidate_artifacts", ["status"])
        op.create_index("ix_candidate_artifacts_source_report_id", "candidate_artifacts", ["source_report_id"])

    # 4. Seed the system user that owns auto-generated candidate versions.
    op.execute(
        sa.text(
            """
            INSERT INTO users (id, email, name, role, is_demo, auth_provider, created_at)
            VALUES (CAST(:id AS uuid), :email, :name, 'user', false, 'system', now())
            ON CONFLICT (id) DO NOTHING
            """
        ).bindparams(id=SYSTEM_USER_ID, email=SYSTEM_USER_EMAIL, name=SYSTEM_USER_NAME)
    )


def downgrade() -> None:
    # Note: PostgreSQL has no DROP VALUE for enums, so the 3 added agentstatus
    # values remain after downgrade (standard alembic limitation). Everything
    # else is reversible.
    op.execute(sa.text("DELETE FROM users WHERE id = :id").bindparams(id=SYSTEM_USER_ID))
    op.drop_table("candidate_artifacts")
    op.drop_column("agent_versions", "source_report_id")
    op.drop_column("agent_versions", "verification_result")
