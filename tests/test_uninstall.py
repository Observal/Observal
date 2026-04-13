"""Tests for the `observal uninstall` command."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

if TYPE_CHECKING:
    from pathlib import Path

from typer.testing import CliRunner

from observal_cli.cmd_uninstall import CONFIRMATION_PHRASE
from observal_cli.main import app as cli_app

runner = CliRunner()

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _plain(text: str) -> str:
    return _ANSI_RE.sub("", text)


# ── Confirmation tests ─────────────────────────────────────


def test_aborts_on_wrong_confirmation(tmp_path: Path):
    """Wrong confirmation phrase should abort."""
    repo = tmp_path / "Observal"
    repo.mkdir()
    (repo / "docker").mkdir()
    (repo / "docker" / "docker-compose.yml").write_text("services:")

    result = runner.invoke(
        cli_app,
        ["uninstall", "--repo-dir", str(repo)],
        input="wrong phrase\n",
    )
    assert result.exit_code == 1
    assert "did not match" in _plain(result.output).lower()


def test_aborts_on_empty_confirmation(tmp_path: Path):
    """Empty confirmation should abort."""
    repo = tmp_path / "Observal"
    repo.mkdir()
    (repo / "docker").mkdir()
    (repo / "docker" / "docker-compose.yml").write_text("services:")

    result = runner.invoke(
        cli_app,
        ["uninstall", "--repo-dir", str(repo)],
        input="\n",
    )
    assert result.exit_code == 1
    output = _plain(result.output).lower()
    # Typer aborts on empty prompt input
    assert "aborted" in output or "did not match" in output


# ── Docker teardown tests ──────────────────────────────────


@patch("observal_cli.cmd_uninstall.subprocess.run")
@patch("observal_cli.cmd_uninstall.shutil.rmtree")
def test_docker_down_called(mock_rmtree: MagicMock, mock_run: MagicMock, tmp_path: Path):
    """docker compose down -v should be called with the correct cwd."""
    repo = tmp_path / "Observal"
    repo.mkdir()
    (repo / "docker").mkdir()
    (repo / "docker" / "docker-compose.yml").write_text("services:")

    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

    result = runner.invoke(
        cli_app,
        ["uninstall", "--repo-dir", str(repo), "--keep-config", "--keep-cli"],
        input=f"{CONFIRMATION_PHRASE}\n",
    )
    assert result.exit_code == 0

    # Find the docker compose call
    docker_calls = [
        c
        for c in mock_run.call_args_list
        if c.args and c.args[0] == ["docker", "compose", "down", "-v", "--rmi", "all"]
    ]
    assert len(docker_calls) == 1
    assert docker_calls[0].kwargs["cwd"] == repo / "docker"


@patch("observal_cli.cmd_uninstall.subprocess.run", side_effect=FileNotFoundError)
@patch("observal_cli.cmd_uninstall.shutil.rmtree")
def test_docker_failure_continues(mock_rmtree: MagicMock, mock_run: MagicMock, tmp_path: Path):
    """Docker failure should not abort the rest of the uninstall."""
    repo = tmp_path / "Observal"
    repo.mkdir()
    (repo / "docker").mkdir()
    (repo / "docker" / "docker-compose.yml").write_text("services:")

    result = runner.invoke(
        cli_app,
        ["uninstall", "--repo-dir", str(repo), "--keep-config", "--keep-cli"],
        input=f"{CONFIRMATION_PHRASE}\n",
    )
    assert result.exit_code == 0
    output = _plain(result.output)
    assert "docker not found" in output.lower()
    assert "uninstalled" in output.lower()


# ── Directory deletion tests ───────────────────────────────


@patch("observal_cli.cmd_uninstall.subprocess.run")
@patch("observal_cli.cmd_uninstall.shutil.rmtree")
def test_repo_directory_deleted(mock_rmtree: MagicMock, mock_run: MagicMock, tmp_path: Path):
    """Repo directory should be deleted after docker teardown."""
    repo = tmp_path / "Observal"
    repo.mkdir()
    (repo / "docker").mkdir()
    (repo / "docker" / "docker-compose.yml").write_text("services:")

    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

    result = runner.invoke(
        cli_app,
        ["uninstall", "--repo-dir", str(repo), "--keep-config", "--keep-cli"],
        input=f"{CONFIRMATION_PHRASE}\n",
    )
    assert result.exit_code == 0
    # rmtree should have been called with the repo path
    rmtree_paths = [str(c.args[0]) for c in mock_rmtree.call_args_list]
    assert str(repo) in rmtree_paths


@patch("observal_cli.cmd_uninstall.subprocess.run")
@patch("observal_cli.cmd_uninstall.shutil.rmtree")
@patch("observal_cli.cmd_uninstall.CONFIG_DIR", new_callable=lambda: property(lambda self: None))
def test_config_directory_deleted(mock_config_dir, mock_rmtree: MagicMock, mock_run: MagicMock, tmp_path: Path):
    """~/.observal/ config should be deleted by default."""
    repo = tmp_path / "Observal"
    repo.mkdir()
    (repo / "docker").mkdir()
    (repo / "docker" / "docker-compose.yml").write_text("services:")

    fake_config = tmp_path / ".observal"
    fake_config.mkdir()

    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

    with patch("observal_cli.cmd_uninstall.CONFIG_DIR", fake_config):
        result = runner.invoke(
            cli_app,
            ["uninstall", "--repo-dir", str(repo), "--keep-cli"],
            input=f"{CONFIRMATION_PHRASE}\n",
        )
    assert result.exit_code == 0
    rmtree_paths = [str(c.args[0]) for c in mock_rmtree.call_args_list]
    assert str(fake_config) in rmtree_paths


@patch("observal_cli.cmd_uninstall.subprocess.run")
@patch("observal_cli.cmd_uninstall.shutil.rmtree")
def test_keep_config_flag(mock_rmtree: MagicMock, mock_run: MagicMock, tmp_path: Path):
    """--keep-config should skip config directory deletion."""
    repo = tmp_path / "Observal"
    repo.mkdir()
    (repo / "docker").mkdir()
    (repo / "docker" / "docker-compose.yml").write_text("services:")

    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

    with patch("observal_cli.cmd_uninstall.CONFIG_DIR", tmp_path / ".observal"):
        result = runner.invoke(
            cli_app,
            ["uninstall", "--repo-dir", str(repo), "--keep-config", "--keep-cli"],
            input=f"{CONFIRMATION_PHRASE}\n",
        )
    assert result.exit_code == 0
    # rmtree should only be called for the repo, not config
    rmtree_paths = [str(c.args[0]) for c in mock_rmtree.call_args_list]
    assert str(tmp_path / ".observal") not in rmtree_paths


# ── CLI uninstall tests ────────────────────────────────────


@patch("observal_cli.cmd_uninstall.subprocess.run")
@patch("observal_cli.cmd_uninstall.shutil.rmtree")
def test_cli_uninstall_called(mock_rmtree: MagicMock, mock_run: MagicMock, tmp_path: Path):
    """uv tool uninstall should be called when --keep-cli is not set."""
    repo = tmp_path / "Observal"
    repo.mkdir()
    (repo / "docker").mkdir()
    (repo / "docker" / "docker-compose.yml").write_text("services:")

    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

    with patch("observal_cli.cmd_uninstall.CONFIG_DIR", tmp_path / ".observal"):
        result = runner.invoke(
            cli_app,
            ["uninstall", "--repo-dir", str(repo), "--keep-config"],
            input=f"{CONFIRMATION_PHRASE}\n",
        )
    assert result.exit_code == 0
    uv_calls = [
        c for c in mock_run.call_args_list if c.args and c.args[0] == ["uv", "tool", "uninstall", "observal-cli"]
    ]
    assert len(uv_calls) == 1


@patch("observal_cli.cmd_uninstall.subprocess.run")
@patch("observal_cli.cmd_uninstall.shutil.rmtree")
def test_keep_cli_flag(mock_rmtree: MagicMock, mock_run: MagicMock, tmp_path: Path):
    """--keep-cli should skip CLI uninstall."""
    repo = tmp_path / "Observal"
    repo.mkdir()
    (repo / "docker").mkdir()
    (repo / "docker" / "docker-compose.yml").write_text("services:")

    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

    result = runner.invoke(
        cli_app,
        ["uninstall", "--repo-dir", str(repo), "--keep-config", "--keep-cli"],
        input=f"{CONFIRMATION_PHRASE}\n",
    )
    assert result.exit_code == 0
    uv_calls = [
        c for c in mock_run.call_args_list if c.args and c.args[0] == ["uv", "tool", "uninstall", "observal-cli"]
    ]
    assert len(uv_calls) == 0


# ── Repo detection tests ──────────────────────────────────


@patch("observal_cli.cmd_uninstall.subprocess.run")
@patch("observal_cli.cmd_uninstall.shutil.rmtree")
def test_explicit_repo_dir_option(mock_rmtree: MagicMock, mock_run: MagicMock, tmp_path: Path):
    """--repo-dir should be used directly when provided."""
    repo = tmp_path / "my-observal"
    repo.mkdir()
    (repo / "docker").mkdir()
    (repo / "docker" / "docker-compose.yml").write_text("services:")

    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

    result = runner.invoke(
        cli_app,
        ["uninstall", "--repo-dir", str(repo), "--keep-config", "--keep-cli"],
        input=f"{CONFIRMATION_PHRASE}\n",
    )
    assert result.exit_code == 0
    docker_calls = [
        c
        for c in mock_run.call_args_list
        if c.args and c.args[0] == ["docker", "compose", "down", "-v", "--rmi", "all"]
    ]
    assert len(docker_calls) == 1
    assert docker_calls[0].kwargs["cwd"] == repo / "docker"


def test_repo_not_found_continues(tmp_path: Path):
    """When repo dir cannot be detected, command still proceeds with config/cli cleanup."""
    with (
        patch("observal_cli.cmd_uninstall.subprocess.run") as mock_run,
        patch("observal_cli.cmd_uninstall.shutil.rmtree"),
        patch("observal_cli.cmd_uninstall.Path.cwd", return_value=tmp_path),
        patch("observal_cli.cmd_uninstall.CONFIG_DIR", tmp_path / ".observal"),
    ):
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        result = runner.invoke(
            cli_app,
            ["uninstall", "--keep-config"],
            input=f"{CONFIRMATION_PHRASE}\n",
        )
    assert result.exit_code == 0
    output = _plain(result.output)
    assert "not detected" in output.lower()
    assert "uninstalled" in output.lower()


# ── Help text test ─────────────────────────────────────────


def test_help_shows_uninstall():
    """observal uninstall --help should show the command description."""
    result = runner.invoke(cli_app, ["uninstall", "--help"])
    assert result.exit_code == 0
    output = _plain(result.output)
    assert "uninstall" in output.lower()
    assert "--repo-dir" in output
    assert "--keep-config" in output
    assert "--keep-cli" in output
