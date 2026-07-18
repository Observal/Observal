# SPDX-FileCopyrightText: 2026 Annie Chiang <anniechiang.yn@gmail.com>
# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Tests for observal_cli.cmd_doctor helpers."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest
import typer

if TYPE_CHECKING:
    from pathlib import Path
from observal_cli.cmd_doctor import (
    _check_antigravity,
    _check_claude_code,
    _check_codex,
    _check_copilot,
    _check_copilot_cli,
    _check_cursor,
    _check_kiro,
    _check_observal_config,
    _check_observal_skill_missing,
    _check_opencode,
    _check_pi,
    _cleanup_claude_code,
    _cleanup_codex,
    _cleanup_copilot,
    _cleanup_copilot_cli,
    _cleanup_cursor,
    _cleanup_kiro,
    _cleanup_opencode,
    _parse_mcp_servers,
    _patch_antigravity,
    _patch_claude_code,
    _patch_codex,
    _patch_copilot,
    _patch_copilot_cli,
    _patch_cursor,
    _patch_kiro,
    _patch_opencode,
    _patch_pi,
    _shim_config_file,
    _wrap_with_shim,
    doctor_patch,
)
from observal_cli.shared.utils import (
    is_already_shimmed,
    is_observal_hook_entry,
    is_observal_matcher_group,
)
from observal_shared.opencode_plugin_source import OPENCODE_PLUGIN_SOURCE


@pytest.fixture(autouse=True)
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr("observal_cli.settings_reconciler.CLAUDE_SETTINGS_PATH", tmp_path / ".claude/settings.json")
    monkeypatch.setattr("observal_cli.settings_reconciler.config.save", lambda updates: None)
    return tmp_path


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class TestShimHelpers:
    def test_detects_shimmed_entries(self):
        assert not is_already_shimmed({"command": "node", "args": ["server.js"]})
        assert is_already_shimmed({"command": "observal-shim", "args": ["--mcp-id", "x", "--", "node"]})
        assert is_already_shimmed({"command": "env", "args": ["observal-shim", "--", "node"]})

    def test_wraps_stdio_mcp_without_touching_env(self):
        entry = {"command": "python", "args": ["-m", "server"], "env": {"A": "B"}}

        wrapped = _wrap_with_shim(entry, "py-server")

        assert wrapped["command"] == "observal-shim"
        assert wrapped["args"] == ["--mcp-id", "py-server", "--", "python", "-m", "server"]
        assert wrapped["env"] == {"A": "B"}

    def test_remote_mcp_is_not_wrapped(self):
        entry = {"url": "https://example.com/mcp", "transport": "sse"}

        assert _wrap_with_shim(entry, "remote") == entry

    @pytest.mark.parametrize(
        ("harness", "config_data", "expected"),
        [
            ("cursor", {"mcpServers": {"cursor-tool": {}}}, "cursor-tool"),
            ("copilot", {"servers": {"copilot-tool": {}}}, "copilot-tool"),
            ("copilot-cli", {"mcpServers": {"cli-tool": {}}}, "cli-tool"),
            ("opencode", {"mcp": {"opencode-tool": {}}}, "opencode-tool"),
            ("codex", {"mcp_servers": {"codex-tool": {}}}, "codex-tool"),
        ],
    )
    def test_parse_mcp_servers_uses_harness_registry_keys(self, harness: str, config_data: dict, expected: str):
        assert expected in _parse_mcp_servers(config_data, harness)

    def test_shim_config_file_wraps_and_backs_up(self, tmp_path: Path):
        config_path = tmp_path / "mcp.json"
        write_json(config_path, {"mcpServers": {"tool": {"command": "node", "args": ["server.js"]}}})

        assert _shim_config_file(config_path, "cursor", dry_run=False) == 1

        data = read_json(config_path)
        assert data["mcpServers"]["tool"]["command"] == "observal-shim"
        assert list(tmp_path.glob("mcp.pre-observal.*.bak"))

    def test_shim_config_file_dry_run_does_not_write(self, tmp_path: Path):
        config_path = tmp_path / "mcp.json"
        original = {"mcpServers": {"tool": {"command": "node"}}}
        write_json(config_path, original)

        assert _shim_config_file(config_path, "cursor", dry_run=True) == 1
        assert read_json(config_path) == original


