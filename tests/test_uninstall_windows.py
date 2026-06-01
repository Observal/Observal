# SPDX-FileCopyrightText: 2026 Vishnu Muthiah <vishnu.muthiah04@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Tests for Windows-specific uninstall behaviour (runs on any platform via mocking)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from observal_cli.cmd_uninstall import (
    CONFIRMATION_PHRASE,
    _create_windows_cleanup_script,
)
from observal_cli.main import app as cli_app

runner = CliRunner()


# ── Cleanup script generation ─────────────────────────────


def test_script_contains_repo_deletion(tmp_path: Path):
    script = _create_windows_cleanup_script(
        repo_root=Path("C:\\Users\\test\\Observal"),
        config_dir=None,
        uninstall_cli=False,
        uv_path=None,
    )
    try:
        content = script.read_text(encoding="utf-8")
        assert "Remove-Item" in content
        assert "C:\\Users\\test\\Observal" in content
        # Path must be inside a here-string (single-quote block)
        assert "$repoPath = @'" in content
    finally:
        script.unlink(missing_ok=True)


def test_script_contains_config_deletion(tmp_path: Path):
    script = _create_windows_cleanup_script(
        repo_root=None,
        config_dir=Path("C:\\Users\\test\\.observal"),
        uninstall_cli=False,
        uv_path=None,
    )
    try:
        content = script.read_text(encoding="utf-8")
        assert "$configPath = @'" in content
        assert "C:\\Users\\test\\.observal" in content
    finally:
        script.unlink(missing_ok=True)


def test_script_contains_uv_uninstall():
    uv = "C:\\Users\\test\\.local\\bin\\uv.exe"
    script = _create_windows_cleanup_script(
        repo_root=None,
        config_dir=None,
        uninstall_cli=True,
        uv_path=uv,
    )
    try:
        content = script.read_text(encoding="utf-8")
        assert "$uvPath = @'" in content
        assert uv in content
        assert "tool uninstall observal-cli" in content
    finally:
        script.unlink(missing_ok=True)


def test_script_skips_uv_when_path_is_none():
    script = _create_windows_cleanup_script(
        repo_root=None,
        config_dir=None,
        uninstall_cli=True,
        uv_path=None,
    )
    try:
        content = script.read_text(encoding="utf-8")
        assert "tool uninstall" not in content
    finally:
        script.unlink(missing_ok=True)


def test_script_self_deletes():
    script = _create_windows_cleanup_script(
        repo_root=Path("C:\\repo"),
        config_dir=None,
        uninstall_cli=False,
        uv_path=None,
    )
    try:
        content = script.read_text(encoding="utf-8")
        assert "$PSCommandPath" in content
    finally:
        script.unlink(missing_ok=True)


def test_script_retry_timing():
    """Repo deletion should retry 5 times with 3-second delays (15s window)."""
    script = _create_windows_cleanup_script(
        repo_root=Path("C:\\repo"),
        config_dir=None,
        uninstall_cli=False,
        uv_path=None,
    )
    try:
        content = script.read_text(encoding="utf-8")
        assert "$i -lt 5" in content
        assert "Start-Sleep -Seconds 3" in content
    finally:
        script.unlink(missing_ok=True)


# ── Windows uninstall integration (mocked platform) ──────


def _make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "Observal"
    repo.mkdir()
    (repo / "docker").mkdir()
    (repo / "docker" / "docker-compose.yml").write_text("services:")
    return repo


