# SPDX-FileCopyrightText: 2026 kilqwe <shreyas0514@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Tests for Pi harness adapter config generation (PiAdapter.format_config)."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

from services.harness.pi import PiAdapter


# Helper
def _mock_ctx(
    *,
    safe_name: str = "test-agent",
    rules_content: str | None = None,
    mcp_configs: dict | None = None,
    skill_configs: list | None = None,
    scope: str = "user",
) -> MagicMock:
    """Return a minimal fake ConfigContext for harness PiAdapter."""
    ctx = MagicMock()
    ctx.safe_name = safe_name
    ctx.rules_content = rules_content
    ctx.mcp_configs = mcp_configs
    ctx.skill_configs = skill_configs
    ctx.options = {"scope": scope}
    return ctx


# Tests


class TestPiAdapterMcpConfig:
    """MCP config generation produces valid JSON matching Pi expected schema."""

    def test_mcp_config_present_in_output(self):
        ctx = _mock_ctx(mcp_configs={"fs-server": {"command": "npx", "args": []}})
        result = PiAdapter().format_config(ctx)
        assert "mcp_config" in result

    def test_mcp_config_content_is_json_serializable(self):
        ctx = _mock_ctx(mcp_configs={"fs-server": {"command": "npx", "args": []}})
        result = PiAdapter().format_config(ctx)
        serialized = json.dumps(result["mcp_config"]["content"])
        parsed = json.loads(serialized)
        assert "mcpServers" in parsed

    def test_mcp_config_wraps_servers_under_mcp_servers_key(self):
        servers = {"my-server": {"command": "python", "args": ["-m", "myserver"]}}
        ctx = _mock_ctx(mcp_configs=servers)
        result = PiAdapter().format_config(ctx)
        assert result["mcp_config"]["content"]["mcpServers"] == servers

    def test_mcp_config_path_includes_agent_name(self):
        ctx = _mock_ctx(safe_name="my-agent", mcp_configs={"s": {}})
        result = PiAdapter().format_config(ctx)
        assert "my-agent" in result["mcp_config"]["path"]


class TestPiAdapterSkillFile:
    """Skill file generation writes correctly formatted SKILL.md paths."""

    def test_skill_components_present_in_output(self):
        skills = [{"name": "review", "content": "## Review\nDo a code review."}]
        ctx = _mock_ctx(skill_configs=skills)
        result = PiAdapter().format_config(ctx)
        assert "skill_components" in result

    def test_skill_path_includes_agent_name(self):
        skills = [{"name": "review", "content": "## Review"}]
        ctx = _mock_ctx(safe_name="my-agent", skill_configs=skills)
        result = PiAdapter().format_config(ctx)
        assert "my-agent" in result["skill_components"][0]["path"]

    def test_skill_path_includes_skill_name(self):
        skills = [{"name": "review", "content": "## Review"}]
        ctx = _mock_ctx(safe_name="my-agent", skill_configs=skills)
        result = PiAdapter().format_config(ctx)
        assert "review" in result["skill_components"][0]["path"]

    def test_multiple_skills_each_get_own_path(self):
        skills = [
            {"name": "review", "content": "## Review"},
            {"name": "test", "content": "## Test"},
        ]
        ctx = _mock_ctx(safe_name="my-agent", skill_configs=skills)
        result = PiAdapter().format_config(ctx)
        paths = [s["path"] for s in result["skill_components"]]
        assert paths[0] != paths[1]
        assert "review" in paths[0]
        assert "test" in paths[1]


class TestPiAdapterAgentProfile:
    """Agent profile (AGENTS.md) generation includes agent name in path."""

    def test_agent_profile_present_when_rules_content_set(self):
        ctx = _mock_ctx(rules_content="You are a helpful agent.")
        result = PiAdapter().format_config(ctx)
        assert "agent_profile" in result

    def test_agent_profile_content_matches_input(self):
        content = "You are a helpful agent.\n\n## Skills\n- review"
        ctx = _mock_ctx(rules_content=content)
        result = PiAdapter().format_config(ctx)
        assert result["agent_profile"]["content"] == content

    def test_agent_profile_path_includes_agent_name(self):
        ctx = _mock_ctx(safe_name="my-agent", rules_content="some prompt")
        result = PiAdapter().format_config(ctx)
        assert "my-agent" in result["agent_profile"]["path"]

    def test_agent_profile_path_contains_agents_md(self):
        ctx = _mock_ctx(rules_content="some prompt")
        result = PiAdapter().format_config(ctx)
        assert "AGENTS.md" in result["agent_profile"]["path"]


class TestPiAdapterEdgeCases:
    """Edge cases: empty/None inputs produce no output keys, no crash."""

    def test_empty_context_returns_empty_dict(self):
        ctx = _mock_ctx()
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

    def test_no_agent_profile_key_when_rules_content_is_none(self):
        ctx = _mock_ctx(mcp_configs={"s": {}})
        result = PiAdapter().format_config(ctx)
        assert "agent_profile" not in result

    def test_harness_name_is_pi(self):
        assert PiAdapter().harness_name == "pi"
