# SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""One-time ClickHouse -> DuckDB cutover, driven by ``observal server upgrade``.

A deployment created before the DuckDB release stores telemetry in a
``observal-clickhouse`` container. Upgrading it requires more than pulling new
images: the compose topology changes, a shared analytics token must exist, and
every telemetry row has to be copied and verified before the new API starts.

This module chains the pieces that already exist (release bundle, token
provisioning, ``migrate duckdb``, health gates) into a single, idempotent,
fail-closed flow:

    detect legacy state
      -> back up PostgreSQL
      -> install the release compose/nginx files (server-package installs)
      -> provision DUCKDB_ANALYTICS_TOKEN / DUCKDB_ANALYTICS_URL
      -> start only observal-duckdb next to the running ClickHouse
      -> export ClickHouse -> load DuckDB -> verify checksums and row counts
      -> (caller deploys the new API and health-checks it)
      -> stop ClickHouse, keep its volume, write a completion marker

ClickHouse is never written to. Any failure before the deploy step leaves the
old stack untouched and running.
"""

from __future__ import annotations

import io
import json
import os
import re
import secrets
import shutil
import subprocess
import tarfile
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile, TemporaryDirectory
from typing import TYPE_CHECKING
from urllib.parse import urlparse, urlunparse

import httpx
from loguru import logger as optic

if TYPE_CHECKING:
    from collections.abc import Callable

MARKER_NAME = ".observal-cutover-complete.json"
LEGACY_COMPOSE_BACKUP = "docker-compose.clickhouse.bak.yml"
CLICKHOUSE_SERVICE = "observal-clickhouse"
DUCKDB_SERVICE = "observal-duckdb"
LEGACY_WRITER_SERVICES = ("observal-api", "observal-worker")
RELEASE_FILES = ("docker-compose.yml", "nginx.conf", "docker-compose.observability.yml")
RUNBOOK_URL = "https://github.com/Observal/Observal/blob/main/docs/architecture/duckdb-replacement.md#cutover-runbook"


class CutoverError(RuntimeError):
    """A cutover step failed; the legacy stack is still intact."""

    def __init__(self, message: str, *, remediation: str = "") -> None:
        super().__init__(message)
        self.remediation = remediation or f"Follow the manual runbook at {RUNBOOK_URL}."


@dataclass
class LegacyState:
    """What the deployment directory tells us about the pre-DuckDB install."""

    compose_dir: Path
    compose_path: Path
    env_file: Path
    flavor: str  # "package" (release tarball + secrets/) or "source" (git checkout)
    compose_has_clickhouse: bool
    compose_has_duckdb: bool
    env_has_clickhouse: bool
    env_has_duckdb: bool
    marker_path: Path
    marker_exists: bool
    clickhouse_container: str | None

    @property
    def needs_cutover(self) -> bool:
        if self.marker_exists:
            return False
        legacy_shape = self.compose_has_clickhouse or self.env_has_clickhouse
        return legacy_shape and self.clickhouse_container is not None


@dataclass
class CutoverResult:
    started_at: str
    completed_at: str = ""
    from_version: str = ""
    to_version: str = ""
    flavor: str = ""
    backup: str | None = None
    export_dir: str = ""
    legacy_compose_backup: str | None = None
    clickhouse_container: str | None = None
    legacy_writer_containers: list[str] = field(default_factory=list)
    row_counts: dict = field(default_factory=dict)
    total_rows: int = 0
    clickhouse_stopped: bool = False


# ── detection ────────────────────────────────────────────────────────────────


def _env_value(env_file: Path, key: str) -> str:
    if not env_file.exists():
        return ""
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith(f"{key}="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def _find_env_file(compose_dir: Path) -> Path:
    for candidate in (compose_dir / ".env", compose_dir.parent / ".env"):
        if candidate.exists():
            return candidate
    return compose_dir / ".env"


def _docker(*args: str, cwd: Path | None = None, timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", *args], cwd=cwd, capture_output=True, text=True, timeout=timeout)


def compose_project_name(compose_dir: Path) -> str:
    """Mirror Compose's project-name resolution: env, project .env, then directory name."""
    name = os.environ.get("COMPOSE_PROJECT_NAME") or _env_value(compose_dir / ".env", "COMPOSE_PROJECT_NAME")
    if not name:
        name = compose_dir.resolve().name
    name = re.sub(r"[^a-z0-9_-]", "", name.lower())
    return name.lstrip("_-") or "default"


