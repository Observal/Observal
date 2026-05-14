# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only
"""Skill model simplification — align with git-first model

Adds git_url, skill_md_content, git_ref, validated to skill_versions.
Drops 7 bloated columns that belong in SKILL.md (has_scripts, has_templates,
is_power, power_md, triggers, mcp_server_config, activation_keywords).

Revision ID: 0006
Revises: 0005
Create Date: 2026-05-14
"""

import sqlalchemy as sa

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

_DROP_COLS = [
    "has_scripts",
    "has_templates",
    "is_power",
    "power_md",
    "triggers",
    "mcp_server_config",
    "activation_keywords",
]

_ADD_COLS = [
    ("git_url", sa.String(500), True),
    ("skill_md_content", sa.Text(), True),
    ("git_ref", sa.String(255), True),
    ("validated", sa.Boolean(), False),
]


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = {c["name"] for c in inspector.get_columns("skill_versions")}

    for col_name, col_type, nullable in _ADD_COLS:
        if col_name not in existing:
            if nullable:
                op.add_column("skill_versions", sa.Column(col_name, col_type, nullable=True))
            else:
                op.add_column(
                    "skill_versions",
                    sa.Column(col_name, col_type, nullable=False, server_default=sa.false()),
                )

    for col_name in _DROP_COLS:
        if col_name in existing:
            op.drop_column("skill_versions", col_name)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = {c["name"] for c in inspector.get_columns("skill_versions")}

    for col_name, _col_type, _nullable in _ADD_COLS:
        if col_name in existing:
            op.drop_column("skill_versions", col_name)

    restore = [
        ("has_scripts", sa.Boolean(), False, sa.false()),
        ("has_templates", sa.Boolean(), False, sa.false()),
        ("is_power", sa.Boolean(), False, sa.false()),
        ("power_md", sa.Text(), True, None),
        ("triggers", sa.JSON(), True, None),
        ("mcp_server_config", sa.JSON(), True, None),
        ("activation_keywords", sa.JSON(), True, None),
    ]
    for col_name, col_type, nullable, server_default in restore:
        if col_name not in existing:
            if server_default is not None:
                op.add_column(
                    "skill_versions",
                    sa.Column(col_name, col_type, nullable=nullable, server_default=server_default),
                )
            else:
                op.add_column("skill_versions", sa.Column(col_name, col_type, nullable=nullable))
