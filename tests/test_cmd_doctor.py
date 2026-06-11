# SPDX-FileCopyrightText: Annie Chiang <anniechiang.yn@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Unit tests for observal_cli/cmd_doctor.py helpers.

Covers: _is_already_shimmed, _wrap_with_shim, _parse_mcp_servers,
_is_observal_matcher_group, _is_observal_hook_entry,
_cleanup_claude_code, _cleanup_kiro, _patch_claude_code, _patch_kiro.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from unittest.mock import patch

if TYPE_CHECKING:
    from pathlib import Path

import pytest

from observal_cli.cmd_doctor import (
    _cleanup_claude_code,
    _cleanup_kiro,
    _parse_mcp_servers,
    _patch_claude_code,
    _patch_kiro,
    _wrap_with_shim,
)
from observal_cli.shared.utils import (
    is_already_shimmed as _is_already_shimmed,
    is_observal_hook_entry as _is_observal_hook_entry,
    is_observal_matcher_group as _is_observal_matcher_group,
)

# -- Fixtures ------------------------------------------------------


@pytest.fixture()
def settings_path(tmp_path: Path):
    """Patch CLAUDE_SETTINGS_PATH to a temp file."""
    fake_path = tmp_path / ".claude" / "settings.json"
    with patch("observal_cli.settings_reconciler.CLAUDE_SETTINGS_PATH", fake_path):
        yield fake_path


@pytest.fixture()
def config_path(tmp_path: Path):
    """Patch config module to use a temp dir."""
    fake_config = tmp_path / ".observal" / "config.json"
    fake_config.parent.mkdir(parents=True, exist_ok=True)
    fake_config.write_text("{}", encoding="utf-8")

    def fake_load():
        return json.loads(fake_config.read_text(encoding="utf-8"))

    def fake_save(updates):
        current = fake_load()
        current.update(updates)
        fake_config.write_text(json.dumps(current), encoding="utf-8")

    with (
        patch("observal_cli.settings_reconciler.config.load", side_effect=fake_load),
        patch("observal_cli.settings_reconciler.config.save", side_effect=fake_save),
    ):
        yield fake_config


@pytest.fixture()
def kiro_agents_dir(tmp_path: Path):
    """Create a temp ~/.kiro/agents/ directory with one empty agent file."""
    agents_dir = tmp_path / ".kiro" / "agents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    agent_file = agents_dir / "default.json"
    agent_file.write_text("{}", encoding="utf-8")
    return agents_dir


# -- _is_already_shimmed -------------------------------------------


class TestIsAlreadyShimmed:
    def test_bare_command_not_shimmed(self):
        """A plain command like 'node' is not shimmed."""
        entry = {"command": "node", "args": ["index.js"]}
        assert not _is_already_shimmed(entry)

    def test_shim_command_is_shimmed(self):
        """An entry whose command is observal-shim is already shimmed."""
        entry = {"command": "observal-shim", "args": ["--mcp-id", "my-tool", "--", "node"]}
        assert _is_already_shimmed(entry)

    def test_shim_in_args_is_shimmed(self):
        """An entry with observal-shim anywhere in args is already shimmed."""
        entry = {"command": "env", "args": ["observal-shim", "--mcp-id", "x", "--", "node"]}
        assert _is_already_shimmed(entry)


# -- _wrap_with_shim -----------------------------------------------


class TestWrapWithShim:
    def test_stdio_entry_is_wrapped(self):
        """A stdio entry gets its command replaced with observal-shim."""
        entry = {"command": "node", "args": ["tool/index.js"]}
        result = _wrap_with_shim(entry, "my-tool")

        assert result["command"] == "observal-shim"
        assert "node" in result["args"]
        assert "my-tool" in result["args"]

    def test_http_url_entry_passes_through(self):
        """An entry with a url field is returned unchanged."""
        entry = {"url": "http://localhost:3000/mcp", "transport": "sse"}
        result = _wrap_with_shim(entry, "remote-tool")

        assert result == entry

    def test_wrapped_entry_preserves_original_args(self):
        """Original args are appended after -- in the shimmed entry."""
        entry = {"command": "python", "args": ["-m", "my_server"]}
        result = _wrap_with_shim(entry, "py-tool")

        assert "-m" in result["args"]
        assert "my_server" in result["args"]


# -- _parse_mcp_servers --------------------------------------------


