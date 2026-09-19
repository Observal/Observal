# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-FileCopyrightText: 2026 Srihari <sriharilegend23@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Database backup and restore for Observal server upgrades.

Supports:
  - PostgreSQL: pg_dump (custom format) via Docker exec
  - DuckDB analytics: checkpoint + volume archive via Docker exec
  - Backup retention pruning
"""

from __future__ import annotations

import shutil
import subprocess
import tarfile
import time
from datetime import UTC, datetime
from pathlib import Path

from rich import print as rprint

from observal_cli.config import CONFIG_DIR

BACKUPS_DIR = CONFIG_DIR / "backups"
DEFAULT_RETENTION = 3  # Keep last N backups


def _restart_analytics_or_raise(compose_dir: Path) -> None:
    """Start DuckDB after a backup attempt and require confirmed health."""
    restart_error = ""
    try:
        restarted = subprocess.run(
            ["docker", "compose", "up", "-d", "observal-duckdb"],
            capture_output=True,
            cwd=compose_dir,
            timeout=300,
        )
        if restarted.returncode != 0:
            restart_error = restarted.stderr.decode(errors="replace")[:200]
    except subprocess.TimeoutExpired:
        restart_error = "restart command timed out"
    except OSError as exc:
        restart_error = str(exc)

    # A timed-out/non-zero compose command may still have started the service.
    # Confirm its actual state before deciding whether the upgrade can proceed.
    if _wait_for_service_healthy(compose_dir, "observal-duckdb", timeout=60):
        return
    detail = f": {restart_error}" if restart_error else ""
    raise RuntimeError(f"DuckDB analytics did not recover after the backup attempt{detail}")


def create_backup(compose_dir: Path, from_version: str, *, include_analytics: bool = True) -> Path:
    """Create a pre-upgrade backup of PostgreSQL + the DuckDB analytics store.

    Args:
        compose_dir: Directory containing docker-compose.yml.
        from_version: Current server version (used in backup dir name).
        include_analytics: Archive the DuckDB volume. Pass ``False`` for a
            legacy ClickHouse deployment that has no ``observal-duckdb``
            service yet; ClickHouse itself is never modified by the cutover.

    Returns:
        Path to the backup directory.

    Raises:
        RuntimeError: If backup creation fails.
    """
    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    backup_dir = BACKUPS_DIR / f"v{from_version}-{ts}"
    backup_dir.mkdir(parents=True, exist_ok=False, mode=0o700)
    backup_dir.chmod(0o700)

    # PostgreSQL backup (custom format for selective restore)
    pg_dump_path = backup_dir / "pg.dump"
    rprint("[dim]  Backing up PostgreSQL...[/dim]")
    result = subprocess.run(
        [
            "docker",
            "compose",
            "exec",
            "-T",
            "observal-db",
            "pg_dump",
            "-U",
            "postgres",
            "-Fc",
            "observal",
        ],
        capture_output=True,
        cwd=compose_dir,
        timeout=300,
    )
    if result.returncode != 0:
        shutil.rmtree(backup_dir, ignore_errors=True)
        raise RuntimeError(f"pg_dump failed: {result.stderr.decode()[:200]}")

    pg_dump_path.write_bytes(result.stdout)
    pg_dump_path.chmod(0o600)
    if pg_dump_path.stat().st_size < 100:
        shutil.rmtree(backup_dir, ignore_errors=True)
        raise RuntimeError("pg_dump produced empty/tiny file - backup may be invalid")

    pg_size_mb = pg_dump_path.stat().st_size / (1024 * 1024)
    rprint(f"[dim]  PostgreSQL: {pg_size_mb:.1f} MB[/dim]")

    if not include_analytics:
        rprint("[dim]  Analytics: skipped (legacy ClickHouse volume is left untouched)[/dim]")
        return backup_dir

    # DuckDB analytics: flush the WAL, then archive the data directory.
    duckdb_archive = backup_dir / "analytics.tar.gz"
    rprint("[dim]  Backing up DuckDB analytics...[/dim]")
    # The checkpoint is best-effort. A timeout must not prevent the archive,
    # which is the only recoverable copy of the analytics volume.
    try:
        checkpoint = subprocess.run(
            [
                "docker",
                "compose",
                "exec",
                "-T",
                "observal-duckdb",
                "/app/.venv/bin/python",
                "-c",
                (
                    "import os, urllib.request;"
                    "token = os.environ.get('DUCKDB_ANALYTICS_TOKEN') or '';"
                    "path = os.environ.get('DUCKDB_ANALYTICS_TOKEN_FILE');"
                    "token = token or (open(path).read().strip() if path and os.path.exists(path) else '');"
                    "req=urllib.request.Request('http://127.0.0.1:8484/admin/checkpoint', method='POST');"
                    "req.add_header('Authorization', 'Bearer ' + token);"
                    "urllib.request.urlopen(req, timeout=30).read()"
                ),
            ],
            capture_output=True,
            cwd=compose_dir,
            timeout=120,
        )
        if checkpoint.returncode != 0:
            rprint("[yellow]  DuckDB checkpoint failed (non-critical)[/yellow]")
    except (subprocess.TimeoutExpired, OSError):
        rprint("[yellow]  DuckDB checkpoint timed out (non-critical)[/yellow]")

    # A failed or timed-out stop may still have stopped the container. Always
    # attempt to bring it back once a stop was requested, including early-return
    # paths where the analytics archive is skipped.
    try:
        try:
            stopped = subprocess.run(
                ["docker", "compose", "stop", "observal-duckdb"],
                capture_output=True,
                cwd=compose_dir,
                timeout=300,
            )
        except (subprocess.TimeoutExpired, OSError):
            rprint("[yellow]  DuckDB stop timed out; analytics backup skipped[/yellow]")
            return backup_dir
        if stopped.returncode != 0:
            rprint("[yellow]  DuckDB could not be stopped; analytics backup skipped[/yellow]")
            return backup_dir

        try:
            with duckdb_archive.open("wb") as output:
                archive = subprocess.run(
                    [
                        "docker",
                        "compose",
                        "run",
                        "--rm",
                        "--no-deps",
                        "-T",
                        "observal-duckdb",
                        "tar",
                        "czf",
                        "-",
                        "--exclude=./staging",
                        "-C",
                        "/data",
                        ".",
                    ],
                    stdout=output,
                    stderr=subprocess.PIPE,
                    cwd=compose_dir,
                    timeout=600,
                )
            if archive.returncode == 0 and duckdb_archive.stat().st_size:
                duckdb_archive.chmod(0o600)
                size_mb = duckdb_archive.stat().st_size / (1024 * 1024)
                rprint(f"[dim]  DuckDB analytics: {size_mb:.1f} MB[/dim]")
            else:
                duckdb_archive.unlink(missing_ok=True)
                rprint("[yellow]  DuckDB archive failed (non-critical)[/yellow]")
        except (subprocess.TimeoutExpired, OSError):
            duckdb_archive.unlink(missing_ok=True)
            rprint("[yellow]  DuckDB archive timed out (non-critical)[/yellow]")
    finally:
        _restart_analytics_or_raise(compose_dir)

    return backup_dir


def restore_backup(backup_path: Path, compose_dir: Path) -> bool:
    """Restore PostgreSQL and the DuckDB analytics store from a backup.

    Args:
        backup_path: Path to backup directory containing pg.dump (and, for
            backups taken since the DuckDB cutover, analytics.tar.gz).
        compose_dir: Directory containing docker-compose.yml.

    Returns:
        True when the DuckDB analytics store was restored, False when the
        backup predates it and only PostgreSQL came back.
    """
    pg_dump = backup_path / "pg.dump"
    if not pg_dump.exists():
        raise RuntimeError(f"Backup file not found: {pg_dump}")

    rprint("[dim]  Restoring PostgreSQL...[/dim]")

    # Pipe pg.dump content into pg_restore via docker exec
    with pg_dump.open("rb") as f:
        result = subprocess.run(
            [
                "docker",
                "compose",
                "exec",
                "-T",
                "observal-db",
                "pg_restore",
                "-U",
                "postgres",
                "-d",
                "observal",
                "--clean",
                "--if-exists",
            ],
            stdin=f,
            capture_output=True,
            cwd=compose_dir,
            timeout=300,
        )
    # pg_restore returns non-zero for warnings (e.g., "relation does not exist")
    # which are safe to ignore during --clean restore
    if result.returncode not in (0, 1):
        raise RuntimeError(f"pg_restore failed: {result.stderr.decode()[:200]}")

    rprint("[dim]  PostgreSQL restored.[/dim]")

    analytics_archive = backup_path / "analytics.tar.gz"
    if analytics_archive.exists():
        _restore_analytics(analytics_archive, compose_dir)
        return True

    rprint("[yellow]  No analytics archive in this backup; DuckDB telemetry was not restored.[/yellow]")
    return False


def _wait_for_service_healthy(compose_dir: Path, service: str, timeout: int = 180) -> bool:
    """Poll a compose service until Docker reports it healthy."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        listed = subprocess.run(
            ["docker", "compose", "ps", "-q", service],
            cwd=compose_dir,
            capture_output=True,
            text=True,
        )
        container_ids = [line for line in listed.stdout.splitlines() if line.strip()]
        if container_ids:
            state = subprocess.run(
                ["docker", "inspect", "-f", "{{.State.Health.Status}}", container_ids[0]],
                capture_output=True,
                text=True,
            )
            if state.stdout.strip() == "healthy":
                return True
        time.sleep(2)
    return False


