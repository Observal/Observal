# SPDX-FileCopyrightText: 2026 Swathi Saravanan <ss4522@cornell.edu>
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Add eval_spec_dags table

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-08
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS eval_spec_dags (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            task_type VARCHAR(255) NOT NULL,
            version VARCHAR(50) NOT NULL,
            dag_json JSON NOT NULL,
            source VARCHAR(32) NOT NULL DEFAULT 'hand_authored',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            created_by VARCHAR(255)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_eval_spec_dags_task_type ON eval_spec_dags (task_type)")
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_eval_spec_dags_task_type_version ON eval_spec_dags (task_type, version)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS eval_spec_dags")
