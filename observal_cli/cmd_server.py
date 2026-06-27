# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""CLI commands for managing the embedded Observal server.

Provides `observal server start|stop|status|logs|reset|install|config` commands
for running a fully self-contained Observal instance with embedded PostgreSQL,
ClickHouse, and Redis.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import typer
from loguru import logger as optic
from rich.console import Console
from rich.table import Table

try:
    from observal_cli.server.constants import (
        API_PORT,
        CONFIG_DIR,
        LOG_DIR,
        OBSERVAL_HOME,
    )
except ImportError:
    # server.constants may not exist yet (feature not merged)
    # Provide fallback values for the upgrade/rollback commands
    from pathlib import Path as _Path

    API_PORT = 8000
    OBSERVAL_HOME = _Path.home() / ".observal"
    CONFIG_DIR = OBSERVAL_HOME / "config"
    LOG_DIR = OBSERVAL_HOME / "logs"

server_app = typer.Typer(
    name="server",
    help="Manage the embedded Observal server (PostgreSQL + ClickHouse + Redis + API).",
    no_args_is_help=True,
)

console = Console()


def _require_super_admin() -> None:
    """Verify the current user has super_admin role. Exit if not."""
    from rich import print as rprint

    from observal_cli import client

    try:
        user = client.get("/api/v1/auth/whoami")
    except SystemExit as exc:
        rprint("[red]Authentication required.[/red]")
        rprint("[dim]  Run [bold]observal auth login[/bold] first.[/dim]")
        raise typer.Exit(1) from exc
    role = user.get("role", "")
    if role != "super_admin":
        rprint("[red]Permission denied.[/red] Server management requires super_admin role.")
        rprint(f"[dim]  Current role: {role}[/dim]")
        raise typer.Exit(1)


@server_app.command()
def start(
    port: int = typer.Option(API_PORT, "--port", "-p", help="API port"),
    host: str = typer.Option("0.0.0.0", "--host", help="Bind address"),
    background: bool = typer.Option(False, "--background", "-d", help="Run in background (daemonize)"),
) -> None:
    """Start all services and the Observal API server.

    On first run, downloads database binaries and initializes data directories.

    Example:
        observal server start
        observal server start --port 9000
        observal server start --background
    """
    import socket

    from observal_cli.server.deps import all_installed, install_dependencies
    from observal_cli.server.orchestrator import Orchestrator
    from observal_cli.server.updater import check_for_update

    # Check if port is available, try fallbacks if default
    def _port_available(p: int) -> bool:
        optic.trace("p={}", p)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", p))
                return True
            except OSError:
                return False

    if not _port_available(port):
        # Only try fallbacks if the user didn't explicitly specify a port
        if port == API_PORT:
            fallbacks = [port + 1, port + 2, port + 10, port + 100]
            for candidate in fallbacks:
                if _port_available(candidate):
                    console.print(f"[yellow]Port {port} in use,[/yellow] using :{candidate} instead")
                    port = candidate
                    break
            else:
                console.print(f"[red]Error:[/red] Port {port} and fallbacks are all in use.")
                console.print("  Use [cyan]--port[/cyan] to specify a different port, or stop the conflicting process.")
                raise typer.Exit(1)
        else:
            console.print(f"[red]Error:[/red] Port {port} is already in use.")
            console.print("  Use [cyan]--port[/cyan] to specify a different port, or stop the conflicting process.")
            raise typer.Exit(1)

    # Check for updates (non-blocking, cached)
    check_for_update(quiet=True)

    # Ensure dependencies are installed
    if not all_installed():
        console.print("[blue]==>[/blue] First run - installing database dependencies...")
        console.print()
        install_dependencies()
        console.print()

    # Start everything
    orch = Orchestrator(port=port, host=host)

    if orch.is_running():
        console.print("[yellow]Warning:[/yellow] Services are already running.")
        console.print("  Run [cyan]observal server stop[/cyan] first, or use [cyan]observal server restart[/cyan]")
        raise typer.Exit(1)

    orch.start_all(foreground=not background)

    if background:
        # Print update notice if available
        check_for_update(quiet=False)


@server_app.command()
def stop() -> None:
    """Stop all running services.

    Gracefully shuts down in reverse order: API → Redis → ClickHouse → PostgreSQL.

    Example:
        observal server stop
    """
    from observal_cli.server.orchestrator import Orchestrator

    orch = Orchestrator()
    orch.stop_all()


