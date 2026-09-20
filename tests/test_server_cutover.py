# SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Automatic ClickHouse -> DuckDB cutover driven by ``observal server upgrade``."""

from __future__ import annotations

import io
import json
import os
import subprocess
import tarfile
from types import SimpleNamespace
from typing import TYPE_CHECKING
from unittest.mock import ANY, MagicMock

import httpx
import pytest

if TYPE_CHECKING:
    from pathlib import Path

from observal_cli import cmd_server
from observal_cli.errors import CliError
from observal_cli.server import cutover

LEGACY_COMPOSE = "services:\n  observal-clickhouse:\n    image: clickhouse/clickhouse-server:26.6\n  observal-api: {}\n"
NEW_COMPOSE = "services:\n  observal-duckdb:\n    image: ghcr.io/observal/observal-duckdb:${OBSERVAL_VERSION}\n  observal-api: {}\n"


def _docker_stub(containers: list[str], *, running: bool = True, port: str = "127.0.0.1:8123"):
    """Return a subprocess.run replacement that answers the docker CLI calls the cutover makes."""

    def run(cmd, **_kwargs):
        if cmd[:3] == ["docker", "ps", "-a"]:
            return SimpleNamespace(returncode=0, stdout="\n".join(containers) + "\n", stderr="")
        if cmd[:2] == ["docker", "inspect"]:
            return SimpleNamespace(returncode=0, stdout="true\n" if running else "false\n", stderr="")
        if cmd[:2] == ["docker", "port"]:
            return SimpleNamespace(returncode=0, stdout=f"{port}\n", stderr="")
        if cmd[:2] in (["docker", "start"], ["docker", "stop"]):
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if cmd[:3] == ["docker", "compose", "up"]:
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        raise AssertionError(f"unexpected command {cmd}")

    return run


@pytest.fixture
def package_dir(tmp_path: Path) -> Path:
    compose_dir = tmp_path / "opt-observal"
    compose_dir.mkdir()
    (compose_dir / "docker-compose.yml").write_text(LEGACY_COMPOSE)
    (compose_dir / "setup.sh").write_text("#!/bin/sh\n")
    secrets = compose_dir / "secrets"
    (secrets / "clickhouse").mkdir(parents=True)
    (secrets / "clickhouse" / "clickhouse_password").write_text("ch-secret\n")
    (compose_dir / ".env").write_text("OBSERVAL_VERSION=1.13.1\nCLICKHOUSE_URL_FILE=/run/secrets/clickhouse_url\n")
    (secrets / "clickhouse_url").write_text("clickhouse://default:ch-secret@observal-clickhouse:8123/observal\n")
    return compose_dir


@pytest.fixture
def source_dir(tmp_path: Path) -> Path:
    root = tmp_path / "checkout"
    compose_dir = root / "docker"
    compose_dir.mkdir(parents=True)
    (compose_dir / "docker-compose.yml").write_text(NEW_COMPOSE)  # operator already pulled
    (root / ".env").write_text(
        "OBSERVAL_VERSION=1.13.1\nCLICKHOUSE_URL=clickhouse://default:clickhouse@observal-clickhouse:8123/observal\n"
    )
    return compose_dir


# ── detection ─────────────────────────────────────────────────────────────────


def test_detects_package_legacy_by_compose_labels(package_dir: Path, monkeypatch) -> None:
    seen: list[list[str]] = []
    stub = _docker_stub(["opt-observal-observal-clickhouse-1"])

    def run(cmd, **kwargs):
        seen.append(cmd)
        return stub(cmd, **kwargs)

    monkeypatch.setattr(cutover.subprocess, "run", run)
    state = cutover.detect_legacy_state(package_dir)
    assert any("label=com.docker.compose.project=opt-observal" in c for c in seen[0])
    assert any(f"label=com.docker.compose.service={cutover.CLICKHOUSE_SERVICE}" in c for c in seen[0])
    assert state.flavor == "package"
    assert state.compose_has_clickhouse and not state.compose_has_duckdb
    assert state.env_has_clickhouse and not state.env_has_duckdb
    assert state.clickhouse_container == "opt-observal-observal-clickhouse-1"
    assert state.needs_cutover is True


