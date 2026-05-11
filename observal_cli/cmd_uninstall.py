# SPDX-FileCopyrightText: 2026 Vishnu Muthiah <vishnu.muthiah04@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Observal uninstall command — tears down Docker stack, removes repo and config."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import typer
from rich import print as rprint

from observal_cli.config import CONFIG_DIR
from observal_cli.render import spinner

CONFIRMATION_PHRASE = "confirm"


def _find_repo_root(explicit_dir: str | None) -> Path | None:
    """Locate the Observal repo root by looking for docker/docker-compose.yml."""
    if explicit_dir:
        candidate = Path(explicit_dir).resolve()
        if (candidate / "docker" / "docker-compose.yml").exists():
            return candidate
        rprint(f"[red]No docker/docker-compose.yml found in {candidate}[/red]")
        return None

    # Check CWD and walk up parent directories
    current = Path.cwd().resolve()
    for directory in [current, *current.parents]:
        if (directory / "docker" / "docker-compose.yml").exists():
            return directory

    rprint("[yellow]Could not detect Observal repo directory.[/yellow]")
    rprint("[bold bright_magenta]Run from inside the repo or pass --repo-dir.[/bold bright_magenta]")
    return None


def _docker_teardown(repo_root: Path) -> bool:
    """Run docker compose down -v --rmi all to stop containers, remove volumes and images."""
    docker_dir = repo_root / "docker"
    try:
        with spinner("Stopping containers, removing volumes and images..."):
            result = subprocess.run(
                ["docker", "compose", "down", "-v", "--rmi", "all"],
                cwd=docker_dir,
                capture_output=True,
                text=True,
                timeout=120,
            )
        if result.returncode == 0:
            rprint("[green]\u2713 Docker containers, volumes, and images removed.[/green]")
            return True
        else:
            rprint(f"[red]Docker teardown failed:[/red] {result.stderr.strip()}")
            return False
    except FileNotFoundError:
        rprint("[yellow]docker not found. Skipping container teardown.[/yellow]")
        return False
    except subprocess.TimeoutExpired:
        rprint("[red]Docker teardown timed out.[/red]")
        return False


def _delete_directory(path: Path, label: str) -> bool:
    """Remove a directory tree, handling errors gracefully."""
    if not path.exists():
        rprint(f"[dim]{label} not found at {path}, skipping.[/dim]")
        return True
    try:
        shutil.rmtree(path)
        rprint(f"[green]\u2713 Deleted {label}: {path}[/green]")
        return True
    except PermissionError:
        rprint(f"[red]Permission denied deleting {label}: {path}[/red]")
        return False
    except OSError as exc:
        rprint(f"[red]Failed to delete {label}: {exc}[/red]")
        return False


def _create_windows_cleanup_script(
    repo_root: Path | None,
    config_dir: Path | None,
    uninstall_cli: bool,
    uv_path: str | None,
) -> Path:
    """Create a PowerShell cleanup script for Windows post-exit cleanup."""
    script_lines = [
        "# Observal post-exit cleanup script (auto-generated)",
        "Start-Sleep -Seconds 3",
        "",
    ]

    if repo_root:
        script_lines.extend(
            [
                "# Delete repo directory (retry to handle terminal CWD / OneDrive locks)",
                "$repoPath = @'",
                str(repo_root),
                "'@",
                "for ($i = 0; $i -lt 5; $i++) {",
                "    if (Test-Path $repoPath) {",
                "        try {",
                "            Remove-Item -Path $repoPath -Recurse -Force -ErrorAction Stop",
                "            Write-Host 'Deleted repo directory.'",
                "            break",
                "        } catch {",
                "            Start-Sleep -Seconds 3",
                "        }",
                "    } else { break }",
                "}",
                "",
            ]
        )

    if config_dir:
        script_lines.extend(
            [
                "# Delete config directory",
                "$configPath = @'",
                str(config_dir),
                "'@",
                "for ($i = 0; $i -lt 3; $i++) {",
                "    if (Test-Path $configPath) {",
                "        try {",
                "            Remove-Item -Path $configPath -Recurse -Force -ErrorAction Stop",
                "            Write-Host 'Deleted config directory.'",
                "            break",
                "        } catch {",
                "            Start-Sleep -Seconds 2",
                "        }",
                "    } else { break }",
                "}",
                "",
            ]
        )

    if uninstall_cli and uv_path:
        script_lines.extend(
            [
                "# Uninstall CLI tool",
                "$uvPath = @'",
                uv_path,
                "'@",
                "try {",
                "    & $uvPath tool uninstall observal-cli 2>&1 | Out-Null",
                "    Write-Host 'CLI tool uninstalled.'",
                "} catch {",
                "    Write-Host 'Failed to uninstall CLI tool.'",
                "}",
                "",
            ]
        )

    script_lines.extend(
        [
            "# Self-delete",
            "Start-Sleep -Seconds 1",
            "Remove-Item -Path $PSCommandPath -Force -ErrorAction SilentlyContinue",
        ]
    )

    fd, script_path = tempfile.mkstemp(suffix=".ps1", prefix="observal_cleanup_")
    os.close(fd)
    Path(script_path).write_text("\n".join(script_lines), encoding="utf-8")
    return Path(script_path)


