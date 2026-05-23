# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Tests for observal_cli.install_detector."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from observal_cli.install_detector import (
    InstallMethod,
    _detect_from_path,
)


class TestDetectFromPath:
    def test_homebrew_detected(self):
        path = Path("/opt/homebrew/bin/observal")
        result = _detect_from_path(path, str(path).lower())
        assert result.method == InstallMethod.HOMEBREW
        assert result.managed_by == "brew"
        assert result.writable is False

    def test_linuxbrew_detected(self):
        path = Path("/home/user/.linuxbrew/bin/observal")
        result = _detect_from_path(path, str(path).lower())
        assert result.method == InstallMethod.HOMEBREW
        assert result.managed_by == "brew"

    def test_system_package_detected(self):
        path = Path("/usr/bin/observal")
        with patch("os.access", return_value=False):
            result = _detect_from_path(path, str(path).lower())
        assert result.method == InstallMethod.SYSTEM_PACKAGE
        assert result.writable is False

    def test_binary_frozen(self, monkeypatch):
        monkeypatch.setattr("sys.frozen", True, raising=False)
        path = Path("/home/user/bin/observal")
        with patch("os.access", return_value=True):
            result = _detect_from_path(path, str(path).lower())
        assert result.method == InstallMethod.BINARY
        assert result.writable is True

    def test_uv_tool_dir(self, monkeypatch, tmp_path):
        uv_dir = tmp_path / ".local" / "share" / "uv" / "tools"
        uv_dir.mkdir(parents=True)
        binary = uv_dir / "observal"
        binary.touch()

        monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
        result = _detect_from_path(binary, str(binary).lower())
        assert result.method == InstallMethod.UV_TOOL
        assert result.managed_by == "uv"

    def test_fallback_pip(self, monkeypatch):
        monkeypatch.delattr("sys.frozen", raising=False)
        path = Path("/home/user/.venv/bin/observal")
        # Not under uv dir, not homebrew, not system, not frozen
        with (
            patch("os.access", return_value=True),
            patch("observal_cli.install_detector._check_uv_tool_list", return_value=False),
        ):
            result = _detect_from_path(path, str(path).lower())
        assert result.method == InstallMethod.PIP
        assert result.managed_by == "pip"


class TestWritableCheck:
    def test_writable_true(self):
        path = Path("/tmp/observal")
        with patch("os.access", return_value=True):
            result = _detect_from_path(path, str(path).lower())
        # Falls through to pip since not frozen, not uv, etc.
        assert result.writable is True

    def test_writable_false(self):
        path = Path("/usr/bin/observal")
        with patch("os.access", return_value=False):
            result = _detect_from_path(path, str(path).lower())
        assert result.writable is False