def _find_clickhouse_container(compose_dir: Path) -> str | None:
    """Return this project's legacy ClickHouse container (running or stopped), if any.

    Compose labels are authoritative so a stale container from another project
    directory is never mistaken for the source of truth.
    """
    project = compose_project_name(compose_dir)
    listed = _docker(
        "ps",
        "-a",
        "--filter",
        f"label=com.docker.compose.project={project}",
        "--filter",
        f"label=com.docker.compose.service={CLICKHOUSE_SERVICE}",
        "--format",
        "{{.Names}}",
    )
    if listed.returncode != 0:
        return None
    names = [n for n in listed.stdout.splitlines() if n.strip()]
    return names[0] if names else None


def detect_legacy_state(compose_dir: Path) -> LegacyState:
    compose_path = next(
        (compose_dir / n for n in ("docker-compose.yml", "compose.yml") if (compose_dir / n).is_file()),
        compose_dir / "docker-compose.yml",
    )
    compose_text = compose_path.read_text(encoding="utf-8") if compose_path.exists() else ""
    env_file = _find_env_file(compose_dir)
    flavor = "package" if (compose_dir / "setup.sh").exists() or (compose_dir / "secrets").is_dir() else "source"
    marker = compose_dir / MARKER_NAME
    env_has_clickhouse = bool(_env_value(env_file, "CLICKHOUSE_URL") or _env_value(env_file, "CLICKHOUSE_URL_FILE"))
    env_has_duckdb = bool(
        _env_value(env_file, "DUCKDB_ANALYTICS_TOKEN") or _env_value(env_file, "DUCKDB_ANALYTICS_TOKEN_FILE")
    )
    compose_has_clickhouse = CLICKHOUSE_SERVICE in compose_text
    # CLICKHOUSE_URL remains authoritative until the completion marker exists.
    # A failed attempt may already have installed the DuckDB compose/env values;
    # it must still be detected and retried rather than treated as complete.
    legacy_shape = compose_has_clickhouse or env_has_clickhouse
    # Only consult Docker when the files look legacy: a normal upgrade must not
    # depend on the daemon for detection.
    container = _find_clickhouse_container(compose_dir) if legacy_shape and not marker.exists() else None
    return LegacyState(
        compose_dir=compose_dir,
        compose_path=compose_path,
        env_file=env_file,
        flavor=flavor,
        compose_has_clickhouse=compose_has_clickhouse,
        compose_has_duckdb=DUCKDB_SERVICE in compose_text,
        env_has_clickhouse=env_has_clickhouse,
        env_has_duckdb=env_has_duckdb,
        marker_path=marker,
        marker_exists=marker.exists(),
        clickhouse_container=container,
    )


# ── connection resolution ────────────────────────────────────────────────────


def _secret_file(compose_dir: Path, env_file: Path, key: str) -> str:
    """Resolve ``<KEY>_FILE`` (container path) to a host-side secrets file."""
    container_path = _env_value(env_file, f"{key}_FILE")
    if not container_path:
        return ""
    relative = container_path.removeprefix("/run/secrets/").lstrip("/")
    for candidate in (compose_dir / "secrets" / relative, compose_dir / "secrets" / Path(relative).name):
        if candidate.is_file():
            return candidate.read_text(encoding="utf-8").strip()
    return ""


def _host_port(container: str, container_port: int) -> str | None:
    result = _docker("port", container, str(container_port))
    if result.returncode != 0:
        return None
    for line in result.stdout.splitlines():
        # "127.0.0.1:8123" or "0.0.0.0:8123" or "[::]:8123"
        m = re.search(r":(\d+)\s*$", line.strip())
        if m:
            return m.group(1)
    return None


