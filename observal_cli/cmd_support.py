# SPDX-FileCopyrightText: 2026 Naraen Rammoorthi <naraen13@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""observal support: generate and inspect diagnostic support bundles.

Bundles contain no customer data or row contents - only aggregate counts,
version info, sanitised configuration, health probes, and optional system
metrics.  Every value passes through the central Redaction Layer before
being written to the archive.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import platform
import socket
import tarfile
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

import httpx
import typer
from rich import print as rprint
from rich.tree import Tree

from observal_cli import config, render
from observal_cli.render import console, spinner
from observal_cli.support import CollectorResult
from observal_cli.support.manifest import BundleManifest, compute_file_entry
from observal_cli.support.redaction import RedactionStats, redact_value

# ── Schema version ───────────────────────────────────────────────────

CURRENT_SCHEMA_VERSION = 1

support_app = typer.Typer(
    help="Generate and inspect diagnostic support bundles. Bundles contain no customer data or row contents.",
    no_args_is_help=True,
)

# ── Config allowlist ─────────────────────────────────────────────────

CONFIG_ALLOWLIST = frozenset(
    {
        "DATABASE_URL",
        "CLICKHOUSE_URL",
        "REDIS_URL",
        "REDIS_SOCKET_TIMEOUT",
        "EVAL_MODEL_NAME",
        "EVAL_MODEL_PROVIDER",
        "AWS_REGION",
        "FRONTEND_URL",
        "JWT_ACCESS_TOKEN_EXPIRE_MINUTES",
        "JWT_REFRESH_TOKEN_EXPIRE_DAYS",
        "JWT_SIGNING_ALGORITHM",
        "JWT_HOOKS_TOKEN_EXPIRE_MINUTES",
        "RATE_LIMIT_AUTH",
        "RATE_LIMIT_AUTH_STRICT",
        "DATA_RETENTION_DAYS",
        "PRODUCT_ANALYTICS_ENABLED",
        # Value is redacted by the Redaction Layer (key matches api_key pattern)
        "POSTHOG_API_KEY",
        "POSTHOG_HOST",
    }
)


SIZE_BUDGET_BYTES = 100 * 1024 * 1024  # 100 MB uncompressed warning threshold


# ── CollectorResult ──────────────────────────────────────────────────


# ── Local collectors ─────────────────────────────────────────────────


def _config_allowlisted(server_response: dict) -> CollectorResult:
    """Filter server config response to allowlist keys, then redact values."""
    t0 = time.monotonic()
    try:
        collectors = server_response.get("collectors", {})
        config_data = collectors.get("config", {})
        raw_config = config_data.get("data", {}) if isinstance(config_data, dict) else {}

        if not isinstance(raw_config, dict):
            raw_config = {}

        # Filter to allowlist only
        filtered = {k: v for k, v in raw_config.items() if k in CONFIG_ALLOWLIST}

        # Redact values
        redacted, _count = redact_value(filtered)

        elapsed_ms = int((time.monotonic() - t0) * 1000)
        return CollectorResult(
            name="config_allowlisted",
            ok=True,
            duration_ms=elapsed_ms,
            data=redacted,
        )
    except Exception as exc:
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        return CollectorResult(
            name="config_allowlisted",
            ok=False,
            duration_ms=elapsed_ms,
            data=None,
            error=str(exc),
        )


# ── Archive helpers ──────────────────────────────────────────────────


def _add_bytes_to_tar(tar: tarfile.TarFile, name: str, data: bytes) -> None:
    """Add in-memory bytes to a tarfile as a regular file."""
    info = tarfile.TarInfo(name=name)
    info.size = len(data)
    info.mtime = int(time.time())
    tar.addfile(info, io.BytesIO(data))


