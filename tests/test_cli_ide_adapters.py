# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Tests for the CLI-side IDE adapter protocol and registry."""

from __future__ import annotations

import pytest

from observal_cli.ide import (
    DiscoveredMcp,
    HookSpec,
    NotSupported,
    ScanResult,
    ensure_loaded,
    get_adapter,
    get_all_adapters,
)
from observal_cli.ide_registry import IDE_REGISTRY


@pytest.fixture(autouse=True)
def _load_adapters():
    """Ensure all adapters are registered before each test."""
    ensure_loaded()


class TestAdapterRegistry:
    """Test adapter registration and lookup."""

    def test_all_registry_adapters_registered(self):
        adapters = get_all_adapters()
        assert set(adapters.keys()) == set(IDE_REGISTRY)

    def test_get_adapter_by_canonical_name(self):
        adapter = get_adapter("claude-code")
        assert adapter.ide_name == "claude-code"

    def test_get_adapter_by_underscore_alias(self):
        assert get_adapter("claude_code").ide_name == "claude-code"
        assert get_adapter("copilot_cli").ide_name == "copilot-cli"

    def test_get_adapter_unknown_raises_keyerror(self):
        with pytest.raises(KeyError, match="No adapter registered"):
            get_adapter("nonexistent-ide")

    def test_all_adapters_have_required_methods(self):
        required_methods = [
            "scan_home",
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
    def _lockfile_for(ide_name: str) -> dict:
        return {
            "ides": {
                ide_name: {
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
        ("ide_name", "expected"),
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
                    "user:rules/agent-one.mdc",
                    "user:agents/agent-one.md",
                    "project:.cursor/rules/agent-one.mdc",
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
                {"user:AGENTS.md", "project:AGENTS.md", "user:config.toml"},
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
    def test_adapter_managed_files_match_existing_layer_paths(self, ide_name, expected):
        adapter = get_adapter(ide_name)
        assert adapter.get_observal_managed_files(self._lockfile_for(ide_name)) == expected

    def test_layer_managed_files_delegates_to_adapter(self):
        from observal_cli.layer import _get_observal_managed_files

        lockfile = self._lockfile_for("codex")
        assert _get_observal_managed_files(lockfile, "codex", None) == {
            "user:AGENTS.md",
            "project:AGENTS.md",
            "user:config.toml",
        }


class TestAdapterProtocol:
    """Test that each adapter satisfies the protocol interface."""

    @pytest.mark.parametrize(
        "ide_name",
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
    def test_scan_home_returns_scan_result(self, ide_name, tmp_path):
        adapter = get_adapter(ide_name)
        result = adapter.scan_home(home=tmp_path)
        assert isinstance(result, ScanResult)
        assert isinstance(result.mcps, list)
        assert isinstance(result.skills, list)
        assert isinstance(result.hooks, list)
        assert isinstance(result.agents, list)

    @pytest.mark.parametrize(
        "ide_name",
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
    def test_scan_project_returns_scan_result(self, ide_name, tmp_path):
        adapter = get_adapter(ide_name)
        result = adapter.scan_project(tmp_path)
        assert isinstance(result, ScanResult)

    @pytest.mark.parametrize(
        "ide_name",
        [
            "claude-code",
            "cursor",
            "kiro",
            # copilot (VS Code) intentionally omitted: uses OTel export, not hooks
            "copilot-cli",
            "opencode",
        ],
    )
    def test_get_hook_spec_returns_hook_spec(self, ide_name):
        adapter = get_adapter(ide_name)
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
        "ide_name",
        [
            "claude-code",
            "cursor",
            "kiro",
            "copilot",
            "copilot-cli",
            "opencode",
        ],
    )
    def test_detect_hooks_returns_string(self, ide_name, tmp_path):
        adapter = get_adapter(ide_name)
        result = adapter.detect_hooks(tmp_path)
        assert result in ("installed", "partial", "none", "missing")

    @pytest.mark.parametrize(
        "ide_name",
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
    def test_shim_status_returns_string(self, ide_name):
        adapter = get_adapter(ide_name)
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
    """Tests for stub adapters that raise NotSupported for unsupported ops."""

    @pytest.mark.parametrize("ide_name", ["codex"])
    def test_generate_hook_config_raises_not_supported(self, ide_name):
        adapter = get_adapter(ide_name)
        with pytest.raises(NotSupported):
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
    """Test that IDE_Registry feature flags gate method access."""

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
