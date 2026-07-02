# SPDX-FileCopyrightText: 2026 kilqwe <shreyas0514@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Tests for Pi IDE adapter config generation (PiAdapter.format_config)."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

from services.ide.pi import PiAdapter

# Helper Functions and Fixtures


def _mock_ctx(
    *,
    rules_content: str | None = None,
    mcp_configs: dict | None = None,
    skill_configs: list | None = None,
    scope: str = "project",
) -> MagicMock:
    """Return a minimal fake ConfigContext for PiAdapter."""
    ctx = MagicMock()
    ctx.safe_name = "test-agent"
    ctx.rules_content = rules_content
    ctx.mcp_configs = mcp_configs
    ctx.skill_configs = skill_configs
    ctx.options = {"scope": scope}
    return ctx


# Tests


class TestPiAdapterMcpConfig:
    """MCP config generation produces valid JSON matching Pi expected schema."""

    def test_mcp_config_present_in_output(self):
        ctx = _mock_ctx(
            mcp_configs={"fs-server": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem"]}}
        )
        result = PiAdapter().format_config(ctx)
        assert "mcp_config" in result

    def test_mcp_config_content_is_json_serializable(self):
        ctx = _mock_ctx(mcp_configs={"fs-server": {"command": "npx", "args": []}})
        result = PiAdapter().format_config(ctx)
        # Must round-trip through JSON without error
        serialized = json.dumps(result["mcp_config"]["content"])
        parsed = json.loads(serialized)
        assert "mcpServers" in parsed

    def test_mcp_config_wraps_servers_under_mcp_servers_key(self):
        servers = {"my-server": {"command": "python", "args": ["-m", "myserver"]}}
        ctx = _mock_ctx(mcp_configs=servers)
        result = PiAdapter().format_config(ctx)
        assert result["mcp_config"]["content"]["mcpServers"] == servers

    def test_mcp_config_path_set_for_project_scope(self):
        ctx = _mock_ctx(mcp_configs={"s": {}}, scope="project")
        result = PiAdapter().format_config(ctx)
        # Project-scope path should be a non-empty string
        assert isinstance(result["mcp_config"]["path"], str)
        assert result["mcp_config"]["path"]


class TestPiAdapterSkillFile:
    """Skill file generation writes correctly formatted skill components."""

    def test_skill_components_present_in_output(self):
        skills = [{"name": "review", "content": "## Review\nDo a code review."}]
        ctx = _mock_ctx(skill_configs=skills)
        result = PiAdapter().format_config(ctx)
        assert "skill_components" in result

    def test_skill_components_match_input(self):
        skills = [{"name": "review", "content": "## Review\nDo a code review."}]
        ctx = _mock_ctx(skill_configs=skills)
        result = PiAdapter().format_config(ctx)
        assert result["skill_components"] == skills

    def test_multiple_skills_all_present(self):
        skills = [
            {"name": "review", "content": "## Review"},
            {"name": "test", "content": "## Test"},
        ]
        ctx = _mock_ctx(skill_configs=skills)
        result = PiAdapter().format_config(ctx)
        assert len(result["skill_components"]) == 2


class TestPiAdapterHookScript:
    """Rules/hook file generation includes expected path and content (AGENTS.md)."""

    def test_rules_file_present_when_rules_content_set(self):
        ctx = _mock_ctx(rules_content="You are a helpful agent.")
        result = PiAdapter().format_config(ctx)
        assert "rules_file" in result

    def test_rules_file_content_matches_input(self):
        content = "You are a helpful agent.\n\n## Skills\n- review"
        ctx = _mock_ctx(rules_content=content)
        result = PiAdapter().format_config(ctx)
        assert result["rules_file"]["content"] == content

    def test_rules_file_path_contains_agents_md(self):
        ctx = _mock_ctx(rules_content="some prompt")
        result = PiAdapter().format_config(ctx)
        assert "AGENTS.md" in result["rules_file"]["path"]


class TestPiAdapterEdgeCases:
    """Edge cases: empty/None inputs produce no output keys, no crash."""

    def test_empty_context_returns_empty_dict(self):
        ctx = _mock_ctx()  # all None by default
        result = PiAdapter().format_config(ctx)
        assert result == {}

    def test_no_mcp_config_key_when_mcp_configs_is_none(self):
        ctx = _mock_ctx(rules_content="hi")
        result = PiAdapter().format_config(ctx)
        assert "mcp_config" not in result

    def test_no_skill_components_key_when_skill_configs_is_none(self):
        ctx = _mock_ctx(rules_content="hi")
        result = PiAdapter().format_config(ctx)
        assert "skill_components" not in result

    def test_no_rules_file_key_when_rules_content_is_none(self):
        ctx = _mock_ctx(mcp_configs={"s": {}})
        result = PiAdapter().format_config(ctx)
        assert "rules_file" not in result

    def test_ide_name_is_pi(self):
        assert PiAdapter().ide_name == "pi"