def _spawn_windows_cleanup(script_path: Path) -> bool:
    """Spawn a detached PowerShell process to run the cleanup script."""
    try:
        detached_process = 0x00000008
        create_new_process_group = 0x00000200
        create_no_window = 0x08000000

        subprocess.Popen(
            [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-WindowStyle",
                "Hidden",
                "-File",
                str(script_path),
            ],
            creationflags=detached_process | create_new_process_group | create_no_window,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
        )
        return True
    except FileNotFoundError:
        rprint("[red]PowerShell not found. Cannot run cleanup script.[/red]")
        rprint(f"[yellow]Run manually:[/yellow] [dim]powershell -ExecutionPolicy Bypass -File {script_path}[/dim]")
        return False
    except OSError as exc:
        rprint(f"[red]Failed to spawn cleanup process:[/red] {exc}")
        return False


def _uninstall_cli() -> bool:
    """Uninstall the CLI tool via uv."""
    try:
        with spinner("Uninstalling CLI tool..."):
            result = subprocess.run(
                ["uv", "tool", "uninstall", "observal-cli"],
                capture_output=True,
                text=True,
                timeout=60,
            )
        if result.returncode == 0:
            rprint("[green]\u2713 CLI tool uninstalled.[/green]")
            return True
        else:
            rprint(f"[red]CLI uninstall failed:[/red] {result.stderr.strip()}")
            return False
    except FileNotFoundError:
        rprint("[yellow]uv not found. Remove the CLI manually.[/yellow]")
        return False