def _write_archive(
    output_path: Path,
    files: dict[str, bytes],
    manifest: BundleManifest,
) -> None:
    """Write a .tar.gz archive with 0o600 permissions.

    Uses a temp file + os.replace for atomic rename on POSIX.
    """
    # Ensure parent directory exists
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.NamedTemporaryFile(
        suffix=".tar.gz",
        dir=str(output_path.parent),
        delete=False,
    ) as tmp:
        tmp_path = tmp.name

    try:
        with tarfile.open(tmp_path, "w:gz") as tar:
            # Write manifest first
            manifest_bytes = manifest.to_json().encode("utf-8")
            _add_bytes_to_tar(tar, "bundle_manifest.json", manifest_bytes)

            # Write all collected files
            for rel_path, content in sorted(files.items()):
                _add_bytes_to_tar(tar, rel_path, content)

        # Set restrictive permissions before moving to final location
        os.chmod(tmp_path, 0o600)
        os.replace(tmp_path, str(output_path))
    except Exception:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise


def _human_size(size_bytes: int) -> str:
    """Format bytes as a human-readable string."""
    for unit in ("B", "KB", "MB", "GB"):
        if abs(size_bytes) < 1024:
            return f"{size_bytes:.1f} {unit}" if unit != "B" else f"{size_bytes} {unit}"
        size_bytes /= 1024  # type: ignore[assignment]
    return f"{size_bytes:.1f} TB"


# ── CLI version helper ───────────────────────────────────────────────


def _get_cli_version() -> str:
    try:
        from importlib.metadata import version as pkg_version

        return pkg_version("observal-cli")
    except Exception:
        return "dev"


# ── Bundle command ───────────────────────────────────────────────────


