# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""OpenCode doctor patch tests."""

from observal_shared.opencode_plugin_source import OPENCODE_PLUGIN_SOURCE

from observal_cli.cmd_doctor import _check_opencode, _patch_opencode


def test_opencode_patch_updates_only_when_hash_differs(tmp_path, monkeypatch):
    monkeypatch.setattr("observal_cli.cmd_doctor.Path.home", lambda: tmp_path)
    plugin_path = tmp_path / ".config" / "opencode" / "plugins" / "observal-plugin.ts"

    assert _patch_opencode(dry_run=False) is True
    assert plugin_path.read_text() == OPENCODE_PLUGIN_SOURCE

    assert _patch_opencode(dry_run=False) is False

    plugin_path.write_text("old plugin")
    assert _patch_opencode(dry_run=False) is True
    assert plugin_path.read_text() == OPENCODE_PLUGIN_SOURCE


def test_opencode_check_warns_for_stub(tmp_path, monkeypatch):
    monkeypatch.setattr("observal_cli.cmd_doctor.Path.home", lambda: tmp_path)
    plugin_path = tmp_path / ".config" / "opencode" / "plugins" / "observal-plugin.ts"
    plugin_path.parent.mkdir(parents=True)
    plugin_path.write_text("// offline stub\nexport const ObservalPlugin = async () => ({ event: async () => {} });")
    issues: list[str] = []
    warnings: list[str] = []

    _check_opencode(issues, warnings)

    assert issues == []
    assert any("offline stub" in warning for warning in warnings)


def test_opencode_check_warns_for_drift(tmp_path, monkeypatch):
    monkeypatch.setattr("observal_cli.cmd_doctor.Path.home", lambda: tmp_path)
    plugin_path = tmp_path / ".config" / "opencode" / "plugins" / "observal-plugin.ts"
    plugin_path.parent.mkdir(parents=True)
    plugin_path.write_text(OPENCODE_PLUGIN_SOURCE.replace("session.idle", "session.idle.modified", 1))
    issues: list[str] = []
    warnings: list[str] = []

    _check_opencode(issues, warnings)

    assert issues == []
    assert any("stale or modified" in warning for warning in warnings)


def test_opencode_check_accepts_current_plugin(tmp_path, monkeypatch):
    monkeypatch.setattr("observal_cli.cmd_doctor.Path.home", lambda: tmp_path)
    plugin_path = tmp_path / ".config" / "opencode" / "plugins" / "observal-plugin.ts"
    plugin_path.parent.mkdir(parents=True)
    plugin_path.write_text(OPENCODE_PLUGIN_SOURCE)
    issues: list[str] = []
    warnings: list[str] = []

    _check_opencode(issues, warnings)

    assert issues == []
    assert warnings == []