@server_app.command()
def restart(
    port: int = typer.Option(API_PORT, "--port", "-p", help="API port"),
    host: str = typer.Option("0.0.0.0", "--host", help="Bind address"),
) -> None:
    """Restart all services.

    Example:
        observal server restart
    """
    optic.trace("port={}, host={}", port, host)
    from observal_cli.server.orchestrator import Orchestrator

    orch = Orchestrator(port=port, host=host)
    if orch.is_running():
        orch.stop_all()
    orch.start_all(foreground=True)


@server_app.command()
def status() -> None:
    """Show status of all services.

    Example:
        observal server status
    """
    from observal_cli.server.orchestrator import Orchestrator

    orch = Orchestrator()
    statuses = orch.status()

    table = Table(title="Observal Service Status")
    table.add_column("Service", style="bold")
    table.add_column("Status")
    table.add_column("Port")

    status_styles = {
        "running": "[green]running[/green]",
        "stopped": "[red]stopped[/red]",
        "not initialized": "[dim]not initialized[/dim]",
    }

    try:
        from observal_cli.server.constants import (
            CLICKHOUSE_HTTP_PORT,
            POSTGRES_PORT,
            REDIS_PORT,
        )
    except ImportError:
        POSTGRES_PORT, CLICKHOUSE_HTTP_PORT, REDIS_PORT = 5480, 8124, 6380  # noqa: N806

    port_map = {
        "postgres": str(POSTGRES_PORT),
        "clickhouse": str(CLICKHOUSE_HTTP_PORT),
        "redis": str(REDIS_PORT),
        "api": str(API_PORT),
    }

    for service, state in statuses.items():
        table.add_row(
            service.capitalize(),
            status_styles.get(state, state),
            port_map.get(service, "-"),
        )

    console.print(table)


@server_app.command()
def logs(
    service: str = typer.Argument(
        None,
        help="Service to show logs for (postgres, clickhouse, redis, api). Default: all.",
    ),
    follow: bool = typer.Option(False, "--follow", "-f", help="Follow log output"),
    lines: int = typer.Option(50, "--lines", "-n", help="Number of lines to show"),
) -> None:
    """Show service logs.

    Example:
        observal server logs
        observal server logs postgres
        observal server logs -f
        observal server logs api -n 100
    """
    optic.trace("service={}, follow={}", service, follow)
    log_files = {
        "postgres": LOG_DIR / "postgres.log",
        "clickhouse": LOG_DIR / "clickhouse-startup.log",
        "redis": LOG_DIR / "redis.log",
        "api": LOG_DIR / "api.log",
    }

    if service:
        if service not in log_files:
            console.print(f"[red]Error:[/red] Unknown service '{service}'. Choose from: {', '.join(log_files.keys())}")
            raise typer.Exit(1)
        files = [log_files[service]]
    else:
        files = [f for f in log_files.values() if f.exists()]

    if not files:
        console.print("[yellow]No log files found.[/yellow] Has the server been started?")
        raise typer.Exit(1)

    if follow:
        # Use tail -f for following
        cmd = ["tail", "-f"] + [str(f) for f in files if f.exists()]
        try:
            subprocess.run(cmd)
        except KeyboardInterrupt:
            pass
    else:
        for log_file in files:
            if log_file.exists():
                content = log_file.read_text()
                log_lines = content.splitlines()
                tail = log_lines[-lines:] if len(log_lines) > lines else log_lines
                if len(files) > 1:
                    console.print(f"\n[bold]==> {log_file.stem} <==[/bold]")
                for line in tail:
                    console.print(line)


@server_app.command()
def install(
    upgrade: bool = typer.Option(False, "--upgrade", help="Re-download even if already installed"),
) -> None:
    """Download database dependency binaries (PostgreSQL, ClickHouse, Redis).

    Automatically runs on first `server start`, but can be invoked manually
    to pre-download or upgrade dependencies.

    Example:
        observal server install
        observal server install --upgrade
    """
    optic.trace("upgrade={}", upgrade)
    from observal_cli.server.deps import install_dependencies

    install_dependencies(force=upgrade)
    console.print()
    console.print("[green]\u2713[/green] All dependencies installed")
    console.print("  Run [cyan]observal server start[/cyan] to start the server")


@server_app.command()
def reset(
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation prompt"),
) -> None:
    """Stop all services and wipe all data. Requires re-initialization on next start.

    Example:
        observal server reset
        observal server reset --force
    """
    optic.trace("force={}", force)
    from observal_cli.server.orchestrator import Orchestrator

    if not force:
        confirm = typer.confirm("This will delete all Observal data (databases, config, keys). Continue?")
        if not confirm:
            raise typer.Abort()

    orch = Orchestrator()
    orch.reset()