@support_app.command()
def bundle(
    output: Path = typer.Option(
        None,
        "--output",
        "-o",
        help="Archive output path (default: ./observal-support-{timestamp}.tar.gz)",
    ),
    logs_since: str = typer.Option(
        "1h",
        "--logs-since",
        help="Duration of logs to include (e.g. 1h, 30m, 2d)",
    ),
    include_system: bool = typer.Option(
        True,
        "--include-system/--no-include-system",
        help="Include OS/CPU/memory/disk metrics",
    ),
) -> None:
    """Generate a diagnostic support bundle. No customer data or row contents included.

    Collects version info, health probes, aggregate counts, recent logs, and
    system metrics into a .tar.gz archive. No customer data or row contents
    are included: all values pass through the Redaction Layer before writing.

    The bundle is useful for sharing with support or diagnosing issues without
    exposing sensitive data. Archive permissions are set to 0600.

    Examples:
        observal support bundle
        observal support bundle -o /tmp/diag.tar.gz --logs-since 2h
        observal support bundle --no-include-system
    """
    # Determine output path
    if output is None:
        timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        output = Path(f"observal-support-{timestamp}.tar.gz")

    redaction_stats = RedactionStats()

    # ── Collect remote diagnostics ────────────────────────
    server_response: dict = {}
    with spinner("Collecting diagnostics..."):
        try:
            cfg = config.get_or_exit()
            base_url = cfg["server_url"].rstrip("/")
            headers = {"Authorization": f"Bearer {cfg['access_token']}"}
            timeout = config.get_timeout()
            r = httpx.post(
                f"{base_url}/api/v1/support/collect",
                json={"collectors": ["all"], "logs_since": logs_since},
                headers=headers,
                timeout=timeout,
            )
            r.raise_for_status()
            server_response = r.json()
        except httpx.HTTPStatusError as exc:
            code = exc.response.status_code
            if code == 404:
                rprint(
                    "[yellow]Warning:[/yellow] Server does not have the support endpoint yet. "
                    "Rebuild the server container to enable remote collectors."
                )
            elif code == 401:
                rprint(
                    "[yellow]Warning:[/yellow] Authentication failed. Run [bold]observal auth login[/bold] to re-authenticate."
                )
            else:
                rprint(f"[yellow]Warning:[/yellow] Server returned HTTP {code}. Remote collectors skipped.")
            server_response = {}
        except (httpx.ConnectError, httpx.ReadTimeout, httpx.ConnectTimeout):
            rprint("[yellow]Warning:[/yellow] Could not reach server. Bundle will contain only local data.")
            server_response = {}
        except SystemExit:
            # config.get_or_exit() may raise if not configured
            rprint("[yellow]Warning:[/yellow] CLI not configured. Run [bold]observal auth login[/bold] first.")
            server_response = {}

    if not isinstance(server_response, dict):
        server_response = {}

    # ── Parse remote collector results ────────────────────
    remote_results: list[CollectorResult] = []
    server_version = server_response.get("server_version", "unknown")
    for name, cdata in server_response.get("collectors", {}).items():
        if isinstance(cdata, dict):
            remote_results.append(
                CollectorResult(
                    name=name,
                    ok=cdata.get("ok", False),
                    duration_ms=cdata.get("duration_ms", 0),
                    data=cdata.get("data"),
                    error=cdata.get("error"),
                )
            )

    # ── Run local collectors in parallel ──────────────────
    local_results: list[CollectorResult] = []

    def _run_config_collector() -> CollectorResult:
        return _config_allowlisted(server_response)

    local_tasks = [_run_config_collector]

    if include_system:
        try:
            from observal_cli.support.collectors import system_info as _system_info_fn

            def _run_system_collector() -> CollectorResult:
                return _system_info_fn({}, server_response)

            local_tasks.append(_run_system_collector)
        except ImportError:
            pass

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(fn) for fn in local_tasks]
        for future in futures:
            try:
                # Note: timeout only stops waiting - it does not kill the worker
                # thread. For these short collectors (system info, config filter)
                # this is fine; a hanging thread will be cleaned up at process exit.
                result = future.result(timeout=10)
                local_results.append(result)
            except Exception as exc:
                local_results.append(
                    CollectorResult(
                        name="unknown",
                        ok=False,
                        duration_ms=10000,
                        data=None,
                        error=f"Collector timed out or failed: {type(exc).__name__}",
                    )
                )

    all_results = remote_results + local_results

    # ── Redact all values and build file dict ─────────────
    files: dict[str, bytes] = {}

    for result in all_results:
        if not result.ok or result.data is None:
            continue

        # Handle special cases for remote collectors that map to multiple files.
        # These branches redact internally and continue, so the generic redaction
        # at the bottom of the loop only runs for simple single-file collectors.
        if result.name == "versions":
            # Split versions data into separate files
            if isinstance(result.data, dict):
                redacted_versions, ver_count = redact_value(result.data)
                redaction_stats.record("versions/app.json", ver_count)

                app_data = {
                    "cli_version": _get_cli_version(),
                    "server_version": server_version,
                    "build_hash": redacted_versions.get("build_hash", "unknown"),
                    "app_version": redacted_versions.get("app_version", "unknown"),
                }
                files["versions/app.json"] = json.dumps(app_data, indent=2).encode("utf-8")

                alembic_data = {"current_revision": redacted_versions.get("alembic_revision", "unknown")}
                files["versions/alembic.json"] = json.dumps(alembic_data, indent=2).encode("utf-8")

                ch_data = {
                    "server_version": redacted_versions.get("clickhouse_version", "unknown"),
                    "tables": redacted_versions.get("clickhouse_tables", []),
                }
                files["versions/clickhouse.json"] = json.dumps(ch_data, indent=2).encode("utf-8")
            continue

        if result.name == "health":
            # Split health data into separate files per service
            if isinstance(result.data, dict):
                redacted_health, health_count = redact_value(result.data)
                redaction_stats.record("health/health.json", health_count)
                for svc_name, svc_data in redacted_health.items():
                    svc_bytes = json.dumps(svc_data, indent=2, default=str).encode("utf-8")
                    files[f"health/{svc_name}.json"] = svc_bytes
            continue

        if result.name == "aggregates":
            # Split aggregates into PG and CH count files
            if isinstance(result.data, dict):
                redacted_agg, agg_count = redact_value(result.data)
                redaction_stats.record("aggregates/aggregates.json", agg_count)
                pg_counts = redacted_agg.get("pg_table_counts", {})
                ch_counts = redacted_agg.get("ch_table_counts", {})
                files["aggregates/pg_table_counts.json"] = json.dumps(pg_counts, indent=2, default=str).encode("utf-8")
                files["aggregates/ch_table_counts.json"] = json.dumps(ch_counts, indent=2, default=str).encode("utf-8")
            continue

        if result.name == "logs":
            # Log lines: redact each line individually, write as newline-delimited JSON
            if isinstance(result.data, dict):
                lines = result.data.get("lines", [])
                redacted_lines: list[str] = []
                for line in lines:
                    redacted_line, line_count = redact_value(line)
                    redaction_stats.record("logs/recent.ndjson", line_count)
                    redacted_lines.append(json.dumps(redacted_line, default=str))
                if redacted_lines:
                    files["logs/recent.ndjson"] = "\n".join(redacted_lines).encode("utf-8")
                elif result.data.get("note"):
                    # Write the note so the bundle still has the logs file
                    files["logs/recent.ndjson"] = json.dumps({"note": result.data["note"]}, indent=2).encode("utf-8")
            continue

        # Generic single-file collectors (config_allowlisted, system_info, etc.)
        redacted_data, count = redact_value(result.data)
        redaction_stats.record(result.target_path, count)

        if isinstance(redacted_data, str):
            file_bytes = redacted_data.encode("utf-8")
        else:
            file_bytes = json.dumps(redacted_data, indent=2, default=str).encode("utf-8")

        files[result.target_path] = file_bytes

    # If no data at all, exit with error
    if not files:
        rprint("[red]Error:[/red] No diagnostic data could be collected. Bundle not created.")
        raise typer.Exit(1)

    # ── Build manifest ────────────────────────────────────
    cli_version = _get_cli_version()

    # Compute file inventory (SHA-256 hashes)
    file_inventory = [compute_file_entry(path, content) for path, content in sorted(files.items())]

    # Build collector results summary
    collector_summary = {}
    for r in all_results:
        collector_summary[r.name] = {"ok": r.ok, "duration_ms": r.duration_ms}
        if r.error:
            collector_summary[r.name]["error"] = r.error

    manifest = BundleManifest(
        bundle_schema_version="1",
        created_at=datetime.now(UTC).isoformat(),
        cli_version=cli_version,
        host_os=platform.system(),
        node_id=hashlib.sha256(socket.gethostname().encode()).hexdigest()[:12],
        flags_used={
            "output": output.name,
            "logs_since": logs_since,
            "include_system": include_system,
        },
        collector_results=collector_summary,
        redaction_counts=redaction_stats.counts,
        file_inventory=file_inventory,
    )

    # ── Size budget check ─────────────────────────────────
    manifest_bytes = manifest.to_json().encode("utf-8")
    total_uncompressed = sum(len(v) for v in files.values()) + len(manifest_bytes)

    if total_uncompressed > SIZE_BUDGET_BYTES:
        rprint(
            f"[yellow]Warning:[/yellow] Uncompressed bundle size is "
            f"{_human_size(total_uncompressed)} (exceeds 100 MB budget)."
        )
        if not typer.confirm("Continue writing the archive?"):
            rprint("[dim]Bundle creation cancelled.[/dim]")
            raise typer.Exit(0)

    # ── Write archive ─────────────────────────────────────
    with spinner("Writing archive..."):
        _write_archive(output, files, manifest)

    archive_size = output.stat().st_size
    rprint(f"[green]✓[/green] Support bundle written to [bold]{output}[/bold] ({_human_size(archive_size)})")
    rprint("[dim]  Review contents with: observal support inspect " + str(output) + "[/dim]")


