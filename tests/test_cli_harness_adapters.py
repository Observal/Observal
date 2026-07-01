# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Tests for the CLI-side harness adapter protocol and registry."""

from __future__ import annotations

from pathlib import Path

import pytest

from observal_cli.harness import (
    DiscoveredMcp,
    HookSpec,
    NotSupportedError,
    ScanResult,
    ensure_loaded,
    get_adapter,
    get_all_adapters,
)
from observal_cli.harness_registry import HARNESS_REGISTRY


@pytest.fixture(autouse=True)
def _load_adapters():
    """Ensure all adapters are registered before each test."""
    ensure_loaded()


class TestAdapterRegistry:
    """Test adapter registration and lookup."""

    def test_all_registry_adapters_registered(self):
        adapters = get_all_adapters()
        assert set(adapters.keys()) == set(HARNESS_REGISTRY)

    def test_get_adapter_by_canonical_name(self):
        adapter = get_adapter("claude-code")
        assert adapter.harness_name == "claude-code"

    def test_get_adapter_requires_canonical_name(self):
        with pytest.raises(KeyError):
            get_adapter("claude_code")
        with pytest.raises(KeyError):
            get_adapter("copilot_cli")

    def test_get_adapter_unknown_raises_keyerror(self):
        with pytest.raises(KeyError, match="No adapter registered"):
            get_adapter("nonexistent-ide")

    def test_all_adapters_have_required_methods(self):
        required_methods = [
            "scan_home",
            "is_installed",
            "scan_project",
            "get_hook_spec",
            "generate_hook_config",
            "detect_hooks",
            "shim_status",
            "get_observal_managed_files",
        ]
        for name, adapter in get_all_adapters().items():
            for method in required_methods:
                assert hasattr(adapter, method), f"{name} missing {method}"
                assert callable(getattr(adapter, method)), f"{name}.{method} not callable"


class TestManagedLayerFiles:
    """Test adapter-owned layer source attribution."""

    @staticmethod
    def _lockfile_for(harness_name: str) -> dict:
        return {
            "ides": {
                harness_name: {
                    "agents": [
                        {
                            "name": "agent-one",
                            "components": [
                                {"type": "skill", "name": "skill-one"},
                                {"type": "mcp", "name": "mcp-one"},
                            ],
                        }
                    ],
                    "standalone": [
                        {"type": "skill", "name": "standalone-skill"},
                        {"type": "mcp", "name": "standalone-mcp"},
                    ],
                }
            }
        }

    @pytest.mark.parametrize(
        ("harness_name", "expected"),
        [
            (
                "claude-code",
                {
                    "user:agents/agent-one.md",
                    "project:.claude/agents/agent-one.md",
                    "user:skills/skill-one/SKILL.md",
                    "user:skills/standalone-skill/SKILL.md",
                },
            ),
            (
                "cursor",
                {
                    "user:agents/agent-one.md",
                    "project:.cursor/agents/agent-one.md",
                    "user:rules/skill-one.mdc",
                    "user:skills/skill-one/SKILL.md",
                    "user:rules/standalone-skill.mdc",
                    "user:skills/standalone-skill/SKILL.md",
                },
            ),
            (
                "kiro",
                {
                    "user:agents/agent-one.json",
                    "project:.kiro/agents/agent-one.json",
                    "user:skills/skill-one/SKILL.md",
                    "user:skills/standalone-skill/SKILL.md",
                },
            ),
            (
                "codex",
                {"user:agents/agent-one.toml", "project:.codex/agents/agent-one.toml", "user:config.toml"},
            ),
            (
                "copilot",
                {"project:.github/agents/agent-one.agent.md"},
            ),
            (
                "copilot-cli",
                {
                    "project:.github/agents/agent-one.agent.md",
                    "project:.agents/skills/skill-one/SKILL.md",
                    "user:skills/skill-one/SKILL.md",
                    "project:.agents/skills/standalone-skill/SKILL.md",
                    "user:skills/standalone-skill/SKILL.md",
                },
            ),
            (
                "opencode",
                {
                    "user:agents/agent-one.md",
                    "project:.opencode/agents/agent-one.md",
                    "user:skills/skill-one/SKILL.md",
                    "project:.opencode/skills/skill-one/SKILL.md",
                    "user:skills/standalone-skill/SKILL.md",
                    "project:.opencode/skills/standalone-skill/SKILL.md",
                },
            ),
            (
                "pi",
                {
                    "user:AGENTS.md",
                    "user:skills/skill-one/SKILL.md",
                    "user:skills/standalone-skill/SKILL.md",
                },
            ),
        ],
    )
    def test_adapter_managed_files_match_existing_layer_paths(self, harness_name, expected):
        adapter = get_adapter(harness_name)
        assert adapter.get_observal_managed_files(self._lockfile_for(harness_name)) == expected

    def test_layer_managed_files_delegates_to_adapter(self):
        from observal_cli.layer import _get_observal_managed_files

        lockfile = self._lockfile_for("codex")
        assert _get_observal_managed_files(lockfile, "codex", None) == {
            "user:agents/agent-one.toml",
            "project:.codex/agents/agent-one.toml",
            "user:config.toml",
        }