def test_detects_source_legacy_from_env_after_git_pull(source_dir: Path, monkeypatch) -> None:
    monkeypatch.setattr(cutover.subprocess, "run", _docker_stub(["docker-observal-clickhouse-1"]))
    state = cutover.detect_legacy_state(source_dir)
    assert state.flavor == "source"
    assert state.compose_has_duckdb and not state.compose_has_clickhouse
    assert state.env_has_clickhouse and not state.env_has_duckdb
    assert state.needs_cutover is True


def test_non_legacy_deployment_never_touches_docker(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "docker-compose.yml").write_text(NEW_COMPOSE)
    (tmp_path / ".env").write_text("OBSERVAL_VERSION=2.0.0\nDUCKDB_ANALYTICS_TOKEN=abc\n")
    boom = MagicMock(side_effect=AssertionError("docker must not be called"))
    monkeypatch.setattr(cutover.subprocess, "run", boom)
    state = cutover.detect_legacy_state(tmp_path)
    assert state.needs_cutover is False
    boom.assert_not_called()


def test_marker_short_circuits_and_no_container_means_no_cutover(package_dir: Path, monkeypatch) -> None:
    monkeypatch.setattr(cutover.subprocess, "run", _docker_stub([]))
    assert cutover.detect_legacy_state(package_dir).needs_cutover is False  # nothing to migrate from

    (package_dir / cutover.MARKER_NAME).write_text("{}")
    boom = MagicMock(side_effect=AssertionError("docker must not be called once the marker exists"))
    monkeypatch.setattr(cutover.subprocess, "run", boom)
    state = cutover.detect_legacy_state(package_dir)
    assert state.marker_exists and state.needs_cutover is False


# ── connection resolution ─────────────────────────────────────────────────────


def test_resolves_host_side_clickhouse_url_from_secret_file_and_published_port(package_dir: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        cutover.subprocess, "run", _docker_stub(["opt-observal-observal-clickhouse-1"], port="127.0.0.1:18123")
    )
    state = cutover.detect_legacy_state(package_dir)
    assert cutover.resolve_clickhouse_url(state) == "clickhouse://default:ch-secret@127.0.0.1:18123/observal"


def test_resolves_clickhouse_url_from_plain_env(source_dir: Path, monkeypatch) -> None:
    monkeypatch.setattr(cutover.subprocess, "run", _docker_stub(["docker-observal-clickhouse-1"]))
    state = cutover.detect_legacy_state(source_dir)
    assert cutover.resolve_clickhouse_url(state) == "clickhouse://default:clickhouse@127.0.0.1:8123/observal"


# ── provisioning ──────────────────────────────────────────────────────────────


def test_provision_package_secrets_is_idempotent_and_never_overwrites(package_dir: Path, monkeypatch) -> None:
    monkeypatch.setattr(cutover.subprocess, "run", _docker_stub(["x-observal-clickhouse-1"]))
    state = cutover.detect_legacy_state(package_dir)
    cutover.provision_duckdb_secrets(state, lambda _m: None)
    token_file = package_dir / "secrets" / "duckdb" / "duckdb_analytics_token"
    first = token_file.read_text()
    assert len(first.strip()) >= 32
    assert (token_file.stat().st_mode & 0o777) == 0o640
    assert token_file.stat().st_gid == os.getgid()
    assert ((package_dir / "secrets" / "duckdb_analytics_url").stat().st_mode & 0o777) == 0o640
    env = (package_dir / ".env").read_text()
    assert f"OBSERVAL_SECRET_GID={os.getgid()}" in env
    assert "DUCKDB_ANALYTICS_TOKEN_FILE=/run/secrets/duckdb/duckdb_analytics_token" in env
    assert "CLICKHOUSE_URL_FILE=/run/secrets/clickhouse_url" in env  # untouched
    assert env.count("OBSERVAL_VERSION=") == 1

    cutover.provision_duckdb_secrets(state, lambda _m: None)
    assert token_file.read_text() == first
    assert (package_dir / ".env").read_text() == env
    url, token = cutover.resolve_duckdb_params(cutover.detect_legacy_state(package_dir))
    assert url == "duckdb://127.0.0.1:8484/observal" and token == first.strip()