def resolve_clickhouse_url(state: LegacyState) -> str:
    """Build a host-reachable ClickHouse URL from the legacy configuration."""
    raw = _env_value(state.env_file, "CLICKHOUSE_URL") or _secret_file(
        state.compose_dir, state.env_file, "CLICKHOUSE_URL"
    )
    if not raw:
        user = _env_value(state.env_file, "CLICKHOUSE_USER") or "default"
        password = _env_value(state.env_file, "CLICKHOUSE_PASSWORD") or _secret_file(
            state.compose_dir, state.env_file, "CLICKHOUSE_PASSWORD"
        )
        legacy_secret = state.compose_dir / "secrets" / "clickhouse" / "clickhouse_password"
        if not password and legacy_secret.is_file():
            password = legacy_secret.read_text(encoding="utf-8").strip()
        raw = f"clickhouse://{user}:{password}@{CLICKHOUSE_SERVICE}:8123/observal"
    parsed = urlparse(raw)
    port = None
    if state.clickhouse_container:
        port = _host_port(state.clickhouse_container, 8123)
    port = port or _env_value(state.env_file, "CLICKHOUSE_HOST_PORT") or "8123"
    auth = ""
    if parsed.username:
        auth = parsed.username + (f":{parsed.password}" if parsed.password else "") + "@"
    netloc = f"{auth}127.0.0.1:{port}"
    return urlunparse((parsed.scheme or "clickhouse", netloc, parsed.path or "/observal", "", "", ""))


def resolve_duckdb_params(state: LegacyState) -> tuple[str, str]:
    """Return (host-side duckdb URL, token) after provisioning."""
    token = ""
    for path in _container_env_files(state):
        token = _env_value(path, "DUCKDB_ANALYTICS_TOKEN") or _secret_file(
            state.compose_dir, path, "DUCKDB_ANALYTICS_TOKEN"
        )
        if token:
            break
    port = _env_value(state.env_file, "DUCKDB_HOST_PORT") or "8484"
    return f"duckdb://127.0.0.1:{port}/observal", token


# ── steps ────────────────────────────────────────────────────────────────────


def _running_service_containers(compose_dir: Path, service: str) -> list[str]:
    project = compose_project_name(compose_dir)
    listed = _docker(
        "ps",
        "--filter",
        f"label=com.docker.compose.project={project}",
        "--filter",
        f"label=com.docker.compose.service={service}",
        "--format",
        "{{.Names}}",
    )
    if listed.returncode != 0:
        raise CutoverError(f"could not list legacy {service} containers: {listed.stderr.strip()[:200]}")
    return [name for name in listed.stdout.splitlines() if name.strip()]


def restart_legacy_writers(containers: list[str], log: Callable[[str], None]) -> None:
    """Best-effort restart of writer containers stopped before a failed cutover."""
    for container in containers:
        result = _docker("start", container, timeout=180)
        if result.returncode != 0:
            log(f"[yellow]Could not restart {container}: {result.stderr.strip()[:120]}[/yellow]")


def quiesce_legacy_writers(state: LegacyState, log: Callable[[str], None]) -> list[str]:
    """Stop every legacy API/worker container before fixing the export cutoff."""
    containers = [
        container
        for service in LEGACY_WRITER_SERVICES
        for container in _running_service_containers(state.compose_dir, service)
    ]
    stopped: list[str] = []
    for container in containers:
        result = _docker("stop", container, timeout=180)
        if result.returncode != 0:
            restart_legacy_writers(stopped, log)
            raise CutoverError(f"could not stop legacy writer {container}: {result.stderr.strip()[:200]}")
        stopped.append(container)
    if stopped:
        log(f"Paused {len(stopped)} legacy API/worker container(s) for a consistent export")
    return stopped


def ensure_clickhouse_running(state: LegacyState, log: Callable[[str], None]) -> str:
    """Start the legacy container if it is stopped and wait for /ping."""
    if not state.clickhouse_container:
        raise CutoverError(
            "No legacy ClickHouse container was found, so there is nothing to migrate from.",
            remediation="Recreate the previous release with its ClickHouse volume, or import a telemetry export.",
        )
    running = _docker("inspect", "-f", "{{.State.Running}}", state.clickhouse_container).stdout.strip()
    if running != "true":
        log(f"Starting stopped ClickHouse container {state.clickhouse_container} for export")
        started = _docker("start", state.clickhouse_container, timeout=120)
        if started.returncode != 0:
            raise CutoverError(f"could not start {state.clickhouse_container}: {started.stderr.strip()[:200]}")
    url = resolve_clickhouse_url(state)
    parsed = urlparse(url)
    ping = f"http://{parsed.hostname}:{parsed.port}/ping"
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        try:
            if httpx.get(ping, timeout=3).status_code == 200:
                return url
        except httpx.HTTPError:
            pass
        time.sleep(2)
    raise CutoverError(f"ClickHouse did not answer {ping} within 90s")