class TestActiveIdeDetection:
    """Test adapter-owned active harness detection."""

    @pytest.mark.parametrize(
        ("harness_name", "marker"),
        [
            ("claude-code", ".claude"),
            ("cursor", ".cursor"),
            ("kiro", ".kiro"),
            ("codex", ".codex"),
            ("copilot", ".vscode/extensions/github.copilot-1.0.0"),
            ("copilot-cli", ".copilot"),
            ("opencode", ".config/opencode"),
            ("antigravity", ".gemini/antigravity-cli"),
            ("pi", ".pi/agent"),
        ],
    )
    def test_adapter_is_installed_uses_home_markers(self, harness_name, marker, tmp_path):
        adapter = get_adapter(harness_name)
        assert adapter.is_installed(tmp_path) is False
        (tmp_path / Path(marker)).mkdir(parents=True)
        assert adapter.is_installed(tmp_path) is True

    def test_layer_detect_active_harnesses_delegates_to_adapters(self, tmp_path, monkeypatch):
        from observal_cli.layer import _detect_active_harnesses

        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        (tmp_path / ".cursor").mkdir()
        (tmp_path / ".codex").mkdir()
        (tmp_path / ".pi" / "agent").mkdir(parents=True)

        assert _detect_active_harnesses() == ["cursor", "codex", "pi"]

    def test_pi_layer_manifest_includes_isolated_agent_profiles(self, tmp_path, monkeypatch):
        from observal_cli.layer import build_layer_manifest

        monkeypatch.setenv("HOME", str(tmp_path))
        pi_home = tmp_path / ".pi" / "agent"
        (pi_home / "agents" / "my-agent" / "skills" / "pi-skill").mkdir(parents=True)
        (pi_home / "agents" / "my-agent" / "AGENTS.md").write_text("# Agent")
        (pi_home / "agents" / "my-agent" / "mcp.json").write_text("{}")
        (pi_home / "agents" / "my-agent" / "skills" / "pi-skill" / "SKILL.md").write_text("# Skill")

        paths = {entry["path"] for entry in build_layer_manifest("pi")}

        assert "user:agents/my-agent/AGENTS.md" in paths
        assert "user:agents/my-agent/mcp.json" in paths
        assert "user:agents/my-agent/skills/pi-skill/SKILL.md" in paths