class TestParseMcpServers:
    def test_mcpServers_key(self):
        """claude-code uses the top-level mcpServers key."""
        config_data = {"mcpServers": {"my-tool": {"command": "node"}}}
        result = _parse_mcp_servers(config_data, "claude-code")
        assert "my-tool" in result

    def test_mcp_dot_servers_key(self):
        """codex uses the nested mcp.servers key."""
        config_data = {"mcp": {"servers": {"codex-tool": {"command": "python"}}}}
        result = _parse_mcp_servers(config_data, "codex")
        assert "codex-tool" in result

    def test_mcp_key(self):
        """opencode uses the top-level mcp key directly."""
        config_data = {"mcp": {"opencode-tool": {"command": "node"}}}
        result = _parse_mcp_servers(config_data, "opencode")
        assert "opencode-tool" in result

    def test_servers_key(self):
        """copilot uses the top-level servers key."""
        config_data = {"servers": {"copilot-tool": {"command": "node"}}}
        result = _parse_mcp_servers(config_data, "copilot")
        assert "copilot-tool" in result

    def test_empty_config_returns_empty_dict(self):
        """Missing key returns an empty dict rather than raising."""
        result = _parse_mcp_servers({}, "claude-code")
        assert result == {}


# -- _is_observal_matcher_group / _is_observal_hook_entry ---------


class TestHookIdentification:
    def test_legacy_hook_marker_identified(self):
        """Legacy observal-hook path is recognised as an Observal entry."""
        entry = {"type": "command", "command": "/path/to/observal-hook.sh"}
        assert _is_observal_hook_entry(entry)

    def test_new_module_path_identified(self):
        """Current session_push module path is recognised as an Observal entry."""
        entry = {"type": "command", "command": "python -m observal_cli.hooks.session_push"}
        assert _is_observal_hook_entry(entry)

    def test_foreign_hook_entry_not_identified(self):
        """An unrelated hook command is not mistaken for Observal."""
        entry = {"type": "command", "command": "/usr/local/bin/my-custom-hook.sh"}
        assert not _is_observal_hook_entry(entry)

    def test_metadata_key_identifies_group(self):
        """A matcher group with _observal metadata is identified as Observal-managed."""
        group = {
            "_observal": {"version": "1"},
            "hooks": [{"type": "command", "command": "/some/path.sh"}],
        }
        assert _is_observal_matcher_group(group)

    def test_legacy_path_in_hooks_identifies_group(self):
        """A group without metadata but with a legacy hook path is still identified."""
        group = {"hooks": [{"type": "command", "command": "/path/to/observal-hook.sh"}]}
        assert _is_observal_matcher_group(group)

    def test_foreign_group_not_identified(self):
        """A group containing only foreign hooks is not identified as Observal."""
        group = {"hooks": [{"type": "command", "command": "/usr/bin/my-linter.sh"}]}
        assert not _is_observal_matcher_group(group)


# -- _cleanup_claude_code ------------------------------------------


class TestCleanupClaudeCode:
    def test_dry_run_produces_no_writes(self, tmp_path: Path, monkeypatch):
        """dry_run=True computes changes but does not modify the file."""
        monkeypatch.setenv("HOME", str(tmp_path))

        settings_path = tmp_path / ".claude" / "settings.json"
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "hooks": {
                "UserPromptSubmit": [
                    {
                        "_observal": {"version": "1"},
                        "hooks": [{"type": "command", "command": "observal_cli.hooks.session_push"}],
                    }
                ]
            }
        }
        settings_path.write_text(json.dumps(data), encoding="utf-8")
        original_mtime = settings_path.stat().st_mtime

        _cleanup_claude_code(dry_run=True)

        assert settings_path.stat().st_mtime == original_mtime

    def test_non_dry_strips_observal_hooks(self, tmp_path: Path, monkeypatch):
        """Non-dry run removes Observal-managed hook groups."""
        monkeypatch.setenv("HOME", str(tmp_path))

        settings_path = tmp_path / ".claude" / "settings.json"
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "hooks": {
                "UserPromptSubmit": [
                    {
                        "_observal": {"version": "1"},
                        "hooks": [{"type": "command", "command": "observal_cli.hooks.session_push"}],
                    }
                ]
            }
        }
        settings_path.write_text(json.dumps(data), encoding="utf-8")

        _cleanup_claude_code(dry_run=False)

        written = json.loads(settings_path.read_text(encoding="utf-8"))
        assert "UserPromptSubmit" not in written.get("hooks", {})

    def test_non_dry_preserves_foreign_hooks(self, tmp_path: Path, monkeypatch):
        """Non-dry run keeps non-Observal hooks untouched."""
        monkeypatch.setenv("HOME", str(tmp_path))

        settings_path = tmp_path / ".claude" / "settings.json"
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        foreign_group = {"hooks": [{"type": "command", "command": "/usr/bin/my-linter.sh"}]}
        observal_group = {
            "_observal": {"version": "1"},
            "hooks": [{"type": "command", "command": "observal_cli.hooks.session_push"}],
        }
        data = {"hooks": {"UserPromptSubmit": [foreign_group, observal_group]}}
        settings_path.write_text(json.dumps(data), encoding="utf-8")

        _cleanup_claude_code(dry_run=False)

        written = json.loads(settings_path.read_text(encoding="utf-8"))
        groups = written.get("hooks", {}).get("UserPromptSubmit", [])
        assert groups == [foreign_group]