def install_release_files(state: LegacyState, target: str, repo: str, log: Callable[[str], None]) -> Path | None:
    """Install the target release's compose/nginx files; return the legacy compose backup path."""
    if state.flavor == "source":
        if state.compose_has_clickhouse:
            raise CutoverError(
                "This is a source checkout whose docker/docker-compose.yml still defines ClickHouse.",
                remediation="Run `git pull` (or check out the release tag) so the compose file defines "
                "observal-duckdb, then re-run `observal server upgrade`.",
            )
        return None  # the checkout already carries the new topology

    bundle = f"observal-server-v{target}.tar.gz"
    url = f"https://github.com/{repo}/releases/download/v{target}/{bundle}"
    log(f"Downloading release bundle {bundle}")
    try:
        response = httpx.get(url, follow_redirects=True, timeout=120)
    except httpx.HTTPError as error:
        raise CutoverError(f"could not download {url}: {error}") from error
    if response.status_code != 200:
        raise CutoverError(f"release bundle not found: HTTP {response.status_code} for {url}")

    backup = state.compose_dir / LEGACY_COMPOSE_BACKUP
    if not backup.exists():
        shutil.copy2(state.compose_path, backup)
    with TemporaryDirectory() as tmp, tarfile.open(fileobj=io.BytesIO(response.content), mode="r:gz") as tar:
        tar.extractall(tmp, filter="data")
        root = next(Path(tmp).glob("observal-server-v*"), Path(tmp))
        installed = []
        for name in RELEASE_FILES:
            src = root / name
            if src.is_file():
                shutil.copy2(src, state.compose_dir / name)
                installed.append(name)
        if "docker-compose.yml" not in installed:
            raise CutoverError(f"release bundle {bundle} did not contain docker-compose.yml")
    log(f"Installed {', '.join(installed)} (legacy compose kept as {backup.name})")
    return backup


def _append_env_lines(env_file: Path, lines: dict[str, str]) -> None:
    """Append ``KEY=value`` for keys that are absent; never overwrite."""
    existing = env_file.read_text(encoding="utf-8") if env_file.exists() else ""
    present = {ln.split("=", 1)[0].strip() for ln in existing.splitlines() if "=" in ln and not ln.startswith("#")}
    additions = [f"{k}={v}" for k, v in lines.items() if k not in present]
    if not additions:
        return
    content = existing.rstrip("\n") + ("\n" if existing else "") + "\n".join(additions) + "\n"
    env_file.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile("w", encoding="utf-8", dir=env_file.parent, prefix=f".{env_file.name}.", delete=False) as f:
        f.write(content)
        f.flush()
        os.fsync(f.fileno())
        tmp = Path(f.name)
    tmp.chmod(0o600)
    tmp.replace(env_file)


def _container_env_files(state: LegacyState) -> list[Path]:
    """Every ``.env`` the containers read: compose ``env_file:`` entries plus the interpolation file.

    The source compose interpolates ``${VAR}`` from ``docker/.env`` but hands
    containers ``../.env``; a token written to only one of them is invisible to
    the other side.
    """
    files: dict[Path, None] = {state.env_file.resolve(): None}
    if state.compose_path.exists():
        text = state.compose_path.read_text(encoding="utf-8")
        for match in re.finditer(r"^\s*env_file:\s*\n((?:\s*-\s*.+\n)+)", text, re.MULTILINE):
            for entry in re.findall(r"-\s*(\S+)", match.group(1)):
                candidate = (state.compose_dir / entry.strip("'\"")).resolve()
                if candidate.exists():
                    files[candidate] = None
        for match in re.finditer(r"^\s*env_file:\s*(\S+)\s*$", text, re.MULTILINE):
            candidate = (state.compose_dir / match.group(1).strip("'\"")).resolve()
            if candidate.exists():
                files[candidate] = None
    return list(files)