class TestAdapterProtocol:
    """Test that each adapter satisfies the protocol interface."""

    @pytest.mark.parametrize(
        "harness_name",
        [
            "claude-code",
            "cursor",
            "kiro",
            "codex",
            "copilot",
            "copilot-cli",
            "opencode",
        ],
    )
    def test_scan_home_returns_scan_result(self, harness_name, tmp_path):
        adapter = get_adapter(harness_name)
        result = adapter.scan_home(home=tmp_path)
        assert isinstance(result, ScanResult)
        assert isinstance(result.mcps, list)
        assert isinstance(result.skills, list)
        assert isinstance(result.hooks, list)
        assert isinstance(result.agents, list)

    @pytest.mark.parametrize(
        "harness_name",
        [
            "claude-code",
            "cursor",
            "kiro",
            "codex",
            "copilot",
            "copilot-cli",
            "opencode",
        ],
    )
    def test_scan_project_returns_scan_result(self, harness_name, tmp_path):
        adapter = get_adapter(harness_name)
        result = adapter.scan_project(tmp_path)
        assert isinstance(result, ScanResult)

    @pytest.mark.parametrize(
        "harness_name",
        [
            "claude-code",
            "cursor",
            "kiro",
            # copilot (VS Code) intentionally omitted: uses OTel export, not hooks
            "copilot-cli",
            "opencode",
        ],
    )
    def test_get_hook_spec_returns_hook_spec(self, harness_name):
        adapter = get_adapter(harness_name)
        spec = adapter.get_hook_spec()
        assert isinstance(spec, HookSpec)

    def test_copilot_get_hook_spec(self):
        """Copilot VS Code supports hooks with PascalCase events."""
        adapter = get_adapter("copilot")
        spec = adapter.get_hook_spec()
        assert isinstance(spec, HookSpec)
        assert "SessionStart" in spec.events
        assert "UserPromptSubmit" in spec.events
        assert "Stop" in spec.events

    @pytest.mark.parametrize(
        "harness_name",
        [
            "claude-code",
            "cursor",
            "kiro",
            "copilot",
            "copilot-cli",
            "opencode",
        ],
    )
    def test_detect_hooks_returns_string(self, harness_name, tmp_path):
        adapter = get_adapter(harness_name)
        result = adapter.detect_hooks(tmp_path)
        assert result in ("installed", "partial", "none", "missing")

    @pytest.mark.parametrize(
        "harness_name",
        [
            "claude-code",
            "cursor",
            "kiro",
            "codex",
            "copilot",
            "copilot-cli",
            "opencode",
        ],
    )
    def test_shim_status_returns_string(self, harness_name):
        adapter = get_adapter(harness_name)
        result = adapter.shim_status([])
        assert result in ("all", "partial", "none")


class TestClaudeCodeAdapter:
    """Tests specific to the Claude Code adapter (full implementation)."""

    def test_hook_spec_has_events(self):
        adapter = get_adapter("claude-code")
        spec = adapter.get_hook_spec()
        assert "PreToolUse" in spec.events
        assert "Stop" in spec.events
        assert spec.format == "command"

    def test_generate_hook_config_returns_dict(self):
        adapter = get_adapter("claude-code")
        config = adapter.generate_hook_config(
            observal_url="http://localhost:8000",
            api_key="test-key",
        )
        assert isinstance(config, dict)

    def test_scan_home_with_settings(self, tmp_path):
        import json

        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        # Claude Code discovers MCPs via plugin system
        settings = {"enabledPlugins": {"test-plugin@marketplace": True}}
        (claude_dir / "settings.json").write_text(json.dumps(settings))

        # Create plugin with MCP
        plugin_dir = claude_dir / "plugins" / "cache" / "marketplace" / "test-plugin" / "1.0.0"
        plugin_dir.mkdir(parents=True)
        mcp_data = {"mcpServers": {"test-server": {"command": "node", "args": ["server.js"]}}}
        (plugin_dir / ".mcp.json").write_text(json.dumps(mcp_data))

        adapter = get_adapter("claude-code")
        result = adapter.scan_home(home=tmp_path)
        assert isinstance(result, ScanResult)
        assert any(m.name == "test-server" for m in result.mcps)


