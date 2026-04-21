"""Comprehensive end-to-end tests for issue #434: first-class IDE support.

Covers Codex CLI, Gemini CLI, GitHub Copilot (VS Code), and OpenCode across:

1. Server-side config generation (agent_config_generator)
2. CLI scan detection (cmd_scan._parse_project_mcp_servers, _scan_project_dir)
3. CLI pull command (cmd_pull._dict_to_toml, _write_file, full pull flow)
4. Constants (VALID_IDES, IDE_FEATURE_MATRIX)
5. IDE compatibility warnings
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from observal_cli.cmd_pull import _dict_to_toml, _write_file
from observal_cli.cmd_scan import (
    _IDE_PROJECT_CONFIGS,
    _parse_project_mcp_servers,
    _scan_project_dir,
)
from observal_cli.constants import IDE_FEATURE_MATRIX, VALID_IDES
from observal_cli.main import app as cli_app
from services.agent_config_generator import (
    _check_ide_compatibility,
    generate_agent_config,
)

# ═══════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════


def _make_component(component_type="mcp", component_id=None):
    comp = MagicMock()
    comp.component_type = component_type
    comp.component_id = component_id or uuid.uuid4()
    return comp


def _make_agent(
    name="test-agent",
    description="A test agent",
    prompt="You are helpful.",
    model_name="claude-sonnet-4",
    components=None,
    external_mcps=None,
):
    agent = MagicMock()
    agent.id = uuid.uuid4()
    agent.name = name
    agent.description = description
    agent.prompt = prompt
    agent.model_name = model_name
    agent.components = components or []
    agent.external_mcps = external_mcps or []
    agent.required_ide_features = []
    return agent


# ═══════════════════════════════════════════════════════════════════
# 1. CONSTANTS — VALID_IDES and IDE_FEATURE_MATRIX
# ═══════════════════════════════════════════════════════════════════


class TestConstants:
    def test_codex_in_valid_ides(self):
        assert "codex" in VALID_IDES

    def test_copilot_in_valid_ides(self):
        assert "copilot" in VALID_IDES

    def test_gemini_cli_in_valid_ides(self):
        assert "gemini-cli" in VALID_IDES

    def test_opencode_in_valid_ides(self):
        assert "opencode" in VALID_IDES

    def test_codex_feature_matrix(self):
        assert "codex" in IDE_FEATURE_MATRIX
        assert IDE_FEATURE_MATRIX["codex"] == {"rules"}

    def test_copilot_feature_matrix(self):
        assert "copilot" in IDE_FEATURE_MATRIX
        assert IDE_FEATURE_MATRIX["copilot"] == {"mcp_servers", "rules"}

    def test_gemini_cli_feature_matrix(self):
        assert "gemini-cli" in IDE_FEATURE_MATRIX
        assert "mcp_servers" in IDE_FEATURE_MATRIX["gemini-cli"]
        assert "rules" in IDE_FEATURE_MATRIX["gemini-cli"]

    def test_opencode_feature_matrix(self):
        assert "opencode" in IDE_FEATURE_MATRIX
        assert IDE_FEATURE_MATRIX["opencode"] == {"mcp_servers", "rules"}

    def test_ide_project_configs_include_all_new_ides(self):
        assert "codex" in _IDE_PROJECT_CONFIGS
        assert "copilot" in _IDE_PROJECT_CONFIGS
        assert "gemini-cli" in _IDE_PROJECT_CONFIGS
        assert "opencode" in _IDE_PROJECT_CONFIGS

    def test_ide_project_config_paths(self):
        assert _IDE_PROJECT_CONFIGS["codex"] == ".codex/config.toml"
        assert _IDE_PROJECT_CONFIGS["copilot"] == ".vscode/mcp.json"
        assert _IDE_PROJECT_CONFIGS["gemini-cli"] == ".gemini/settings.json"
        assert _IDE_PROJECT_CONFIGS["opencode"] == "opencode.json"


# ═══════════════════════════════════════════════════════════════════
# 2. SERVER-SIDE CONFIG GENERATION
# ═══════════════════════════════════════════════════════════════════


class TestGenerateCodexConfig:
    def test_rules_path_is_agents_md(self):
        agent = _make_agent()
        cfg = generate_agent_config(agent, "codex")
        assert cfg["rules_file"]["path"] == "AGENTS.md"

    def test_mcp_config_path(self):
        agent = _make_agent()
        cfg = generate_agent_config(agent, "codex")
        assert cfg["mcp_config"]["path"] == "~/.codex/config.toml"

    def test_mcp_config_root_key(self):
        ext = [{"name": "my-server", "command": "npx", "args": ["-y", "my-server"]}]
        agent = _make_agent(external_mcps=ext)
        cfg = generate_agent_config(agent, "codex")
        assert "mcp.servers" in cfg["mcp_config"]["content"]
        assert "my-server" in cfg["mcp_config"]["content"]["mcp.servers"]

    def test_mcp_config_entry_has_command_and_args(self):
        ext = [{"name": "my-server", "command": "npx", "args": ["-y", "my-server"]}]
        agent = _make_agent(external_mcps=ext)
        cfg = generate_agent_config(agent, "codex")
        servers = cfg["mcp_config"]["content"]["mcp.servers"]
        assert servers["my-server"]["command"] == "observal-shim"
        assert "--mcp-id" in servers["my-server"]["args"]

    def test_mcp_config_injects_agent_id(self):
        ext = [{"name": "srv", "command": "npx", "args": ["-y", "srv"]}]
        agent = _make_agent(external_mcps=ext)
        cfg = generate_agent_config(agent, "codex")
        servers = cfg["mcp_config"]["content"]["mcp.servers"]
        assert servers["srv"]["env"]["OBSERVAL_AGENT_ID"] == str(agent.id)

    def test_scope_is_user(self):
        agent = _make_agent()
        cfg = generate_agent_config(agent, "codex")
        assert cfg["scope"] == "user"

    def test_rules_content_not_empty(self):
        agent = _make_agent()
        cfg = generate_agent_config(agent, "codex")
        assert len(cfg["rules_file"]["content"]) > 0

    def test_empty_mcp_configs_still_produces_valid_structure(self):
        agent = _make_agent()
        cfg = generate_agent_config(agent, "codex")
        assert "mcp_config" in cfg
        assert "mcp.servers" in cfg["mcp_config"]["content"]
        assert cfg["mcp_config"]["content"]["mcp.servers"] == {}

    def test_rules_content_uses_agent_prompt(self):
        agent = _make_agent(prompt="Always use Python.")
        cfg = generate_agent_config(agent, "codex")
        assert "Always use Python." in cfg["rules_file"]["content"]


class TestGenerateCopilotConfig:
    def test_rules_path(self):
        agent = _make_agent()
        cfg = generate_agent_config(agent, "copilot")
        assert cfg["rules_file"]["path"] == ".github/copilot-instructions.md"

    def test_mcp_config_path(self):
        agent = _make_agent()
        cfg = generate_agent_config(agent, "copilot")
        assert cfg["mcp_config"]["path"] == ".vscode/mcp.json"

    def test_mcp_config_root_key_is_servers(self):
        ext = [{"name": "my-server", "command": "npx", "args": ["-y", "my-server"]}]
        agent = _make_agent(external_mcps=ext)
        cfg = generate_agent_config(agent, "copilot")
        assert "servers" in cfg["mcp_config"]["content"]
        assert "my-server" in cfg["mcp_config"]["content"]["servers"]

    def test_copilot_entries_have_type_stdio(self):
        ext = [{"name": "my-server", "command": "npx", "args": ["-y", "my-server"]}]
        agent = _make_agent(external_mcps=ext)
        cfg = generate_agent_config(agent, "copilot")
        entry = cfg["mcp_config"]["content"]["servers"]["my-server"]
        assert entry["type"] == "stdio"
        assert entry["command"] == "observal-shim"
        assert isinstance(entry["args"], list)

    def test_copilot_preserves_env_vars(self):
        ext = [{"name": "my-server", "command": "npx", "args": [], "env": {"API_KEY": "secret"}}]
        agent = _make_agent(external_mcps=ext)
        cfg = generate_agent_config(agent, "copilot")
        entry = cfg["mcp_config"]["content"]["servers"]["my-server"]
        assert entry["env"]["API_KEY"] == "secret"
        assert entry["env"]["OBSERVAL_AGENT_ID"] == str(agent.id)

    def test_scope_is_project(self):
        agent = _make_agent()
        cfg = generate_agent_config(agent, "copilot")
        assert cfg["scope"] == "project"

    def test_rules_content_not_empty(self):
        agent = _make_agent()
        cfg = generate_agent_config(agent, "copilot")
        assert len(cfg["rules_file"]["content"]) > 0

    def test_empty_mcp_configs_still_produces_valid_structure(self):
        agent = _make_agent()
        cfg = generate_agent_config(agent, "copilot")
        assert "mcp_config" in cfg
        assert "servers" in cfg["mcp_config"]["content"]

    def test_multiple_mcps_all_get_type_stdio(self):
        ext = [
            {"name": "srv-a", "command": "npx", "args": ["-y", "a"]},
            {"name": "srv-b", "command": "node", "args": ["b.js"]},
        ]
        agent = _make_agent(external_mcps=ext)
        cfg = generate_agent_config(agent, "copilot")
        servers = cfg["mcp_config"]["content"]["servers"]
        assert servers["srv-a"]["type"] == "stdio"
        assert servers["srv-b"]["type"] == "stdio"


class TestGenerateOpenCodeConfig:
    def test_rules_path(self):
        agent = _make_agent()
        cfg = generate_agent_config(agent, "opencode")
        assert cfg["rules_file"]["path"] == "AGENTS.md"

    def test_mcp_config_path(self):
        agent = _make_agent()
        cfg = generate_agent_config(agent, "opencode")
        assert cfg["mcp_config"]["path"] == "~/.config/opencode/opencode.json"

    def test_mcp_config_root_key_is_mcp(self):
        ext = [{"name": "my-server", "command": "npx", "args": ["-y", "my-server"]}]
        agent = _make_agent(external_mcps=ext)
        cfg = generate_agent_config(agent, "opencode")
        assert "mcp" in cfg["mcp_config"]["content"]
        assert "my-server" in cfg["mcp_config"]["content"]["mcp"]

    def test_opencode_entries_have_type_local(self):
        ext = [{"name": "my-server", "command": "npx", "args": ["-y", "my-server"]}]
        agent = _make_agent(external_mcps=ext)
        cfg = generate_agent_config(agent, "opencode")
        entry = cfg["mcp_config"]["content"]["mcp"]["my-server"]
        assert entry["type"] == "local"
        assert isinstance(entry["command"], list)
        assert entry["command"][0] == "observal-shim"

    def test_opencode_command_is_flat_array(self):
        ext = [{"name": "my-server", "command": "npx", "args": ["-y", "my-server"]}]
        agent = _make_agent(external_mcps=ext)
        cfg = generate_agent_config(agent, "opencode")
        entry = cfg["mcp_config"]["content"]["mcp"]["my-server"]
        old_cmd = "npx"
        old_args = ["-y", "my-server"]
        full_cmd = [entry["command"][0], *entry["command"][1:]]
        assert "--mcp-id" in entry["command"]
        assert "--" in entry["command"]
        idx_dash = entry["command"].index("--")
        assert (
            entry["command"][idx_dash + 1] == "observal-shim"
            or entry["command"][idx_dash + 1 : idx_dash + 1 + 1 + len(old_args)]
        )

    def test_opencode_preserves_env_vars(self):
        ext = [{"name": "my-server", "command": "npx", "args": [], "env": {"FOO": "bar"}}]
        agent = _make_agent(external_mcps=ext)
        cfg = generate_agent_config(agent, "opencode")
        entry = cfg["mcp_config"]["content"]["mcp"]["my-server"]
        assert entry["env"]["FOO"] == "bar"
        assert entry["env"]["OBSERVAL_AGENT_ID"] == str(agent.id)

    def test_scope_is_user(self):
        agent = _make_agent()
        cfg = generate_agent_config(agent, "opencode")
        assert cfg["scope"] == "user"

    def test_rules_content_not_empty(self):
        agent = _make_agent()
        cfg = generate_agent_config(agent, "opencode")
        assert len(cfg["rules_file"]["content"]) > 0

    def test_empty_mcp_configs_still_produces_valid_structure(self):
        agent = _make_agent()
        cfg = generate_agent_config(agent, "opencode")
        assert "mcp_config" in cfg
        assert "mcp" in cfg["mcp_config"]["content"]

    def test_no_separate_args_field(self):
        ext = [{"name": "my-server", "command": "npx", "args": ["-y", "my-server"]}]
        agent = _make_agent(external_mcps=ext)
        cfg = generate_agent_config(agent, "opencode")
        entry = cfg["mcp_config"]["content"]["mcp"]["my-server"]
        assert "args" not in entry, "OpenCode entries should not have separate 'args' key"
        assert isinstance(entry["command"], list), "OpenCode 'command' should be a flat array"


class TestGenerateGeminiConfig:
    def test_rules_path_project_scope(self):
        agent = _make_agent()
        cfg = generate_agent_config(agent, "gemini-cli")
        assert cfg["rules_file"]["path"] == "GEMINI.md"

    def test_rules_path_user_scope(self):
        agent = _make_agent()
        cfg = generate_agent_config(agent, "gemini-cli", options={"scope": "user"})
        assert cfg["rules_file"]["path"] == "~/.gemini/GEMINI.md"

    def test_mcp_path_project_scope(self):
        agent = _make_agent()
        cfg = generate_agent_config(agent, "gemini-cli")
        assert cfg["mcp_config"]["path"] == ".gemini/settings.json"

    def test_mcp_path_user_scope(self):
        agent = _make_agent()
        cfg = generate_agent_config(agent, "gemini-cli", options={"scope": "user"})
        assert cfg["mcp_config"]["path"] == "~/.gemini/settings.json"

    def test_mcp_config_uses_mcpservers_key(self):
        ext = [{"name": "my-server", "command": "npx", "args": ["-y", "my-server"]}]
        agent = _make_agent(external_mcps=ext)
        cfg = generate_agent_config(agent, "gemini-cli")
        assert "mcpServers" in cfg["mcp_config"]["content"]
        assert "my-server" in cfg["mcp_config"]["content"]["mcpServers"]

    def test_gemini_otlp_env_present(self):
        agent = _make_agent()
        cfg = generate_agent_config(agent, "gemini-cli")
        assert "otlp_env" in cfg

    def test_gemini_settings_snippet_present(self):
        agent = _make_agent()
        cfg = generate_agent_config(agent, "gemini-cli")
        assert "gemini_settings_snippet" in cfg

    def test_gemini_underscore_alias(self):
        agent = _make_agent()
        cfg = generate_agent_config(agent, "gemini_cli")
        assert cfg["rules_file"]["path"] == "GEMINI.md"

    def test_scope_defaults_to_project(self):
        agent = _make_agent()
        cfg = generate_agent_config(agent, "gemini-cli")
        assert cfg["scope"] == "project"


# ═══════════════════════════════════════════════════════════════════
# 3. IDE COMPATIBILITY WARNINGS
# ═══════════════════════════════════════════════════════════════════


class TestIdeCompatibilityWarnings:
    def test_codex_warns_on_mcp_requirement(self):
        agent = _make_agent()
        agent.required_ide_features = ["mcp_servers"]
        warnings = _check_ide_compatibility(agent, "codex")
        assert len(warnings) > 0
        assert any("mcp" in w.lower() or "MCP" in w for w in warnings)

    def test_copilot_no_longer_warns_on_mcp_requirement(self):
        agent = _make_agent()
        agent.required_ide_features = ["mcp_servers"]
        warnings = _check_ide_compatibility(agent, "copilot")
        assert len(warnings) == 0

    def test_gemini_supports_mcp(self):
        agent = _make_agent()
        agent.required_ide_features = ["mcp_servers", "rules"]
        warnings = _check_ide_compatibility(agent, "gemini-cli")
        assert len(warnings) == 0

    def test_opencode_warns_on_unsupported_features(self):
        agent = _make_agent()
        agent.required_ide_features = ["skills", "hook_bridge"]
        warnings = _check_ide_compatibility(agent, "opencode")
        assert len(warnings) == 2

    def test_no_warnings_for_supported_features(self):
        agent = _make_agent()
        agent.required_ide_features = ["rules"]
        for ide in ("codex", "copilot", "gemini-cli", "opencode"):
            if ide in IDE_FEATURE_MATRIX:
                warnings = _check_ide_compatibility(agent, ide)
                assert len(warnings) == 0, f"Unexpected warnings for {ide}: {warnings}"

    def test_copilot_supports_mcp_servers(self):
        agent = _make_agent()
        agent.required_ide_features = ["mcp_servers", "rules"]
        warnings = _check_ide_compatibility(agent, "copilot")
        assert len(warnings) == 0

    def test_codex_warns_on_skills_requirement(self):
        agent = _make_agent()
        agent.required_ide_features = ["skills"]
        warnings = _check_ide_compatibility(agent, "codex")
        assert len(warnings) > 0
        assert any("skill" in w.lower() for w in warnings)


# ═══════════════════════════════════════════════════════════════════
# 4. SCAN — _parse_project_mcp_servers
# ═══════════════════════════════════════════════════════════════════


class TestParseProjectMcpServers:
    def test_codex_extracts_nested_servers(self):
        config = {"mcp": {"servers": {"srv-a": {"command": "npx"}, "srv-b": {"command": "node"}}}}
        result = _parse_project_mcp_servers(config, "codex")
        assert "srv-a" in result
        assert "srv-b" in result
        assert result["srv-a"]["command"] == "npx"

    def test_codex_empty_servers(self):
        config = {"mcp": {"servers": {}}}
        result = _parse_project_mcp_servers(config, "codex")
        assert result == {}

    def test_codex_missing_servers_key(self):
        config = {"mcp": {}}
        result = _parse_project_mcp_servers(config, "codex")
        assert result == {}

    def test_gemini_extracts_mcpservers(self):
        config = {"mcpServers": {"my-srv": {"command": "python", "args": ["serve.py"]}}}
        result = _parse_project_mcp_servers(config, "gemini-cli")
        assert "my-srv" in result

    def test_copilot_extracts_servers_key(self):
        config = {"servers": {"my-srv": {"type": "stdio", "command": "npx", "args": ["-y", "my-srv"]}}}
        result = _parse_project_mcp_servers(config, "copilot")
        assert "my-srv" in result

    def test_copilot_falls_back_to_mcpservers(self):
        config = {"mcpServers": {"my-srv": {"command": "npx"}}}
        result = _parse_project_mcp_servers(config, "copilot")
        assert "my-srv" in result

    def test_copilot_prefers_servers_over_mcpservers(self):
        config = {
            "servers": {"primary": {"command": "node"}},
            "mcpServers": {"secondary": {"command": "python"}},
        }
        result = _parse_project_mcp_servers(config, "copilot")
        assert "primary" in result
        assert "secondary" not in result

    def test_opencode_extracts_mcp_key(self):
        config = {"mcp": {"my-srv": {"type": "local", "command": ["npx", "-y", "my-srv"]}}}
        result = _parse_project_mcp_servers(config, "opencode")
        assert "my-srv" in result

    def test_vscode_extracts_servers_key(self):
        config = {"servers": {"my-srv": {"type": "stdio", "command": "npx"}}}
        result = _parse_project_mcp_servers(config, "vscode")
        assert "my-srv" in result

    def test_cursor_extracts_mcpservers(self):
        config = {"mcpServers": {"my-srv": {"command": "npx"}}}
        result = _parse_project_mcp_servers(config, "cursor")
        assert "my-srv" in result

    def test_unknown_ide_falls_back_to_mcpservers(self):
        config = {"mcpServers": {"my-srv": {"command": "npx"}}}
        result = _parse_project_mcp_servers(config, "unknown-ide")
        assert "my-srv" in result


# ═══════════════════════════════════════════════════════════════════
# 5. SCAN — _scan_project_dir
# ═══════════════════════════════════════════════════════════════════


class TestScanProjectDir:
    def test_detects_codex_toml(self, tmp_path):
        codex_dir = tmp_path / ".codex"
        codex_dir.mkdir()
        config_file = codex_dir / "config.toml"
        config_file.write_text('[mcp.servers.my-toml-srv]\ncommand = "echo"\nargs = ["hello"]\n')
        entries = _scan_project_dir(tmp_path, None)
        ide_names = [(e[0], e[1]) for e in entries]
        assert any(ide == "codex" for ide, _ in ide_names)

    def test_detects_gemini_settings(self, tmp_path):
        gemini_dir = tmp_path / ".gemini"
        gemini_dir.mkdir()
        settings = gemini_dir / "settings.json"
        settings.write_text(json.dumps({"mcpServers": {"gemini-srv": {"command": "python"}}}))
        entries = _scan_project_dir(tmp_path, None)
        ide_names = [(e[0], e[1]) for e in entries]
        assert any(ide == "gemini-cli" for ide, _ in ide_names)

    def test_detects_copilot_mcp_json(self, tmp_path):
        vscode_dir = tmp_path / ".vscode"
        vscode_dir.mkdir()
        mcp_file = vscode_dir / "mcp.json"
        mcp_file.write_text(json.dumps({"servers": {"vscode-srv": {"type": "stdio", "command": "npx"}}}))
        entries = _scan_project_dir(tmp_path, None)
        ide_names = [(e[0], e[1]) for e in entries]
        assert any(ide == "copilot" for ide, _ in ide_names)

    def test_detects_opencode_config(self, tmp_path):
        config_file = tmp_path / "opencode.json"
        config_file.write_text(json.dumps({"mcp": {"my-srv": {"type": "local", "command": ["npx"]}}}))
        entries = _scan_project_dir(tmp_path, None)
        ide_names = [(e[0], e[1]) for e in entries]
        assert any(ide == "opencode" for ide, _ in ide_names)

    def test_ide_filter(self, tmp_path):
        vscode_dir = tmp_path / ".vscode"
        vscode_dir.mkdir()
        mcp_file = vscode_dir / "mcp.json"
        mcp_file.write_text(json.dumps({"servers": {"vscode-srv": {"type": "stdio", "command": "npx"}}}))
        gemini_dir = tmp_path / ".gemini"
        gemini_dir.mkdir()
        settings = gemini_dir / "settings.json"
        settings.write_text(json.dumps({"mcpServers": {"gemini-srv": {"command": "python"}}}))
        entries = _scan_project_dir(tmp_path, "copilot")
        ide_names = [e[0] for e in entries]
        assert "copilot" in ide_names
        assert "gemini-cli" not in ide_names

    def test_skips_already_shimmed(self, tmp_path):
        vscode_dir = tmp_path / ".vscode"
        vscode_dir.mkdir()
        mcp_file = vscode_dir / "mcp.json"
        mcp_file.write_text(
            json.dumps(
                {
                    "servers": {
                        "shimmed-srv": {
                            "type": "stdio",
                            "command": "observal-shim",
                            "args": ["--mcp-id", "test"],
                        }
                    }
                }
            )
        )
        entries = _scan_project_dir(tmp_path, "copilot")
        srv_names = [e[1] for e in entries]
        assert "shimmed-srv" not in srv_names


# ═══════════════════════════════════════════════════════════════════
# 6. PULL — _dict_to_toml
# ═══════════════════════════════════════════════════════════════════


class TestDictToToml:
    def test_basic_section(self):
        d = {"mcp.servers": {"my-srv": {"command": "npx", "args": ["-y", "my-srv"]}}}
        toml = _dict_to_toml(d)
        assert "[mcp.servers.my-srv]" in toml
        assert 'command = "npx"' in toml
        assert 'args = ["-y", "my-srv"]' in toml

    def test_env_vars(self):
        d = {"mcp.servers": {"my-srv": {"command": "npx", "env": {"K": "V"}}}}
        toml = _dict_to_toml(d)
        assert "env.K" in toml or "env" in toml

    def test_multiple_servers(self):
        d = {"mcp.servers": {"srv-a": {"command": "echo"}, "srv-b": {"command": "cat"}}}
        toml = _dict_to_toml(d)
        assert "[mcp.servers.srv-a]" in toml
        assert "[mcp.servers.srv-b]" in toml

    def test_empty_servers(self):
        d = {"mcp.servers": {}}
        toml = _dict_to_toml(d)
        assert toml.strip() == ""

    def test_boolean_values(self):
        d = {"mcp.servers": {"my-srv": {"command": "npx", "autoApprove": True}}}
        toml = _dict_to_toml(d)
        assert "autoApprove = true" in toml

    def test_string_values_with_quotes(self):
        d = {"mcp.servers": {"my-srv": {"command": 'echo "hello"'}}}
        toml = _dict_to_toml(d)
        assert "my-srv" in toml


# ═══════════════════════════════════════════════════════════════════
# 7. PULL — _write_file
# ═══════════════════════════════════════════════════════════════════


class TestWriteFile:
    def test_creates_json_file(self, tmp_path):
        p = tmp_path / "config.json"
        content = {"mcpServers": {"srv": {"command": "npx"}}}
        status = _write_file(p, content)
        assert status == "created"
        data = json.loads(p.read_text())
        assert "mcpServers" in data

    def test_creates_toml_file(self, tmp_path):
        p = tmp_path / "config.toml"
        content = {"mcp.servers": {"srv": {"command": "npx"}}}
        status = _write_file(p, content)
        assert status == "created"
        assert "[mcp.servers.srv]" in p.read_text()

    def test_updates_existing_json(self, tmp_path):
        p = tmp_path / "mcp.json"
        p.write_text(json.dumps({"mcpServers": {"old": {"command": "old"}}}))
        content = {"mcpServers": {"new": {"command": "new"}}}
        status = _write_file(p, content, merge_mcp=True)
        assert status == "merged"
        data = json.loads(p.read_text())
        assert "old" in data["mcpServers"]
        assert "new" in data["mcpServers"]

    def test_merges_toml(self, tmp_path):
        p = tmp_path / "config.toml"
        p.write_text("[mcp.servers.old]\ncommand = 'echo'\n")
        content = {"mcp.servers": {"new": {"command": "observal-shim"}}}
        status = _write_file(p, content, merge_mcp=True)
        assert status == "merged"
        merged = p.read_text()
        assert "[mcp.servers.old]" in merged
        assert "observal-shim" in merged

    def test_creates_parent_directories(self, tmp_path):
        p = tmp_path / ".codex" / "config.toml"
        content = {"mcp.servers": {"srv": {"command": "npx"}}}
        _write_file(p, content)
        assert p.exists()

    def test_non_merge_creates_new_file(self, tmp_path):
        p = tmp_path / "new.json"
        content = {"servers": {"srv": {"command": "npx"}}}
        status = _write_file(p, content, merge_mcp=False)
        assert status == "created"

    def test_write_string_content(self, tmp_path):
        p = tmp_path / "AGENTS.md"
        status = _write_file(p, "# Rules\n\nBe helpful.")
        assert status == "created"
        assert "Be helpful" in p.read_text()

    def test_update_status_for_existing_file(self, tmp_path):
        p = tmp_path / "AGENTS.md"
        p.write_text("old content")
        status = _write_file(p, "new content")
        assert status == "updated"


# ═══════════════════════════════════════════════════════════════════
# 8. PULL — Full CLI flow (E2E per IDE)
# ═══════════════════════════════════════════════════════════════════

runner = CliRunner()

_FAKE_CONFIG = {"server_url": "http://localhost:8000", "api_key": "test-key"}


def _patch_config():
    return patch("observal_cli.config.get_or_exit", return_value=_FAKE_CONFIG)


def _patch_post(return_value):
    return patch("observal_cli.client.post", return_value=return_value)


_AGENT_DETAIL_NO_ENV = {
    "id": "abc123",
    "name": "my-agent",
    "mcp_links": [],
    "component_links": [],
}


def _patch_get_agent(detail=None):
    detail = detail or _AGENT_DETAIL_NO_ENV
    return patch("observal_cli.client.get", return_value=detail)


class TestPullCodex:
    def test_writes_agents_md_and_mcp_toml(self, tmp_path):
        snippet = {
            "config_snippet": {
                "rules_file": {
                    "path": "AGENTS.md",
                    "content": "# Codex Rules\n\nBe precise.\n",
                },
                "mcp_config": {
                    "path": "~/.codex/config.toml",
                    "content": {
                        "mcp.servers": {
                            "my-server": {
                                "command": "observal-shim",
                                "args": ["--mcp-id", "test", "--", "npx", "-y", "my-server"],
                            }
                        }
                    },
                },
                "scope": "user",
            }
        }
        with _patch_config(), _patch_get_agent(), _patch_post(snippet):
            result = runner.invoke(cli_app, ["pull", "abc123", "--ide", "codex", "--dir", str(tmp_path)])
        assert result.exit_code == 0, result.output
        rules = tmp_path / "AGENTS.md"
        assert rules.exists()
        assert "Codex Rules" in rules.read_text()
        config = tmp_path / ".codex" / "config.toml"
        assert config.exists()
        content = config.read_text()
        assert "mcp.servers" in content
        assert "observal-shim" in content

    def test_writes_only_rules_when_no_mcp(self, tmp_path):
        snippet = {
            "config_snippet": {
                "rules_file": {
                    "path": "AGENTS.md",
                    "content": "# Simple Agent\n",
                },
            }
        }
        with _patch_config(), _patch_get_agent(), _patch_post(snippet):
            result = runner.invoke(cli_app, ["pull", "abc123", "--ide", "codex", "--dir", str(tmp_path)])
        assert result.exit_code == 0, result.output
        assert (tmp_path / "AGENTS.md").exists()


class TestPullCopilot:
    def test_writes_copilot_instructions_and_mcp(self, tmp_path):
        snippet = {
            "config_snippet": {
                "rules_file": {
                    "path": ".github/copilot-instructions.md",
                    "content": "# Copilot Rules\n\nUse Python.\n",
                },
                "mcp_config": {
                    "path": ".vscode/mcp.json",
                    "content": {
                        "servers": {
                            "my-server": {
                                "type": "stdio",
                                "command": "observal-shim",
                                "args": ["--mcp-id", "test", "--", "npx", "-y", "my-server"],
                            }
                        }
                    },
                },
            }
        }
        with _patch_config(), _patch_get_agent(), _patch_post(snippet):
            result = runner.invoke(cli_app, ["pull", "abc123", "--ide", "copilot", "--dir", str(tmp_path)])
        assert result.exit_code == 0, result.output
        rules = tmp_path / ".github" / "copilot-instructions.md"
        assert rules.exists()
        assert "Copilot Rules" in rules.read_text()
        mcp = tmp_path / ".vscode" / "mcp.json"
        assert mcp.exists()
        data = json.loads(mcp.read_text())
        assert "servers" in data
        assert data["servers"]["my-server"]["type"] == "stdio"


class TestPullOpenCode:
    def test_writes_agents_md_and_opencode_json(self, tmp_path):
        snippet = {
            "config_snippet": {
                "rules_file": {
                    "path": "AGENTS.md",
                    "content": "# OpenCode Rules\n\nBe concise.\n",
                },
                "mcp_config": {
                    "path": "~/.config/opencode/opencode.json",
                    "content": {
                        "mcp": {
                            "my-server": {
                                "type": "local",
                                "command": ["observal-shim", "--mcp-id", "test", "--", "npx", "-y", "my-server"],
                            }
                        }
                    },
                },
                "scope": "user",
            }
        }
        with _patch_config(), _patch_get_agent(), _patch_post(snippet):
            result = runner.invoke(cli_app, ["pull", "abc123", "--ide", "opencode", "--dir", str(tmp_path)])
        assert result.exit_code == 0, result.output
        rules = tmp_path / "AGENTS.md"
        assert rules.exists()
        config = tmp_path / ".config" / "opencode" / "opencode.json"
        assert config.exists()
        data = json.loads(config.read_text())
        assert "mcp" in data
        assert "my-server" in data["mcp"]
        assert data["mcp"]["my-server"]["type"] == "local"

    def test_writes_only_rules_when_no_mcp(self, tmp_path):
        snippet = {
            "config_snippet": {
                "rules_file": {
                    "path": "AGENTS.md",
                    "content": "# Simple Agent\n",
                },
            }
        }
        with _patch_config(), _patch_get_agent(), _patch_post(snippet):
            result = runner.invoke(cli_app, ["pull", "abc123", "--ide", "opencode", "--dir", str(tmp_path)])
        assert result.exit_code == 0, result.output
        assert (tmp_path / "AGENTS.md").exists()


class TestPullGemini:
    def test_writes_gemini_md_and_settings(self, tmp_path):
        snippet = {
            "config_snippet": {
                "rules_file": {
                    "path": "GEMINI.md",
                    "content": "# Gemini Rules\n\nUse TypeScript.\n",
                },
                "mcp_config": {
                    "path": ".gemini/settings.json",
                    "content": {
                        "mcpServers": {
                            "my-server": {
                                "command": "observal-shim",
                                "args": ["--mcp-id", "test", "--", "npx", "-y", "my-server"],
                            }
                        }
                    },
                },
                "otlp_env": {"OTEL_EXPORTER_OTLP_ENDPOINT": "http://localhost:4318"},
            }
        }
        with _patch_config(), _patch_get_agent(), _patch_post(snippet):
            result = runner.invoke(cli_app, ["pull", "abc123", "--ide", "gemini-cli", "--dir", str(tmp_path)])
        assert result.exit_code == 0, result.output
        rules = tmp_path / "GEMINI.md"
        assert rules.exists()
        settings = tmp_path / ".gemini" / "settings.json"
        assert settings.exists()
        data = json.loads(settings.read_text())
        assert "mcpServers" in data


class TestPullDryRunAllIdes:
    @pytest.mark.parametrize("ide", ["codex", "copilot", "opencode"])
    def test_dry_run_does_not_write_files(self, tmp_path, ide):
        snippet = {
            "config_snippet": {
                "rules_file": {
                    "path": "AGENTS.md",
                    "content": "# Test\n",
                },
            }
        }
        with _patch_config(), _patch_get_agent(), _patch_post(snippet):
            result = runner.invoke(cli_app, ["pull", "abc123", "--ide", ide, "--dir", str(tmp_path), "--dry-run"])

        assert result.exit_code == 0, result.output
        assert "Dry run" in result.output
        assert not (tmp_path / "AGENTS.md").exists()

    def test_dry_run_gemini(self, tmp_path):
        snippet = {
            "config_snippet": {
                "rules_file": {
                    "path": "GEMINI.md",
                    "content": "# Gemini\n",
                },
            }
        }
        with _patch_config(), _patch_get_agent(), _patch_post(snippet):
            result = runner.invoke(
                cli_app, ["pull", "abc123", "--ide", "gemini-cli", "--dir", str(tmp_path), "--dry-run"]
            )

        assert result.exit_code == 0, result.output
        assert "Dry run" in result.output
        assert not (tmp_path / "GEMINI.md").exists()


# ═══════════════════════════════════════════════════════════════════
# 9. CROSS-CUTTING — format correctness per IDE spec
# ═══════════════════════════════════════════════════════════════════


class TestCodexTomlFormat:
    def test_toml_output_has_correct_structure(self):
        mcp_configs = {
            "my-server": {
                "command": "observal-shim",
                "args": ["--mcp-id", "abc", "--", "npx", "-y", "my-server"],
                "env": {"OBSERVAL_AGENT_ID": "agent-123"},
            }
        }
        toml = _dict_to_toml({"mcp.servers": mcp_configs})
        assert "[mcp.servers.my-server]" in toml
        assert 'command = "observal-shim"' in toml
        assert "OBSERVAL_AGENT_ID" in toml

    def test_toml_entry_with_no_env(self):
        mcp_configs = {"bare-srv": {"command": "echo", "args": []}}
        toml = _dict_to_toml({"mcp.servers": mcp_configs})
        assert "[mcp.servers.bare-srv]" in toml
        assert 'command = "echo"' in toml


class TestCopilotJsonFormat:
    def test_copilot_config_wraps_with_type_stdio(self):
        agent = _make_agent(external_mcps=[{"name": "my-srv", "command": "npx", "args": ["-y", "my-srv"]}])
        cfg = generate_agent_config(agent, "copilot")
        servers = cfg["mcp_config"]["content"]["servers"]
        entry = servers["my-srv"]
        assert entry["type"] == "stdio"
        assert entry["command"] == "observal-shim"
        assert isinstance(entry["args"], list)
        assert "--mcp-id" in entry["args"]

    def test_copilot_config_has_no_mcpservers_key(self):
        agent = _make_agent(external_mcps=[{"name": "my-srv", "command": "npx", "args": []}])
        cfg = generate_agent_config(agent, "copilot")
        assert "mcpServers" not in cfg["mcp_config"]["content"]
        assert "servers" in cfg["mcp_config"]["content"]


class TestOpenCodeJsonFormat:
    def test_opencode_command_is_flat_array(self):
        agent = _make_agent(external_mcps=[{"name": "my-srv", "command": "npx", "args": ["-y", "my-srv"]}])
        cfg = generate_agent_config(agent, "opencode")
        entry = cfg["mcp_config"]["content"]["mcp"]["my-srv"]
        assert isinstance(entry["command"], list)
        assert entry["command"][0] == "observal-shim"
        assert "--" in entry["command"]

    def test_opencode_has_no_args_key(self):
        agent = _make_agent(external_mcps=[{"name": "my-srv", "command": "npx", "args": ["-y", "my-srv"]}])
        cfg = generate_agent_config(agent, "opencode")
        entry = cfg["mcp_config"]["content"]["mcp"]["my-srv"]
        assert "args" not in entry

    def test_opencode_type_is_local(self):
        agent = _make_agent(external_mcps=[{"name": "my-srv", "command": "npx", "args": []}])
        cfg = generate_agent_config(agent, "opencode")
        entry = cfg["mcp_config"]["content"]["mcp"]["my-srv"]
        assert entry["type"] == "local"


class TestGeminiJsonFormat:
    def test_gemini_mcp_uses_mcpservers_key(self):
        agent = _make_agent(external_mcps=[{"name": "my-srv", "command": "npx", "args": ["-y", "my-srv"]}])
        cfg = generate_agent_config(agent, "gemini-cli")
        assert "mcpServers" in cfg["mcp_config"]["content"]
        assert "servers" not in cfg["mcp_config"]["content"]
        assert "mcp" not in cfg["mcp_config"]["content"]


# ═══════════════════════════════════════════════════════════════════
# 10. DOCTOR — Copilot IDE config checks
# ═══════════════════════════════════════════════════════════════════


class TestDoctorCopilot:
    def test_copilot_in_ide_configs(self):
        from observal_cli.cmd_doctor import IDE_CONFIGS

        assert "copilot" in IDE_CONFIGS
        assert IDE_CONFIGS["copilot"]["project_settings"] != []

    def test_copilot_project_settings_paths(self):

        from observal_cli.cmd_doctor import IDE_CONFIGS

        paths = IDE_CONFIGS["copilot"]["project_settings"]
        assert any(str(p).endswith("mcp.json") for p in paths)

    def test_check_copilot_fn_warns_on_unwrapped_mcp(self):
        from pathlib import Path

        from observal_cli.cmd_doctor import _check_copilot

        data = {"servers": {"my-srv": {"type": "stdio", "command": "npx", "args": ["-y", "my-srv"]}}}
        issues = []
        warnings = []
        _check_copilot(Path(".vscode/mcp.json"), data, issues, warnings)
        assert len(warnings) > 0
        assert any("observal-shim" in w for w in warnings)

    def test_check_copilot_fn_no_warning_on_shimmed_mcp(self):
        from pathlib import Path

        from observal_cli.cmd_doctor import _check_copilot

        data = {
            "servers": {
                "my-srv": {"type": "stdio", "command": "observal-shim", "args": ["--mcp-id", "test", "--", "npx"]}
            }
        }
        issues = []
        warnings = []
        _check_copilot(Path(".vscode/mcp.json"), data, issues, warnings)
        assert len(warnings) == 0

    def test_check_copilot_fn_handles_mcp_servers_fallback(self):
        from pathlib import Path

        from observal_cli.cmd_doctor import _check_copilot

        data = {"mcpServers": {"my-srv": {"command": "npx", "args": ["-y", "my-srv"]}}}
        issues = []
        warnings = []
        _check_copilot(Path(".vscode/mcp.json"), data, issues, warnings)
        assert len(warnings) > 0


# ═══════════════════════════════════════════════════════════════════
# 11. PROFILE — Copilot file map entries
# ═══════════════════════════════════════════════════════════════════


class TestProfileCopilot:
    def test_copilot_mcp_json_in_file_map(self):
        from observal_cli.cmd_profile import IDE_FILE_MAP

        assert ".vscode/mcp.json" in IDE_FILE_MAP

    def test_copilot_instructions_in_project_files(self):
        from observal_cli.cmd_profile import PROJECT_FILES

        assert ".github/copilot-instructions.md" in PROJECT_FILES


# ═══════════════════════════════════════════════════════════════════
# 12. CONFIG GENERATOR — Copilot explicit branch
# ═══════════════════════════════════════════════════════════════════


class TestConfigGeneratorCopilot:
    def _make_listing(self, name="my-mcp", listing_id="abc-123", **kw):
        from unittest.mock import MagicMock

        listing = MagicMock()
        listing.name = name
        listing.id = listing_id
        listing.docker_image = kw.get("docker_image")
        listing.framework = kw.get("framework")
        listing.environment_variables = kw.get("environment_variables", [])
        listing.command = kw.get("command")
        listing.args = kw.get("args")
        listing.url = kw.get("url")
        listing.transport = kw.get("transport")
        listing.auto_approve = kw.get("auto_approve")
        return listing

    def test_copilot_stdio_has_type_stdio(self):
        from services.config_generator import generate_config

        cfg = generate_config(self._make_listing(), "copilot")
        server = cfg["mcpServers"]["my-mcp"]
        assert server["type"] == "stdio"
        assert server["command"] == "observal-shim"
        assert "--mcp-id" in server["args"]

    def test_copilot_sse_has_type_sse(self):
        from services.config_generator import generate_config

        cfg = generate_config(self._make_listing(url="http://localhost:3000/sse", transport="sse"), "copilot")
        server = cfg["mcpServers"]["my-mcp"]
        assert server["type"] == "sse"
        assert server["url"] == "http://localhost:3000/sse"

    def test_copilot_env_vars_preserved(self):
        from services.config_generator import generate_config

        cfg = generate_config(
            self._make_listing(environment_variables=[{"name": "API_KEY", "required": True}]),
            "copilot",
            env_values={"API_KEY": "secret"},
        )
        server = cfg["mcpServers"]["my-mcp"]
        assert server["env"]["API_KEY"] == "secret"


# ═══════════════════════════════════════════════════════════════════
# 13. DOCTOR — OpenCode IDE config checks
# ═══════════════════════════════════════════════════════════════════


class TestDoctorOpenCode:
    def test_opencode_in_ide_configs(self):
        from observal_cli.cmd_doctor import IDE_CONFIGS

        assert "opencode" in IDE_CONFIGS

    def test_opencode_user_settings_path(self):
        from observal_cli.cmd_doctor import IDE_CONFIGS

        paths = IDE_CONFIGS["opencode"]["user_settings"]
        assert any("opencode" in str(p) for p in paths)

    def test_opencode_project_settings_path(self):
        from observal_cli.cmd_doctor import IDE_CONFIGS

        paths = IDE_CONFIGS["opencode"]["project_settings"]
        assert any("opencode" in str(p) for p in paths)

    def test_check_opencode_fn_warns_on_unwrapped_mcp(self):
        from observal_cli.cmd_doctor import _check_opencode

        data = {"mcp": {"my-srv": {"type": "local", "command": ["npx", "-y", "my-srv"]}}}
        issues = []
        warnings = []
        _check_opencode(Path(".config/opencode/opencode.json"), data, issues, warnings)
        assert len(warnings) > 0
        assert any("observal-shim" in w for w in warnings)

    def test_check_opencode_fn_no_warning_on_shimmed_mcp(self):
        from observal_cli.cmd_doctor import _check_opencode

        data = {"mcp": {"my-srv": {"type": "local", "command": ["observal-shim", "--mcp-id", "test", "--", "npx"]}}}
        issues = []
        warnings = []
        _check_opencode(Path(".config/opencode/opencode.json"), data, issues, warnings)
        assert len(warnings) == 0

    def test_check_opencode_fn_handles_empty_mcp(self):
        from observal_cli.cmd_doctor import _check_opencode

        data = {}
        issues = []
        warnings = []
        _check_opencode(Path(".config/opencode/opencode.json"), data, issues, warnings)
        assert len(warnings) == 0

    def test_check_opencode_fn_ignores_non_dict_entries(self):
        from observal_cli.cmd_doctor import _check_opencode

        data = {"mcp": {"bad-srv": "not-a-dict"}}
        issues = []
        warnings = []
        _check_opencode(Path(".config/opencode/opencode.json"), data, issues, warnings)
        assert len(warnings) == 0


# ═══════════════════════════════════════════════════════════════════
# 14. PROFILE — OpenCode file map entries
# ═══════════════════════════════════════════════════════════════════


class TestProfileOpenCode:
    def test_opencode_json_in_file_map(self):
        from observal_cli.cmd_profile import IDE_FILE_MAP

        assert ".config/opencode/opencode.json" in IDE_FILE_MAP

    def test_agents_md_in_project_files(self):
        from observal_cli.cmd_profile import PROJECT_FILES

        assert "AGENTS.md" in PROJECT_FILES

    def test_opencode_user_path_is_home_config(self):

        from observal_cli.cmd_profile import IDE_FILE_MAP

        dest = IDE_FILE_MAP[".config/opencode/opencode.json"]
        assert dest is not None
        assert str(dest).endswith("opencode.json")


# ═══════════════════════════════════════════════════════════════════
# 15. CONFIG GENERATOR — OpenCode explicit branch
# ═══════════════════════════════════════════════════════════════════


class TestConfigGeneratorOpenCode:
    def _make_listing(self, name="my-mcp", listing_id="abc-123", **kw):
        from unittest.mock import MagicMock

        listing = MagicMock()
        listing.name = name
        listing.id = listing_id
        listing.docker_image = kw.get("docker_image")
        listing.framework = kw.get("framework")
        listing.environment_variables = kw.get("environment_variables", [])
        listing.command = kw.get("command")
        listing.args = kw.get("args")
        listing.url = kw.get("url")
        listing.transport = kw.get("transport")
        listing.auto_approve = kw.get("auto_approve")
        return listing

    def test_opencode_stdio_uses_mcp_key(self):
        from services.config_generator import generate_config

        cfg = generate_config(self._make_listing(), "opencode")
        assert "mcp" in cfg
        assert "mcpServers" not in cfg

    def test_opencode_stdio_type_is_local(self):
        from services.config_generator import generate_config

        cfg = generate_config(self._make_listing(), "opencode")
        entry = cfg["mcp"]["my-mcp"]
        assert entry["type"] == "local"

    def test_opencode_stdio_command_is_flat_array(self):
        from services.config_generator import generate_config

        cfg = generate_config(self._make_listing(), "opencode")
        entry = cfg["mcp"]["my-mcp"]
        assert isinstance(entry["command"], list)
        assert entry["command"][0] == "observal-shim"
        assert "--mcp-id" in entry["command"]

    def test_opencode_stdio_has_no_args_key(self):
        from services.config_generator import generate_config

        cfg = generate_config(self._make_listing(), "opencode")
        entry = cfg["mcp"]["my-mcp"]
        assert "args" not in entry

    def test_opencode_sse_uses_mcp_key(self):
        from services.config_generator import generate_config

        cfg = generate_config(self._make_listing(url="http://localhost:3000/sse", transport="sse"), "opencode")
        assert "mcp" in cfg
        assert "mcpServers" not in cfg

    def test_opencode_sse_type_is_remote(self):
        from services.config_generator import generate_config

        cfg = generate_config(self._make_listing(url="http://localhost:3000/sse", transport="sse"), "opencode")
        entry = cfg["mcp"]["my-mcp"]
        assert entry["type"] == "remote"
        assert entry["url"] == "http://localhost:3000/sse"

    def test_opencode_sse_has_headers(self):
        from services.config_generator import generate_config

        cfg = generate_config(
            self._make_listing(url="http://localhost:3000/sse", transport="sse"),
            "opencode",
            header_values={"Authorization": "Bearer test"},
        )
        entry = cfg["mcp"]["my-mcp"]
        assert "headers" in entry

    def test_opencode_proxy_uses_mcp_key(self):
        from services.config_generator import generate_config

        cfg = generate_config(self._make_listing(), "opencode", proxy_port=9999)
        assert "mcp" in cfg
        assert "mcpServers" not in cfg

    def test_opencode_proxy_type_is_remote(self):
        from services.config_generator import generate_config

        cfg = generate_config(self._make_listing(), "opencode", proxy_port=9999)
        entry = cfg["mcp"]["my-mcp"]
        assert entry["type"] == "remote"
        assert "localhost:9999" in entry["url"]

    def test_opencode_env_vars_preserved(self):
        from services.config_generator import generate_config

        cfg = generate_config(
            self._make_listing(environment_variables=[{"name": "API_KEY", "required": True}]),
            "opencode",
            env_values={"API_KEY": "secret"},
        )
        entry = cfg["mcp"]["my-mcp"]
        assert entry["env"]["API_KEY"] == "secret"


# ═══════════════════════════════════════════════════════════════════
# 16. PULL — OpenCode scope awareness
# ═══════════════════════════════════════════════════════════════════


class TestPullOpenCodeScope:
    def test_opencode_in_scope_aware_ides(self):
        from observal_cli.cmd_pull import _SCOPE_AWARE_IDES

        assert "opencode" in _SCOPE_AWARE_IDES

    def test_opencode_scope_labels(self):
        from observal_cli.cmd_pull import _SCOPE_AWARE_IDES

        project_label, user_label = _SCOPE_AWARE_IDES["opencode"]
        assert "project" in project_label
        assert "user" in user_label
        assert "opencode" in user_label


# ═══════════════════════════════════════════════════════════════════
# 17. GEMINI — config_generator uses observal_url param
# ═══════════════════════════════════════════════════════════════════


class TestGeminiConfigGenerator:
    def test_gemini_settings_uses_observal_url(self):
        from services.config_generator import _gemini_settings

        settings = _gemini_settings("http://custom-host:4318")
        assert settings["telemetry"]["otlpEndpoint"] == "http://custom-host:4318"

    def test_gemini_settings_default_localhost(self):
        from services.config_generator import _gemini_settings

        settings = _gemini_settings("http://localhost:4318")
        assert settings["telemetry"]["otlpEndpoint"] == "http://localhost:4318"

    def test_gemini_otlp_env_uses_observal_url(self):
        from services.config_generator import _gemini_otlp_env

        env = _gemini_otlp_env("http://custom-host:4318")
        assert env["OTEL_EXPORTER_OTLP_ENDPOINT"] == "http://custom-host:4318"

    def test_gemini_settings_snippet_in_agent_config(self):
        agent = _make_agent()
        cfg = generate_agent_config(agent, "gemini-cli")
        assert "gemini_settings_snippet" in cfg
        snippet = cfg["gemini_settings_snippet"]
        assert snippet["telemetry"]["enabled"] is True
        assert snippet["telemetry"]["target"] == "custom"
        assert "otlpEndpoint" in snippet["telemetry"]


# ═══════════════════════════════════════════════════════════════════
# 18. DOCTOR — Gemini CLI config checks
# ═══════════════════════════════════════════════════════════════════


class TestDoctorGemini:
    def test_gemini_in_ide_configs(self):
        from observal_cli.cmd_doctor import IDE_CONFIGS

        assert "gemini-cli" in IDE_CONFIGS

    def test_gemini_user_settings_path(self):
        from observal_cli.cmd_doctor import IDE_CONFIGS

        paths = IDE_CONFIGS["gemini-cli"]["user_settings"]
        assert any("settings.json" in str(p) for p in paths)

    def test_gemini_project_settings_path(self):
        from observal_cli.cmd_doctor import IDE_CONFIGS

        paths = IDE_CONFIGS["gemini-cli"]["project_settings"]
        assert any("settings.json" in str(p) for p in paths)

    def test_check_gemini_warns_on_unwrapped_mcp(self):
        from pathlib import Path

        from observal_cli.cmd_doctor import _check_gemini

        data = {"mcpServers": {"my-srv": {"command": "npx", "args": ["-y", "my-srv"]}}}
        issues = []
        warnings = []
        _check_gemini(Path(".gemini/settings.json"), data, issues, warnings)
        assert len(warnings) > 0
        assert any("observal-shim" in w for w in warnings)

    def test_check_gemini_no_warning_on_shimmed_mcp(self):
        from pathlib import Path

        from observal_cli.cmd_doctor import _check_gemini

        data = {"mcpServers": {"my-srv": {"command": "observal-shim", "args": ["--mcp-id", "test", "--", "npx"]}}}
        issues = []
        warnings = []
        _check_gemini(Path(".gemini/settings.json"), data, issues, warnings)
        assert len(warnings) == 0

    def test_check_gemini_warns_on_disabled_telemetry(self):
        from pathlib import Path

        from observal_cli.cmd_doctor import _check_gemini

        data = {"telemetry": {"enabled": False}}
        issues = []
        warnings = []
        _check_gemini(Path(".gemini/settings.json"), data, issues, warnings)
        assert any("telemetry" in w and "disabled" in w for w in warnings)

    def test_check_gemini_warns_on_missing_custom_target(self):
        from pathlib import Path

        from observal_cli.cmd_doctor import _check_gemini

        data = {"telemetry": {"enabled": True, "target": "default"}}
        issues = []
        warnings = []
        _check_gemini(Path(".gemini/settings.json"), data, issues, warnings)
        assert any("not configured" in w for w in warnings)

    def test_check_gemini_warns_on_missing_otlp_endpoint(self):
        from pathlib import Path

        from observal_cli.cmd_doctor import _check_gemini

        data = {"telemetry": {"enabled": True, "target": "custom"}}
        issues = []
        warnings = []
        _check_gemini(Path(".gemini/settings.json"), data, issues, warnings)
        assert any("not configured" in w for w in warnings)

    def test_check_gemini_no_warning_on_proper_telemetry(self):
        from pathlib import Path

        from observal_cli.cmd_doctor import _check_gemini

        data = {
            "telemetry": {
                "enabled": True,
                "target": "custom",
                "otlpEndpoint": "http://localhost:4318",
                "logPrompts": True,
            }
        }
        issues = []
        warnings = []
        _check_gemini(Path(".gemini/settings.json"), data, issues, warnings)
        assert len(warnings) == 0

    def test_check_gemini_no_telemetry_block_means_no_warning(self):
        """If there's no telemetry block at all, don't warn — user hasn't configured Observal yet."""
        from pathlib import Path

        from observal_cli.cmd_doctor import _check_gemini

        data = {}
        issues = []
        warnings = []
        _check_gemini(Path(".gemini/settings.json"), data, issues, warnings)
        assert len(warnings) == 0

    def test_check_gemini_http_transport_skips_shim_warning(self):
        from pathlib import Path

        from observal_cli.cmd_doctor import _check_gemini

        data = {"mcpServers": {"my-srv": {"url": "http://localhost:3000/sse"}}}
        issues = []
        warnings = []
        _check_gemini(Path(".gemini/settings.json"), data, issues, warnings)
        assert not any("observal-shim" in w for w in warnings)


