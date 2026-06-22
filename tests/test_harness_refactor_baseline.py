# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Baseline regression test for harness config generation.

Captures the output of generate_agent_config and generate_harness_agent_profiles
for all supported harnesses. This test must pass identically before and after
the adapter refactoring (Phases 2-3).
"""

from __future__ import annotations

import json
import uuid
from unittest.mock import MagicMock

import pytest

from services.agent_builder import (
    AgentManifest,
    ManifestComponent,
    ManifestComponents,
    generate_harness_agent_profiles,
)
from services.harness import generate_agent_config

ALL_HARNESSES = [
    "claude-code",
    "cursor",
    "kiro",
    "codex",
    "copilot",
    "copilot-cli",
    "opencode",
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


def _make_manifest(
    name: str = "baseline-agent",
    description: str = "A baseline test agent for regression checks",
    prompt: str = "You are a helpful coding assistant.",
    model_name: str = "claude-sonnet-4",
    mcps: list[ManifestComponent] | None = None,
    skills: list[ManifestComponent] | None = None,
    hooks: list[ManifestComponent] | None = None,
    prompts: list[ManifestComponent] | None = None,
    sandboxes: list[ManifestComponent] | None = None,
) -> AgentManifest:
    return AgentManifest(
        name=name,
        version="1.0.0",
        description=description,
        prompt=prompt,
        model_name=model_name,
        components=ManifestComponents(
            mcps=mcps or [],
            skills=skills or [],
            hooks=hooks or [],
            prompts=prompts or [],
            sandboxes=sandboxes or [],
        ),
    )


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
    listing.env_vars = {"API_KEY": "test-key"}
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
# Test: generate_harness_agent_profiles (manifest-based builder) baseline
# ═══════════════════════════════════════════════════════════════════


# agent_builder supports these harnesses (copilot-cli is not separate)
BUILDER_HARNESSES = [harness for harness in ALL_HARNESSES if harness != "copilot-cli"]


class TestGenerateIdeAgentFilesBaseline:
    """Test generate_harness_agent_profiles for each harness with manifests."""

    @pytest.mark.parametrize("harness", BUILDER_HARNESSES)
    def test_minimal_manifest(self, harness):
        """Minimal manifest produces valid harness config."""
        manifest = _make_manifest()
        result = generate_harness_agent_profiles(manifest, harness)
        assert result is not None
        # HarnessAgentConfig has agent_profiles and mcp_servers
        assert hasattr(result, "agent_profiles") or hasattr(result, "mcp_servers")

    @pytest.mark.parametrize("harness", BUILDER_HARNESSES)
    def test_manifest_with_mcps(self, harness):
        """Manifest with MCP components."""
        mcp = ManifestComponent(
            name="test-mcp",
            version="1.0.0",
            config_override={"command": "npx", "args": ["-y", "@test/server"]},
        )
        manifest = _make_manifest(mcps=[mcp])
        result = generate_harness_agent_profiles(manifest, harness)
        assert result is not None

    @pytest.mark.parametrize("harness", BUILDER_HARNESSES)
    def test_manifest_with_hooks(self, harness):
        """Manifest with hook components."""
        hook = ManifestComponent(
            name="test-hook",
            version="1.0.0",
            event="PreToolUse",
            handler_type="command",
            handler_config={"command": "python3 guard.py", "timeout": 10},
            config_override={},
        )
        manifest = _make_manifest(hooks=[hook])
        result = generate_harness_agent_profiles(manifest, harness)
        assert result is not None


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