@server_app.command()
def config() -> None:
    """Show current server configuration.

    Example:
        observal server config
    """
    config_file = OBSERVAL_HOME / "observal.yaml"

    table = Table(title="Observal Server Configuration")
    table.add_column("Setting", style="bold")
    table.add_column("Value")

    try:
        from observal_cli.server.constants import (
            CLICKHOUSE_HTTP_PORT,
            POSTGRES_PORT,
            REDIS_PORT,
        )
    except ImportError:
        POSTGRES_PORT, CLICKHOUSE_HTTP_PORT, REDIS_PORT = 5480, 8124, 6380  # noqa: N806

    table.add_row("Home directory", str(OBSERVAL_HOME))
    table.add_row("API port", str(API_PORT))
    table.add_row("PostgreSQL port", str(POSTGRES_PORT))
    table.add_row("ClickHouse port", str(CLICKHOUSE_HTTP_PORT))
    table.add_row("Redis port", str(REDIS_PORT))
    table.add_row("Config dir", str(CONFIG_DIR))
    table.add_row("Log dir", str(LOG_DIR))

    if config_file.exists():
        table.add_row("Config file", str(config_file))
    else:
        table.add_row("Config file", "[dim]not created (using defaults)[/dim]")

    console.print(table)


# ═══════════════════════════════════════════════════════════
# Server upgrade/rollback commands (Docker mode)
# ═══════════════════════════════════════════════════════════


def _find_compose_dir() -> Path:
    """Find the Docker Compose directory for the Observal deployment."""
    # Check common locations
    candidates = [
        Path.cwd() / "docker",  # dev: project root with docker/ subdir
        Path.cwd(),  # production: cwd IS the compose dir
        Path("/opt/observal"),  # server-package default install
        OBSERVAL_HOME / "docker",
    ]
    for d in candidates:
        if (d / "docker-compose.yml").exists() or (d / "compose.yml").exists():
            return d
    return Path("/opt/observal")  # Default


def _get_current_server_version(compose_dir: Path) -> str:
    """Get current OBSERVAL_VERSION from .env file."""
    # Check .env in compose dir first, then parent (dev setup has .env at project root)
    optic.trace("compose_dir={}", compose_dir)
    candidates = [
        compose_dir / ".env",
        compose_dir.parent / ".env",
    ]
    for env_file in candidates:
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                if line.startswith("OBSERVAL_VERSION="):
                    return line.split("=", 1)[1].strip().strip('"')
    return "unknown"


def _find_env_file(compose_dir: Path) -> Path:
    """Find the .env file (may be in compose dir or parent)."""
    optic.trace("compose_dir={}", compose_dir)
    if (compose_dir / ".env").exists():
        return compose_dir / ".env"
    if (compose_dir.parent / ".env").exists():
        return compose_dir.parent / ".env"
    return compose_dir / ".env"  # Default (will be created)


def _get_health_url(compose_dir: Path) -> str:
    """Get the health check URL from .env or defaults.

    Reads LB_HOST_PORT (preferred) or API_HOST_PORT from .env to determine
    the correct port. Falls back to 8000 (standard API port) if neither is set.
    """
    optic.trace("compose_dir={}", compose_dir)
    env_file = _find_env_file(compose_dir)
    lb_port = None
    api_port = None
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line.startswith("LB_HOST_PORT="):
                lb_port = line.split("=", 1)[1].strip().strip('"') or None
            elif line.startswith("API_HOST_PORT="):
                api_port = line.split("=", 1)[1].strip().strip('"') or None
    port = lb_port or api_port or "8000"
    return f"http://localhost:{port}/readyz"


def _update_env_version(compose_dir: Path, version: str) -> None:
    """Update OBSERVAL_VERSION in .env file."""
    optic.trace("compose_dir={}, version={}", compose_dir, version)
    env_file = _find_env_file(compose_dir)
    if not env_file.exists():
        env_file.write_text(f"OBSERVAL_VERSION={version}\n")
        return

    lines = env_file.read_text().splitlines()
    found = False
    for i, line in enumerate(lines):
        if line.startswith("OBSERVAL_VERSION="):
            lines[i] = f"OBSERVAL_VERSION={version}"
            found = True
            break
    if not found:
        lines.append(f"OBSERVAL_VERSION={version}")
    env_file.write_text("\n".join(lines) + "\n")


