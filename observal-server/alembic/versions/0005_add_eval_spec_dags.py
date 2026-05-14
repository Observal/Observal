# SPDX-FileCopyrightText: 2026 Swathi Saravanan <ss4522@cornell.edu>
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Add eval_spec_dags table

Revision ID: 0005
Revises: 0004
Create Date: 2026-05-08
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "eval_spec_dags" not in inspector.get_table_names():
        op.create_table(
            "eval_spec_dags",
            sa.Column(
                "id",
                postgresql.UUID(as_uuid=True),
                primary_key=True,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column("task_type", sa.String(255), nullable=False),
            sa.Column("version", sa.String(50), nullable=False),
            sa.Column("dag_json", postgresql.JSON(), nullable=False),
            sa.Column("source", sa.String(32), nullable=False, server_default="hand_authored"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("created_by", sa.String(255), nullable=True),
            sa.UniqueConstraint("task_type", "version", name="ux_eval_spec_dags_task_type_version"),
        )
    op.create_index(
        "ix_eval_spec_dags_task_type",
        "eval_spec_dags",
        ["task_type"],
        unique=False,
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_index("ix_eval_spec_dags_task_type", table_name="eval_spec_dags", if_exists=True)
    op.drop_table("eval_spec_dags", if_exists=True)
