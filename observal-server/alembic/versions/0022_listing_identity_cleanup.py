"""Drop version-specific columns from listing tables (identity-only cleanup).

Revision ID: 0022
Revises: 0021
Create Date: 2026-04-30
"""

from collections.abc import Sequence
from typing import Union

from alembic import op

revision: str = "0022"
down_revision: Union[str, Sequence[str], None] = "0021"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- mcp_listings ---
    op.drop_index("ix_mcp_listings_status", table_name="mcp_listings")
    for col in [
        "version",
        "git_url",
        "git_ref",
        "description",
        "transport",
        "framework",
        "docker_image",
        "command",
        "args",
        "url",
        "headers",
        "auto_approve",
        "mcp_validated",
        "tools_schema",
        "environment_variables",
        "supported_ides",
        "setup_instructions",
        "changelog",
        "status",
        "rejection_reason",
        "download_count",
    ]:
        op.drop_column("mcp_listings", col)

    # --- skill_listings ---
    op.drop_index("ix_skill_listings_status", table_name="skill_listings")
    for col in [
        "version",
        "description",
        "git_url",
        "git_ref",
        "supported_ides",
        "status",
        "rejection_reason",
        "download_count",
        "skill_path",
        "target_agents",
        "task_type",
        "triggers",
        "slash_command",
        "has_scripts",
        "has_templates",
        "is_power",
        "power_md",
        "mcp_server_config",
        "activation_keywords",
    ]:
        op.drop_column("skill_listings", col)

    # --- hook_listings ---
    op.drop_index("ix_hook_listings_status", table_name="hook_listings")
    for col in [
        "version",
        "description",
        "git_url",
        "git_ref",
        "supported_ides",
        "status",
        "rejection_reason",
        "download_count",
        "event",
        "execution_mode",
        "priority",
        "handler_type",
        "handler_config",
        "input_schema",
        "output_schema",
        "scope",
        "tool_filter",
        "file_pattern",
    ]:
        op.drop_column("hook_listings", col)

    # --- prompt_listings ---
    op.drop_index("ix_prompt_listings_status", table_name="prompt_listings")
    for col in [
        "version",
        "description",
        "git_url",
        "git_ref",
        "supported_ides",
        "status",
        "rejection_reason",
        "download_count",
        "category",
        "template",
        "variables",
        "model_hints",
        "tags",
    ]:
        op.drop_column("prompt_listings", col)

    # --- sandbox_listings ---
    op.drop_index("ix_sandbox_listings_status", table_name="sandbox_listings")
    for col in [
        "version",
        "description",
        "git_url",
        "git_ref",
        "supported_ides",
        "status",
        "rejection_reason",
        "download_count",
        "runtime_type",
        "image",
        "dockerfile_url",
        "resource_limits",
        "network_policy",
        "allowed_mounts",
        "env_vars",
        "entrypoint",
    ]:
        op.drop_column("sandbox_listings", col)

    # --- Drop source fields from inline-only version tables ---
    # Skills, hooks, and prompts are inline content (no git repos).
    # source_url/source_ref/resolved_sha only belong on MCP and sandbox.
    for table in ["skill_versions", "hook_versions", "prompt_versions"]:
        for col in ["source_url", "source_ref", "resolved_sha"]:
            op.drop_column(table, col)


def downgrade() -> None:
    raise NotImplementedError("Clean-break migration")
