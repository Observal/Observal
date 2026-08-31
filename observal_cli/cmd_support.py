# SPDX-FileCopyrightText: 2026 Naraen Rammoorthi <naraen13@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""observal doctor support: generate and inspect diagnostic support bundles.

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
import re
import socket
import tarfile
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

import typer
from rich import print as rprint
from rich.tree import Tree
from typer.models import OptionInfo

from observal_cli import client, render
from observal_cli.errors import CliError, ErrorCategory, fail
from observal_cli.render import OutputMode, console, esc, output_json, spinner
from observal_cli.support import CollectorResult
from observal_cli.support.manifest import BundleManifest, compute_file_entry
from observal_cli.support.redaction import RedactionStats, redact_value

# ── Schema version ───────────────────────────────────────────────────

CURRENT_SCHEMA_VERSION = 1

support_app = typer.Typer(
    help=(
        "Generate and inspect diagnostic support bundles. Bundles contain no customer data or row contents.\n\n"
        "Examples:\n"
        "  observal doctor support bundle\n"
        "  observal doctor support inspect ./observal-support.tar.gz"
    ),
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
    }
)


SIZE_BUDGET_BYTES = 100 * 1024 * 1024
MAX_INSPECT_BYTES = 1024 * 1024
_DURATION_RE = re.compile(r"^(?:[1-9]\d*[dhms])+$", re.IGNORECASE)
_SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_REMOTE_COLLECTORS = frozenset({"versions", "health", "config", "aggregates", "errors", "logs"})


def _value(value):
    return value.default if isinstance(value, OptionInfo) else value


def _progress(output: OutputMode | str, message: str):
    from contextlib import nullcontext

    return nullcontext() if _value(output) == "json" else spinner(message)


def _safe_archive_path(name: str) -> bool:
    path = PurePosixPath(name)
    return (
        bool(name)
        and "\\" not in name
        and not re.match(r"^[A-Za-z]:", name)
        and not path.is_absolute()
        and ".." not in path.parts
    )


