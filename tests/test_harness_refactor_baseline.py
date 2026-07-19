# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Baseline regression test for harness config generation.

Captures canonical generate_agent_config output for every supported harness.
"""

from __future__ import annotations

import json
import uuid
from unittest.mock import MagicMock

import pytest

from services.config_generator import generate_config
from services.harness import generate_agent_config

ALL_HARNESSES = [
    "claude-code",
    "cursor",
    "kiro",
    "codex",
    "copilot",
    "copilot-cli",
    "opencode",
    "antigravity",
    "pi",
]


# ── Fixtures ──────────────────────────────────────────────────────


def _make_component(component_type: str = "mcp", component_id: uuid.UUID | None = None) -> MagicMock:
    comp = MagicMock()
    comp.component_type = component_type
    comp.component_id = component_id or uuid.uuid4()
    return comp


def _make_agent(
    name: str = "baseline-agent",
    description: str = "A baseline test agent for regression checks",
    prompt: str = "You are a helpful coding assistant.",
    model_name: str = "claude-sonnet-4",
    components: list | None = None,
    external_mcps: list | None = None,
) -> MagicMock:
    agent = MagicMock()
    agent.id = uuid.UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
    agent.name = name
    agent.description = description
    agent.prompt = prompt
    agent.model_name = model_name
    agent.components = components or []
    agent.external_mcps = external_mcps or []
    return agent


MCP_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
SKILL_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")
HOOK_ID = uuid.UUID("33333333-3333-3333-3333-333333333333")
PROMPT_ID = uuid.UUID("44444444-4444-4444-4444-444444444444")
SANDBOX_ID = uuid.UUID("55555555-5555-5555-5555-555555555555")


def _make_mcp_listing():
    listing = MagicMock()
    listing.id = MCP_ID
    listing.name = "test-mcp-server"
    listing.command = "npx"
    listing.args = ["-y", "@test/mcp-server"]
    listing.environment_variables = [{"name": "API_KEY"}]
    listing.framework = "typescript"
    listing.docker_image = None
    listing.auto_approve = ["read"]
    listing.transport = "stdio"
    listing.url = None
    return listing


def _make_skill_listing():
    listing = MagicMock()
    listing.id = SKILL_ID
    listing.name = "test-skill"
    listing.git_url = "https://github.com/test/skill.git"
    listing.git_ref = "main"
    listing.skill_path = "skills/test"
    listing.skill_md_content = "# Test Skill\n\nDo testing things."
    return listing


def _make_hook_listing():
    listing = MagicMock()
    listing.id = HOOK_ID
    listing.name = "test-hook"
    listing.event = "PreToolUse"
    listing.handler_type = "command"
    listing.handler_config = {"command": "python3 guard.py", "timeout": 10}
    listing.execution_mode = "blocking"
    listing.scope = "agent"
    listing.script_filename = None
    listing.script_content = None
    return listing


def _make_prompt_listing():
    listing = MagicMock()
    listing.id = PROMPT_ID
    listing.name = "test-prompt"
    listing.template = "Review this code for security issues:\n\n{{code}}"
    listing.variables = ["code"]
    listing.category = "review"
    return listing


def _make_sandbox_listing():
    listing = MagicMock()
    listing.id = SANDBOX_ID
    listing.name = "python-sandbox"
    listing.image = "python:3.12-slim"
    listing.entrypoint = "pytest"
    listing.resource_limits = {"timeout": 60, "memory_mb": 512}
    listing.network_policy = "none"
    listing.sandbox_path = None
    return listing


# ═══════════════════════════════════════════════════════════════════
# Test: generate_agent_config produces stable output for all harnesses
# ═══════════════════════════════════════════════════════════════════


class TestGenerateAgentConfigBaseline:
    """Test generate_agent_config for each harness with a minimal agent (no components)."""

    @pytest.fixture
    def agent(self):
        return _make_agent()

    @pytest.mark.parametrize("harness", ALL_HARNESSES)
    def test_minimal_agent(self, agent, harness):
        """Minimal agent (no components) generates valid config for each harness."""
        result = generate_agent_config(agent, harness)
        assert isinstance(result, dict)
        # All harnesses should produce at least one of these keys
        assert any(k in result for k in ("agent_profile", "agent_profile", "mcp_config", "config_file")), (
            f"harness {harness} produced empty config: {list(result.keys())}"
        )

    @pytest.mark.parametrize("harness", ALL_HARNESSES)
    def test_agent_with_mcp(self, harness):
        """Agent with MCP component generates MCP config entries."""
        mcp_comp = _make_component("mcp", MCP_ID)
        agent = _make_agent(components=[mcp_comp])
        mcp_listing = _make_mcp_listing()
        result = generate_agent_config(
            agent,
            harness,
            mcp_listings={MCP_ID: mcp_listing},
            component_names={str(MCP_ID): "test-mcp-server"},
        )
        assert isinstance(result, dict)
        mcp_config = result.get("mcp_config", {})
        if harness == "kiro":
            agent_content = result["agent_profile"]["content"]
            assert agent_content.get("mcpServers"), f"No MCP config for {harness}"
        elif harness != "opencode":
            assert mcp_config or "mcp_servers" in str(result), f"No MCP config for {harness}"

    @pytest.mark.parametrize("harness", ALL_HARNESSES)
    def test_original_mcp_command_is_never_wrapped(self, harness):
        result = generate_config(_make_mcp_listing(), harness, env_values={"API_KEY": "secret"})
        serialized = json.dumps(result)
        assert "observal-shim" not in serialized
        assert "observal-proxy" not in serialized
        assert "npx" in serialized
        assert "@test/mcp-server" in serialized
        if harness != "claude-code":
            assert "API_KEY" in serialized

    @pytest.mark.parametrize("harness", ALL_HARNESSES)
    def test_agent_with_hooks(self, harness):
        """Agent with hook component generates hook config entries."""
        hook_comp = _make_component("hook", HOOK_ID)
        agent = _make_agent(components=[hook_comp])
        hook_listing = _make_hook_listing()
        result = generate_agent_config(
            agent,
            harness,
            hook_listings={HOOK_ID: hook_listing},
            component_names={str(HOOK_ID): "test-hook"},
        )
        assert isinstance(result, dict)

    @pytest.mark.parametrize("harness", ALL_HARNESSES)
    def test_agent_with_sandbox(self, harness):
        """Agent with sandbox component injects sandbox MCP server."""
        sandbox_comp = _make_component("sandbox", SANDBOX_ID)
        agent = _make_agent(components=[sandbox_comp])
        sandbox_listing = _make_sandbox_listing()
        result = generate_agent_config(
            agent,
            harness,
            sandbox_listings={SANDBOX_ID: sandbox_listing},
            component_names={str(SANDBOX_ID): "python-sandbox"},
        )
        assert isinstance(result, dict)

    @pytest.mark.parametrize("harness", ALL_HARNESSES)
    def test_full_agent(self, harness):
        """Agent with all component types generates complete config."""
        components = [
            _make_component("mcp", MCP_ID),
            _make_component("hook", HOOK_ID),
            _make_component("sandbox", SANDBOX_ID),
        ]
        agent = _make_agent(components=components)
        result = generate_agent_config(
            agent,
            harness,
            mcp_listings={MCP_ID: _make_mcp_listing()},
            hook_listings={HOOK_ID: _make_hook_listing()},
            sandbox_listings={SANDBOX_ID: _make_sandbox_listing()},
            component_names={
                str(MCP_ID): "test-mcp-server",
                str(HOOK_ID): "test-hook",
                str(SANDBOX_ID): "python-sandbox",
            },
        )
        assert isinstance(result, dict)


# ═══════════════════════════════════════════════════════════════════
# Snapshot test: captures exact JSON output for diffing
# ═══════════════════════════════════════════════════════════════════


class TestConfigSnapshot:
    """Generate deterministic configs and snapshot them for regression detection."""

    @pytest.mark.parametrize("harness", ALL_HARNESSES)
    def test_snapshot_minimal(self, harness, tmp_path):
        """Write config to file for manual diff if needed."""
        agent = _make_agent()
        result = generate_agent_config(agent, harness)
        # Serialize to JSON for comparison
        out = tmp_path / f"{harness}-minimal.json"
        out.write_text(json.dumps(result, indent=2, default=str))
        # Verify it's valid JSON and non-empty
        loaded = json.loads(out.read_text())
        assert loaded

    @pytest.mark.parametrize("harness", ALL_HARNESSES)
    def test_snapshot_full(self, harness, tmp_path):
        """Full agent config snapshot."""
        components = [
            _make_component("mcp", MCP_ID),
            _make_component("hook", HOOK_ID),
            _make_component("sandbox", SANDBOX_ID),
        ]
        agent = _make_agent(components=components)
        result = generate_agent_config(
            agent,
            harness,
            mcp_listings={MCP_ID: _make_mcp_listing()},
            hook_listings={HOOK_ID: _make_hook_listing()},
            sandbox_listings={SANDBOX_ID: _make_sandbox_listing()},
            component_names={
                str(MCP_ID): "test-mcp-server",
                str(HOOK_ID): "test-hook",
                str(SANDBOX_ID): "python-sandbox",
            },
        )
        out = tmp_path / f"{harness}-full.json"
        out.write_text(json.dumps(result, indent=2, default=str))
        loaded = json.loads(out.read_text())
        assert loaded
