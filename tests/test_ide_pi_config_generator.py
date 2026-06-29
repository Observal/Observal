# SPDX-FileCopyrightText: 2026 Aryan Iyappan <aryaniyappan2006@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Unit tests for the Pi IDE config generator (observal-server/services/ide/pi.py).

Covers:
- MCP config generation produces valid JSON matching Pi expected schema.
- Skill file generation writes correctly formatted SKILL.md entries.
- Pi hook spec returns extension-type metadata with expected event wiring.
- Edge case: empty component list produces no files (no crash).
"""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock

from services.ide import generate_agent_config

# ── Helpers ───────────────────────────────────────────────────────


def _make_agent(
    name: str = "pi-test-agent",
    description: str = "A Pi test agent",
    prompt: str = "You are a Pi assistant.",
    model_name: str = "claude-sonnet-4",
    components: list | None = None,
    external_mcps: list | None = None,
) -> MagicMock:
    agent = MagicMock()
    agent.id = uuid.uuid4()
    agent.name = name
    agent.description = description
    agent.prompt = prompt
    agent.model_name = model_name
    agent.components = components or []
    agent.external_mcps = external_mcps or []
    return agent


def _make_component(component_type: str = "mcp", component_id: uuid.UUID | None = None) -> MagicMock:
    comp = MagicMock()
    comp.component_type = component_type
    comp.component_id = component_id or uuid.uuid4()
    return comp


# ═══════════════════════════════════════════════════════════════════
# 1. MCP config generation — Pi expected schema
# ═══════════════════════════════════════════════════════════════════


class TestPiMcpConfig:
    """MCP config generation produces valid JSON matching Pi expected schema."""

    def test_mcp_config_present_when_external_mcps_provided(self):
        ext = [{"name": "my-mcp", "command": "npx", "args": ["-y", "my-mcp"]}]
        agent = _make_agent(external_mcps=ext)
        cfg = generate_agent_config(agent, "pi")
        assert "mcp_config" in cfg

    def test_mcp_config_has_mcpservers_key(self):
        """Pi uses the mcpServers key, matching pi-mcp-adapter expectations."""
        ext = [{"name": "my-mcp", "command": "npx", "args": ["-y", "my-mcp"]}]
        agent = _make_agent(external_mcps=ext)
        cfg = generate_agent_config(agent, "pi")
        assert "mcpServers" in cfg["mcp_config"]["content"]

    def test_mcp_config_default_scope_path_is_user_home(self):
        """Default scope is 'user', so MCP config should go to ~/.pi/agent/mcp.json."""
        ext = [{"name": "my-mcp", "command": "npx", "args": ["-y", "my-mcp"]}]
        agent = _make_agent(external_mcps=ext)
        cfg = generate_agent_config(agent, "pi")
        assert cfg["mcp_config"]["path"] == "~/.pi/agent/mcp.json"

    def test_mcp_config_project_scope_path(self):
        """Project scope writes MCP config to .pi/mcp.json."""
        ext = [{"name": "my-mcp", "command": "npx", "args": ["-y", "my-mcp"]}]
        agent = _make_agent(external_mcps=ext)
        cfg = generate_agent_config(agent, "pi", options={"scope": "project"})
        assert cfg["mcp_config"]["path"] == ".pi/mcp.json"

    def test_mcp_server_entries_appear_in_mcpservers(self):
        """Named MCP entries land inside the mcpServers dict."""
        ext = [{"name": "my-mcp", "command": "npx", "args": ["-y", "my-mcp"]}]
        agent = _make_agent(external_mcps=ext)
        cfg = generate_agent_config(agent, "pi")
        servers = cfg["mcp_config"]["content"]["mcpServers"]
        assert "my-mcp" in servers

    def test_no_mcp_config_when_no_mcps(self):
        """No mcp_config key when the agent has no MCP components."""
        agent = _make_agent()
        cfg = generate_agent_config(agent, "pi")
        assert "mcp_config" not in cfg


# ═══════════════════════════════════════════════════════════════════
# 2. Skill file generation — SKILL.md entries for Pi
# ═══════════════════════════════════════════════════════════════════


class TestPiSkillComponents:
    """Skill file generation writes correctly formatted SKILL.md entries."""

    def test_skill_components_present_when_skills_provided(self):
        """skill_configs are passed through as skill_components for Pi."""
        skill_id = uuid.uuid4()
        skill_listing = MagicMock()
        skill_listing.id = skill_id
        skill_listing.name = "my-skill"
        skill_listing.description = "A helpful skill"
        skill_listing.slash_command = "myskill"
        skill_listing.task_type = "general"
        skill_listing.git_url = "https://example.com/skill.git"
        skill_listing.git_ref = "main"
        skill_listing.skill_path = "/"
        skill_listing.skill_md_content = None
        skill_listing.script_content = None
        skill_listing.script_filename = None

        comp = _make_component("skill", skill_id)
        agent = _make_agent(components=[comp])
        cfg = generate_agent_config(agent, "pi", skill_listings={skill_id: skill_listing})
        assert "skill_components" in cfg

    def test_skill_components_includes_skill_name(self):
        """Each skill_component entry exposes the skill name."""
        skill_id = uuid.uuid4()
        skill_listing = MagicMock()
        skill_listing.id = skill_id
        skill_listing.name = "my-skill"
        skill_listing.description = "Does something"
        skill_listing.slash_command = "myskill"
        skill_listing.task_type = "general"
        skill_listing.git_url = "https://example.com/skill.git"
        skill_listing.git_ref = "main"
        skill_listing.skill_path = "/"
        skill_listing.skill_md_content = None
        skill_listing.script_content = None
        skill_listing.script_filename = None

        comp = _make_component("skill", skill_id)
        agent = _make_agent(components=[comp])
        cfg = generate_agent_config(agent, "pi", skill_listings={skill_id: skill_listing})
        names = [s["name"] for s in cfg["skill_components"]]
        assert "my-skill" in names

    def test_no_skill_components_when_no_skills(self):
        """No skill_components key when the agent has no skill components."""
        agent = _make_agent()
        cfg = generate_agent_config(agent, "pi")
        assert "skill_components" not in cfg


# ═══════════════════════════════════════════════════════════════════
# 3. Hook spec — Pi uses extension-based hooks, not file hooks
# ═══════════════════════════════════════════════════════════════════


class TestPiHookSpec:
    """Pi hook spec returns extension-type metadata with correct event wiring.

    Pi telemetry is delivered via the observal-pi npm extension (not
    a command-based hook script), so the hook type should be 'extension'
    and the package should be 'observal-pi'.
    """

    def test_hook_spec_returns_extension_type(self):
        from observal_cli.ide_specs.pi_hooks_spec import build_hooks

        spec = build_hooks()
        assert spec["hook_type"] == "extension"

    def test_hook_spec_references_observal_pi_package(self):
        """observal-pi is the telemetry extension for Pi."""
        from observal_cli.ide_specs.pi_hooks_spec import build_hooks

        spec = build_hooks()
        assert spec["package"] == "observal-pi"

    def test_hook_spec_provides_install_command(self):
        """The install command wires Pi to the Observal telemetry extension."""
        from observal_cli.ide_specs.pi_hooks_spec import build_hooks

        spec = build_hooks()
        assert "install_command" in spec
        assert "observal-pi" in spec["install_command"]

    def test_pi_adapter_does_not_produce_hooks_config_key(self):
        """Pi uses extension hooks; the server adapter never emits a hooks_config key."""
        agent = _make_agent()
        cfg = generate_agent_config(agent, "pi")
        assert "hooks_config" not in cfg


# ═══════════════════════════════════════════════════════════════════
# 4. Edge case — empty component list produces no files (no crash)
# ═══════════════════════════════════════════════════════════════════


class TestPiEdgeCases:
    """Edge case: empty component list produces no files (no crash)."""

    def test_empty_components_does_not_crash(self):
        agent = _make_agent(components=[], external_mcps=[])
        cfg = generate_agent_config(agent, "pi")
        assert isinstance(cfg, dict)

    def test_empty_components_produces_no_mcp_config(self):
        agent = _make_agent(components=[], external_mcps=[])
        cfg = generate_agent_config(agent, "pi")
        assert "mcp_config" not in cfg

    def test_empty_components_produces_no_skill_components(self):
        agent = _make_agent(components=[], external_mcps=[])
        cfg = generate_agent_config(agent, "pi")
        assert "skill_components" not in cfg

    def test_rules_file_still_present_with_empty_components(self):
        """rules_file is always produced (from the agent prompt), even with no components."""
        agent = _make_agent(prompt="Be helpful.", components=[], external_mcps=[])
        cfg = generate_agent_config(agent, "pi")
        assert "rules_file" in cfg
        assert "Be helpful." in cfg["rules_file"]["content"]


# ═══════════════════════════════════════════════════════════════════
# 5. Rules file — scope and content checks
# ═══════════════════════════════════════════════════════════════════


class TestPiRulesFile:
    def test_rules_file_default_scope_is_user_home(self):
        """Default scope is 'user', so AGENTS.md goes to ~/.pi/agent/AGENTS.md."""
        agent = _make_agent()
        cfg = generate_agent_config(agent, "pi")
        assert cfg["rules_file"]["path"] == "~/.pi/agent/AGENTS.md"

    def test_rules_file_project_scope(self):
        """Project scope writes AGENTS.md to the project root."""
        agent = _make_agent()
        cfg = generate_agent_config(agent, "pi", options={"scope": "project"})
        assert cfg["rules_file"]["path"] == "AGENTS.md"

    def test_rules_file_content_contains_prompt(self):
        agent = _make_agent(prompt="Custom Pi prompt.")
        cfg = generate_agent_config(agent, "pi")
        assert "Custom Pi prompt." in cfg["rules_file"]["content"]
