# SPDX-FileCopyrightText: 2026 Kaushik Kumar <kaushikrjpm10@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Add success_criteria to agent_versions.

Revision ID: 016_agent_success_criteria
Revises: 015_sandbox_runtime_config
"""

import sqlalchemy as sa

from alembic import op

revision = "016_agent_success_criteria"
down_revision = "015_sandbox_runtime_config"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("agent_versions", sa.Column("success_criteria", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("agent_versions", "success_criteria")