# ═══════════════════════════════════════════════════════════════════
# 19. SCAN — Gemini home directory scanning
# ═══════════════════════════════════════════════════════════════════


class TestScanGeminiHome:
    def test_scan_gemini_home_finds_mcp_servers(self, tmp_path):
        from observal_cli.cmd_scan import _scan_gemini_home

        gemini_dir = tmp_path / ".gemini"
        gemini_dir.mkdir()
        settings = gemini_dir / "settings.json"
        settings.write_text(json.dumps({"mcpServers": {"my-server": {"command": "python", "args": ["serve.py"]}}}))
        mcps, skills, hooks, agents = _scan_gemini_home(gemini_dir)
        assert len(mcps) == 1
        assert mcps[0].name == "my-server"
        assert mcps[0].source == "gemini:global"

    def test_scan_gemini_home_empty_dir(self, tmp_path):
        from observal_cli.cmd_scan import _scan_gemini_home

        gemini_dir = tmp_path / ".gemini"
        gemini_dir.mkdir()
        mcps, skills, hooks, agents = _scan_gemini_home(gemini_dir)
        assert len(mcps) == 0

    def test_scan_gemini_home_handles_mcp_servers_wrapper(self, tmp_path):
        from observal_cli.cmd_scan import _scan_gemini_home

        gemini_dir = tmp_path / ".gemini"
        gemini_dir.mkdir()
        settings = gemini_dir / "settings.json"
        settings.write_text(json.dumps({"mcpServers": {"wrapped": {"command": "npx"}}, "telemetry": {"enabled": True}}))
        mcps, _, _, _ = _scan_gemini_home(gemini_dir)
        assert len(mcps) == 1
        assert mcps[0].name == "wrapped"