def provision_duckdb_secrets(state: LegacyState, log: Callable[[str], None]) -> None:
    """Create the analytics token and URL if missing, matching setup.sh's layout."""
    if state.flavor == "package":
        secrets_dir = state.compose_dir / "secrets"
        duck_dir = secrets_dir / "duckdb"
        duck_dir.mkdir(parents=True, exist_ok=True)
        secrets_dir.chmod(0o750)
        duck_dir.chmod(0o750)
        token_file = duck_dir / "duckdb_analytics_token"
        if not token_file.is_file() or not token_file.read_text().strip():
            token_file.write_text(secrets.token_urlsafe(32) + "\n", encoding="utf-8")
            token_file.chmod(0o600)
            log("Generated secrets/duckdb/duckdb_analytics_token")
        url_file = secrets_dir / "duckdb_analytics_url"
        if not url_file.is_file() or not url_file.read_text().strip():
            url_file.write_text(f"duckdb://{DUCKDB_SERVICE}:8484/observal\n", encoding="utf-8")
            url_file.chmod(0o600)
        _append_env_lines(
            state.env_file,
            {
                "DUCKDB_ANALYTICS_URL_FILE": "/run/secrets/duckdb_analytics_url",
                "DUCKDB_ANALYTICS_TOKEN_FILE": "/run/secrets/duckdb/duckdb_analytics_token",
                "DUCKDB_MEMORY_LIMIT": "2GB",
                "DUCKDB_CONTAINER_MEMORY_LIMIT": "3GB",
            },
        )
        return

    targets = _container_env_files(state)
    token = next(
        (_env_value(path, "DUCKDB_ANALYTICS_TOKEN") for path in targets if _env_value(path, "DUCKDB_ANALYTICS_TOKEN")),
        "",
    )
    if not token:
        token = secrets.token_urlsafe(32)
        log("Generated DUCKDB_ANALYTICS_TOKEN")
    additions = {"DUCKDB_ANALYTICS_URL": f"duckdb://{DUCKDB_SERVICE}:8484/observal", "DUCKDB_ANALYTICS_TOKEN": token}
    for path in targets:
        _append_env_lines(path, additions)


def start_duckdb_service(state: LegacyState, target: str, log: Callable[[str], None]) -> tuple[str, str]:
    """Bring up only observal-duckdb (ClickHouse stays running) and require authenticated health."""
    env = {**os.environ, "OBSERVAL_VERSION": target}
    log("Starting observal-duckdb alongside ClickHouse")
    up = subprocess.run(
        ["docker", "compose", "up", "-d", "--no-deps", DUCKDB_SERVICE],
        cwd=state.compose_dir,
        env=env,
        capture_output=True,
        text=True,
        timeout=600,
    )
    if up.returncode != 0:
        raise CutoverError(f"docker compose up observal-duckdb failed: {up.stderr.strip()[:300]}")
    url, token = resolve_duckdb_params(state)
    if not token:
        raise CutoverError("DUCKDB_ANALYTICS_TOKEN could not be resolved after provisioning")
    parsed = urlparse(url.replace("duckdb://", "http://"))
    version_url = f"http://{parsed.hostname}:{parsed.port or 8484}/version"
    deadline = time.monotonic() + 120
    last = ""
    while time.monotonic() < deadline:
        try:
            resp = httpx.get(version_url, headers={"Authorization": f"Bearer {token}"}, timeout=5)
            if resp.status_code == 200:
                return url, token
            last = f"HTTP {resp.status_code}"
        except httpx.HTTPError as error:
            last = type(error).__name__
        time.sleep(3)
    raise CutoverError(f"observal-duckdb did not pass authenticated health within 120s ({last})")