@server_app.command(name="upgrade")
def server_upgrade(
    version: str | None = typer.Option(
        None, "--version", "-v", help="Target version (e.g. 0.9.0). Defaults to latest."
    ),
    skip_backup: bool = typer.Option(False, "--skip-backup", help="Skip pre-upgrade database backup"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show upgrade plan without applying changes"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip interactive confirmation prompt"),
) -> None:
    """Upgrade the Observal server to the latest or a specified version.

    Pulls new Docker images from GHCR, creates a database backup (unless
    skipped), and recreates containers. Runs a health check after upgrade
    and automatically rolls back if the server fails to start.

    Requires super_admin role.

    Examples:
        observal server upgrade
        observal server upgrade --version 0.9.0
        observal server upgrade --dry-run
        observal server upgrade --skip-backup --force
    """
    optic.trace("version={}, skip_backup={}", version, skip_backup)
    _require_super_admin()
    from observal_cli import version_check
    from observal_cli.upgrade_lock import UpgradeLockError, acquire_lock, release_lock

    compose_dir = _find_compose_dir()
    current = _get_current_server_version(compose_dir)

    # Resolve target version
    if version:
        target = version
    else:
        with console.status("Checking for latest version..."):
            rel = version_check._fetch_from_github()
        if not rel:
            console.print("[red]Failed to fetch latest release from GitHub.[/red]")
            raise typer.Exit(1)
        target = rel["latest_version"]

    if target == current:
        console.print(f"[green]Already on v{current}.[/green]")
        raise typer.Exit(0)

    # Verify image exists on GHCR before any state changes
    with console.status("Verifying image on GHCR..."):
        if not version_check.verify_server_image_exists(target):
            console.print(f"[red]Image not found on GHCR: ghcr.io/observal/observal-api:{target}[/red]")
            console.print("[dim]Check available versions with: observal server versions[/dim]")
            raise typer.Exit(1)

    if dry_run:
        console.print(f"[dim]Dry run: would upgrade v{current} → v{target}[/dim]")
        console.print(f"[dim]  Pull: ghcr.io/observal/observal-api:{target}[/dim]")
        console.print(f"[dim]  Pull: ghcr.io/observal/observal-web:{target}[/dim]")
        console.print(f"[dim]  Compose dir: {compose_dir}[/dim]")
        raise typer.Exit(0)

    if not force:
        console.print(f"  Current: [dim]v{current}[/dim]")
        console.print(f"  Target:  [green]v{target}[/green]")
        console.print(f"  Images:  [dim]ghcr.io/observal/observal-{{api,web}}:{target}[/dim]")
        if not typer.confirm("\nProceed with server upgrade?"):
            raise typer.Abort()

    try:
        lock = acquire_lock("server")
    except UpgradeLockError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    backup_path = None
    try:
        # Backup
        if not skip_backup:
            from observal_cli.server.backup import create_backup

            console.print("[blue]==>[/blue] Creating backup...")
            backup_path = create_backup(compose_dir, current)
            console.print(f"  Backup: {backup_path}")

        # Pull new images
        console.print(f"[blue]==>[/blue] Pulling images for v{target}...")
        import os

        env = {**os.environ, "OBSERVAL_VERSION": target}
        result = subprocess.run(
            ["docker", "compose", "pull"],
            cwd=compose_dir,
            env=env,
            capture_output=True,
            text=True,
            timeout=600,
        )
        if result.returncode != 0:
            console.print(f"[red]Pull failed:[/red] {result.stderr[:200]}")
            raise typer.Exit(1)

        # Update .env
        _update_env_version(compose_dir, target)

        # Recreate containers
        console.print("[blue]==>[/blue] Recreating containers...")
        result = subprocess.run(
            ["docker", "compose", "up", "-d"],
            cwd=compose_dir,
            capture_output=True,
            text=True,
            timeout=300,
        )
        if result.returncode != 0:
            console.print(f"[red]Container recreation failed:[/red] {result.stderr[:200]}")
            # Rollback .env
            _update_env_version(compose_dir, current)
            raise typer.Exit(1)

        # Health check
        console.print("[blue]==>[/blue] Health check...")
        import time

        import httpx

        healthy = False
        for _ in range(24):  # 120s total
            time.sleep(5)
            try:
                resp = httpx.get(_get_health_url(compose_dir), timeout=5)
                if resp.status_code == 200:
                    healthy = True
                    break
            except Exception:
                continue

        if not healthy:
            console.print("[red]Health check failed! Rolling back...[/red]")
            _update_env_version(compose_dir, current)
            subprocess.run(["docker", "compose", "up", "-d"], cwd=compose_dir, capture_output=True)
            raise typer.Exit(1)

        console.print(f"[green]✓ Upgraded to v{target}[/green]")
        if backup_path:
            console.print(f"  Backup: {backup_path}")
        console.print("  Rollback: [dim]observal server rollback[/dim]")

    finally:
        release_lock(lock)


