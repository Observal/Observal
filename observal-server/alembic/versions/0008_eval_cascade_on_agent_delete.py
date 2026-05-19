# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only
"""Add ON DELETE CASCADE to eval_runs and scorecards agent_id FK.

Revision ID: 0008
Revises: 0007
Create Date: 2026-05-17
"""

from alembic import op

revision = "0008"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # eval_runs.agent_id → agents.id CASCADE
    op.drop_constraint("eval_runs_agent_id_fkey", "eval_runs", type_="foreignkey")
    op.create_foreign_key(
        "eval_runs_agent_id_fkey",
        "eval_runs",
        "agents",
        ["agent_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # scorecards.agent_id → agents.id CASCADE
    op.drop_constraint("scorecards_agent_id_fkey", "scorecards", type_="foreignkey")
    op.create_foreign_key(
        "scorecards_agent_id_fkey",
        "scorecards",
        "agents",
        ["agent_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint("scorecards_agent_id_fkey", "scorecards", type_="foreignkey")
    op.create_foreign_key(
        "scorecards_agent_id_fkey",
        "scorecards",
        "agents",
        ["agent_id"],
        ["id"],
    )

    op.drop_constraint("eval_runs_agent_id_fkey", "eval_runs", type_="foreignkey")
    op.create_foreign_key(
        "eval_runs_agent_id_fkey",
        "eval_runs",
        "agents",
        ["agent_id"],
        ["id"],
    )