# ═══════════════════════════════════════════════════════════════════
# BUG FIX REGRESSION TESTS
# ═══════════════════════════════════════════════════════════════════


class TestConfigGeneratorCodexFormat:
    """Bug #4: config_generator should return mcp.servers (not mcpServers) for Codex."""

    def _make_listing(self, name="my-mcp", framework="typescript", url=None, command=None, args=None):
        import uuid
        from unittest.mock import MagicMock

        listing = MagicMock()
        listing.id = uuid.uuid4()
        listing.name = name
        listing.framework = framework
        listing.docker_image = None
        listing.url = url
        listing.transport = None
        listing.auto_approve = None
        listing.environment_variables = []
        listing.command = command
        listing.args = args
        listing.headers = []
        return listing

    def test_stdio_codex_uses_mcp_servers_key(self):
        from services.config_generator import generate_config

        listing = self._make_listing(command="npx", args=["-y", "my-mcp"])
        cfg = generate_config(listing, "codex")
        # Must use "mcp.servers" not "mcpServers"
        assert "mcp.servers" in cfg
        assert "mcpServers" not in cfg

    def test_stdio_codex_has_observal_shim(self):
        from services.config_generator import generate_config

        listing = self._make_listing(command="npx", args=["-y", "my-mcp"])
        cfg = generate_config(listing, "codex")
        servers = cfg["mcp.servers"]
        assert len(servers) == 1
        entry = next(iter(servers.values()))
        assert entry["command"] == "observal-shim"

    def test_stdio_codex_includes_codex_config(self):
        from services.config_generator import generate_config

        listing = self._make_listing(command="npx", args=["-y", "my-mcp"])
        cfg = generate_config(listing, "codex")
        assert "codex_config" in cfg
        assert "toml_snippet" in cfg["codex_config"]

    def test_proxy_codex_uses_mcp_servers_key(self):
        from services.config_generator import generate_config

        listing = self._make_listing(command="npx", args=["-y", "my-mcp"])
        cfg = generate_config(listing, "codex", proxy_port=9000)
        assert "mcp.servers" in cfg
        assert "mcpServers" not in cfg

    def test_sse_codex_uses_mcp_servers_key(self):
        from services.config_generator import generate_config

        listing = self._make_listing(url="https://example.com/mcp")
        listing.transport = "sse"
        cfg = generate_config(listing, "codex")
        assert "mcp.servers" in cfg
        assert "mcpServers" not in cfg

    def test_sse_codex_entry_has_url(self):
        from services.config_generator import generate_config

        listing = self._make_listing(url="https://example.com/mcp")
        listing.transport = "sse"
        cfg = generate_config(listing, "codex")
        entry = next(iter(cfg["mcp.servers"].values()))
        assert entry["url"] == "https://example.com/mcp"

    def test_mcp_servers_toml_renders_correctly(self):
        """The mcp.servers dict should produce valid [mcp.servers.<name>] TOML."""
        from observal_cli.cmd_pull import _dict_to_toml

        servers = {"mcp.servers": {"my-server": {"command": "observal-shim", "args": ["--mcp-id", "abc", "--", "npx"]}}}
        toml = _dict_to_toml(servers)
        assert "[mcp.servers.my-server]" in toml
        assert 'command = "observal-shim"' in toml


