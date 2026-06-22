# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only
"""rename ide fields to harness

Revision ID: 1a79544a6936
Revises: 1caa45d85720
Create Date: 2026-06-21 21:22:19.200845

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "1a79544a6936"
down_revision: str | Sequence[str] | None = "1caa45d85720"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _rename(table: str, old: str, new: str) -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns(table)}
    if old in columns and new not in columns:
        op.alter_column(table, old, new_column_name=new)


def upgrade() -> None:
    """Upgrade schema."""
    _rename("agent_download_records", "ide", "harness")
    _rename("agent_versions", "ide_configs", "harness_configs")
    _rename("agent_versions", "supported_ides", "supported_harnesses")
    _rename("agent_versions", "models_by_ide", "models_by_harness")
    _rename("agent_versions", "required_ide_features", "required_capabilities")
    _rename("agent_versions", "inferred_supported_ides", "inferred_supported_harnesses")
    for table in (
        "hook_versions",
        "mcp_versions",
        "prompt_versions",
        "sandbox_versions",
        "skill_versions",
    ):
        _rename(table, "supported_ides", "supported_harnesses")
    for table in (
        "hook_downloads",
        "mcp_downloads",
        "prompt_downloads",
        "sandbox_downloads",
        "skill_downloads",
    ):
        _rename(table, "ide", "harness")


def downgrade() -> None:
    """Downgrade schema."""
    _rename("agent_download_records", "harness", "ide")
    _rename("agent_versions", "harness_configs", "ide_configs")
    _rename("agent_versions", "supported_harnesses", "supported_ides")
    _rename("agent_versions", "models_by_harness", "models_by_ide")
    _rename("agent_versions", "required_capabilities", "required_ide_features")
    _rename("agent_versions", "inferred_supported_harnesses", "inferred_supported_ides")
    for table in (
        "hook_versions",
        "mcp_versions",
        "prompt_versions",
        "sandbox_versions",
        "skill_versions",
    ):
        _rename(table, "supported_harnesses", "supported_ides")
    for table in (
        "hook_downloads",
        "mcp_downloads",
        "prompt_downloads",
        "sandbox_downloads",
        "skill_downloads",
    ):
        _rename(table, "harness", "ide")