class TestHookIdentification:
    def test_identifies_observal_hook_entries_and_groups(self):
        assert is_observal_hook_entry({"command": "python -m observal_cli.hooks.session_push"})
        assert is_observal_hook_entry({"command": "/tmp/observal-hook.sh"})
        assert not is_observal_hook_entry({"command": "/usr/bin/custom"})
        assert is_observal_matcher_group({"_observal": {"version": "1"}, "hooks": [{"command": "x"}]})
        assert is_observal_matcher_group({"hooks": [{"command": "/tmp/observal-hook.sh"}]})
        assert not is_observal_matcher_group({"hooks": [{"command": "/usr/bin/custom"}]})


class TestChecks:
    def test_observal_config_missing_is_issue(self):
        issues: list[str] = []
        warnings: list[str] = []

        _check_observal_config(issues, warnings)

        assert any("auth login" in issue for issue in issues)
        assert warnings == []

    def test_observal_config_health_failure_is_issue(self, tmp_path: Path):
        write_json(tmp_path / ".observal/config.json", {"access_token": "token", "server_url": "http://server"})

        with patch("httpx.get", side_effect=RuntimeError("down")):
            issues: list[str] = []
            _check_observal_config(issues, [])

        assert any("Cannot reach" in issue for issue in issues)

    def test_claude_detects_disabled_hooks_and_missing_session_push(self, tmp_path: Path):
        write_json(tmp_path / ".claude/settings.json", {"disableAllHooks": True, "hooks": {}})
        issues: list[str] = []
        warnings: list[str] = []

        _check_claude_code(issues, warnings)

        assert any("disableAllHooks" in issue for issue in issues)
        assert any("Claude Code session push hooks not installed" in warning for warning in warnings)

    def test_kiro_warns_when_agent_has_no_session_push(self, tmp_path: Path):
        write_json(tmp_path / ".kiro/agents/default.json", {"hooks": {}})
        warnings: list[str] = []

        _check_kiro([], warnings)

        assert any("Kiro acknowledged session hooks not installed" in warning for warning in warnings)

    def test_pi_warns_when_extension_package_missing(self, tmp_path: Path):
        write_json(tmp_path / ".pi/agent/settings.json", {"packages": []})
        warnings: list[str] = []

        _check_pi([], warnings)

        assert any("observal-pi" in warning for warning in warnings)

    def test_cursor_warns_when_hooks_file_missing(self, tmp_path: Path):
        (tmp_path / ".cursor").mkdir()
        warnings: list[str] = []

        _check_cursor([], warnings)

        assert any("Cursor session push hooks not installed" in warning for warning in warnings)

    def test_codex_reports_disabled_hook_flag(self, tmp_path: Path):
        codex_dir = tmp_path / ".codex"
        codex_dir.mkdir()
        (codex_dir / "config.toml").write_text("codex_hooks = false\n", encoding="utf-8")
        issues: list[str] = []
        warnings: list[str] = []

        _check_codex(issues, warnings)

        assert any("codex_hooks = false" in issue for issue in issues)
        assert any("Codex session push hooks not installed" in warning for warning in warnings)

    def test_copilot_warns_when_vscode_exists_without_hooks(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".vscode").mkdir()
        warnings: list[str] = []

        _check_copilot([], warnings)

        assert any("Copilot (VS Code) session push hooks not installed" in warning for warning in warnings)

    def test_copilot_cli_warns_when_hooks_missing(self, tmp_path: Path):
        (tmp_path / ".copilot").mkdir()
        warnings: list[str] = []

        _check_copilot_cli([], warnings)

        assert any("Copilot CLI session push hooks not installed" in warning for warning in warnings)

    def test_opencode_warns_for_missing_plugin(self, tmp_path: Path):
        (tmp_path / ".config/opencode").mkdir(parents=True)
        warnings: list[str] = []

        _check_opencode([], warnings)

        assert any("OpenCode observal plugin not installed" in warning for warning in warnings)

    def test_antigravity_warns_when_hooks_missing(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        config_dir = tmp_path / ".gemini/antigravity-cli"
        config_dir.mkdir(parents=True)
        monkeypatch.setattr("observal_cli.shared.utils.resolve_antigravity_config_dir", lambda: config_dir)
        warnings: list[str] = []

        _check_antigravity([], warnings)

        assert any("Antigravity session push hooks not installed" in warning for warning in warnings)

    def test_observal_skill_missing_reports_detected_harnesses(self, tmp_path: Path):
        (tmp_path / ".pi/agent").mkdir(parents=True)

        missing = _check_observal_skill_missing()

        assert "Pi" in missing


class TestPatchFunctions:
    def test_patch_claude_code_writes_and_is_idempotent(self, tmp_path: Path):
        settings_path = tmp_path / ".claude/settings.json"

        assert _patch_claude_code(dry_run=False) is True
        assert "hooks" in read_json(settings_path)
        assert _patch_claude_code(dry_run=False) is False

    def test_patch_kiro_is_skipped_because_pull_installs_agent_hooks(self, tmp_path: Path):
        write_json(tmp_path / ".kiro/agents/default.json", {})

        assert _patch_kiro(dry_run=False) is False
        assert read_json(tmp_path / ".kiro/agents/default.json") == {}

    def test_patch_cursor_writes_hooks_and_preserves_foreign_entries(self, tmp_path: Path):
        hooks_path = tmp_path / ".cursor/hooks.json"
        write_json(hooks_path, {"hooks": {"beforeSubmitPrompt": [{"command": "foreign"}]}})

        assert _patch_cursor(dry_run=False) is True
        data = read_json(hooks_path)
        commands = [entry["command"] for entry in data["hooks"]["beforeSubmitPrompt"]]
        assert "foreign" in commands
        assert any("cursor_session_push" in command for command in commands)
        assert _patch_cursor(dry_run=False) is False

    def test_patch_pi_adds_package_and_is_idempotent(self, tmp_path: Path):
        write_json(tmp_path / ".pi/agent/settings.json", {"packages": []})

        assert _patch_pi(dry_run=False) is True
        assert "npm:observal-pi" in read_json(tmp_path / ".pi/agent/settings.json")["packages"]
        assert _patch_pi(dry_run=False) is False

    def test_patch_codex_writes_hooks_and_enables_flag(self, tmp_path: Path):
        codex_dir = tmp_path / ".codex"
        codex_dir.mkdir()
        (codex_dir / "config.toml").write_text("codex_hooks = false\n", encoding="utf-8")
        write_json(codex_dir / "hooks.json", {"hooks": {"Stop": [{"hooks": [{"command": "foreign"}]}]}})

        assert _patch_codex(dry_run=False) is True

        assert "codex_hooks = true" in (codex_dir / "config.toml").read_text(encoding="utf-8")
        groups = read_json(codex_dir / "hooks.json")["hooks"]["Stop"]
        assert any(group.get("hooks", [{}])[0].get("command") == "foreign" for group in groups)
        assert any(
            "codex_session_push" in hook.get("command", "") for group in groups for hook in group.get("hooks", [])
        )

    def test_patch_copilot_writes_project_hooks_and_wrapper(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.chdir(tmp_path)

        assert _patch_copilot(dry_run=False) is True

        hooks_path = tmp_path / ".github/hooks/observal.json"
        ps1_path = tmp_path / ".github/hooks/run_hook.ps1"
        assert hooks_path.exists()
        assert ps1_path.exists()
        assert _patch_copilot(dry_run=False) is False

    def test_patch_copilot_cli_writes_home_hooks(self, tmp_path: Path):
        assert _patch_copilot_cli(dry_run=False) is True

        hooks_path = tmp_path / ".copilot/hooks/observal.json"
        assert any(
            "copilot_cli_session_push" in entry.get("bash", "")
            for entries in read_json(hooks_path)["hooks"].values()
            for entry in entries
        )
        assert _patch_copilot_cli(dry_run=False) is False

    def test_patch_opencode_writes_current_plugin(self, tmp_path: Path):
        assert _patch_opencode(dry_run=False) is True

        plugin_path = tmp_path / ".config/opencode/plugins/observal-plugin.ts"
        assert plugin_path.read_text(encoding="utf-8") == OPENCODE_PLUGIN_SOURCE
        assert _patch_opencode(dry_run=False) is False

    def test_patch_antigravity_writes_hooks(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        config_dir = tmp_path / ".gemini/antigravity-cli"
        config_dir.mkdir(parents=True)
        monkeypatch.setattr("observal_cli.shared.utils.resolve_antigravity_config_dir", lambda: config_dir)

        assert _patch_antigravity(dry_run=False) is True

        assert "observal-telemetry" in read_json(config_dir / "hooks.json")
        assert _patch_antigravity(dry_run=False) is False

    def test_doctor_patch_requires_mode_and_target(self):
        with pytest.raises(typer.Exit) as exc:
            doctor_patch(hook=False, shim=False, all_=False, all_harnesses=False, harness=[], dry_run=False)

        assert exc.value.exit_code == 1

    def test_doctor_patch_rejects_unknown_harness(self):
        with (
            patch("observal_cli.cmd_doctor.config.load", return_value={"server_url": "http://server"}),
            pytest.raises(typer.Exit) as exc,
        ):
            doctor_patch(hook=True, shim=False, all_=False, all_harnesses=False, harness=["wat"], dry_run=False)

        assert exc.value.exit_code == 1


class TestCleanupFunctions:
    def test_cleanup_claude_preserves_foreign_hooks(self, tmp_path: Path):
        settings_path = tmp_path / ".claude/settings.json"
        foreign = {"hooks": [{"command": "foreign"}]}
        managed = {"_observal": {"version": "1"}, "hooks": [{"command": "observal_cli.hooks.session_push"}]}
        write_json(
            settings_path, {"hooks": {"Stop": [foreign, managed]}, "env": {"OBSERVAL_HOOKS_URL": "x", "KEEP": "y"}}
        )

        assert _cleanup_claude_code(dry_run=False) is True

        data = read_json(settings_path)
        assert data["hooks"]["Stop"] == [foreign]
        assert data["env"] == {"KEEP": "y"}

    def test_cleanup_kiro_preserves_foreign_hooks(self, tmp_path: Path):
        agent_path = tmp_path / ".kiro/agents/default.json"
        foreign = {"command": "foreign"}
        managed = {"command": "python -m observal_cli.hooks.kiro_session_push"}
        write_json(agent_path, {"hooks": {"userPromptSubmit": [foreign, managed]}})

        assert _cleanup_kiro(dry_run=False) is True

        assert read_json(agent_path)["hooks"]["userPromptSubmit"] == [foreign]

    def test_cleanup_cursor_preserves_foreign_hooks(self, tmp_path: Path):
        hooks_path = tmp_path / ".cursor/hooks.json"
        write_json(hooks_path, {"hooks": {"stop": [{"command": "foreign"}, {"command": "cursor_session_push"}]}})

        assert _cleanup_cursor(dry_run=False) is True

        assert read_json(hooks_path)["hooks"]["stop"] == [{"command": "foreign"}]

    def test_cleanup_codex_preserves_foreign_groups(self, tmp_path: Path):
        hooks_path = tmp_path / ".codex/hooks.json"
        foreign = {"hooks": [{"command": "foreign"}]}
        managed = {"hooks": [{"command": "python -m observal_cli.hooks.codex_session_push"}]}
        write_json(hooks_path, {"hooks": {"Stop": [foreign, managed]}})

        assert _cleanup_codex(dry_run=False) is True

        assert read_json(hooks_path)["hooks"]["Stop"] == [foreign]

    def test_cleanup_copilot_removes_project_and_home_files(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.chdir(tmp_path)
        project_hooks = tmp_path / ".github/hooks/observal.json"
        home_hooks = tmp_path / ".copilot/hooks/observal.json"
        ps1 = tmp_path / ".github/hooks/run_hook.ps1"
        write_json(project_hooks, {})
        write_json(home_hooks, {})
        ps1.write_text("copilot_vscode_session_push", encoding="utf-8")

        assert _cleanup_copilot(dry_run=False) is True

        assert not project_hooks.exists()
        assert not home_hooks.exists()
        assert not ps1.exists()

    def test_cleanup_copilot_cli_removes_home_hook_file(self, tmp_path: Path):
        hooks_path = tmp_path / ".copilot/hooks/observal.json"
        write_json(hooks_path, {})

        assert _cleanup_copilot_cli(dry_run=False) is True

        assert not hooks_path.exists()

    def test_cleanup_opencode_removes_plugin(self, tmp_path: Path):
        plugin_path = tmp_path / ".config/opencode/plugins/observal-plugin.ts"
        plugin_path.parent.mkdir(parents=True)
        plugin_path.write_text("plugin", encoding="utf-8")

        assert _cleanup_opencode(dry_run=False) is True

        assert not plugin_path.exists()