# ── Inspect helpers ──────────────────────────────────────────────────


def _print_file_tree(members: list[tarfile.TarInfo]) -> None:
    """Print a Rich tree view of all files in the archive with human-readable sizes.

    Accepts a pre-filtered list of safe tar members to avoid displaying
    entries with path traversal attacks.
    """
    tree = Tree("[bold]Bundle contents[/bold]")
    for member in sorted(members, key=lambda m: m.name):
        if member.isfile():
            size = _human_size(member.size)
            tree.add(f"{member.name}  [dim]{size}[/dim]")
    console.print(tree)


def _is_safe_tar_member(member: tarfile.TarInfo) -> bool:
    """Reject tar members with path traversal attacks.

    Uses os.path.normpath to catch normalized traversal (e.g. foo/../../etc)
    while allowing legitimate names like 'foo..bar.json'.
    """
    normalized = os.path.normpath(member.name)
    return not normalized.startswith(("..", os.sep)) and not os.path.isabs(normalized)


# ── Inspect command ──────────────────────────────────────────────────


@support_app.command()
def inspect(
    bundle_path: Path = typer.Argument(
        ...,
        help="Path to a .tar.gz support bundle",
    ),
    show: str | None = typer.Option(
        None,
        "--show",
        help="Print contents of a specific file from the archive",
    ),
) -> None:
    """Inspect a support bundle.

    Displays the bundle manifest (schema version, collector results, redaction
    counts), a file tree with sizes, and optionally prints the contents of a
    specific file from the archive using --show.

    Examples:
        observal support inspect ./observal-support-20260101-120000.tar.gz
        observal support inspect bundle.tar.gz --show health/postgres.json
    """
    if not bundle_path.exists():
        render.error(f"Bundle not found: {bundle_path}")
        raise typer.Exit(1)

    try:
        tar = tarfile.open(bundle_path, "r:gz")  # noqa: SIM115
    except (tarfile.TarError, OSError):
        render.error(f"Cannot open bundle: {bundle_path}")
        raise typer.Exit(1)

    with tar:
        # Safety: filter members to prevent path traversal attacks
        safe_members = [m for m in tar.getmembers() if _is_safe_tar_member(m)]

        # Read and display manifest
        try:
            manifest_member = tar.getmember("bundle_manifest.json")
            manifest_file = tar.extractfile(manifest_member)
            if manifest_file is None:
                render.error("Invalid bundle: bundle_manifest.json is not a regular file")
                raise typer.Exit(1)
            manifest_data = json.loads(manifest_file.read())
        except KeyError:
            render.error("Invalid bundle: bundle_manifest.json missing or malformed")
            raise typer.Exit(1)
        except json.JSONDecodeError:
            render.error("Invalid bundle: bundle_manifest.json missing or malformed")
            raise typer.Exit(1)

        # Schema version warning
        schema_version = manifest_data.get("bundle_schema_version", "1")
        try:
            version_int = int(schema_version)
            if version_int > CURRENT_SCHEMA_VERSION:
                render.warning(
                    f"Bundle created by a newer CLI (schema v{schema_version}). Some fields may not be recognized."
                )
        except (ValueError, TypeError):
            render.warning(f"Unrecognized bundle schema version: {schema_version}")

        # Print manifest as formatted JSON
        console.print_json(json.dumps(manifest_data, indent=2))

        # Print file tree with sizes (using safe_members to exclude path traversal entries)
        _print_file_tree(safe_members)

        # --show: print specific file contents
        if show:
            try:
                member = tar.getmember(show)
                if not _is_safe_tar_member(member):
                    render.error(f"Unsafe path rejected: {show}")
                    raise typer.Exit(1)
                extracted = tar.extractfile(member)
                if extracted is None:
                    render.error(f"Cannot read file from archive: {show}")
                    raise typer.Exit(1)
                content = extracted.read().decode("utf-8", errors="replace")
                console.print(content)
            except KeyError:
                available = sorted(m.name for m in safe_members if m.isfile())
                render.error(f"File not found in archive: {show}")
                rprint("[dim]Available files:[/dim]")
                for f in available:
                    rprint(f"  {f}")
                raise typer.Exit(1)