def migrate_telemetry(clickhouse_url: str, duckdb_url: str, token: str, export_dir: Path, reporter) -> dict:
    """Export -> load -> verify. Raises on any mismatch."""
    from observal_cli.cmd_migrate import DuckDBVerificationError, run_duckdb_migration
    from observal_shared.migration import DuckDBConnParams, MigrationError

    export_dir.mkdir(parents=True, exist_ok=True)
    try:
        return run_duckdb_migration(
            clickhouse_url=clickhouse_url,
            duckdb=DuckDBConnParams(url=duckdb_url, token=token),
            export_dir=export_dir,
            reporter=reporter,
        )
    except DuckDBVerificationError as error:
        raise CutoverError(
            f"telemetry verification failed: {error.summary}",
            remediation="ClickHouse was not modified. Fix the reported table, then re-run `observal server upgrade`.",
        ) from error
    except MigrationError as error:
        raise CutoverError(f"telemetry migration failed: {type(error).__name__}: {error}") from error


def verify_post_deploy(health_url: str, duckdb_url: str, token: str, expected: dict[str, int]) -> None:
    """After the new API is up: /health must report analytics ok and counts must hold."""
    try:
        health = httpx.get(health_url.replace("/readyz", "/health"), timeout=10).json()
    except (httpx.HTTPError, ValueError) as error:
        raise CutoverError(f"could not read /health after deploy: {error}") from error
    if health.get("analytics") != "ok":
        raise CutoverError(f"/health reports analytics={health.get('analytics')!r} after deploy")
    parsed = urlparse(duckdb_url.replace("duckdb://", "http://"))
    base = f"http://{parsed.hostname}:{parsed.port or 8484}"
    for table, minimum in expected.items():
        resp = httpx.post(
            f"{base}/query",
            json={"sql": f"SELECT count(*) AS n FROM {table}"},
            headers={"Authorization": f"Bearer {token}"},
            timeout=60,
        )
        if resp.status_code != 200:
            raise CutoverError(f"post-deploy count of {table} failed: HTTP {resp.status_code}")
        actual = int((resp.json().get("data") or [{}])[0].get("n") or 0)
        if actual < minimum:
            raise CutoverError(f"post-deploy {table} holds {actual} rows, expected at least {minimum}")


def retire_clickhouse(state: LegacyState, result: CutoverResult, log: Callable[[str], None]) -> None:
    """Stop the ClickHouse container (volume kept) and record completion."""
    # Once the token is provisioned a re-detected state no longer looks legacy,
    # so the container recorded at the start of the cutover is authoritative.
    container = result.clickhouse_container or state.clickhouse_container
    if container:
        result.clickhouse_container = container
        stopped = _docker("stop", container, timeout=180)
        result.clickhouse_stopped = stopped.returncode == 0
        if result.clickhouse_stopped:
            log(f"Stopped {container}; its volume is preserved for rollback")
        else:
            log(f"[yellow]Could not stop {container}: {stopped.stderr.strip()[:120]}[/yellow]")
    result.completed_at = datetime.now(UTC).isoformat()
    state.marker_path.write_text(json.dumps(asdict(result), indent=2, default=str) + "\n", encoding="utf-8")
    state.marker_path.chmod(0o600)


def restore_legacy_compose(state: LegacyState) -> bool:
    """Reinstate the ClickHouse compose file saved by ``install_release_files``.

    Source checkouts have no saved copy (the operator pulled the new file); in
    that case nothing is changed and ``False`` is returned.
    """
    backup = state.compose_dir / LEGACY_COMPOSE_BACKUP
    if not backup.is_file():
        return False
    failed_new = state.compose_dir / "docker-compose.duckdb.failed.yml"
    if state.compose_path.exists():
        shutil.copy2(state.compose_path, failed_new)
    shutil.copy2(backup, state.compose_path)
    return True


def cutover_marker(compose_dir: Path) -> dict | None:
    path = compose_dir / MARKER_NAME
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return {"corrupt": True}


# ── orchestration entry point ────────────────────────────────────────────────


