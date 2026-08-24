# SPDX-FileCopyrightText: 2026 Annie Chiang <anniechiang.yn@gmail.com>
# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-FileCopyrightText: 2026 EuanTop <euan@mail.bnu.edu.cn>
# SPDX-FileCopyrightText: 2026 amogh-dongre <amoghdongre16@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Tests for observal_cli.cmd_doctor helpers."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import typer
from typer.testing import CliRunner

from observal_cli import pi_extension
from observal_cli.cmd_doctor import (
    _check_antigravity,
    _check_claude_code,
    _check_codex,
    _check_copilot,
    _check_copilot_cli,
    _check_cursor,
    _check_goose,
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
    _cleanup_goose,
    _cleanup_kiro,
    _cleanup_opencode,
    _cleanup_pi,
    _patch_antigravity,
    _patch_claude_code,
    _patch_codex,
    _patch_copilot,
    _patch_copilot_cli,
    _patch_cursor,
    _patch_goose,
    _patch_kiro,
    _patch_opencode,
    _patch_pi,
    doctor_app,
    doctor_patch,
)
from observal_cli.shared.utils import is_observal_hook_entry, is_observal_matcher_group
from observal_shared.opencode_plugin_source import OPENCODE_PLUGIN_SOURCE

# Fixed regardless of what observal-cli version this test environment actually
# resolves (which varies across invocation contexts) - keeps Pi stale/current/newer
# comparisons deterministic.
CLI_VERSION = "2.0.0"