def _duration_seconds(value: str) -> int:
    units = {"d": 86400, "h": 3600, "m": 60, "s": 1}
    return sum(int(amount) * units[unit.lower()] for amount, unit in re.findall(r"(\d+)([dhms])", value))


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
    file: Path | None = typer.Option(
        None,
        "--file",
        "-f",
        help="Archive path (default: ./observal-support-{timestamp}.tar.gz)",
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
    force: bool = typer.Option(False, "--force", "--yes", help="Overwrite files and skip size confirmation"),
    output: OutputMode = typer.Option("table", "--output", "-o"),
) -> None:
    """Generate a diagnostic support bundle. No customer data or row contents included.

    Collects version info, health probes, aggregate counts, recent logs, and
    system metrics into a .tar.gz archive. No customer data or row contents
    are included: all values pass through the Redaction Layer before writing.

    The bundle is useful for sharing with support or diagnosing issues without
    exposing sensitive data. Archive permissions are set to 0600.

    Examples:
        observal doctor support bundle
        observal doctor support bundle --file /tmp/diag.tar.gz --logs-since 2h
        observal doctor support bundle --no-include-system --output json
    """
    output = _value(output)
    force = _value(force)
    file = _value(file)
    logs_since = _value(logs_since)
    include_system = _value(include_system)
    if not _DURATION_RE.fullmatch(logs_since) or _duration_seconds(logs_since) > 30 * 86400:
        fail(
            ErrorCategory.VALIDATION,
            f"Invalid log duration: {logs_since}.",
            operation="Generate support bundle",
            resource="log duration",
            remediation="Use a positive duration no greater than 30 days, such as 30m, 2h, or 1d12h.",
        )
    if file is None:
        timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        file = Path(f"observal-support-{timestamp}.tar.gz")
    file = file.expanduser()
    if file.exists() and not force:
        if output == "json":
            fail(
                ErrorCategory.CONFLICT,
                f"Support bundle already exists: {file}.",
                operation="Generate support bundle",
                resource=str(file),
                remediation="Choose another path or add --force.",
            )
        typer.confirm(f"Overwrite {file}?", abort=True)

    redaction_stats = RedactionStats()
    warnings: list[str] = []
    remote_status = "collected"
    remote_error: str | None = None

    def warn(message: str) -> None:
        warnings.append(message)
        if output != "json":
            rprint(f"[yellow]Warning:[/yellow] {esc(message)}")

    # Remote collection is optional by design. Every fallback is recorded in
    # the manifest result and JSON response rather than silently swallowed.
    server_response: dict = {}
    with _progress(output, "Collecting diagnostics..."):
        try:
            response = client.post(
                "/api/v1/support/collect",
                {"collectors": ["all"], "logs_since": logs_since},
            )
            if not isinstance(response, dict):
                raise ValueError("support response must be a JSON object")
            server_response = response
        except CliError as error:
            remote_status = error.category.value
            remote_error = f"Remote collectors unavailable: {error.message} Local collectors will continue."
            warn(remote_error)
        except (TypeError, ValueError) as error:
            remote_status = "invalid_response"
            remote_error = (
                f"Remote collectors returned invalid data: {type(error).__name__}. Local collectors will continue."
            )
            warn(remote_error)

    remote_results: list[CollectorResult] = []
    if remote_error:
        remote_results.append(CollectorResult(name="remote", ok=False, duration_ms=0, data=None, error=remote_error))
    server_version = str(server_response.get("server_version") or "unknown")
    collectors = server_response.get("collectors", {})
    if not isinstance(collectors, dict):
        warn("Remote collector results were not an object and were skipped.")
        collectors = {}
    for name, collector_data in collectors.items():
        if name not in _REMOTE_COLLECTORS:
            warn(f"Unknown remote collector skipped: {name}.")
            continue
        if not isinstance(collector_data, dict):
            warn(f"Invalid remote collector skipped: {name}.")
            continue
        try:
            duration_ms = int(collector_data.get("duration_ms", 0))
        except (TypeError, ValueError):
            warn(f"Invalid remote collector duration skipped: {name}.")
            continue
        remote_results.append(
            CollectorResult(
                name=name,
                ok=bool(collector_data.get("ok", False)),
                duration_ms=duration_ms,
                data=collector_data.get("data"),
                error=str(collector_data.get("error")) if collector_data.get("error") else None,
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
        except ImportError as error:
            local_results.append(
                CollectorResult(
                    name="system_info",
                    ok=False,
                    duration_ms=0,
                    data=None,
                    error=f"System collector unavailable: {type(error).__name__}",
                )
            )

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
        if result.name == "config":
            # The local allowlist collector is the only writer for config/config.json.
            continue

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
                for service_name, service_data in redacted_health.items():
                    if not _SAFE_NAME_RE.fullmatch(str(service_name)):
                        warn(f"Unsafe health collector name skipped: {service_name}.")
                        continue
                    service_bytes = json.dumps(service_data, indent=2, default=str).encode("utf-8")
                    files[f"health/{service_name}.json"] = service_bytes
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
                    note, note_count = redact_value(result.data["note"])
                    redaction_stats.record("logs/recent.ndjson", note_count)
                    files["logs/recent.ndjson"] = json.dumps({"note": note}, indent=2).encode("utf-8")
            continue

        # Generic single-file collectors (config_allowlisted, system_info, etc.)
        redacted_data, count = redact_value(result.data)
        redaction_stats.record(result.target_path, count)

        if isinstance(redacted_data, str):
            file_bytes = redacted_data.encode("utf-8")
        else:
            file_bytes = json.dumps(redacted_data, indent=2, default=str).encode("utf-8")

        files[result.target_path] = file_bytes

    unsafe_paths = [path for path in files if not _safe_archive_path(path)]
    if unsafe_paths:
        fail(
            ErrorCategory.VALIDATION,
            "A support collector produced an unsafe archive path.",
            operation="Generate support bundle",
            resource=unsafe_paths[0],
            remediation="Update the CLI or server before generating another bundle.",
        )
    if not files:
        fail(
            ErrorCategory.UNAVAILABLE,
            "No diagnostic data could be collected.",
            operation="Generate support bundle",
            resource="support collectors",
            remediation="Check local collector dependencies or server connectivity and retry.",
        )

    # ── Build manifest ────────────────────────────────────
    cli_version = _get_cli_version()

    # Compute file inventory (SHA-256 hashes)
    file_inventory = [compute_file_entry(path, content) for path, content in sorted(files.items())]

    # Build collector results summary
    collector_summary = {}
    for r in all_results:
        collector_summary[r.name] = {"ok": r.ok, "duration_ms": r.duration_ms}
        if r.error:
            collector_summary[r.name]["error"] = redact_value(r.error)[0]

    manifest = BundleManifest(
        bundle_schema_version="1",
        created_at=datetime.now(UTC).isoformat(),
        cli_version=cli_version,
        host_os=platform.system(),
        node_id=hashlib.sha256(socket.gethostname().encode()).hexdigest()[:12],
        flags_used={
            "file": file.name,
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
        message = f"Uncompressed bundle size {_human_size(total_uncompressed)} exceeds the 100 MB budget."
        warn(message)
        if output == "json" and not force:
            fail(
                ErrorCategory.VALIDATION,
                message,
                operation="Generate support bundle",
                resource="bundle size",
                remediation="Add --force to accept the large archive or collect fewer logs.",
            )
        if output != "json" and not force and not typer.confirm("Continue writing the archive?"):
            rprint("[dim]Bundle creation cancelled.[/dim]")
            return

    try:
        with _progress(output, "Writing archive..."):
            _write_archive(file, files, manifest)
        archive_size = file.stat().st_size
    except (OSError, tarfile.TarError) as error:
        fail(
            ErrorCategory.UNAVAILABLE,
            f"Could not write support bundle: {file}.",
            operation="Generate support bundle",
            resource=str(file),
            remediation="Check the destination path, free space, and permissions, then retry.",
            detail=repr(error),
        )

    result = {
        "path": str(file),
        "size_bytes": archive_size,
        "remote_status": remote_status,
        "warnings": warnings,
        "collector_results": collector_summary,
        "redaction_counts": redaction_stats.counts,
    }
    if output == "json":
        output_json(result)
        return
    rprint(f"[green]✓[/green] Support bundle written to [bold]{esc(file)}[/bold] ({_human_size(archive_size)})")
    rprint(f"[dim]  Review contents with: observal doctor support inspect {esc(file)}[/dim]")


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
            tree.add(f"{esc(member.name)}  [dim]{size}[/dim]")
    console.print(tree)


def _is_safe_tar_member(member: tarfile.TarInfo) -> bool:
    """Reject tar members with path traversal attacks.

    Uses os.path.normpath to catch normalized traversal (e.g. foo/../../etc)
    while allowing legitimate names like 'foo..bar.json'.
    """
    normalized = os.path.normpath(member.name)
    return _safe_archive_path(member.name) and not normalized.startswith(("..", os.sep))


# ── Inspect command ──────────────────────────────────────────────────


@support_app.command()
def inspect(
    bundle_path: Path = typer.Argument(..., help="Path to a .tar.gz support bundle"),
    show: str | None = typer.Option(None, "--show", help="Print one regular file from the archive"),
    output: OutputMode = typer.Option("table", "--output", "-o"),
) -> None:
    """Inspect a support bundle without extracting it.

    Examples:
        observal doctor support inspect ./observal-support.tar.gz
        observal doctor support inspect bundle.tar.gz --show health/postgres.json
        observal doctor support inspect bundle.tar.gz --output json
    """
    output = _value(output)
    show = _value(show)
    bundle_path = bundle_path.expanduser()
    if not bundle_path.is_file():
        fail(
            ErrorCategory.NOT_FOUND,
            f"Support bundle not found: {bundle_path}.",
            operation="Inspect support bundle",
            resource=str(bundle_path),
            remediation="Choose an existing .tar.gz support bundle.",
        )
    try:
        tar = tarfile.open(bundle_path, "r:gz")  # noqa: SIM115
    except (tarfile.TarError, OSError) as error:
        fail(
            ErrorCategory.VALIDATION,
            f"Cannot open support bundle: {bundle_path}.",
            operation="Inspect support bundle",
            resource=str(bundle_path),
            remediation="Choose a valid .tar.gz support bundle.",
            detail=repr(error),
        )

    warnings: list[str] = []
    shown: dict | None = None
    with tar:
        members = tar.getmembers()
        safe_members = [member for member in members if _is_safe_tar_member(member)]
        if len(safe_members) != len(members):
            warnings.append(f"Ignored {len(members) - len(safe_members)} unsafe archive member(s).")

        manifest_member = next(
            (member for member in safe_members if member.name == "bundle_manifest.json" and member.isfile()),
            None,
        )
        if manifest_member is None:
            fail(
                ErrorCategory.VALIDATION,
                "Support bundle manifest is missing or is not a regular file.",
                operation="Inspect support bundle",
                resource="bundle_manifest.json",
                remediation="Generate a new bundle with the current CLI.",
            )
        if manifest_member.size > MAX_INSPECT_BYTES:
            fail(
                ErrorCategory.VALIDATION,
                "Support bundle manifest exceeds the inspection size limit.",
                operation="Inspect support bundle",
                resource="bundle_manifest.json",
                remediation="Generate a new bundle with the current CLI.",
            )
        manifest_file = tar.extractfile(manifest_member)
        if manifest_file is None:
            fail(
                ErrorCategory.VALIDATION,
                "Support bundle manifest cannot be read.",
                operation="Inspect support bundle",
                resource="bundle_manifest.json",
                remediation="Generate a new bundle with the current CLI.",
            )
        try:
            manifest_data = json.loads(manifest_file.read())
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            fail(
                ErrorCategory.VALIDATION,
                "Support bundle manifest is malformed.",
                operation="Inspect support bundle",
                resource="bundle_manifest.json",
                remediation="Generate a new bundle with the current CLI.",
                detail=repr(error),
            )
        if not isinstance(manifest_data, dict):
            fail(
                ErrorCategory.VALIDATION,
                "Support bundle manifest must be a JSON object.",
                operation="Inspect support bundle",
                resource="bundle_manifest.json",
                remediation="Generate a new bundle with the current CLI.",
            )

        schema_version = manifest_data.get("bundle_schema_version", "1")
        try:
            version_int = int(schema_version)
            if version_int > CURRENT_SCHEMA_VERSION:
                warnings.append(f"Bundle uses newer schema v{schema_version}; some fields may not be recognized.")
        except (ValueError, TypeError):
            warnings.append(f"Unrecognized bundle schema version: {schema_version}.")

        if show:
            if not _safe_archive_path(show):
                fail(
                    ErrorCategory.VALIDATION,
                    f"Unsafe archive path: {show}.",
                    operation="Inspect support bundle",
                    resource=show,
                    remediation="Choose a regular file listed in the bundle.",
                )
            member = next((item for item in safe_members if item.name == show and item.isfile()), None)
            if member is None:
                available = ", ".join(sorted(item.name for item in safe_members if item.isfile()))
                fail(
                    ErrorCategory.NOT_FOUND,
                    f"File not found in support bundle: {show}.",
                    operation="Inspect support bundle",
                    resource=show,
                    remediation=f"Choose an available file: {available}.",
                )
            if member.size > MAX_INSPECT_BYTES:
                fail(
                    ErrorCategory.VALIDATION,
                    f"Support bundle file is too large to display: {show}.",
                    operation="Inspect support bundle",
                    resource=show,
                    remediation="Inspect the archive with a size-limited local tool.",
                )
            extracted = tar.extractfile(member)
            if extracted is None:
                fail(
                    ErrorCategory.VALIDATION,
                    f"Support bundle file cannot be read: {show}.",
                    operation="Inspect support bundle",
                    resource=show,
                    remediation="Generate a new support bundle.",
                )
            shown = {"path": show, "content": extracted.read().decode("utf-8", errors="replace")}

    files = [
        {"path": member.name, "size_bytes": member.size}
        for member in sorted(safe_members, key=lambda item: item.name)
        if member.isfile()
    ]
    result = {"manifest": manifest_data, "files": files, "warnings": warnings, "shown": shown}
    if output == "json":
        output_json(result)
        return

    for warning in warnings:
        render.warning(warning)
    console.print_json(json.dumps(manifest_data, indent=2))
    _print_file_tree(safe_members)
    if shown:
        typer.echo(shown["content"])