def run_cutover(
    state: LegacyState,
    *,
    current: str,
    target: str,
    repo: str,
    skip_backup: bool,
    log: Callable[[str], None],
    reporter,
) -> tuple[CutoverResult, str, str]:
    """Run every pre-deploy cutover step. Returns (result, duckdb_url, token).

    The caller deploys the new release afterwards and then calls
    ``verify_post_deploy`` and ``retire_clickhouse``.
    """
    from observal_cli.server.backup import create_backup

    result = CutoverResult(
        started_at=datetime.now(UTC).isoformat(),
        from_version=current,
        to_version=target,
        flavor=state.flavor,
        clickhouse_container=state.clickhouse_container,
    )
    optic.info("clickhouse cutover start flavor={} compose_dir={}", state.flavor, state.compose_dir)

    clickhouse_url = ensure_clickhouse_running(state, log)
    result.legacy_writer_containers = quiesce_legacy_writers(state, log)

    try:
        if not skip_backup:
            log("Backing up PostgreSQL")
            try:
                result.backup = str(create_backup(state.compose_dir, current, include_analytics=False))
            except RuntimeError as error:
                raise CutoverError(f"pre-cutover backup failed: {error}") from error

        backup_compose = install_release_files(state, target, repo, log)
        result.legacy_compose_backup = str(backup_compose) if backup_compose else None

        provision_duckdb_secrets(state, log)
        duckdb_url, token = start_duckdb_service(state, target, log)

        export_dir = state.compose_dir / "telemetry-export" / datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        result.export_dir = str(export_dir)
        log("Copying telemetry from ClickHouse into DuckDB")
        payload = migrate_telemetry(clickhouse_url, duckdb_url, token, export_dir, reporter)
        result.row_counts = {t: c["duckdb_rows"] for t, c in payload["verification"]["row_counts"].items()}
        result.total_rows = payload["load"]["total_rows"]
        log(f"Verified {result.total_rows:,} rows across {payload['load']['tables_imported']} tables")
        return result, duckdb_url, token
    except BaseException:
        try:
            restore_legacy_compose(state)
        except OSError as error:
            log(f"[yellow]Could not restore the legacy compose file: {error}[/yellow]")
        restart_legacy_writers(result.legacy_writer_containers, log)
        raise


# ── embedded mode (observal server start) ────────────────────────────────────
#
# The pre-DuckDB embedded stack ran a ClickHouse binary from ~/.observal/bin on
# HTTP port 8124 with data under ~/.observal/data/clickhouse. The DuckDB
# analytics service now owns port 8124, and the new CLI's ``server stop`` no
# longer knows the old clickhouse.pid, so an orphaned ClickHouse would block
# DuckDB from starting. The embedded cutover therefore: kills the orphan,
# relaunches ClickHouse on a temporary port against its existing data
# directory, migrates into the already-running DuckDB service, stops it again,
# and writes a marker so it is never started again.

EMBEDDED_MARKER_NAME = ".clickhouse-cutover-complete.json"
EMBEDDED_LEGACY_HTTP_PORT = 8124
EMBEDDED_CUTOVER_HTTP_PORT = 18124
EMBEDDED_CUTOVER_TCP_PORT = 19100


@dataclass
class EmbeddedLegacy:
    binary: Path
    data_dir: Path
    marker_path: Path
    pid_file: Path
    log_dir: Path
    config_dir: Path

    @property
    def present(self) -> bool:
        return self.binary.is_file() and self.data_dir.is_dir() and not self.marker_path.exists()


def detect_embedded_legacy() -> EmbeddedLegacy:
    from observal_cli.server.constants import BIN_DIR, CONFIG_DIR, DATA_DIR, LOG_DIR, RUN_DIR

    return EmbeddedLegacy(
        binary=BIN_DIR / "clickhouse",
        data_dir=DATA_DIR / "clickhouse",
        marker_path=DATA_DIR / EMBEDDED_MARKER_NAME,
        pid_file=RUN_DIR / "clickhouse.pid",
        log_dir=LOG_DIR,
        config_dir=CONFIG_DIR,
    )


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def stop_orphan_embedded_clickhouse(legacy: EmbeddedLegacy, log: Callable[[str], None]) -> bool:
    """Terminate a ClickHouse left running by the previous CLI. Returns True if one was stopped."""
    import signal

    if not legacy.pid_file.exists():
        return False
    try:
        pid = int(legacy.pid_file.read_text().strip())
    except ValueError:
        legacy.pid_file.unlink(missing_ok=True)
        return False
    if not _pid_alive(pid):
        legacy.pid_file.unlink(missing_ok=True)
        return False
    log(f"Stopping legacy ClickHouse process {pid} so the analytics service can bind its port")
    os.kill(pid, signal.SIGTERM)
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline and _pid_alive(pid):
        time.sleep(0.5)
    if _pid_alive(pid):
        os.kill(pid, signal.SIGKILL)
        time.sleep(1)
    legacy.pid_file.unlink(missing_ok=True)
    return True


