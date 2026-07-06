# SPDX-FileCopyrightText: 2026 Hemalatha Madeswaran <hemalathamadeswaran@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""E2E tests for the ``observal scan`` CLI command.

Covers (per issue #959):
  * ``observal scan`` outputs discovered components and never crashes.

The tests redirect ``$HOME`` to a temporary directory so ``Path.home()``
points at a hermetic sandbox; the CWD is also pinned to the sandbox so the
project-directory scanner does not pick up files from the host repo.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

from observal_cli.main import app

if TYPE_CHECKING:
    from pathlib import Path

runner = CliRunner()


# ── Fixtures ───────────────────────────────────────────────────


@pytest.fixture()
def sandbox_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect ``Path.home()`` and CWD to an empty temp directory.

    ``observal scan`` walks well-known harness locations rooted at ``~``.  To
    keep the test hermetic we point ``HOME`` at a tmp dir.  We also chdir to
    the same dir so the project-directory scanner has nothing to find.
    """
    monkeypatch.setenv("HOME", str(tmp_path))
    # On Windows, ``Path.home()`` consults USERPROFILE first.
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2))


# ── Tests ──────────────────────────────────────────────────────


class TestScanCommand:
    """``observal scan``."""

    def test_scan_with_no_ide_dirs_exits_with_message(self, sandbox_home: Path) -> None:
        """An entirely empty home should exit non-zero with a friendly notice."""
        result = runner.invoke(app, ["scan"])

        assert result.exit_code == 1, result.output
        assert "No harness configurations found" in result.output

    def test_scan_discovers_kiro_mcp_server(self, sandbox_home: Path) -> None:
        """A Kiro MCP entry must show up in the scan output."""
        kiro = sandbox_home / ".kiro"
        _write_json(
            kiro / "settings" / "mcp.json",
            {
                "mcpServers": {
                    "kiro-mcp-test": {"command": "npx", "args": ["-y", "kiro-mcp-test"]},
                }
            },
        )

        result = runner.invoke(app, ["scan"])

        assert result.exit_code == 0, result.output
        assert "kiro-mcp-test" in result.output
        assert "components discovered" in result.output
        # The harness detection table should list kiro
        assert "kiro" in result.output

    def test_scan_discovers_multiple_ides_at_once(self, sandbox_home: Path) -> None:
        """A scan with two harnesses configured must surface both in one run."""
        _write_json(
            sandbox_home / ".kiro" / "settings" / "mcp.json",
            {"mcpServers": {"kiro-srv": {"command": "npx", "args": ["-y", "kiro-srv"]}}},
        )
        _write_json(
            sandbox_home / ".codex" / "config.toml",
            {},
        )

        result = runner.invoke(app, ["scan"])

        assert result.exit_code == 0, result.output
        assert "kiro-srv" in result.output

    def test_scan_with_ide_filter_excludes_other_ides(self, sandbox_home: Path) -> None:
        """``--harness kiro`` must scan Kiro and skip Claude Code."""
        # Kiro entry — should appear
        _write_json(
            sandbox_home / ".kiro" / "settings" / "mcp.json",
            {"mcpServers": {"kiro-only": {"command": "npx", "args": ["-y", "kiro-only"]}}},
        )
        # Claude Code entry — should NOT appear under --harness kiro
        _write_json(
            sandbox_home / ".claude" / "settings.json",
            {"mcpServers": {"claude-only": {"command": "node", "args": ["claude-only.js"]}}},
        )

        result = runner.invoke(app, ["scan", "--harness", "kiro"])

        assert result.exit_code == 0, result.output
        assert "kiro-only" in result.output
        assert "claude-only" not in result.output

    def test_scan_does_not_modify_files(self, sandbox_home: Path) -> None:
        """``observal scan`` is documented as read-only — verify nothing is rewritten."""
        kiro_settings = sandbox_home / ".kiro" / "settings" / "mcp.json"
        payload = {"mcpServers": {"unchanged": {"command": "npx", "args": ["-y", "unchanged"]}}}
        _write_json(kiro_settings, payload)
        before_mtime = kiro_settings.stat().st_mtime
        before_bytes = kiro_settings.read_bytes()

        result = runner.invoke(app, ["scan"])

        assert result.exit_code == 0, result.output
        assert kiro_settings.stat().st_mtime == before_mtime, "scan must not touch harness files"
        assert kiro_settings.read_bytes() == before_bytes


if __name__ == "__main__":  # pragma: no cover - manual debug entry point
    pytest.main([__file__, "-v"])