@pytest.fixture(autouse=True)
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr("observal_cli.settings_reconciler.CLAUDE_SETTINGS_PATH", tmp_path / ".claude/settings.json")
    monkeypatch.setattr("observal_cli.settings_reconciler.config.save", lambda updates: None)
    monkeypatch.setattr("observal_cli.lockfile.LOCKFILE_PATH", tmp_path / ".observal/lockfile.json")
    monkeypatch.setattr("observal_cli.lockfile._LOCKFILE_LOCK", tmp_path / ".observal/lockfile.lock")
    monkeypatch.setattr(pi_extension, "get_current_version", lambda: CLI_VERSION)
    return tmp_path


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture
def goose_home(isolated_home: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Pin goose's environment-derived directories to the isolated home."""
    monkeypatch.delenv("GOOSE_PATH_ROOT", raising=False)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.delenv("APPDATA", raising=False)  # goose reads %APPDATA% on Windows
    (isolated_home / ".config/goose").mkdir(parents=True)
    return isolated_home


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

    def test_pi_warns_when_direct_extension_is_missing(self, tmp_path: Path):
        write_json(tmp_path / ".pi/agent/settings.json", {"packages": []})
        warnings: list[str] = []

        _check_pi([], warnings)

        assert any("extensions/observal.ts" in warning for warning in warnings)

    def test_pi_is_silent_when_npm_package_is_current(self, tmp_path: Path):
        write_json(tmp_path / ".pi/agent/settings.json", {"packages": [f"npm:observal-pi@{CLI_VERSION}"]})
        warnings: list[str] = []

        _check_pi([], warnings)

        assert warnings == []
        assert not (tmp_path / ".pi/agent/extensions/observal.ts").exists()

    def test_pi_is_silent_when_npm_package_is_unpinned(self, tmp_path: Path):
        write_json(tmp_path / ".pi/agent/settings.json", {"packages": ["npm:observal-pi"]})
        warnings: list[str] = []

        _check_pi([], warnings)

        assert warnings == []
        assert not (tmp_path / ".pi/agent/extensions/observal.ts").exists()

    def test_pi_warns_when_pinned_npm_package_is_stale(self, tmp_path: Path):
        write_json(tmp_path / ".pi/agent/settings.json", {"packages": ["npm:observal-pi@0.0.1"]})
        warnings: list[str] = []

        _check_pi([], warnings)

        assert any("pi update npm:observal-pi" in warning for warning in warnings)
        assert not (tmp_path / ".pi/agent/extensions/observal.ts").exists()

    def test_pi_is_silent_when_local_install_is_current(self, tmp_path: Path):
        extension = tmp_path / ".pi/agent/extensions/observal.ts"
        extension.parent.mkdir(parents=True)
        extension.write_text(pi_extension.extension_source(), encoding="utf-8")
        write_json(
            tmp_path / ".pi/agent/extensions/.observal-extension.json",
            {"managed": True, "version": CLI_VERSION},
        )
        warnings: list[str] = []

        _check_pi([], warnings)

        assert warnings == []

    def test_pi_warns_when_local_install_is_stale(self, tmp_path: Path):
        extension = tmp_path / ".pi/agent/extensions/observal.ts"
        extension.parent.mkdir(parents=True)
        extension.write_text("old content", encoding="utf-8")
        write_json(
            tmp_path / ".pi/agent/extensions/.observal-extension.json",
            {"managed": True, "version": "0.0.1"},
        )
        warnings: list[str] = []

        _check_pi([], warnings)

        assert any("stale" in warning for warning in warnings)

    def test_pi_is_silent_when_local_install_is_newer(self, tmp_path: Path):
        extension = tmp_path / ".pi/agent/extensions/observal.ts"
        extension.parent.mkdir(parents=True)
        extension.write_text("future content", encoding="utf-8")
        write_json(
            tmp_path / ".pi/agent/extensions/.observal-extension.json",
            {"managed": True, "version": "9999.0.0"},
        )
        warnings: list[str] = []

        _check_pi([], warnings)

        assert warnings == []
        assert extension.read_text(encoding="utf-8") == "future content"

    def test_pi_warns_of_conflict_with_unmanaged_local_file(self, tmp_path: Path):
        extension = tmp_path / ".pi/agent/extensions/observal.ts"
        extension.parent.mkdir(parents=True)
        extension.write_text("hand-written extension", encoding="utf-8")
        warnings: list[str] = []

        _check_pi([], warnings)

        assert any("not managed by Observal" in warning for warning in warnings)

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

    def test_goose_is_silent_when_not_installed(self, isolated_home: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
        monkeypatch.delenv("XDG_DATA_HOME", raising=False)
        monkeypatch.delenv("APPDATA", raising=False)
        warnings: list[str] = []

        _check_goose([], warnings)

        assert warnings == []

    def test_goose_warns_when_the_hook_plugin_is_missing(self, goose_home: Path):
        warnings: list[str] = []

        _check_goose([], warnings)

        assert any("Goose session push hooks not installed" in warning for warning in warnings)

    def test_goose_warns_when_hooks_are_stale(self, goose_home: Path):
        write_json(
            goose_home / ".agents/plugins/observal/hooks/hooks.json",
            {"hooks": {"SessionEnd": [{"hooks": [{"type": "command", "command": "old"}]}]}},
        )
        warnings: list[str] = []

        _check_goose([], warnings)

        assert any("missing or stale" in warning for warning in warnings)

    def test_goose_reports_invalid_hook_json_as_an_issue(self, goose_home: Path):
        hooks_path = goose_home / ".agents/plugins/observal/hooks/hooks.json"
        hooks_path.parent.mkdir(parents=True)
        hooks_path.write_text("{ not json", encoding="utf-8")
        issues: list[str] = []

        _check_goose(issues, [])

        assert any("not valid JSON" in issue for issue in issues)

    def test_goose_reports_a_non_object_hook_root_as_an_issue(self, goose_home: Path):
        hooks_path = goose_home / ".agents/plugins/observal/hooks/hooks.json"
        hooks_path.parent.mkdir(parents=True)
        hooks_path.write_text("[1]", encoding="utf-8")
        issues: list[str] = []

        _check_goose(issues, [])

        assert any("not valid JSON" in issue for issue in issues)

    def test_goose_is_not_stale_when_foreign_rules_sit_beside_ours(self, goose_home: Path):
        write_json(
            goose_home / ".agents/plugins/observal/hooks/hooks.json",
            {"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "foreign"}]}]}},
        )
        _patch_goose(dry_run=False)
        warnings: list[str] = []

        _check_goose([], warnings)

        assert warnings == []

    def test_observal_skill_missing_reports_detected_harnesses(self, tmp_path: Path):
        (tmp_path / ".pi/agent").mkdir(parents=True)

        missing = _check_observal_skill_missing()

        assert "Pi" in missing

    def test_shared_observal_skill_satisfies_codex_and_pi(self, tmp_path: Path):
        (tmp_path / ".codex").mkdir()
        (tmp_path / ".pi").mkdir()
        source = Path(__file__).parents[1] / "observal_cli/skills/observal/SKILL.md"
        shared = tmp_path / ".agents/skills/observal/SKILL.md"
        shared.parent.mkdir(parents=True)
        shared.write_bytes(source.read_bytes())

        missing = _check_observal_skill_missing()

        assert "Codex" not in missing
        assert "Pi" not in missing


class TestPatchFunctions:
    def test_patch_claude_code_writes_and_is_idempotent(self, tmp_path: Path):
        settings_path = tmp_path / ".claude/settings.json"

        assert _patch_claude_code(dry_run=False) is True
        assert "hooks" in read_json(settings_path)
        assert _patch_claude_code(dry_run=False) is False

    def test_patch_kiro_skips_without_locked_agents(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        from observal_cli import config

        monkeypatch.setattr(config, "load", lambda: {"server_url": "http://localhost:80"})
        write_json(tmp_path / ".kiro/agents/default.json", {})

        assert _patch_kiro(dry_run=False) is False
        assert read_json(tmp_path / ".kiro/agents/default.json") == {}

    def test_patch_kiro_repairs_locked_agent_uuid_hooks(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        from observal_cli import config, lockfile

        agent_id = "00000000-0000-0000-0000-000000000123"
        monkeypatch.setattr(
            config,
            "load",
            lambda: {"server_url": "http://localhost:80", "access_token": "test-token"},
        )
        write_json(tmp_path / ".kiro/agents/test-agent.json", {"name": "test-agent", "hooks": {}})
        lockfile.upsert_agent(
            "kiro",
            name="test-agent",
            agent_id=agent_id,
            version="1.0.0",
            scope="user",
            local_name="test-agent",
        )

        assert _patch_kiro(dry_run=False) is True
        profile = read_json(tmp_path / ".kiro/agents/test-agent.json")
        commands = [entry["command"] for entries in profile["hooks"].values() for entry in entries]
        assert commands
        assert all(agent_id in command for command in commands)

    def test_patch_cursor_writes_hooks_and_preserves_foreign_entries(self, tmp_path: Path):
        hooks_path = tmp_path / ".cursor/hooks.json"
        write_json(hooks_path, {"hooks": {"beforeSubmitPrompt": [{"command": "foreign"}]}})

        assert _patch_cursor(dry_run=False) is True
        data = read_json(hooks_path)
        commands = [entry["command"] for entry in data["hooks"]["beforeSubmitPrompt"]]
        assert "foreign" in commands
        assert any("hooks.session_push --harness cursor" in command for command in commands)
        assert _patch_cursor(dry_run=False) is False

    def test_patch_pi_installs_local_extension_and_manifest(self, tmp_path: Path):
        (tmp_path / ".pi/agent").mkdir(parents=True)

        assert _patch_pi(dry_run=False) is True
        extension = tmp_path / ".pi/agent/extensions/observal.ts"
        manifest = tmp_path / ".pi/agent/extensions/.observal-extension.json"
        assert extension.read_text() == pi_extension.extension_source()
        assert read_json(manifest) == {"managed": True, "version": CLI_VERSION}
        assert _patch_pi(dry_run=False) is False

    def test_patch_pi_skips_local_install_when_npm_is_configured(self, tmp_path: Path):
        settings = tmp_path / ".pi/agent/settings.json"
        write_json(settings, {"packages": ["npm:@observal/pi-insights", "npm:observal-pi"]})

        assert _patch_pi(dry_run=False) is False

        assert not (tmp_path / ".pi/agent/extensions/observal.ts").exists()
        assert read_json(settings)["packages"] == ["npm:@observal/pi-insights", "npm:observal-pi"]

    def test_patch_pi_refreshes_a_stale_managed_install(self, tmp_path: Path):
        extension = tmp_path / ".pi/agent/extensions/observal.ts"
        extension.parent.mkdir(parents=True)
        extension.write_text("old content", encoding="utf-8")
        write_json(
            tmp_path / ".pi/agent/extensions/.observal-extension.json",
            {"managed": True, "version": "0.0.1"},
        )

        assert _patch_pi(dry_run=False) is True

        assert extension.read_text() == pi_extension.extension_source()
        manifest = read_json(tmp_path / ".pi/agent/extensions/.observal-extension.json")
        assert manifest["version"] == CLI_VERSION

    def test_patch_pi_never_overwrites_an_unmanaged_file(self, tmp_path: Path):
        extension = tmp_path / ".pi/agent/extensions/observal.ts"
        extension.parent.mkdir(parents=True)
        extension.write_text("hand-written extension", encoding="utf-8")

        assert _patch_pi(dry_run=False) is False

        assert extension.read_text() == "hand-written extension"
        assert not (tmp_path / ".pi/agent/extensions/.observal-extension.json").exists()

    def test_patch_pi_adopts_a_pre_manifest_install_without_rewriting_content(self, tmp_path: Path):
        extension = tmp_path / ".pi/agent/extensions/observal.ts"
        extension.parent.mkdir(parents=True)
        extension.write_text(pi_extension.extension_source(), encoding="utf-8")

        assert _patch_pi(dry_run=False) is True

        manifest = read_json(tmp_path / ".pi/agent/extensions/.observal-extension.json")
        assert manifest == {"managed": True, "version": CLI_VERSION}
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
            "hooks.session_push --harness codex" in hook.get("command", "")
            for group in groups
            for hook in group.get("hooks", [])
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
            "hooks.session_push --harness copilot-cli" in entry.get("bash", "")
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

    def test_patch_goose_installs_plugin_and_preserves_foreign_hooks(self, goose_home: Path):
        hooks_path = goose_home / ".agents/plugins/observal/hooks/hooks.json"
        write_json(hooks_path, {"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "foreign"}]}]}})

        assert _patch_goose(dry_run=False) is True

        assert read_json(goose_home / ".agents/plugins/observal/plugin.json")["name"] == "observal"
        rules = read_json(hooks_path)["hooks"]
        assert rules["Stop"][0]["hooks"][0]["command"] == "foreign"
        assert any("--harness goose" in handler["command"] for rule in rules["SessionEnd"] for handler in rule["hooks"])
        assert _patch_goose(dry_run=False) is False

    def test_patch_goose_skips_when_goose_is_not_installed(self, isolated_home: Path, monkeypatch):
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
        monkeypatch.delenv("XDG_DATA_HOME", raising=False)
        monkeypatch.delenv("APPDATA", raising=False)

        assert _patch_goose(dry_run=False) is False
        assert not (isolated_home / ".agents").exists()

    def test_patch_goose_dry_run_writes_nothing(self, goose_home: Path):
        assert _patch_goose(dry_run=True) is True
        assert not (goose_home / ".agents").exists()

    def test_doctor_yes_runs_supported_patch_command(self, tmp_path: Path):
        (tmp_path / ".cursor").mkdir()
        with (
            patch("observal_cli.cmd_doctor._check_observal_config"),
            patch(
                "observal_cli.lockfile_reconcile.plan_lockfile_reconciliation",
                return_value=MagicMock(changes=[], warnings=[]),
            ),
            patch("observal_cli.cmd_doctor._patch_targets", return_value={"changed": True}) as patch_targets,
            patch("observal_cli.skill_installer.install_observal_skill"),
        ):
            result = CliRunner().invoke(doctor_app, ["--yes"])

        assert result.exit_code == 0
        patch_targets.assert_called_once()

    def test_doctor_patch_requires_target(self):
        with pytest.raises(typer.Exit) as exc:
            doctor_patch(all_harnesses=False, harness=[], dry_run=False)

        assert exc.value.exit_code == 7

    def test_doctor_patch_rejects_unknown_harness(self):
        with (
            patch("observal_cli.cmd_doctor.config.load", return_value={"server_url": "http://server"}),
            pytest.raises(typer.Exit) as exc,
        ):
            doctor_patch(all_harnesses=False, harness=["wat"], dry_run=False)

        assert exc.value.exit_code == 7


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

    def test_cleanup_pi_removes_a_managed_install(self, tmp_path: Path):
        extension = tmp_path / ".pi/agent/extensions/observal.ts"
        manifest = tmp_path / ".pi/agent/extensions/.observal-extension.json"
        extension.parent.mkdir(parents=True)
        extension.write_text(pi_extension.extension_source(), encoding="utf-8")
        write_json(manifest, {"managed": True, "version": CLI_VERSION})

        assert _cleanup_pi(dry_run=False) is True
        assert not extension.exists()
        assert not manifest.exists()

    def test_cleanup_pi_leaves_npm_registration_untouched(self, tmp_path: Path):
        settings = tmp_path / ".pi/agent/settings.json"
        write_json(settings, {"packages": ["npm:observal-pi", "npm:@observal/pi-insights"]})

        assert _cleanup_pi(dry_run=False) is False
        assert read_json(settings)["packages"] == ["npm:observal-pi", "npm:@observal/pi-insights"]

    def test_cleanup_pi_leaves_an_unmanaged_file_untouched(self, tmp_path: Path):
        extension = tmp_path / ".pi/agent/extensions/observal.ts"
        extension.parent.mkdir(parents=True)
        extension.write_text("hand-written extension", encoding="utf-8")

        assert _cleanup_pi(dry_run=False) is False
        assert extension.read_text() == "hand-written extension"

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

    def test_cleanup_goose_removes_the_hook_plugin(self, goose_home: Path):
        plugin_dir = goose_home / ".agents/plugins/observal"
        write_json(plugin_dir / "hooks/hooks.json", {"hooks": {}})
        write_json(plugin_dir / "plugin.json", {"name": "observal"})

        assert _cleanup_goose(dry_run=False) is True
        assert not plugin_dir.exists()
        assert _cleanup_goose(dry_run=False) is False

    def test_cleanup_goose_dry_run_keeps_the_plugin(self, goose_home: Path):
        plugin_dir = goose_home / ".agents/plugins/observal"
        write_json(plugin_dir / "hooks/hooks.json", {"hooks": {}})

        assert _cleanup_goose(dry_run=True) is True
        assert plugin_dir.exists()

    def test_cleanup_goose_preserves_foreign_hook_rules(self, goose_home: Path):
        hooks_path = goose_home / ".agents/plugins/observal/hooks/hooks.json"
        write_json(hooks_path, {"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "foreign"}]}]}})
        _patch_goose(dry_run=False)

        assert _cleanup_goose(dry_run=False) is True

        rules = read_json(hooks_path)["hooks"]
        assert rules == {"Stop": [{"hooks": [{"type": "command", "command": "foreign"}]}]}