def _embedded_cutover_config(legacy: EmbeddedLegacy) -> Path:
    data = legacy.data_dir
    conf = legacy.config_dir / "clickhouse-cutover.xml"
    conf.parent.mkdir(parents=True, exist_ok=True)
    conf.write_text(
        f"""<?xml version="1.0"?>
<clickhouse>
    <logger>
        <level>warning</level>
        <log>{legacy.log_dir / "clickhouse-cutover.log"}</log>
        <errorlog>{legacy.log_dir / "clickhouse-cutover-error.log"}</errorlog>
    </logger>
    <http_port>{EMBEDDED_CUTOVER_HTTP_PORT}</http_port>
    <tcp_port>{EMBEDDED_CUTOVER_TCP_PORT}</tcp_port>
    <listen_host>127.0.0.1</listen_host>
    <path>{data}/</path>
    <tmp_path>{data}/tmp/</tmp_path>
    <user_files_path>{data}/user_files/</user_files_path>
    <format_schema_path>{data}/format_schemas/</format_schema_path>
    <max_server_memory_usage_ratio>0.5</max_server_memory_usage_ratio>
    <users>
        <default>
            <password></password>
            <networks><ip>127.0.0.1</ip></networks>
            <profile>default</profile>
            <quota>default</quota>
        </default>
    </users>
    <profiles><default></default></profiles>
    <quotas><default></default></quotas>
</clickhouse>
""",
        encoding="utf-8",
    )
    return conf


def run_embedded_cutover(
    legacy: EmbeddedLegacy,
    *,
    duckdb_url: str,
    token: str,
    log: Callable[[str], None],
    reporter,
) -> CutoverResult:
    """Migrate an embedded ClickHouse data directory into the running DuckDB service."""
    result = CutoverResult(started_at=datetime.now(UTC).isoformat(), flavor="embedded")
    for subdir in ("tmp", "user_files", "format_schemas"):
        (legacy.data_dir / subdir).mkdir(parents=True, exist_ok=True)
    config = _embedded_cutover_config(legacy)
    legacy.log_dir.mkdir(parents=True, exist_ok=True)
    log_handle = (legacy.log_dir / "clickhouse-cutover-startup.log").open("w")
    proc = subprocess.Popen(
        [str(legacy.binary), "server", "--config-file", str(config)],
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    try:
        ping = f"http://127.0.0.1:{EMBEDDED_CUTOVER_HTTP_PORT}/ping"
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                raise CutoverError(
                    f"legacy ClickHouse exited immediately (see {legacy.log_dir / 'clickhouse-cutover-startup.log'})"
                )
            try:
                if httpx.get(ping, timeout=2).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(1)
        else:
            raise CutoverError("legacy ClickHouse did not become ready within 60s")

        clickhouse_url = f"clickhouse://default@127.0.0.1:{EMBEDDED_CUTOVER_HTTP_PORT}/observal"
        export_dir = legacy.data_dir.parent / "telemetry-export" / datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        result.export_dir = str(export_dir)
        log("Copying embedded ClickHouse telemetry into DuckDB")
        payload = migrate_telemetry(clickhouse_url, duckdb_url, token, export_dir, reporter)
        result.row_counts = {t: c["duckdb_rows"] for t, c in payload["verification"]["row_counts"].items()}
        result.total_rows = payload["load"]["total_rows"]
        log(f"Verified {result.total_rows:,} rows across {payload['load']['tables_imported']} tables")
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=30)
            except subprocess.TimeoutExpired:
                proc.kill()
        log_handle.close()
        config.unlink(missing_ok=True)

    result.clickhouse_stopped = True
    result.completed_at = datetime.now(UTC).isoformat()
    legacy.marker_path.write_text(json.dumps(asdict(result), indent=2, default=str) + "\n", encoding="utf-8")
    legacy.marker_path.chmod(0o600)
    log(f"ClickHouse retired; data kept at {legacy.data_dir} until you delete it")
    return result