def test_provision_source_env_appends_token(source_dir: Path, monkeypatch) -> None:
    monkeypatch.setattr(cutover.subprocess, "run", _docker_stub(["docker-observal-clickhouse-1"]))
    state = cutover.detect_legacy_state(source_dir)
    cutover.provision_duckdb_secrets(state, lambda _m: None)
    env = (source_dir.parent / ".env").read_text()
    assert "DUCKDB_ANALYTICS_URL=duckdb://observal-duckdb:8484/observal" in env
    assert "DUCKDB_ANALYTICS_TOKEN=" in env and "CLICKHOUSE_URL=" in env
    retry = cutover.detect_legacy_state(source_dir)
    assert retry.env_has_duckdb is True
    assert retry.needs_cutover is True  # no completion marker: a partial attempt must remain retryable


def test_quiesce_stops_all_legacy_api_and_worker_containers(source_dir: Path, monkeypatch) -> None:
    calls: list[tuple[str, ...]] = []

    def docker(*args, **_kwargs):
        calls.append(args)
        if args[0] == "ps":
            filters = " ".join(args)
            if "observal-api" in filters:
                return SimpleNamespace(returncode=0, stdout="api-1\napi-2\n", stderr="")
            if "observal-worker" in filters:
                return SimpleNamespace(returncode=0, stdout="worker-1\n", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(cutover, "_docker", docker)
    state = cutover.LegacyState(
        compose_dir=source_dir,
        compose_path=source_dir / "docker-compose.yml",
        env_file=source_dir.parent / ".env",
        flavor="source",
        compose_has_clickhouse=False,
        compose_has_duckdb=True,
        env_has_clickhouse=True,
        env_has_duckdb=False,
        marker_path=source_dir / cutover.MARKER_NAME,
        marker_exists=False,
        clickhouse_container="clickhouse-1",
    )

    assert cutover.quiesce_legacy_writers(state, lambda _message: None) == ["api-1", "api-2", "worker-1"]
    assert [call for call in calls if call[0] == "stop"] == [
        ("stop", "api-1"),
        ("stop", "api-2"),
        ("stop", "worker-1"),
    ]


def test_run_cutover_recovers_api_when_worker_stop_times_out(source_dir: Path, monkeypatch) -> None:
    state = cutover.LegacyState(
        compose_dir=source_dir,
        compose_path=source_dir / "docker-compose.yml",
        env_file=source_dir.parent / ".env",
        flavor="source",
        compose_has_clickhouse=False,
        compose_has_duckdb=True,
        env_has_clickhouse=True,
        env_has_duckdb=False,
        marker_path=source_dir / cutover.MARKER_NAME,
        marker_exists=False,
        clickhouse_container="clickhouse-1",
    )
    starts: list[str] = []

    def docker(*args, **_kwargs):
        if args[0] == "ps":
            service_filter = " ".join(args)
            name = "api-1" if "observal-api" in service_filter else "worker-1"
            return SimpleNamespace(returncode=0, stdout=f"{name}\n", stderr="")
        if args[:2] == ("stop", "api-1"):
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if args[:2] == ("stop", "worker-1"):
            raise subprocess.TimeoutExpired(["docker", "stop", "worker-1"], 180)
        if args[0] == "start":
            starts.append(args[1])
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        raise AssertionError(args)

    monkeypatch.setattr(cutover, "_docker", docker)
    monkeypatch.setattr(cutover, "ensure_clickhouse_running", lambda *_args: "clickhouse://source")

    with pytest.raises(subprocess.TimeoutExpired):
        cutover.run_cutover(
            state,
            current="1.13.1",
            target="2.0.0",
            repo="Observal/Observal",
            skip_backup=True,
            log=lambda _message: None,
            reporter=object(),
        )

    assert starts == ["api-1", "worker-1"]


# ── release files ─────────────────────────────────────────────────────────────


def _bundle(version: str, *, with_compose: bool = True) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        files = {"nginx.conf": "server {}\n"}
        if with_compose:
            files["docker-compose.yml"] = NEW_COMPOSE
        for name, body in files.items():
            info = tarfile.TarInfo(f"observal-server-v{version}/{name}")
            data = body.encode()
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def test_install_release_files_swaps_compose_and_keeps_legacy_copy(package_dir: Path, monkeypatch) -> None:
    monkeypatch.setattr(cutover.subprocess, "run", _docker_stub(["x-observal-clickhouse-1"]))
    state = cutover.detect_legacy_state(package_dir)
    monkeypatch.setattr(
        cutover.httpx, "get", MagicMock(return_value=SimpleNamespace(status_code=200, content=_bundle("2.0.0")))
    )
    backup = cutover.install_release_files(state, "2.0.0", "Observal/Observal", lambda _m: None)
    assert backup == package_dir / cutover.LEGACY_COMPOSE_BACKUP
    assert backup.read_text() == LEGACY_COMPOSE
    assert (package_dir / "docker-compose.yml").read_text() == NEW_COMPOSE
    assert (package_dir / "nginx.conf").read_text() == "server {}\n"
    assert cutover.restore_legacy_compose(state) is True
    assert (package_dir / "docker-compose.yml").read_text() == LEGACY_COMPOSE


@pytest.mark.parametrize(
    ("target", "compatible"),
    [("1.13.1", False), ("1.99.0", False), ("2.0.0rc1", False), ("2.0.0", True), ("2.1.0", True), ("10.0.0", True)],
)
@pytest.mark.parametrize("flavor", ["package", "source"])
def test_completed_cutover_pins_release_and_topology(
    package_dir: Path, target: str, compatible: bool, flavor: str
) -> None:
    backup = package_dir / cutover.LEGACY_COMPOSE_BACKUP
    backup.write_text(LEGACY_COMPOSE)
    active = package_dir / "docker-compose.yml"
    active.write_text(NEW_COMPOSE)
    marker = package_dir / cutover.MARKER_NAME
    marker.write_text(json.dumps({"from_version": "1.13.1", "to_version": "2.0.0", "flavor": flavor}))
    marker_before = marker.read_bytes()

    if compatible:
        cutover.validate_duckdb_target(package_dir, target)
    else:
        with pytest.raises(cutover.CutoverError, match="requires DuckDB-compatible releases"):
            cutover.validate_duckdb_target(package_dir, target)

    assert active.read_text() == NEW_COMPOSE
    assert backup.read_text() == LEGACY_COMPOSE
    assert marker.read_bytes() == marker_before
    assert not (package_dir / "docker-compose.duckdb.rollback.yml").exists()


@pytest.mark.parametrize("contents", ["{", "[]", "null", "{}", '{"to_version":"broken"}', '{"to_version":2}'])
def test_cutover_guard_fails_closed_on_invalid_marker(package_dir: Path, contents: str) -> None:
    marker = package_dir / cutover.MARKER_NAME
    marker.write_text(contents)
    with pytest.raises(cutover.CutoverError, match="no valid DuckDB release boundary"):
        cutover.validate_duckdb_target(package_dir, "2.0.0")
    assert marker.read_text() == contents


@pytest.mark.parametrize(
    "topology",
    [LEGACY_COMPOSE, "services: {}", "services: []", "services: [", "[]", NEW_COMPOSE + "  observal-clickhouse: {}\n"],
)
def test_cutover_guard_rejects_missing_duckdb_or_reintroduced_clickhouse(package_dir: Path, topology: str) -> None:
    (package_dir / cutover.MARKER_NAME).write_text(json.dumps({"to_version": "2.0.0"}))
    active = package_dir / "docker-compose.yml"
    active.write_text(topology)
    with pytest.raises(cutover.CutoverError, match="compose topology"):
        cutover.validate_duckdb_target(package_dir, "2.1.0")
    assert active.read_text() == topology


def test_cutover_guard_does_not_block_pre_cutover_recovery(package_dir: Path) -> None:
    cutover.validate_duckdb_target(package_dir, "1.13.1")
    assert (package_dir / "docker-compose.yml").read_text() == LEGACY_COMPOSE


def test_install_release_files_rejects_bundle_without_compose(package_dir: Path, monkeypatch) -> None:
    monkeypatch.setattr(cutover.subprocess, "run", _docker_stub(["x-observal-clickhouse-1"]))
    state = cutover.detect_legacy_state(package_dir)
    monkeypatch.setattr(
        cutover.httpx,
        "get",
        MagicMock(return_value=SimpleNamespace(status_code=200, content=_bundle("2.0.0", with_compose=False))),
    )
    with pytest.raises(cutover.CutoverError, match=r"did not contain docker-compose\.yml"):
        cutover.install_release_files(state, "2.0.0", "Observal/Observal", lambda _m: None)
    assert (package_dir / "docker-compose.yml").read_text() == LEGACY_COMPOSE


def test_source_checkout_still_on_clickhouse_compose_is_told_to_pull(tmp_path: Path, monkeypatch) -> None:
    compose_dir = tmp_path / "docker"
    compose_dir.mkdir()
    (compose_dir / "docker-compose.yml").write_text(LEGACY_COMPOSE)
    (tmp_path / ".env").write_text("CLICKHOUSE_URL=clickhouse://x@observal-clickhouse:8123/observal\n")
    monkeypatch.setattr(cutover.subprocess, "run", _docker_stub(["docker-observal-clickhouse-1"]))
    state = cutover.detect_legacy_state(compose_dir)
    with pytest.raises(cutover.CutoverError) as excinfo:
        cutover.install_release_files(state, "2.0.0", "Observal/Observal", lambda _m: None)
    assert "git pull" in excinfo.value.remediation


# ── verification and retirement ───────────────────────────────────────────────


def test_verify_post_deploy_requires_analytics_ok_and_counts(monkeypatch) -> None:
    monkeypatch.setattr(
        cutover.httpx, "get", MagicMock(return_value=SimpleNamespace(json=lambda: {"analytics": "unreachable"}))
    )
    with pytest.raises(cutover.CutoverError, match="analytics='unreachable'"):
        cutover.verify_post_deploy("http://localhost/readyz", "duckdb://127.0.0.1:8484/observal", "t", {})

    monkeypatch.setattr(cutover.httpx, "get", MagicMock(return_value=SimpleNamespace(json=lambda: {"analytics": "ok"})))
    monkeypatch.setattr(
        cutover.httpx,
        "post",
        MagicMock(return_value=SimpleNamespace(status_code=200, json=lambda: {"data": [{"n": 5}]})),
    )
    with pytest.raises(cutover.CutoverError, match="session_events holds 5 rows, expected at least 10"):
        cutover.verify_post_deploy(
            "http://localhost/readyz", "duckdb://127.0.0.1:8484/observal", "t", {"session_events": 10}
        )
    cutover.verify_post_deploy(
        "http://localhost/readyz", "duckdb://127.0.0.1:8484/observal", "t", {"session_events": 5}
    )


def test_retire_clickhouse_stops_container_and_writes_marker(package_dir: Path, monkeypatch) -> None:
    calls: list[list[str]] = []
    stub = _docker_stub(["opt-observal-observal-clickhouse-1"])

    def run(cmd, **kwargs):
        calls.append(cmd)
        return stub(cmd, **kwargs)

    monkeypatch.setattr(cutover.subprocess, "run", run)
    state = cutover.detect_legacy_state(package_dir)
    result = cutover.CutoverResult(started_at="t0", from_version="1.13.1", to_version="2.0.0", total_rows=42)
    cutover.retire_clickhouse(state, result, lambda _m: None)
    assert ["docker", "stop", "opt-observal-observal-clickhouse-1"] in calls
    marker = json.loads((package_dir / cutover.MARKER_NAME).read_text())
    assert marker["total_rows"] == 42 and marker["clickhouse_stopped"] is True and marker["completed_at"]
    assert cutover.detect_legacy_state(package_dir).needs_cutover is False


# ── orchestration through observal server upgrade ─────────────────────────────


@pytest.fixture
def upgrade_env(package_dir: Path, monkeypatch):
    from observal_cli import upgrade_lock, version_check

    monkeypatch.setattr(cmd_server, "_require_compose_dir", lambda: package_dir)
    monkeypatch.setattr(version_check, "verify_server_image_exists", MagicMock(return_value=True))
    monkeypatch.setattr(version_check, "_github_repo", lambda: "Observal/Observal")
    monkeypatch.setattr(upgrade_lock, "acquire_lock", MagicMock(return_value="lock"))
    monkeypatch.setattr(upgrade_lock, "release_lock", MagicMock())
    monkeypatch.setattr("time.sleep", MagicMock())
    return package_dir


def test_upgrade_runs_cutover_then_deploys_verifies_and_retires_clickhouse(upgrade_env: Path, monkeypatch) -> None:
    compose_dir = upgrade_env
    events: list[str] = []
    stub = _docker_stub(["opt-observal-observal-clickhouse-1"])

    def run(cmd, **kwargs):
        events.append(" ".join(cmd))
        return (
            stub(cmd, **kwargs)
            if (cmd[0] == "docker" and cmd[1] != "compose") or cmd[:3] == ["docker", "compose", "up"]
            else SimpleNamespace(returncode=0, stdout="", stderr="")
        )

    monkeypatch.setattr(cutover.subprocess, "run", run)
    monkeypatch.setattr(cmd_server.subprocess, "run", run)

    def fake_run_cutover(state, **kwargs):
        events.append("cutover")
        assert state.clickhouse_container == "opt-observal-observal-clickhouse-1"
        assert kwargs["current"] == "1.13.1" and kwargs["target"] == "2.0.0"
        # simulate the compose swap the real step performs
        (compose_dir / cutover.LEGACY_COMPOSE_BACKUP).write_text(LEGACY_COMPOSE)
        (compose_dir / "docker-compose.yml").write_text(NEW_COMPOSE)
        result = cutover.CutoverResult(started_at="t0", from_version="1.13.1", to_version="2.0.0")
        result.row_counts = {"session_events": 79534}
        result.total_rows = 79534
        result.backup = str(compose_dir / "backup")
        return result, "duckdb://127.0.0.1:8484/observal", "tok"

    monkeypatch.setattr(cutover, "run_cutover", fake_run_cutover)
    verify = MagicMock(side_effect=lambda *a, **k: events.append("verify"))
    monkeypatch.setattr(cutover, "verify_post_deploy", verify)
    monkeypatch.setattr(httpx, "get", MagicMock(return_value=SimpleNamespace(status_code=200)))

    result = cmd_server._server_upgrade("2.0.0", False, False, True)

    assert result["status"] == "upgraded"
    assert result["clickhouse_cutover"]["total_rows"] == 79534
    assert result["clickhouse_cutover"]["clickhouse_stopped"] is True
    assert events.index("cutover") < events.index("docker compose pull") < events.index("verify")
    assert events.index("verify") < events.index("docker stop opt-observal-observal-clickhouse-1")
    verify.assert_called_once()
    assert verify.call_args.args[3] == {"session_events": 79534}
    assert (compose_dir / cutover.MARKER_NAME).exists()
    assert "OBSERVAL_VERSION=2.0.0" in (compose_dir / ".env").read_text()


def test_run_cutover_failure_restores_compose_and_restarts_quiesced_writers(package_dir: Path, monkeypatch) -> None:
    monkeypatch.setattr(cutover.subprocess, "run", _docker_stub(["opt-observal-observal-clickhouse-1"]))
    state = cutover.detect_legacy_state(package_dir)
    writers = ["api-1", "worker-1"]
    monkeypatch.setattr(cutover, "ensure_clickhouse_running", lambda *_args: "clickhouse://source")
    monkeypatch.setattr(cutover, "quiesce_legacy_writers", lambda *_args: writers)

    def install(*_args):
        backup = package_dir / cutover.LEGACY_COMPOSE_BACKUP
        backup.write_text(LEGACY_COMPOSE)
        (package_dir / "docker-compose.yml").write_text(NEW_COMPOSE)
        return backup

    monkeypatch.setattr(cutover, "install_release_files", install)
    monkeypatch.setattr(cutover, "provision_duckdb_secrets", lambda *_args: None)
    monkeypatch.setattr(cutover, "start_duckdb_service", lambda *_args: ("duckdb://target", "token"))
    monkeypatch.setattr(
        cutover, "migrate_telemetry", MagicMock(side_effect=cutover.CutoverError("injected migration failure"))
    )
    restart = MagicMock()
    monkeypatch.setattr(cutover, "restart_legacy_writers", restart)

    with pytest.raises(cutover.CutoverError, match="injected migration failure"):
        cutover.run_cutover(
            state,
            current="1.13.1",
            target="2.0.0",
            repo="Observal/Observal",
            skip_backup=True,
            log=lambda _message: None,
            reporter=object(),
        )

    assert (package_dir / "docker-compose.yml").read_text() == LEGACY_COMPOSE
    restart.assert_called_once_with(writers, ANY)


def test_pull_failure_after_cutover_restores_compose_and_restarts_writers(upgrade_env: Path, monkeypatch) -> None:
    compose_dir = upgrade_env

    def run(cmd, **_kwargs):
        if cmd[:3] == ["docker", "ps", "-a"]:
            return SimpleNamespace(
                returncode=0,
                stdout="opt-observal-observal-clickhouse-1\n",
                stderr="",
            )
        if cmd[:3] == ["docker", "compose", "pull"]:
            return SimpleNamespace(returncode=1, stdout="", stderr="pull failed")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(cutover.subprocess, "run", run)

    def successful_cutover(state, **_kwargs):
        (compose_dir / "docker-compose.yml").write_text(NEW_COMPOSE)
        result = cutover.CutoverResult(started_at="t0", legacy_writer_containers=["api-1", "worker-1"])
        return result, "duckdb://127.0.0.1:8484/observal", "token"

    monkeypatch.setattr(cutover, "run_cutover", successful_cutover)
    restore = MagicMock(return_value=True)
    restart = MagicMock()
    monkeypatch.setattr(cutover, "restore_legacy_compose", restore)
    monkeypatch.setattr(cutover, "restart_legacy_writers", restart)

    with pytest.raises(CliError):
        cmd_server._server_upgrade("2.0.0", False, False, True)

    restore.assert_called_once()
    restart.assert_called_once_with(["api-1", "worker-1"], ANY)


def test_upgrade_cutover_failure_leaves_legacy_stack_untouched(upgrade_env: Path, monkeypatch) -> None:
    compose_dir = upgrade_env
    stub = _docker_stub(["opt-observal-observal-clickhouse-1"])
    pulled = MagicMock()

    def run(cmd, **kwargs):
        if cmd[:3] == ["docker", "compose", "pull"]:
            pulled(cmd)
        return stub(cmd, **kwargs)

    monkeypatch.setattr(cutover.subprocess, "run", run)

    def failing(state, **_kwargs):
        raise cutover.CutoverError("telemetry verification failed: session_events: expected 10, found 9")

    monkeypatch.setattr(cutover, "run_cutover", failing)

    with pytest.raises(CliError):
        cmd_server._server_upgrade("2.0.0", False, False, True)

    assert (compose_dir / "docker-compose.yml").read_text() == LEGACY_COMPOSE
    assert "OBSERVAL_VERSION=1.13.1" in (compose_dir / ".env").read_text()
    assert not (compose_dir / cutover.MARKER_NAME).exists()
    pulled.assert_not_called()


def test_upgrade_health_failure_after_cutover_restores_legacy_compose(upgrade_env: Path, monkeypatch) -> None:
    compose_dir = upgrade_env
    stub = _docker_stub(["opt-observal-observal-clickhouse-1"])

    def run(cmd, **kwargs):
        if cmd[:2] == ["docker", "compose"]:
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        return stub(cmd, **kwargs)

    monkeypatch.setattr(cutover.subprocess, "run", run)

    def fake_run_cutover(state, **_kwargs):
        (compose_dir / cutover.LEGACY_COMPOSE_BACKUP).write_text(LEGACY_COMPOSE)
        (compose_dir / "docker-compose.yml").write_text(NEW_COMPOSE)
        return cutover.CutoverResult(started_at="t0"), "duckdb://127.0.0.1:8484/observal", "tok"

    monkeypatch.setattr(cutover, "run_cutover", fake_run_cutover)
    monkeypatch.setattr(httpx, "get", MagicMock(side_effect=httpx.ConnectError("down")))
    retire = MagicMock(side_effect=AssertionError("ClickHouse must not be retired when the new API is unhealthy"))
    monkeypatch.setattr(cutover, "retire_clickhouse", retire)

    with pytest.raises(CliError):
        cmd_server._server_upgrade("2.0.0", False, False, True)

    assert (compose_dir / "docker-compose.yml").read_text() == LEGACY_COMPOSE
    assert "OBSERVAL_VERSION=1.13.1" in (compose_dir / ".env").read_text()
    assert not (compose_dir / cutover.MARKER_NAME).exists()


def test_legacy_compose_without_container_refuses(upgrade_env: Path, monkeypatch) -> None:
    monkeypatch.setattr(cutover.subprocess, "run", _docker_stub([]))
    with pytest.raises(CliError):
        cmd_server._server_upgrade("2.0.0", False, False, True)


def test_dry_run_reports_planned_cutover(upgrade_env: Path, monkeypatch) -> None:
    monkeypatch.setattr(cutover.subprocess, "run", _docker_stub(["opt-observal-observal-clickhouse-1"]))
    result = cmd_server._server_upgrade("2.0.0", False, True, True)
    assert result["status"] == "planned" and result["clickhouse_cutover"] is True


# ── embedded mode ─────────────────────────────────────────────────────────────


def test_embedded_detection_and_orphan_stop(tmp_path: Path, monkeypatch) -> None:
    from observal_cli.server import constants

    root = tmp_path / ".observal"
    for name in ("BIN_DIR", "DATA_DIR", "CONFIG_DIR", "LOG_DIR", "RUN_DIR"):
        monkeypatch.setattr(constants, name, root / name.lower())
    legacy = cutover.detect_embedded_legacy()
    assert legacy.present is False

    legacy.binary.parent.mkdir(parents=True)
    legacy.binary.write_text("")
    legacy.data_dir.mkdir(parents=True)
    assert cutover.detect_embedded_legacy().present is True

    legacy.marker_path.write_text("{}")
    assert cutover.detect_embedded_legacy().present is False

    legacy.pid_file.parent.mkdir(parents=True)
    legacy.pid_file.write_text("999999")
    monkeypatch.setattr(cutover, "_pid_alive", lambda _pid: False)
    assert cutover.stop_orphan_embedded_clickhouse(legacy, lambda _m: None) is False
    assert not legacy.pid_file.exists()

    legacy.pid_file.write_text("4242")
    killed: list[tuple[int, int]] = []
    monkeypatch.setattr(cutover, "_pid_alive", lambda _pid: len(killed) == 0)
    monkeypatch.setattr(cutover.os, "kill", lambda pid, sig: killed.append((pid, sig)))
    assert cutover.stop_orphan_embedded_clickhouse(legacy, lambda _m: None) is True
    assert killed and killed[0][0] == 4242
    assert not legacy.pid_file.exists()


def test_embedded_data_without_binary_is_flagged(tmp_path: Path, monkeypatch) -> None:
    """ClickHouse data with no binary left must be reported, not skipped silently."""
    from observal_cli.server import constants

    root = tmp_path / ".observal"
    for name in ("BIN_DIR", "DATA_DIR", "CONFIG_DIR", "LOG_DIR", "RUN_DIR"):
        monkeypatch.setattr(constants, name, root / name.lower())

    legacy = cutover.detect_embedded_legacy()
    legacy.data_dir.mkdir(parents=True)
    legacy.binary.parent.mkdir(parents=True, exist_ok=True)

    detected = cutover.detect_embedded_legacy()
    assert detected.present is False
    assert detected.data_without_binary is True

    legacy.binary.write_text("")
    assert cutover.detect_embedded_legacy().data_without_binary is False


def test_compose_project_name_prefers_env_then_directory(tmp_path, monkeypatch) -> None:
    compose_dir = tmp_path / "My Deploy"
    compose_dir.mkdir()
    monkeypatch.delenv("COMPOSE_PROJECT_NAME", raising=False)
    assert cutover.compose_project_name(compose_dir) == "mydeploy"
    (compose_dir / ".env").write_text("COMPOSE_PROJECT_NAME=legacy\n")
    assert cutover.compose_project_name(compose_dir) == "legacy"
    monkeypatch.setenv("COMPOSE_PROJECT_NAME", "fromenv")
    assert cutover.compose_project_name(compose_dir) == "fromenv"
