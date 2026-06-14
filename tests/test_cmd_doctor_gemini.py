# SPDX-FileCopyrightText: 2026 Madhumidha
# SPDX-FileCopyrightText: 2026 Madhumidha <madhumidha072005@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Tests for Gemini CLI integration in observal doctor."""

import json
from pathlib import Path

from observal_cli.cmd_doctor import _check_gemini, _cleanup_gemini, _patch_gemini
from observal_cli.shared.utils import OBSERVAL_METADATA_KEY


def test_check_gemini_missing_hooks(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    issues = []
    warnings = []

    _check_gemini(issues, warnings)

    assert not issues
    assert not warnings

    # Empty settings.json
    gemini_dir = tmp_path / ".gemini"
    gemini_dir.mkdir()
    hooks_path = gemini_dir / "settings.json"
    hooks_path.write_text("{}")

    warnings.clear()
    _check_gemini(issues, warnings)
    assert len(warnings) == 1
    assert "Gemini CLI session push hooks not installed" in warnings[0]


def test_check_gemini_present_hooks(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    issues = []
    warnings = []

    gemini_dir = tmp_path / ".gemini"
    gemini_dir.mkdir()
    hooks_path = gemini_dir / "settings.json"
    hooks_path.write_text(
        json.dumps(
            {
                "BeforeAgent": [{"hooks": [{"command": "python -m observal_cli.hooks.session_push"}]}],
                "SessionEnd": [{"hooks": [{"command": "python -m observal_cli.hooks.session_push"}]}],
            }
        )
    )

    _check_gemini(issues, warnings)
    assert not issues
    assert not warnings


def test_patch_gemini_dry_run(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    changed = _patch_gemini(dry_run=True)
    assert changed
    assert not (tmp_path / ".gemini" / "settings.json").exists()

    out = capsys.readouterr().out
    assert "Would install hooks" in out


def test_patch_gemini_actual(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    changed = _patch_gemini(dry_run=False)
    assert changed

    hooks_path = tmp_path / ".gemini" / "settings.json"
    assert hooks_path.exists()

    data = json.loads(hooks_path.read_text())
    assert "BeforeAgent" in data
    assert "SessionEnd" in data
    assert OBSERVAL_METADATA_KEY in data["BeforeAgent"][0]


def test_cleanup_gemini(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    gemini_dir = tmp_path / ".gemini"
    gemini_dir.mkdir()
    hooks_path = gemini_dir / "settings.json"
    hooks_path.write_text(
        json.dumps(
            {
                "BeforeAgent": [{OBSERVAL_METADATA_KEY: {"version": "1"}}, {"hooks": [{"command": "foreign_command"}]}],
                "other_setting": True,
            }
        )
    )

    # Run
    changed = _cleanup_gemini(dry_run=True)
    assert changed
    data = json.loads(hooks_path.read_text())
    assert OBSERVAL_METADATA_KEY in data["BeforeAgent"][0]

    changed = _cleanup_gemini(dry_run=False)
    assert changed

    data = json.loads(hooks_path.read_text())
    assert len(data["BeforeAgent"]) == 1
    assert "foreign_command" in data["BeforeAgent"][0]["hooks"][0]["command"]
    assert data["other_setting"] is True

    changed = _cleanup_gemini(dry_run=False)
    assert not changed