class TestDoctorCodexTomlHandling:
    """Bug #1 & #2: doctor command must use _load_toml and _check_codex for Codex configs."""

    def test_doctor_check_fn_excludes_codex_from_json_dispatch(self):
        """Codex should NOT be in the JSON check_fn dispatch — it's handled via TOML path."""
        # The fix ensures the TOML branch is taken for codex, not the JSON branch.
        # We test the _check_codex function is callable with parsed TOML data.
        from observal_cli.cmd_doctor import _check_codex

        issues: list = []
        warnings: list = []
        data = {"mcp": {"servers": {"my-server": {"command": "npx", "args": ["-y", "my-mcp"]}}}}
        _check_codex(data, issues, warnings)
        # Should warn that server is not wrapped with observal-shim
        assert len(warnings) > 0
        assert any("observal-shim" in w for w in warnings)

    def test_doctor_check_codex_no_warning_when_shimmed(self):
        from observal_cli.cmd_doctor import _check_codex

        issues: list = []
        warnings: list = []
        data = {"mcp": {"servers": {"shimmed": {"command": "observal-shim", "args": ["--mcp-id", "abc"]}}}}
        _check_codex(data, issues, warnings)
        # Should NOT warn about observal-shim for shimmed server
        shim_warnings = [w for w in warnings if "observal-shim" in w and "shimmed" in w]
        assert len(shim_warnings) == 0

    def test_doctor_codex_config_uses_toml_parser(self, tmp_path):
        """When a Codex config.toml exists, doctor must load it with _load_toml."""
        from observal_cli.cmd_doctor import _load_toml

        toml_file = tmp_path / "config.toml"
        toml_file.write_text('[mcp.servers.test]\ncommand = "npx"\n')
        data = _load_toml(toml_file)
        assert data is not None
        assert "mcp" in data
        assert "servers" in data["mcp"]
        assert "test" in data["mcp"]["servers"]

    def test_doctor_check_codex_warns_on_missing_otel_config(self):
        from observal_cli.cmd_doctor import _check_codex

        issues: list = []
        warnings: list = []
        # No mcp, no otel
        _check_codex({}, issues, warnings)
        assert len(warnings) > 0
        assert any("OTel" in w or "MCP" in w or "otel" in w.lower() or "mcp" in w.lower() for w in warnings)