@server_app.command(name="rollback")
def server_rollback(
    from_backup: str | None = typer.Option(
        None, "--from-backup", help="Path to a specific backup directory to restore from"
    ),
    force: bool = typer.Option(False, "--force", "-f", help="Skip interactive confirmation prompt"),
) -> None:
    """Rollback the server to a previous version from backup.

    Restores the database from the most recent backup (or a specified one),
    reverts the Docker images, and recreates containers. Runs a health check
    after rollback.

    Requires super_admin role.

    Examples:
        observal server rollback
        observal server rollback --from-backup ~/.observal/backups/v0.7.0-20260521T120000
        observal server rollback --force
    """
    optic.trace("from_backup={}, force={}", from_backup, force)
    _require_super_admin()
    from observal_cli.server.backup import list_backups, restore_backup
    from observal_cli.upgrade_lock import UpgradeLockError, acquire_lock, release_lock

    compose_dir = _find_compose_dir()
    current = _get_current_server_version(compose_dir)

    backups = list_backups()
    if not backups and not from_backup:
        console.print("[red]No backups found. Cannot rollback.[/red]")
        raise typer.Exit(1)

    backup_dir = Path(from_backup) if from_backup else Path(backups[0]["path"])

    if not backup_dir.exists():
        console.print(f"[red]Backup not found: {backup_dir}[/red]")
        raise typer.Exit(1)

    # Extract version from backup dir name (e.g., v0.7.0-20260521T120000)
    prev_version = backup_dir.name.split("-")[0].lstrip("v")

    if not force:
        console.print(f"  Current: [dim]v{current}[/dim]")
        console.print(f"  Rollback to: [yellow]v{prev_version}[/yellow]")
        console.print(f"  Backup: [dim]{backup_dir}[/dim]")
        if not typer.confirm("\nProceed with rollback?"):
            raise typer.Abort()

    try:
        lock = acquire_lock("server")
    except UpgradeLockError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    try:
        # Restore database
        console.print("[blue]==>[/blue] Restoring database...")
        restore_backup(backup_dir, compose_dir)

        # Revert version
        _update_env_version(compose_dir, prev_version)

        # Recreate containers with previous images
        console.print("[blue]==>[/blue] Recreating containers...")
        subprocess.run(
            ["docker", "compose", "up", "-d"],
            cwd=compose_dir,
            capture_output=True,
            timeout=300,
        )

        # Health check
        import time

        import httpx

        console.print("[blue]==>[/blue] Health check...")
        healthy = False
        for _ in range(24):
            time.sleep(5)
            try:
                resp = httpx.get(_get_health_url(compose_dir), timeout=5)
                if resp.status_code == 200:
                    healthy = True
                    break
            except Exception:
                continue

        if healthy:
            console.print(f"[green]✓ Rolled back to v{prev_version}[/green]")
        else:
            console.print("[yellow]⚠ Rollback complete but health check didn't pass.[/yellow]")
            console.print("  Check logs: [dim]docker compose logs -f[/dim]")

    finally:
        release_lock(lock)


@server_app.command(name="versions")
def server_versions() -> None:
    """List available server versions from GHCR and local backup status.

    Shows the current running version, available versions on the container
    registry, and which versions have local database backups.

    Requires super_admin role.

    Examples:
        observal server versions
    """
    _require_super_admin()
    from observal_cli import version_check
    from observal_cli.server.backup import list_backups

    compose_dir = _find_compose_dir()
    current = _get_current_server_version(compose_dir)

    # Fetch available from GHCR
    with console.status("Fetching available versions from GHCR..."):
        available = version_check.fetch_available_server_images()

    backups = list_backups()
    backup_versions = {b["name"].split("-")[0].lstrip("v"): b for b in backups}

    table = Table(title="Server Versions")
    table.add_column("Version", style="bold")
    table.add_column("Status")
    table.add_column("GHCR")
    table.add_column("Backup")

    # Show current + available
    shown = set()
    if current != "unknown":
        backup_info = backup_versions.get(current, {})
        table.add_row(
            current,
            "[green]← current[/green]",
            "✓" if current in available else "-",
            f"{backup_info.get('size_mb', 0)} MB" if backup_info else "-",
        )
        shown.add(current)

    for ver in available[:10]:
        if ver in shown:
            continue
        backup_info = backup_versions.get(ver, {})
        table.add_row(
            ver,
            "",
            "✓",
            f"{backup_info.get('size_mb', 0)} MB" if backup_info else "-",
        )
        shown.add(ver)

    console.print(table)
    console.print(f"\n  Current: v{current} | Images: ghcr.io/observal/observal-{{api,web}}")