@patch("observal_cli.cmd_uninstall.sys")
@patch("observal_cli.cmd_uninstall._spawn_windows_cleanup", return_value=True)
@patch("observal_cli.cmd_uninstall._create_windows_cleanup_script")
@patch("observal_cli.cmd_uninstall.shutil")
@patch("observal_cli.cmd_uninstall.subprocess.run")
def test_windows_uses_deferred_cleanup(
    mock_run: MagicMock,
    mock_shutil: MagicMock,
    mock_create: MagicMock,
    mock_spawn: MagicMock,
    mock_sys: MagicMock,
    tmp_path: Path,
):
    mock_sys.platform = "win32"
    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
    mock_create.return_value = Path("/tmp/fake.ps1")
    mock_shutil.which.return_value = "/usr/bin/uv"

    repo = _make_repo(tmp_path)
    result = runner.invoke(
        cli_app,
        ["self", "uninstall", "--repo-dir", str(repo), "--keep-config"],
        input=f"{CONFIRMATION_PHRASE}\n",
    )
    assert result.exit_code == 0
    mock_create.assert_called_once()
    mock_spawn.assert_called_once()
    # rmtree should NOT have been called (deferred to script)
    mock_shutil.rmtree.assert_not_called()


@patch("observal_cli.cmd_uninstall.sys")
@patch("observal_cli.cmd_uninstall._spawn_windows_cleanup", return_value=True)
@patch("observal_cli.cmd_uninstall._create_windows_cleanup_script")
@patch("observal_cli.cmd_uninstall.shutil")
@patch("observal_cli.cmd_uninstall.subprocess.run")
def test_windows_resolves_uv_path(
    mock_run: MagicMock,
    mock_shutil: MagicMock,
    mock_create: MagicMock,
    mock_spawn: MagicMock,
    mock_sys: MagicMock,
    tmp_path: Path,
):
    mock_sys.platform = "win32"
    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
    mock_create.return_value = Path("/tmp/fake.ps1")
    mock_shutil.which.return_value = "C:\\Users\\test\\.local\\bin\\uv.exe"

    repo = _make_repo(tmp_path)
    result = runner.invoke(
        cli_app,
        ["self", "uninstall", "--repo-dir", str(repo), "--keep-config"],
        input=f"{CONFIRMATION_PHRASE}\n",
    )
    assert result.exit_code == 0
    # uv_path should be the resolved absolute path
    call_kwargs = mock_create.call_args
    assert call_kwargs[1].get("uv_path") or call_kwargs[0][3] == "C:\\Users\\test\\.local\\bin\\uv.exe"


@patch("observal_cli.cmd_uninstall.sys")
@patch("observal_cli.cmd_uninstall.shutil")
@patch("observal_cli.cmd_uninstall.subprocess.run")
def test_windows_uv_not_found_skips_cli(
    mock_run: MagicMock,
    mock_shutil: MagicMock,
    mock_sys: MagicMock,
    tmp_path: Path,
):
    mock_sys.platform = "win32"
    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
    mock_shutil.which.return_value = None

    repo = _make_repo(tmp_path)
    with (
        patch(
            "observal_cli.cmd_uninstall._create_windows_cleanup_script",
            return_value=Path("/tmp/fake.ps1"),
        ) as mock_create,
        patch(
            "observal_cli.cmd_uninstall._spawn_windows_cleanup",
            return_value=True,
        ),
    ):
        result = runner.invoke(
            cli_app,
            ["self", "uninstall", "--repo-dir", str(repo), "--keep-config"],
            input=f"{CONFIRMATION_PHRASE}\n",
        )
    assert result.exit_code == 0
    assert "uv not found" in result.output.lower() or "skipped" in result.output.lower()


@patch("observal_cli.cmd_uninstall.sys")
@patch("observal_cli.cmd_uninstall.subprocess.run")
@patch("observal_cli.cmd_uninstall.shutil.rmtree")
def test_unix_still_uses_sync_cleanup(
    mock_rmtree: MagicMock,
    mock_run: MagicMock,
    mock_sys: MagicMock,
    tmp_path: Path,
):
    mock_sys.platform = "darwin"
    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

    repo = _make_repo(tmp_path)
    result = runner.invoke(
        cli_app,
        ["self", "uninstall", "--repo-dir", str(repo), "--keep-config", "--keep-cli"],
        input=f"{CONFIRMATION_PHRASE}\n",
    )
    assert result.exit_code == 0
    rmtree_paths = [str(c.args[0]) for c in mock_rmtree.call_args_list]
    assert str(repo) in rmtree_paths
