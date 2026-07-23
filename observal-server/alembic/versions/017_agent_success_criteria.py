# SPDX-FileCopyrightText: 2026 Kaushik Kumar <kaushikrjpm10@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Add success_criteria to agent_versions.

Revision ID: 017_agent_success_criteria
Revises: 016_registry_publish_loop
"""

import sqlalchemy as sa

from alembic import op

revision = "017_agent_success_criteria"
down_revision = "016_registry_publish_loop"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("agent_versions", sa.Column("success_criteria", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("agent_versions", "success_criteria")
