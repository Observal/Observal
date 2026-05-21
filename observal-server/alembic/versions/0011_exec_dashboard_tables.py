# SPDX-FileCopyrightText: 2026 Vishnu Muthiah <vishnu.muthiah04@gmail.com>
# SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only
"""Add exec dashboard tables: user_groups, exec_dashboard_config, users.department, agents.category.

Revision ID: 0011
Revises: 0010
Create Date: 2026-05-20
"""

import sqlalchemy as sa

from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # user_groups table (SSO group persistence)
    op.create_table(
        "user_groups",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("group_name", sa.String(255), nullable=False),
        sa.Column("synced_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.UniqueConstraint("user_id", "group_name", name="uq_user_groups_user_group"),
    )
    op.create_index("ix_user_groups_user_id", "user_groups", ["user_id"])
    op.create_index("ix_user_groups_group_name", "user_groups", ["group_name"])

    # exec_dashboard_config table (cost baselines)
    op.create_table(
        "exec_dashboard_config",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "org_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("hourly_dev_cost", sa.Numeric(10, 2), server_default="75.00"),
        sa.Column("pre_ai_baselines", sa.dialects.postgresql.JSON, server_default="{}"),
        sa.Column("department_budgets", sa.dialects.postgresql.JSON, server_default="{}"),
        sa.Column("target_adoption_pct", sa.Integer, server_default="100"),
        sa.Column("target_adoption_date", sa.DATE, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.UniqueConstraint("org_id", name="uq_exec_dashboard_config_org"),
    )

    # users.department column (local-auth fallback)
    op.add_column("users", sa.Column("department", sa.String(255), nullable=True))

    # agents.category column
    op.add_column("agents", sa.Column("category", sa.String(100), nullable=True))


def downgrade() -> None:
    op.drop_column("agents", "category")
    op.drop_column("users", "department")
    op.drop_table("exec_dashboard_config")
    op.drop_index("ix_user_groups_group_name", table_name="user_groups")
    op.drop_index("ix_user_groups_user_id", table_name="user_groups")
    op.drop_table("user_groups")