def register_uninstall(app: typer.Typer):
    """Register the root-level `observal uninstall` command."""

    @app.command("uninstall")
    def uninstall(
        repo_dir: str | None = typer.Option(None, "--repo-dir", "-d", help="Path to cloned Observal repo."),
        keep_config: bool = typer.Option(False, "--keep-config", help="Keep ~/.observal/ config directory."),
        keep_cli: bool = typer.Option(False, "--keep-cli", help="Keep the CLI tool installed."),
        keep_repo: bool = typer.Option(False, "--keep-repo", help="Keep the repo directory (still tears down Docker)."),
    ):
        """Completely uninstall Observal: stop containers, remove volumes, delete repo and config."""
        repo_root = _find_repo_root(repo_dir)

        # Require repo detection - Docker teardown is mandatory
        if repo_root is None:
            rprint("[red]ERROR: Repo not found. Could not initiate Docker teardown: required for uninstall.[/red]")
            raise typer.Exit(1)

        # ── Show what will be removed ──────────────────────
        rprint("\n[bold red]Observal Uninstall[/bold red]\n")
        rprint("[bold]The following will be removed:[/bold]")
        rprint("  - Docker containers and volumes (via docker compose down -v)")
        if not keep_repo:
            rprint(f"  - Repo directory: [bold]{repo_root}[/bold]")
        if not keep_config:
            rprint(f"  - Config directory: [bold]{CONFIG_DIR}[/bold]")
        if not keep_cli:
            rprint("  - CLI tool: observal-cli (via uv)")
        rprint()

        # ── Confirmation ───────────────────────────────────
        rprint("[bold red]WARNING: This action is irreversible.[/bold red]")
        rprint(f'Type [bold]"{CONFIRMATION_PHRASE}"[/bold] to confirm:\n')
        user_input = typer.prompt("Confirm")
        if user_input.strip().lower() != CONFIRMATION_PHRASE:
            rprint("[yellow]Confirmation did not match. Aborting.[/yellow]")
            raise typer.Exit(1)

        rprint()

        # ── Phase 1: Docker teardown ──────────────────────
        _docker_teardown(repo_root)

        # ── Phase 2-4: Cleanup (platform-aware) ────────────
        if sys.platform == "win32":
            # Windows: defer repo/config deletion and CLI uninstall to a
            # detached PowerShell process so file-locks are released first.
            rprint("[bold yellow]Windows detected — using deferred cleanup.[/bold yellow]")
            rprint("[dim]Cleanup will complete after this process exits.[/dim]\n")

            cleanup_repo = repo_root if not keep_repo else None
            cleanup_config = CONFIG_DIR if not keep_config else None
            cleanup_cli = not keep_cli

            # Release *our* CWD lock on the repo dir immediately.
            if cleanup_repo:
                os.chdir(repo_root.parent)

            # Resolve uv to an absolute path for the detached process.
            uv_path: str | None = None
            if cleanup_cli:
                uv_path = shutil.which("uv")
                if not uv_path:
                    rprint("[yellow]uv not found in PATH — CLI uninstall will be skipped.[/yellow]")
                    rprint("[dim]You can manually run: uv tool uninstall observal-cli[/dim]")
                    cleanup_cli = False

            if cleanup_repo or cleanup_config or cleanup_cli:
                try:
                    script_path = _create_windows_cleanup_script(
                        cleanup_repo,
                        cleanup_config,
                        cleanup_cli,
                        uv_path,
                    )
                    if _spawn_windows_cleanup(script_path):
                        if cleanup_repo:
                            rprint("[yellow]⏳ Repo directory deletion scheduled.[/yellow]")
                        if cleanup_config:
                            rprint("[yellow]⏳ Config directory deletion scheduled.[/yellow]")
                        if cleanup_cli:
                            rprint("[yellow]⏳ CLI uninstall scheduled.[/yellow]")
                    else:
                        rprint(f"\n[yellow]Cleanup script created but could not be started:[/yellow] {script_path}")
                        rprint(f"[dim]Run manually: powershell -ExecutionPolicy Bypass -File {script_path}[/dim]")
                except Exception as exc:
                    rprint(f"[red]Failed to create cleanup script:[/red] {exc}")
                    rprint("[yellow]Manual cleanup required:[/yellow]")
                    if cleanup_repo:
                        rprint(f"  - Delete repo: [dim]{repo_root}[/dim]")
                    if cleanup_config:
                        rprint(f"  - Delete config: [dim]{CONFIG_DIR}[/dim]")
                    if cleanup_cli:
                        rprint("  - Run: [dim]uv tool uninstall observal-cli[/dim]")
        else:
            # Unix / macOS: synchronous cleanup.
            if not keep_repo:
                os.chdir(repo_root.parent)
                _delete_directory(repo_root, "Observal repo")

            if not keep_config:
                _delete_directory(CONFIG_DIR, "config directory (~/.observal)")

            if not keep_cli:
                _uninstall_cli()

        rprint("\n[green]Observal has been uninstalled. Goodbye.[/green]")

        if sys.platform == "win32":
            rprint("\n[cyan]Cleanup operations will complete in the background.[/cyan]")
            rprint("[dim]Close this terminal window to release any remaining directory locks.[/dim]")
        elif not keep_repo:
            rprint(
                f"\n[cyan]Run [bold]cd {repo_root.parent}[/bold] or [bold]cd ..[/bold] to leave the deleted directory.[/cyan]"
            )
