"""Add insight_reports, insight_session_facets, insight_session_meta tables.

Revision ID: 0005
Revises: 0004
Create Date: 2026-05-12
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

# Enum type name — managed explicitly to ensure clean downgrade
_STATUS_ENUM_NAME = "insight_report_status"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # --- Fix insight_meta_cache FK (0003 omitted ondelete CASCADE) ---
    if inspector.has_table("insight_meta_cache"):
        # Drop and recreate the FK constraint with CASCADE
        fks = inspector.get_foreign_keys("insight_meta_cache")
        for fk in fks:
            if fk.get("referred_table") == "agents" and "agent_id" in fk.get("constrained_columns", []):
                op.drop_constraint(fk["name"], "insight_meta_cache", type_="foreignkey")
                op.create_foreign_key(
                    fk["name"],
                    "insight_meta_cache",
                    "agents",
                    ["agent_id"],
                    ["id"],
                    ondelete="CASCADE",
                )
                break

    # --- insight_reports ---
    if not inspector.has_table("insight_reports"):
        # Create enum type explicitly (checkfirst handles re-runs)
        status_enum = sa.Enum("pending", "running", "completed", "failed", name=_STATUS_ENUM_NAME)
        status_enum.create(bind, checkfirst=True)

        op.create_table(
            "insight_reports",
            sa.Column(
                "id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
            ),
            sa.Column(
                "agent_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("agents.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "triggered_by",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column(
                "status",
                sa.Enum("pending", "running", "completed", "failed", name=_STATUS_ENUM_NAME, create_type=False),
                nullable=False,
                server_default="pending",
            ),
            sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
            sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
            sa.Column("metrics", postgresql.JSON(), nullable=True),
            sa.Column("narrative", postgresql.JSON(), nullable=True),
            sa.Column("sessions_analyzed", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("llm_model_used", sa.String(255), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column(
                "previous_report_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("insight_reports.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("aggregated_data", postgresql.JSON(), nullable=True),
            sa.Column("report_version", sa.Integer(), nullable=False, server_default="1"),
        )
        op.create_index("ix_insight_reports_agent_id", "insight_reports", ["agent_id"])
        op.create_index("ix_insight_reports_triggered_by", "insight_reports", ["triggered_by"])

    # --- insight_session_facets ---
    if not inspector.has_table("insight_session_facets"):
        op.create_table(
            "insight_session_facets",
            sa.Column(
                "id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
            ),
            sa.Column(
                "agent_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("agents.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("session_id", sa.Text(), nullable=False),
            sa.Column("extracted_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("model_used", sa.String(255), nullable=True),
            sa.Column("facets", postgresql.JSON(), nullable=False),
            sa.UniqueConstraint("agent_id", "session_id", name="uq_session_facets_agent_session"),
        )

    # --- insight_session_meta ---
    if not inspector.has_table("insight_session_meta"):
        op.create_table(
            "insight_session_meta",
            sa.Column(
                "id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
            ),
            sa.Column(
                "agent_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("agents.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("session_id", sa.Text(), nullable=False),
            sa.Column("computed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("meta", postgresql.JSON(), nullable=False),
            sa.UniqueConstraint("agent_id", "session_id", name="uq_session_meta_agent_session"),
        )


def downgrade() -> None:
    op.drop_table("insight_session_meta")
    op.drop_table("insight_session_facets")
    op.drop_table("insight_reports")

    # Drop the enum type created by upgrade
    sa.Enum(name=_STATUS_ENUM_NAME).drop(op.get_bind(), checkfirst=True)