# -- _cleanup_kiro -------------------------------------------------


class TestCleanupKiro:
    def test_dry_run_produces_no_writes(self, tmp_path: Path, monkeypatch, kiro_agents_dir):
        """dry_run=True computes changes but does not modify agent files."""
        monkeypatch.setenv("HOME", str(tmp_path))

        agent_file = kiro_agents_dir / "default.json"
        data = {
            "hooks": {
                "userPromptSubmit": [
                    {"type": "command", "command": "observal_cli.hooks.kiro_session_push"}
                ]
            }
        }
        agent_file.write_text(json.dumps(data), encoding="utf-8")
        original_mtime = agent_file.stat().st_mtime

        _cleanup_kiro(dry_run=True)

        assert agent_file.stat().st_mtime == original_mtime

    def test_non_dry_strips_observal_hooks(self, tmp_path: Path, monkeypatch, kiro_agents_dir):
        """Non-dry run removes Observal hook entries from agent files."""
        monkeypatch.setenv("HOME", str(tmp_path))

        agent_file = kiro_agents_dir / "default.json"
        data = {
            "hooks": {
                "userPromptSubmit": [
                    {"type": "command", "command": "observal_cli.hooks.kiro_session_push"}
                ]
            }
        }
        agent_file.write_text(json.dumps(data), encoding="utf-8")

        _cleanup_kiro(dry_run=False)

        written = json.loads(agent_file.read_text(encoding="utf-8"))
        assert "userPromptSubmit" not in written.get("hooks", {})

    def test_non_dry_preserves_foreign_hooks(self, tmp_path: Path, monkeypatch, kiro_agents_dir):
        """Non-dry run keeps non-Observal hook entries in agent files."""
        monkeypatch.setenv("HOME", str(tmp_path))

        agent_file = kiro_agents_dir / "default.json"
        foreign = {"type": "command", "command": "/usr/bin/foreign-hook.sh"}
        observal = {"type": "command", "command": "observal_cli.hooks.kiro_session_push"}
        data = {"hooks": {"userPromptSubmit": [foreign, observal]}}
        agent_file.write_text(json.dumps(data), encoding="utf-8")

        _cleanup_kiro(dry_run=False)

        written = json.loads(agent_file.read_text(encoding="utf-8"))
        entries = written.get("hooks", {}).get("userPromptSubmit", [])
        assert entries == [foreign]


# -- _patch_claude_code --------------------------------------------


class TestPatchClaudeCode:
    def test_fresh_install_creates_expected_dict(self, tmp_path, monkeypatch, settings_path, config_path):
        """Fresh install writes a settings file containing a hooks key."""
        monkeypatch.setenv("HOME", str(tmp_path))
        settings_path.parent.mkdir(parents=True, exist_ok=True)

        changed = _patch_claude_code(dry_run=False)

        assert changed is True
        assert settings_path.exists()
        written = json.loads(settings_path.read_text(encoding="utf-8"))
        assert "hooks" in written

    def test_second_run_is_idempotent(self, tmp_path, monkeypatch, settings_path, config_path):
        """Running patch twice produces no changes on the second run."""
        monkeypatch.setenv("HOME", str(tmp_path))
        settings_path.parent.mkdir(parents=True, exist_ok=True)

        _patch_claude_code(dry_run=False)
        changed = _patch_claude_code(dry_run=False)

        assert changed is False


# -- _patch_kiro ---------------------------------------------------


class TestPatchKiro:
    def test_fresh_install_creates_expected_dict(self, tmp_path: Path, monkeypatch, kiro_agents_dir):
        """Fresh install writes hooks into the agent file."""
        monkeypatch.setenv("HOME", str(tmp_path))

        changed = _patch_kiro(dry_run=False)

        assert changed is True
        agent_file = kiro_agents_dir / "default.json"
        written = json.loads(agent_file.read_text(encoding="utf-8"))
        assert "hooks" in written

    def test_second_run_is_idempotent(self, tmp_path: Path, monkeypatch, kiro_agents_dir):
        """Running patch twice produces no changes on the second run."""
        monkeypatch.setenv("HOME", str(tmp_path))

        _patch_kiro(dry_run=False)
        changed = _patch_kiro(dry_run=False)

        assert changed is False