class TestKiroAdapter:
    """Tests specific to the Kiro adapter (full implementation)."""

    def test_hook_spec_has_events(self):
        adapter = get_adapter("kiro")
        spec = adapter.get_hook_spec()
        assert len(spec.events) > 0
        assert spec.format == "http"

    def test_generate_hook_config_returns_dict(self):
        adapter = get_adapter("kiro")
        config = adapter.generate_hook_config(
            observal_url="http://localhost:8000",
            api_key="test-key",
        )
        assert isinstance(config, dict)

    def test_scan_home_with_mcp(self, tmp_path):
        import json

        kiro_dir = tmp_path / ".kiro"
        (kiro_dir / "settings").mkdir(parents=True)
        mcp_data = {"mcpServers": {"my-mcp": {"command": "python", "args": ["-m", "mcp"]}}}
        (kiro_dir / "settings" / "mcp.json").write_text(json.dumps(mcp_data))

        adapter = get_adapter("kiro")
        result = adapter.scan_home(home=tmp_path)
        assert any(m.name == "my-mcp" for m in result.mcps)


class TestStubAdapters:
    """Tests for stub adapters that raise NotSupportedError for unsupported ops."""

    @pytest.mark.parametrize("harness_name", ["codex"])
    def test_generate_hook_config_raises_not_supported(self, harness_name):
        adapter = get_adapter(harness_name)
        with pytest.raises(NotSupportedError):
            adapter.generate_hook_config(
                observal_url="http://localhost:8000",
                api_key="test-key",
            )


class TestShimStatus:
    """Test shim status detection."""

    def test_empty_mcps_returns_none(self):
        adapter = get_adapter("claude-code")
        assert adapter.shim_status([]) == "none"

    def test_shimmed_mcp_detected(self):
        adapter = get_adapter("claude-code")
        mcps = [
            DiscoveredMcp(
                name="test",
                command="observal-shim",
                args=["--", "node", "server.js"],
                url=None,
                description="test",
                source="test",
            )
        ]
        assert adapter.shim_status(mcps) == "all"

    def test_unshimmed_mcp_detected(self):
        adapter = get_adapter("claude-code")
        mcps = [
            DiscoveredMcp(
                name="test",
                command="node",
                args=["server.js"],
                url=None,
                description="test",
                source="test",
            )
        ]
        assert adapter.shim_status(mcps) == "none"

    def test_partial_shim_detected(self):
        adapter = get_adapter("claude-code")
        mcps = [
            DiscoveredMcp(
                name="shimmed",
                command="observal-shim",
                args=["--", "node", "a.js"],
                url=None,
                description="",
                source="",
            ),
            DiscoveredMcp(
                name="raw",
                command="node",
                args=["b.js"],
                url=None,
                description="",
                source="",
            ),
        ]
        assert adapter.shim_status(mcps) == "partial"


class TestFeatureGating:
    """Test that harness registry capabilities gate method access."""

    def test_codex_has_hooks_allows_get_hook_spec(self):
        adapter = get_adapter("codex")
        spec = adapter.get_hook_spec()
        assert isinstance(spec, HookSpec)
        assert "UserPromptSubmit" in spec.events

    def test_codex_has_hooks_allows_detect_hooks(self):
        import tempfile
        from pathlib import Path

        adapter = get_adapter("codex")
        result = adapter.detect_hooks(Path(tempfile.mkdtemp()))
        assert result in ("installed", "missing")

    def test_codex_has_mcp_servers_allows_scan_home(self):
        import tempfile
        from pathlib import Path

        adapter = get_adapter("codex")
        # Should not raise, codex has mcp_servers feature
        result = adapter.scan_home(home=Path(tempfile.mkdtemp()))
        assert isinstance(result, ScanResult)

    def test_codex_has_mcp_servers_allows_shim_status(self):
        adapter = get_adapter("codex")
        # Should not raise, codex has mcp_servers feature
        assert adapter.shim_status([]) == "none"

    def test_claude_code_has_all_features_no_gating(self):
        adapter = get_adapter("claude-code")
        # All methods should work without raising
        spec = adapter.get_hook_spec()
        assert len(spec.events) > 0
        assert adapter.shim_status([]) == "none"