def _validate_analytics_archive(archive: Path) -> None:
    """Fully read and validate an analytics archive before touching live data."""
    try:
        with tarfile.open(archive, "r:gz") as bundle:
            for member in bundle:
                member_path = Path(member.name)
                if member_path.is_absolute() or ".." in member_path.parts:
                    raise RuntimeError(f"analytics archive contains unsafe path: {member.name}")
                if member.issym() or member.islnk() or member.isdev():
                    raise RuntimeError(f"analytics archive contains unsafe member: {member.name}")
                if member.isfile():
                    extracted = bundle.extractfile(member)
                    if extracted is None:
                        raise RuntimeError(f"analytics archive member is unreadable: {member.name}")
                    while extracted.read(1024 * 1024):
                        pass
    except (tarfile.TarError, EOFError, OSError) as exc:
        raise RuntimeError(f"analytics archive is invalid: {exc}") from exc


def _restore_analytics(archive: Path, compose_dir: Path) -> None:
    """Replace the DuckDB analytics data directory from a backup archive.

    The analytics service owns the database file as its only writer, so it is
    stopped for the swap and started again afterwards.
    """
    rprint("[dim]  Restoring DuckDB analytics...[/dim]")
    _validate_analytics_archive(archive)

    stopped = subprocess.run(
        ["docker", "compose", "stop", "observal-duckdb"],
        cwd=compose_dir,
        capture_output=True,
        timeout=300,
    )
    if stopped.returncode != 0:
        raise RuntimeError(f"could not stop analytics service: {stopped.stderr.decode()[:200]}")

    try:
        with archive.open("rb") as handle:
            result = subprocess.run(
                [
                    "docker",
                    "compose",
                    "run",
                    "--rm",
                    "--no-deps",
                    "-T",
                    "observal-duckdb",
                    "sh",
                    "-c",
                    (
                        "rm -rf /data/.restore && mkdir /data/.restore && "
                        "tar xzf - -C /data/.restore && "
                        "find /data -mindepth 1 -maxdepth 1 ! -name .restore -exec rm -rf {} + && "
                        "cp -a /data/.restore/. /data/ && rm -rf /data/.restore"
                    ),
                ],
                stdin=handle,
                capture_output=True,
                cwd=compose_dir,
                timeout=1800,
            )
        if result.returncode != 0:
            raise RuntimeError(f"analytics restore failed: {result.stderr.decode()[:200]}")
    except Exception:
        subprocess.run(
            ["docker", "compose", "up", "-d", "observal-duckdb"],
            cwd=compose_dir,
            capture_output=True,
            timeout=300,
        )
        raise

    started = subprocess.run(
        ["docker", "compose", "up", "-d", "observal-duckdb"],
        cwd=compose_dir,
        capture_output=True,
        timeout=300,
    )
    if started.returncode != 0:
        raise RuntimeError(f"could not start analytics service: {started.stderr.decode()[:200]}")
    if not _wait_for_service_healthy(compose_dir, "observal-duckdb"):
        raise RuntimeError("analytics service did not become healthy after the restore")

    rprint("[dim]  DuckDB analytics restored.[/dim]")


