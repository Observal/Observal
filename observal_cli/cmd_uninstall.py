"""Observal uninstall command — tears down Docker stack, removes repo and config."""

from __future__ import annotations

import os
import shutil
import subprocess
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

        # ── Phase 2: Delete repo directory ────────────────
        if not keep_repo:
            # Move to parent of repo dir before deleting it
            os.chdir(repo_root.parent)
            _delete_directory(repo_root, "Observal repo")

        # ── Phase 3: Delete config directory ──────────────
        if not keep_config:
            _delete_directory(CONFIG_DIR, "config directory (~/.observal)")

        # ── Phase 4: Uninstall CLI ────────────────────────
        if not keep_cli:
            _uninstall_cli()

        rprint("\n[green]Observal has been uninstalled. Goodbye![/green]")
        if not keep_repo:
            rprint(f"\n[dim]Run [bold]cd {repo_root.parent}[/bold] to leave the deleted directory.[/dim]")
