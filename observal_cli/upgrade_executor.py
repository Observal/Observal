# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""CLI upgrade executor - handles uv/pip/binary install paths.

Extracted from cmd_ops.py for testability and readability.
"""

from __future__ import annotations

import hashlib
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlparse

import httpx
import typer
from rich import print as rprint

from observal_cli import config
from observal_cli.constants import REDIRECT_ALLOWLIST
from observal_cli.install_detector import InstallInfo, InstallMethod

GITHUB_REPO = "Observal/Observal"


def execute(install_info: InstallInfo, target_version: str, direction: str, spinner) -> None:
    """Execute the actual version change for uv/pip/binary installs.

    Args:
        install_info: Detected install method and path.
        target_version: Target version string (e.g. "0.7.0").
        direction: "upgrade" or "downgrade".
        spinner: Context manager for progress display.
    """
    if install_info.method == InstallMethod.UV_TOOL:
        _install_via_uv(target_version, direction, spinner)
    elif install_info.method == InstallMethod.PIP:
        _install_via_pip(target_version, direction, spinner)
    elif install_info.method == InstallMethod.BINARY:
        _install_binary(install_info, target_version, direction, spinner)
    else:
        rprint(f"[red]Cannot {direction} - unsupported install method: {install_info.method.value}[/red]")
        raise typer.Exit(1)

    # Post-install verification
    _verify_install(direction)


def _install_via_uv(target_version: str, direction: str, spinner) -> None:
    with spinner(f"{direction.capitalize()}ing to v{target_version}..."):
        result = subprocess.run(
            ["uv", "tool", "install", f"observal-cli=={target_version}", "--force"],
            capture_output=True,
            text=True,
            timeout=120,
        )
    if result.returncode != 0:
        rprint(f"[red]{direction.capitalize()} failed:[/red] {result.stderr.strip()}")
        raise typer.Exit(1)


def _install_via_pip(target_version: str, direction: str, spinner) -> None:
    # Uses sys.executable to target the current Python environment. If the CLI
    # is installed via uv (preferred), the uv path is used instead (see execute()).
    # sys.executable is only reached for plain pip/pipx installs.
    with spinner(f"{direction.capitalize()}ing to v{target_version}..."):
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", f"observal-cli=={target_version}", "--quiet"],
            capture_output=True,
            text=True,
            timeout=120,
        )
    if result.returncode != 0:
        rprint(f"[red]{direction.capitalize()} failed:[/red] {result.stderr.strip()}")
        raise typer.Exit(1)


def _install_binary(install_info: InstallInfo, target_version: str, direction: str, spinner) -> None:
    """Download and install standalone binary with checksum verification."""
    system = platform.system().lower()
    machine = platform.machine().lower()

    if machine in ("x86_64", "amd64"):
        arch = "x64"
    elif machine in ("aarch64", "arm64"):
        arch = "arm64"
    else:
        rprint(f"[red]Unsupported architecture: {machine}[/red]")
        raise typer.Exit(1)

    os_name = {"linux": "linux", "darwin": "macos", "windows": "windows"}.get(system)
    if not os_name:
        rprint(f"[red]Unsupported OS: {system}[/red]")
        raise typer.Exit(1)

    suffix = ".exe" if system == "windows" else ""
    artifact_name = f"observal-{os_name}-{arch}{suffix}"

    # Fetch release by tag
    with spinner("Fetching release info..."):
        resp = httpx.get(
            f"https://api.github.com/repos/{GITHUB_REPO}/releases/tags/v{target_version}",
            timeout=15,
            headers={"Accept": "application/vnd.github+json"},
        )
    if resp.status_code != 200:
        rprint(f"[red]Release v{target_version} not found on GitHub.[/red]")
        raise typer.Exit(1)

    release_data = resp.json()
    assets = {a["name"]: a["browser_download_url"] for a in release_data.get("assets", [])}

    if artifact_name not in assets:
        rprint(f"[red]Binary '{artifact_name}' not found in release assets.[/red]")
        raise typer.Exit(1)

    # Download checksums
    checksums = _fetch_checksums(assets)

    # Download binary with redirect validation
    bin_content = _download_binary(assets[artifact_name], spinner, artifact_name)

    # Verify checksum
    _verify_checksum(bin_content, checksums, artifact_name)

    # Backup and replace
    _replace_binary(install_info, bin_content, target_version, system, suffix)


def _fetch_checksums(assets: dict[str, str]) -> dict[str, str]:
    """Download checksums.txt from release assets."""
    checksums: dict[str, str] = {}
    if "checksums.txt" in assets:
        ck_resp = httpx.get(assets["checksums.txt"], timeout=15, follow_redirects=True)
        if ck_resp.status_code == 200:
            for line in ck_resp.text.strip().splitlines():
                parts = line.split()
                if len(parts) == 2:
                    checksums[parts[1]] = parts[0]
    return checksums


def _download_binary(download_url: str, spinner, artifact_name: str) -> bytes:
    """Download binary with redirect domain validation."""
    with spinner(f"Downloading {artifact_name}..."):
        bin_resp = httpx.get(download_url, timeout=120, follow_redirects=True)

    if bin_resp.status_code != 200:
        rprint("[red]Download failed.[/red]")
        raise typer.Exit(1)

    # Validate final URL domain
    final_host = urlparse(str(bin_resp.url)).hostname
    if final_host and final_host not in REDIRECT_ALLOWLIST:
        rprint(f"[red]Download redirected to untrusted host: {final_host}[/red]")
        raise typer.Exit(1)

    return bin_resp.content


def _verify_checksum(content: bytes, checksums: dict[str, str], artifact_name: str) -> None:
    """Verify SHA-256 checksum. Aborts on mismatch."""
    actual_hash = hashlib.sha256(content).hexdigest()
    expected_hash = checksums.get(artifact_name)
    if expected_hash:
        if actual_hash != expected_hash:
            rprint("[red]CHECKSUM MISMATCH - download may be corrupted or tampered.[/red]")
            rprint(f"  Expected: {expected_hash}")
            rprint(f"  Got:      {actual_hash}")
            raise typer.Exit(1)
        rprint(f"[dim]SHA-256 verified: {actual_hash[:16]}...[/dim]")
    else:
        rprint("[yellow]No checksum available for verification.[/yellow]")
        if not typer.confirm("Install without verification?", default=False):
            raise typer.Abort()


def _replace_binary(install_info: InstallInfo, content: bytes, target_version: str, system: str, suffix: str) -> None:
    """Backup current binary and atomically replace with new one."""
    target_path = install_info.path
    if not install_info.writable:
        rprint(f"[red]Cannot write to {target_path} - permission denied.[/red]")
        raise typer.Exit(1)

    # Backup current
    backup_dir = config.CONFIG_DIR / "bin"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / "observal.prev"
    if target_path.exists():
        shutil.copy2(str(target_path), str(backup_path))

    # Write to temp file then atomic rename
    fd, tmp_path = tempfile.mkstemp(
        dir=target_path.parent,
        prefix=".observal-update-",
        suffix=suffix,
    )
    try:
        os.write(fd, content)
        os.close(fd)
        os.chmod(tmp_path, 0o755)

        if system == "windows":
            old_path = target_path.with_suffix(".old")
            target_path.rename(old_path)
            Path(tmp_path).rename(target_path)
        else:
            Path(tmp_path).rename(target_path)
    except OSError as e:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        rprint(f"[red]Failed to replace binary: {e}[/red]")
        raise typer.Exit(1)


def _verify_install(direction: str) -> None:
    """Run observal --version to confirm the install worked."""
    try:
        result = subprocess.run(["observal", "--version"], capture_output=True, text=True, timeout=10)
        new_version = result.stdout.strip().split()[-1] if result.returncode == 0 else "unknown"
        rprint(f"[green]{direction.capitalize()}d to v{new_version}[/green]")
    except (subprocess.TimeoutExpired, OSError, IndexError):
        rprint(f"[green]{direction.capitalize()} complete. Restart your shell to use the new version.[/green]")


def execute_silent(install_info: InstallInfo, target_version: str, direction: str) -> bool:
    """Non-interactive auto-update path. Returns True on success, False on failure.

    Unlike execute(), this never prints to stdout/stderr and never raises typer.Exit.
    Used by auto_update_if_needed() for background minor/patch updates.
    """
    try:
        if install_info.method == InstallMethod.UV_TOOL:
            result = subprocess.run(
                ["uv", "tool", "install", f"observal-cli=={target_version}", "--force"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            return result.returncode == 0
        elif install_info.method == InstallMethod.PIP:
            pip_cmd = [sys.executable, "-m", "pip", "install", f"observal-cli=={target_version}", "--quiet"]
            result = subprocess.run(pip_cmd, capture_output=True, text=True, timeout=30)
            return result.returncode == 0
        else:
            # Binary and other methods are too complex for silent update
            return False
    except (subprocess.TimeoutExpired, OSError):
        return False