def prune_backups(retention: int = DEFAULT_RETENTION) -> list[Path]:
    """Remove old backups beyond retention count.

    Returns list of pruned paths. Never deletes the most recent backup.
    """
    if not BACKUPS_DIR.exists():
        return []

    backups = sorted(BACKUPS_DIR.iterdir(), key=lambda p: p.name, reverse=True)
    if len(backups) <= retention:
        return []

    to_prune = backups[retention:]
    pruned = []
    for path in to_prune:
        if path.is_dir():
            shutil.rmtree(path)
            pruned.append(path)
    return pruned


def list_backups() -> list[dict]:
    """List all available backups with metadata."""
    if not BACKUPS_DIR.exists():
        return []

    results = []
    for path in sorted(BACKUPS_DIR.iterdir(), key=lambda p: p.name, reverse=True):
        if not path.is_dir():
            continue
        pg_dump = path / "pg.dump"
        size_bytes = pg_dump.stat().st_size if pg_dump.exists() else 0
        results.append(
            {
                "path": str(path),
                "name": path.name,
                "size_bytes": size_bytes,
                "size_mb": round(size_bytes / (1024 * 1024), 1),
                "has_pg": pg_dump.exists(),
                "has_analytics": (path / "analytics.tar.gz").exists(),
            }
        )
    return results


def estimate_backup_size(compose_dir: Path) -> int:
    """Estimate backup size in bytes (for pre-flight disk space check)."""
    try:
        result = subprocess.run(
            [
                "docker",
                "compose",
                "exec",
                "-T",
                "observal-db",
                "psql",
                "-U",
                "postgres",
                "-t",
                "-c",
                "SELECT pg_database_size('observal');",
            ],
            capture_output=True,
            text=True,
            cwd=compose_dir,
            timeout=10,
        )
        if result.returncode == 0:
            return int(result.stdout.strip())
    except (subprocess.TimeoutExpired, ValueError, OSError):
        pass
    # Fallback: assume 100MB
    return 100 * 1024 * 1024