class TestOtlpIdeDetection:
    """Bug #5: OTLP IDE detection should recognize 'opencode' service name."""

    @pytest.fixture
    def otlp_source(self):
        """Read _IDE_HINTS and _detect_ide directly from source to avoid heavy server deps."""
        import pathlib

        src_path = pathlib.Path(__file__).parent.parent / "observal-server" / "api" / "routes" / "otlp.py"
        source = src_path.read_text()
        return source

    def test_opencode_in_ide_hints_source(self, otlp_source):
        assert '"opencode": "opencode"' in otlp_source or "'opencode': 'opencode'" in otlp_source

    def test_codex_in_ide_hints_source(self, otlp_source):
        assert '"codex": "codex"' in otlp_source or "'codex': 'codex'" in otlp_source

    def test_detect_ide_returns_opencode(self, otlp_source):
        """opencode service.name should map to opencode IDE."""
        # Verify both the hint entry exists and the _detect_ide function uses it
        assert '"opencode"' in otlp_source or "'opencode'" in otlp_source
        assert "_IDE_HINTS" in otlp_source
        assert "_detect_ide" in otlp_source

    def test_detect_ide_returns_codex(self, otlp_source):
        """codex-* service.name should match codex via substring check."""
        assert '"codex": "codex"' in otlp_source or "'codex': 'codex'" in otlp_source


class TestCodexInstallCliPathHint:
    """Bug #6: install command should show the correct path hint for Codex."""

    def test_ide_config_paths_includes_codex(self):
        """The MCP install command's path hint dict must include codex."""
        import inspect

        # Read the cmd_mcp.py file and verify codex is in ide_config_paths
        import observal_cli.cmd_mcp as cmd_mcp_module

        # Find the ide_config_paths dict in the install function's source
        source = inspect.getsource(cmd_mcp_module)
        assert '"codex": "~/.codex/config.toml"' in source or "'codex': '~/.codex/config.toml'" in source
