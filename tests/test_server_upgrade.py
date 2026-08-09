# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Isolated command tests for embedded and Docker server management."""

from __future__ import annotations

import builtins
import runpy
import socket
import time
from contextlib import contextmanager
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, call

import httpx
import pytest
import typer
from rich.console import Console

from observal_cli import cmd_server


class RecordingConsole:
    """Render Rich output to a deterministic in-memory stream."""

    def __init__(self) -> None:
        self.stream = StringIO()
        self.renderer = Console(file=self.stream, color_system=None, force_terminal=False, width=240)
        self.status_messages: list[str] = []

    def print(self, *values: object, **kwargs: object) -> None:
        self.renderer.print(*values, **kwargs)

    @contextmanager
    def status(self, message: str):
        self.status_messages.append(message)
        yield

    def text(self) -> str:
        return self.stream.getvalue()


class SocketFactory:
    """Return sockets whose binds follow a supplied availability sequence."""

    def __init__(self, available: list[bool]) -> None:
        self.available = iter(available)
        self.binds: list[tuple[str, int]] = []

    def __call__(self, *args: object, **kwargs: object):
        factory = self

        class FakeSocket:
            def __enter__(self):
                return self

            def __exit__(self, *args: object) -> None:
                return None

            def bind(self, address: tuple[str, int]) -> None:
                factory.binds.append(address)
                try:
                    port_available = next(factory.available)
                except StopIteration as exc:
                    raise AssertionError(f"unexpected port probe: {address}") from exc
                if not port_available:
                    raise OSError("address in use")

        return FakeSocket()


def completed(returncode: int = 0, *, stderr: str = "") -> SimpleNamespace:
    return SimpleNamespace(returncode=returncode, stderr=stderr)


def blocked(name: str):
    def fail(*args: object, **kwargs: object):
        raise AssertionError(f"unmocked boundary: {name}, args={args}, kwargs={kwargs}")

    return fail


def block_server_constants(monkeypatch: pytest.MonkeyPatch) -> None:
    real_import = builtins.__import__

    def import_without_constants(
        name: str,
        globals: dict[str, object] | None = None,
        locals: dict[str, object] | None = None,
        fromlist: tuple[str, ...] = (),
        level: int = 0,
    ):
        if name == "observal_cli.server.constants":
            raise ImportError("simulated missing embedded constants")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", import_without_constants)


@pytest.fixture(autouse=True)
def isolated_boundaries(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Redirect user paths and block every external boundary by default."""
    from observal_cli import client, upgrade_lock, version_check
    from observal_cli.server import backup, deps, orchestrator, updater

    home = tmp_path / "user"
    root = home / ".observal"
    console = RecordingConsole()

    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setattr(cmd_server, "OBSERVAL_HOME", root)
    monkeypatch.setattr(cmd_server, "CONFIG_DIR", root / "config")
    monkeypatch.setattr(cmd_server, "LOG_DIR", root / "logs")
    monkeypatch.setattr(cmd_server, "console", console)

    monkeypatch.setattr(socket, "socket", blocked("socket.socket"))
    monkeypatch.setattr(time, "sleep", blocked("time.sleep"))
    monkeypatch.setattr(httpx, "get", blocked("httpx.get"))
    monkeypatch.setattr(typer, "confirm", blocked("typer.confirm"))
    monkeypatch.setattr(cmd_server.subprocess, "run", blocked("subprocess.run"))

    monkeypatch.setattr(client, "get", blocked("client.get"))
    monkeypatch.setattr(orchestrator, "Orchestrator", blocked("Orchestrator"))
    monkeypatch.setattr(deps, "all_installed", blocked("all_installed"))
    monkeypatch.setattr(deps, "install_dependencies", blocked("install_dependencies"))
    monkeypatch.setattr(updater, "check_for_update", blocked("check_for_update"))
    monkeypatch.setattr(version_check, "_fetch_from_github", blocked("fetch_from_github"))
    monkeypatch.setattr(version_check, "verify_server_image_exists", blocked("verify_server_image_exists"))
    monkeypatch.setattr(version_check, "fetch_available_server_images", blocked("fetch_available_server_images"))
    monkeypatch.setattr(backup, "create_backup", blocked("create_backup"))
    monkeypatch.setattr(backup, "list_backups", blocked("list_backups"))
    monkeypatch.setattr(backup, "restore_backup", blocked("restore_backup"))
    monkeypatch.setattr(upgrade_lock, "acquire_lock", blocked("acquire_lock"))
    monkeypatch.setattr(upgrade_lock, "release_lock", blocked("release_lock"))

    return SimpleNamespace(
        tmp=tmp_path,
        home=home,
        root=root,
        console=console,
        client=client,
        version_check=version_check,
        upgrade_lock=upgrade_lock,
        backup=backup,
        deps=deps,
        orchestrator=orchestrator,
        updater=updater,
    )


def patch_orchestrator(
    runtime: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
    *,
    running: bool = False,
    statuses: dict[str, str] | None = None,
) -> tuple[MagicMock, MagicMock]:
    orch = MagicMock()
    orch.is_running.return_value = running
    if statuses is not None:
        orch.status.return_value = statuses
    factory = MagicMock(return_value=orch)
    monkeypatch.setattr(runtime.orchestrator, "Orchestrator", factory)
    return factory, orch


def patch_start_dependencies(
    runtime: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
    *,
    ports: list[bool],
    installed: bool = True,
    running: bool = False,
) -> tuple[SocketFactory, MagicMock, MagicMock, MagicMock, MagicMock, MagicMock]:
    sockets = SocketFactory(ports)
    monkeypatch.setattr(socket, "socket", sockets)
    update = MagicMock()
    all_installed = MagicMock(return_value=installed)
    install_dependencies = MagicMock()
    monkeypatch.setattr(runtime.updater, "check_for_update", update)
    monkeypatch.setattr(runtime.deps, "all_installed", all_installed)
    monkeypatch.setattr(runtime.deps, "install_dependencies", install_dependencies)
    factory, orch = patch_orchestrator(runtime, monkeypatch, running=running)
    return sockets, update, all_installed, install_dependencies, factory, orch


class TestImportFallback:
    def test_module_loads_safe_defaults_without_embedded_constants(
        self, isolated_boundaries: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        block_server_constants(monkeypatch)

        namespace = runpy.run_path(str(cmd_server.__file__))

        assert namespace["API_PORT"] == 8000
        assert namespace["OBSERVAL_HOME"] == isolated_boundaries.home / ".observal"
        assert namespace["CONFIG_DIR"] == isolated_boundaries.home / ".observal/config"
        assert namespace["LOG_DIR"] == isolated_boundaries.home / ".observal/logs"


class TestAuthorization:
    def test_super_admin_is_allowed(
        self, isolated_boundaries: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        get = MagicMock(return_value={"role": "super_admin"})
        monkeypatch.setattr(isolated_boundaries.client, "get", get)

        cmd_server._require_super_admin()

        get.assert_called_once_with("/api/v1/auth/whoami")
        assert isolated_boundaries.console.text() == ""

    def test_missing_authentication_exits_with_login_guidance(
        self,
        isolated_boundaries: SimpleNamespace,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.setattr(isolated_boundaries.client, "get", MagicMock(side_effect=SystemExit(1)))

        with pytest.raises(typer.Exit) as error:
            cmd_server._require_super_admin()

        assert error.value.exit_code == 1
        output = capsys.readouterr().out
        assert "Authentication required" in output
        assert "observal auth login" in output

    def test_non_super_admin_exits_with_current_role(
        self,
        isolated_boundaries: SimpleNamespace,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.setattr(isolated_boundaries.client, "get", MagicMock(return_value={"role": "admin"}))

        with pytest.raises(typer.Exit) as error:
            cmd_server._require_super_admin()

        assert error.value.exit_code == 1
        output = capsys.readouterr().out
        assert "Permission denied" in output
        assert "Current role: admin" in output


class TestEmbeddedLifecycleCommands:
    def test_start_foreground_delegates_without_installing(
        self, isolated_boundaries: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sockets, update, installed, install, factory, orch = patch_start_dependencies(
            isolated_boundaries,
            monkeypatch,
            ports=[True],
        )

        cmd_server.start(port=9123, host="127.0.0.2", background=False)

        assert sockets.binds == [("127.0.0.1", 9123)]
        update.assert_called_once_with(quiet=True)
        installed.assert_called_once_with()
        install.assert_not_called()
        factory.assert_called_once_with(port=9123, host="127.0.0.2")
        orch.is_running.assert_called_once_with()
        orch.start_all.assert_called_once_with(foreground=True)

    def test_start_background_installs_missing_dependencies_and_checks_updates_twice(
        self, isolated_boundaries: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _, update, _, install, _, orch = patch_start_dependencies(
            isolated_boundaries,
            monkeypatch,
            ports=[True],
            installed=False,
        )

        cmd_server.start(port=9000, host="0.0.0.0", background=True)

        install.assert_called_once_with()
        assert update.call_args_list == [call(quiet=True), call(quiet=False)]
        orch.start_all.assert_called_once_with(foreground=False)
        assert "First run" in isolated_boundaries.console.text()

    def test_start_default_port_uses_first_available_fallback(
        self, isolated_boundaries: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sockets, _, _, _, factory, orch = patch_start_dependencies(
            isolated_boundaries,
            monkeypatch,
            ports=[False, False, True],
        )

        cmd_server.start(port=cmd_server.API_PORT, host="localhost", background=False)

        assert sockets.binds == [
            ("127.0.0.1", cmd_server.API_PORT),
            ("127.0.0.1", cmd_server.API_PORT + 1),
            ("127.0.0.1", cmd_server.API_PORT + 2),
        ]
        factory.assert_called_once_with(port=cmd_server.API_PORT + 2, host="localhost")
        orch.start_all.assert_called_once_with(foreground=True)
        assert f"using :{cmd_server.API_PORT + 2} instead" in isolated_boundaries.console.text()

    def test_start_exits_when_default_port_and_fallbacks_are_busy(
        self, isolated_boundaries: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sockets = SocketFactory([False] * 5)
        monkeypatch.setattr(socket, "socket", sockets)

        with pytest.raises(typer.Exit) as error:
            cmd_server.start(port=cmd_server.API_PORT, host="localhost", background=False)

        assert error.value.exit_code == 1
        assert [port for _, port in sockets.binds] == [
            cmd_server.API_PORT,
            cmd_server.API_PORT + 1,
            cmd_server.API_PORT + 2,
            cmd_server.API_PORT + 10,
            cmd_server.API_PORT + 100,
        ]
        output = isolated_boundaries.console.text()
        assert "fallbacks are all in use" in output
        assert "specify a different port" in output

    def test_start_exits_immediately_for_busy_explicit_port(
        self, isolated_boundaries: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sockets = SocketFactory([False])
        monkeypatch.setattr(socket, "socket", sockets)

        with pytest.raises(typer.Exit) as error:
            cmd_server.start(port=9321, host="localhost", background=False)

        assert error.value.exit_code == 1
        assert sockets.binds == [("127.0.0.1", 9321)]
        assert "Port 9321 is already in use" in isolated_boundaries.console.text()

    def test_start_refuses_an_already_running_embedded_server(
        self, isolated_boundaries: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _, _, _, _, _, orch = patch_start_dependencies(
            isolated_boundaries,
            monkeypatch,
            ports=[True],
            running=True,
        )

        with pytest.raises(typer.Exit) as error:
            cmd_server.start(port=9123, host="localhost", background=False)

        assert error.value.exit_code == 1
        orch.start_all.assert_not_called()
        output = isolated_boundaries.console.text()
        assert "already running" in output
        assert "server restart" in output

    def test_stop_delegates_to_orchestrator(
        self, isolated_boundaries: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        factory, orch = patch_orchestrator(isolated_boundaries, monkeypatch)

        cmd_server.stop()

        factory.assert_called_once_with()
        orch.stop_all.assert_called_once_with()

    @pytest.mark.parametrize("running", [False, True])
    def test_restart_stops_only_when_running(
        self,
        running: bool,
        isolated_boundaries: SimpleNamespace,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        factory, orch = patch_orchestrator(isolated_boundaries, monkeypatch, running=running)

        cmd_server.restart(port=9555, host="127.0.0.3")

        factory.assert_called_once_with(port=9555, host="127.0.0.3")
        if running:
            orch.stop_all.assert_called_once_with()
        else:
            orch.stop_all.assert_not_called()
        orch.start_all.assert_called_once_with(foreground=True)

    def test_status_renders_service_states_and_ports(
        self, isolated_boundaries: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        statuses = {
            "postgres": "running",
            "clickhouse": "stopped",
            "redis": "not initialized",
            "api": "running",
            "mystery": "degraded",
        }
        _, orch = patch_orchestrator(isolated_boundaries, monkeypatch, statuses=statuses)

        cmd_server.status()

        orch.status.assert_called_once_with()
        output = isolated_boundaries.console.text()
        for value in (
            "Observal Service Status",
            "Postgres",
            "Clickhouse",
            "Redis",
            "Api",
            "Mystery",
            "running",
            "stopped",
            "not initialized",
            "degraded",
            "5480",
            "8124",
            "6380",
            str(cmd_server.API_PORT),
        ):
            assert value in output


class TestLogsInstallResetAndConfig:
    def test_logs_reject_unknown_service(self, isolated_boundaries: SimpleNamespace) -> None:
        with pytest.raises(typer.Exit) as error:
            cmd_server.logs(service="worker", follow=False, lines=10)

        assert error.value.exit_code == 1
        output = isolated_boundaries.console.text()
        assert "Unknown service 'worker'" in output
        assert "postgres, clickhouse, redis, api" in output

    def test_logs_report_when_no_files_exist(self, isolated_boundaries: SimpleNamespace) -> None:
        with pytest.raises(typer.Exit) as error:
            cmd_server.logs(service=None, follow=False, lines=10)

        assert error.value.exit_code == 1
        assert "No log files found" in isolated_boundaries.console.text()

    def test_logs_show_only_requested_tail_lines(self, isolated_boundaries: SimpleNamespace) -> None:
        isolated_boundaries.root.joinpath("logs").mkdir(parents=True)
        isolated_boundaries.root.joinpath("logs/api.log").write_text("first\nsecond\nthird\n")

        cmd_server.logs(service="api", follow=False, lines=2)

        output = isolated_boundaries.console.text()
        assert "first" not in output
        assert "second" in output
        assert "third" in output
        assert "==>" not in output

    def test_logs_label_each_existing_file_when_showing_all(self, isolated_boundaries: SimpleNamespace) -> None:
        log_dir = isolated_boundaries.root / "logs"
        log_dir.mkdir(parents=True)
        (log_dir / "postgres.log").write_text("postgres message\n")
        (log_dir / "api.log").write_text("api message\n")

        cmd_server.logs(service=None, follow=False, lines=50)

        output = isolated_boundaries.console.text()
        assert "==> postgres <==" in output
        assert "==> api <==" in output
        assert "postgres message" in output
        assert "api message" in output

    def test_follow_logs_delegates_to_tail_and_swallows_interrupt(
        self, isolated_boundaries: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        log_dir = isolated_boundaries.root / "logs"
        log_dir.mkdir(parents=True)
        api_log = log_dir / "api.log"
        api_log.write_text("ready\n")
        run = MagicMock(side_effect=KeyboardInterrupt)
        monkeypatch.setattr(cmd_server.subprocess, "run", run)

        cmd_server.logs(service="api", follow=True, lines=50)

        run.assert_called_once_with(["tail", "-f", str(api_log)])

    @pytest.mark.parametrize("upgrade", [False, True])
    def test_install_delegates_force_and_prints_next_step(
        self,
        upgrade: bool,
        isolated_boundaries: SimpleNamespace,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        install_dependencies = MagicMock()
        monkeypatch.setattr(isolated_boundaries.deps, "install_dependencies", install_dependencies)

        cmd_server.install(upgrade=upgrade)

        install_dependencies.assert_called_once_with(force=upgrade)
        output = isolated_boundaries.console.text()
        assert "All dependencies installed" in output
        assert "observal server start" in output

    def test_reset_decline_aborts_without_constructing_orchestrator(
        self, isolated_boundaries: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        confirm = MagicMock(return_value=False)
        factory = MagicMock()
        monkeypatch.setattr(typer, "confirm", confirm)
        monkeypatch.setattr(isolated_boundaries.orchestrator, "Orchestrator", factory)

        with pytest.raises(typer.Abort):
            cmd_server.reset(force=False)

        confirm.assert_called_once_with("This will delete all Observal data (databases, config, keys). Continue?")
        factory.assert_not_called()

    @pytest.mark.parametrize("force", [False, True])
    def test_reset_delegates_after_confirmation_or_with_force(
        self,
        force: bool,
        isolated_boundaries: SimpleNamespace,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        confirm = MagicMock(return_value=True)
        monkeypatch.setattr(typer, "confirm", confirm)
        factory, orch = patch_orchestrator(isolated_boundaries, monkeypatch)

        cmd_server.reset(force=force)

        if force:
            confirm.assert_not_called()
        else:
            confirm.assert_called_once()
        factory.assert_called_once_with()
        orch.reset.assert_called_once_with()

    def test_status_and_config_use_safe_ports_without_constants(
        self, isolated_boundaries: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        block_server_constants(monkeypatch)
        patch_orchestrator(
            isolated_boundaries,
            monkeypatch,
            statuses={"postgres": "running", "clickhouse": "running", "redis": "running", "api": "running"},
        )

        cmd_server.status()
        cmd_server.config()

        output = isolated_boundaries.console.text()
        for port in ("5480", "8124", "6380", "8000"):
            assert port in output

    @pytest.mark.parametrize("has_file", [False, True])
    def test_config_renders_paths_ports_and_config_file_state(
        self, has_file: bool, isolated_boundaries: SimpleNamespace
    ) -> None:
        isolated_boundaries.root.mkdir(parents=True)
        config_file = isolated_boundaries.root / "observal.yaml"
        if has_file:
            config_file.write_text("server: embedded\n")

        cmd_server.config()

        output = isolated_boundaries.console.text()
        for value in (
            "Observal Server Configuration",
            "Home directory",
            str(isolated_boundaries.root),
            "API port",
            str(cmd_server.API_PORT),
            "PostgreSQL port",
            "5480",
            "ClickHouse port",
            "8124",
            "Redis port",
            "6380",
            str(isolated_boundaries.root / "config"),
            str(isolated_boundaries.root / "logs"),
        ):
            assert value in output
        if has_file:
            assert str(config_file) in output
            assert "not created" not in output
        else:
            assert "not created (using defaults)" in output


class TestDockerConfigurationHelpers:
    @pytest.mark.parametrize("location", ["docker", "cwd", "home", "default"])
    def test_find_compose_dir_uses_candidate_order(
        self,
        location: str,
        isolated_boundaries: SimpleNamespace,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        cwd = isolated_boundaries.tmp / "work"
        cwd.mkdir()
        monkeypatch.setattr(Path, "cwd", lambda: cwd)

        if location == "docker":
            expected = cwd / "docker"
            expected.mkdir()
            (expected / "docker-compose.yml").write_text("services: {}\n")
            (cwd / "compose.yml").write_text("services: {}\n")
        elif location == "cwd":
            expected = cwd
            (cwd / "compose.yml").write_text("services: {}\n")
        elif location == "home":
            expected = isolated_boundaries.root / "docker"
            expected.mkdir(parents=True)
            (expected / "docker-compose.yml").write_text("services: {}\n")
        else:
            expected = Path("/opt/observal")

        real_exists = Path.exists

        def isolated_exists(path: Path) -> bool:
            if path == Path("/opt/observal/docker-compose.yml") or path == Path("/opt/observal/compose.yml"):
                return False
            return real_exists(path)

        monkeypatch.setattr(Path, "exists", isolated_exists)

        assert cmd_server._find_compose_dir() == expected

    def test_get_current_version_prefers_compose_env(self, isolated_boundaries: SimpleNamespace) -> None:
        compose = isolated_boundaries.tmp / "docker"
        compose.mkdir()
        (isolated_boundaries.tmp / ".env").write_text("OBSERVAL_VERSION=parent\n")
        (compose / ".env").write_text('OTHER=x\nOBSERVAL_VERSION="1.2.3"\n')

        assert cmd_server._get_current_server_version(compose) == "1.2.3"

    def test_get_current_version_falls_back_to_parent_env(self, isolated_boundaries: SimpleNamespace) -> None:
        compose = isolated_boundaries.tmp / "docker"
        compose.mkdir()
        (isolated_boundaries.tmp / ".env").write_text("OBSERVAL_VERSION=2.0.0\n")

        assert cmd_server._get_current_server_version(compose) == "2.0.0"

    def test_get_current_version_returns_unknown_without_setting(self, isolated_boundaries: SimpleNamespace) -> None:
        compose = isolated_boundaries.tmp / "docker"
        compose.mkdir()
        (compose / ".env").write_text("OTHER=value\n")

        assert cmd_server._get_current_server_version(compose) == "unknown"

    @pytest.mark.parametrize("location", ["compose", "parent", "missing"])
    def test_find_env_file(
        self,
        location: str,
        isolated_boundaries: SimpleNamespace,
    ) -> None:
        compose = isolated_boundaries.tmp / "docker"
        compose.mkdir()
        if location == "compose":
            expected = compose / ".env"
            expected.write_text("")
            parent = isolated_boundaries.tmp / ".env"
            parent.write_text("")
        elif location == "parent":
            expected = isolated_boundaries.tmp / ".env"
            expected.write_text("")
        else:
            expected = compose / ".env"

        assert cmd_server._find_env_file(compose) == expected

    @pytest.mark.parametrize(
        ("content", "expected"),
        [
            ("LB_HOST_PORT=9001\nAPI_HOST_PORT=9002\n", "http://localhost:9001/readyz"),
            ('LB_HOST_PORT=""\nAPI_HOST_PORT="9010"\n', "http://localhost:9010/readyz"),
            ("OTHER=value\n", "http://localhost:8000/readyz"),
        ],
    )
    def test_health_url_uses_lb_then_api_then_default(
        self,
        content: str,
        expected: str,
        isolated_boundaries: SimpleNamespace,
    ) -> None:
        compose = isolated_boundaries.tmp / "docker"
        compose.mkdir()
        (compose / ".env").write_text(content)

        assert cmd_server._get_health_url(compose) == expected

    def test_health_url_defaults_when_env_is_missing(self, isolated_boundaries: SimpleNamespace) -> None:
        compose = isolated_boundaries.tmp / "docker"
        compose.mkdir()

        assert cmd_server._get_health_url(compose) == "http://localhost:8000/readyz"

    def test_update_env_creates_missing_file(self, isolated_boundaries: SimpleNamespace) -> None:
        compose = isolated_boundaries.tmp / "docker"
        compose.mkdir()

        cmd_server._update_env_version(compose, "1.0.0")

        assert (compose / ".env").read_text() == "OBSERVAL_VERSION=1.0.0\n"

    def test_update_env_replaces_existing_version(self, isolated_boundaries: SimpleNamespace) -> None:
        compose = isolated_boundaries.tmp / "docker"
        compose.mkdir()
        env_file = compose / ".env"
        env_file.write_text("OTHER=kept\nOBSERVAL_VERSION=1.0.0\nAFTER=kept\n")

        cmd_server._update_env_version(compose, "2.0.0")

        assert env_file.read_text() == "OTHER=kept\nOBSERVAL_VERSION=2.0.0\nAFTER=kept\n"

    def test_update_env_appends_missing_version(self, isolated_boundaries: SimpleNamespace) -> None:
        compose = isolated_boundaries.tmp / "docker"
        compose.mkdir()
        env_file = compose / ".env"
        env_file.write_text("OTHER=kept\n")

        cmd_server._update_env_version(compose, "3.0.0")

        assert env_file.read_text() == "OTHER=kept\nOBSERVAL_VERSION=3.0.0\n"


def prepare_upgrade(
    runtime: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
    *,
    current: str = "1.0.0",
) -> SimpleNamespace:
    compose = runtime.tmp / "compose"
    compose.mkdir(exist_ok=True)
    (compose / ".env").write_text(f"OBSERVAL_VERSION={current}\n")

    authorize = MagicMock()
    find_compose = MagicMock(return_value=compose)
    verify = MagicMock(return_value=True)
    acquire = MagicMock(return_value=runtime.tmp / "server.lock")
    release = MagicMock()
    create_backup = MagicMock(return_value=runtime.tmp / "backup")

    monkeypatch.setattr(cmd_server, "_require_super_admin", authorize)
    monkeypatch.setattr(cmd_server, "_find_compose_dir", find_compose)
    monkeypatch.setattr(runtime.version_check, "verify_server_image_exists", verify)
    monkeypatch.setattr(runtime.upgrade_lock, "acquire_lock", acquire)
    monkeypatch.setattr(runtime.upgrade_lock, "release_lock", release)
    monkeypatch.setattr(runtime.backup, "create_backup", create_backup)

    return SimpleNamespace(
        compose=compose,
        authorize=authorize,
        find_compose=find_compose,
        verify=verify,
        acquire=acquire,
        release=release,
        create_backup=create_backup,
    )


class TestServerUpgrade:
    def test_latest_release_fetch_failure_exits(
        self, isolated_boundaries: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        prepared = prepare_upgrade(isolated_boundaries, monkeypatch)
        fetch = MagicMock(return_value=None)
        monkeypatch.setattr(isolated_boundaries.version_check, "_fetch_from_github", fetch)

        with pytest.raises(typer.Exit) as error:
            cmd_server.server_upgrade(version=None, skip_backup=False, dry_run=False, force=True)

        assert error.value.exit_code == 1
        fetch.assert_called_once_with()
        prepared.verify.assert_not_called()
        assert "Failed to fetch latest release" in isolated_boundaries.console.text()

    def test_current_version_exits_without_image_lookup(
        self, isolated_boundaries: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        prepared = prepare_upgrade(isolated_boundaries, monkeypatch, current="1.2.3")

        with pytest.raises(typer.Exit) as error:
            cmd_server.server_upgrade(version="1.2.3", skip_backup=False, dry_run=False, force=True)

        assert error.value.exit_code == 0
        prepared.verify.assert_not_called()
        assert "Already on v1.2.3" in isolated_boundaries.console.text()

    def test_missing_container_image_exits_before_state_changes(
        self, isolated_boundaries: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        prepared = prepare_upgrade(isolated_boundaries, monkeypatch)
        prepared.verify.return_value = False

        with pytest.raises(typer.Exit) as error:
            cmd_server.server_upgrade(version="2.0.0", skip_backup=False, dry_run=False, force=True)

        assert error.value.exit_code == 1
        prepared.verify.assert_called_once_with("2.0.0")
        prepared.acquire.assert_not_called()
        output = isolated_boundaries.console.text()
        assert "Image not found on GHCR" in output
        assert "server versions" in output

    def test_dry_run_resolves_latest_and_prints_plan(
        self, isolated_boundaries: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        prepared = prepare_upgrade(isolated_boundaries, monkeypatch)
        fetch = MagicMock(return_value={"latest_version": "2.1.0"})
        monkeypatch.setattr(isolated_boundaries.version_check, "_fetch_from_github", fetch)

        with pytest.raises(typer.Exit) as error:
            cmd_server.server_upgrade(version=None, skip_backup=False, dry_run=True, force=False)

        assert error.value.exit_code == 0
        prepared.verify.assert_called_once_with("2.1.0")
        prepared.acquire.assert_not_called()
        output = isolated_boundaries.console.text()
        assert "Dry run: would upgrade v1.0.0" in output
        assert "observal-api:2.1.0" in output
        assert str(prepared.compose) in output

    def test_declined_confirmation_aborts_before_locking(
        self, isolated_boundaries: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        prepared = prepare_upgrade(isolated_boundaries, monkeypatch)
        confirm = MagicMock(return_value=False)
        monkeypatch.setattr(typer, "confirm", confirm)

        with pytest.raises(typer.Abort):
            cmd_server.server_upgrade(version="2.0.0", skip_backup=False, dry_run=False, force=False)

        confirm.assert_called_once_with("\nProceed with server upgrade?")
        prepared.acquire.assert_not_called()
        output = isolated_boundaries.console.text()
        assert "Current:" in output
        assert "Target:" in output
        assert "observal-{api,web}:2.0.0" in output

    def test_upgrade_lock_error_is_visible(
        self, isolated_boundaries: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        prepared = prepare_upgrade(isolated_boundaries, monkeypatch)
        prepared.acquire.side_effect = isolated_boundaries.upgrade_lock.UpgradeLockError("upgrade busy")

        with pytest.raises(typer.Exit) as error:
            cmd_server.server_upgrade(version="2.0.0", skip_backup=True, dry_run=False, force=True)

        assert error.value.exit_code == 1
        prepared.acquire.assert_called_once_with("server")
        prepared.release.assert_not_called()
        assert "upgrade busy" in isolated_boundaries.console.text()

    def test_successful_upgrade_backs_up_pulls_recreates_and_waits_for_health(
        self, isolated_boundaries: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        prepared = prepare_upgrade(isolated_boundaries, monkeypatch)
        run = MagicMock(side_effect=[completed(), completed()])
        get = MagicMock(
            side_effect=[
                httpx.ConnectError("starting"),
                SimpleNamespace(status_code=503),
                SimpleNamespace(status_code=200),
            ]
        )
        sleep = MagicMock()
        monkeypatch.setattr(cmd_server.subprocess, "run", run)
        monkeypatch.setattr(httpx, "get", get)
        monkeypatch.setattr(time, "sleep", sleep)

        cmd_server.server_upgrade(version="2.0.0", skip_backup=False, dry_run=False, force=True)

        prepared.create_backup.assert_called_once_with(prepared.compose, "1.0.0")
        assert run.call_args_list[0].args[0] == ["docker", "compose", "pull"]
        assert run.call_args_list[0].kwargs["cwd"] == prepared.compose
        assert run.call_args_list[0].kwargs["env"]["OBSERVAL_VERSION"] == "2.0.0"
        assert run.call_args_list[0].kwargs["capture_output"] is True
        assert run.call_args_list[0].kwargs["text"] is True
        assert run.call_args_list[0].kwargs["timeout"] == 600
        assert run.call_args_list[1] == call(
            ["docker", "compose", "up", "-d"],
            cwd=prepared.compose,
            capture_output=True,
            text=True,
            timeout=300,
        )
        assert get.call_count == 3
        assert all(item.args[0] == "http://localhost:8000/readyz" for item in get.call_args_list)
        assert sleep.call_args_list == [call(5), call(5), call(5)]
        assert (prepared.compose / ".env").read_text() == "OBSERVAL_VERSION=2.0.0\n"
        prepared.release.assert_called_once_with(isolated_boundaries.tmp / "server.lock")
        output = isolated_boundaries.console.text()
        assert "Creating backup" in output
        assert "Upgraded to v2.0.0" in output
        assert str(isolated_boundaries.tmp / "backup") in output
        assert "observal server rollback" in output

    def test_pull_failure_exits_and_releases_lock(
        self, isolated_boundaries: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        prepared = prepare_upgrade(isolated_boundaries, monkeypatch)
        run = MagicMock(return_value=completed(7, stderr="registry unavailable"))
        monkeypatch.setattr(cmd_server.subprocess, "run", run)

        with pytest.raises(typer.Exit) as error:
            cmd_server.server_upgrade(version="2.0.0", skip_backup=True, dry_run=False, force=True)

        assert error.value.exit_code == 1
        assert run.call_count == 1
        assert (prepared.compose / ".env").read_text() == "OBSERVAL_VERSION=1.0.0\n"
        prepared.create_backup.assert_not_called()
        prepared.release.assert_called_once_with(isolated_boundaries.tmp / "server.lock")
        assert "Pull failed: registry unavailable" in isolated_boundaries.console.text()

    def test_recreate_failure_restores_current_env_and_releases_lock(
        self, isolated_boundaries: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        prepared = prepare_upgrade(isolated_boundaries, monkeypatch)
        run = MagicMock(side_effect=[completed(), completed(8, stderr="compose failed")])
        monkeypatch.setattr(cmd_server.subprocess, "run", run)

        with pytest.raises(typer.Exit) as error:
            cmd_server.server_upgrade(version="2.0.0", skip_backup=True, dry_run=False, force=True)

        assert error.value.exit_code == 1
        assert run.call_count == 2
        assert (prepared.compose / ".env").read_text() == "OBSERVAL_VERSION=1.0.0\n"
        prepared.release.assert_called_once_with(isolated_boundaries.tmp / "server.lock")
        assert "Container recreation failed: compose failed" in isolated_boundaries.console.text()

    def test_failed_health_check_rolls_back_env_and_containers(
        self, isolated_boundaries: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        prepared = prepare_upgrade(isolated_boundaries, monkeypatch)
        run = MagicMock(side_effect=[completed(), completed(), completed()])
        get = MagicMock(return_value=SimpleNamespace(status_code=503))
        sleep = MagicMock()
        monkeypatch.setattr(cmd_server.subprocess, "run", run)
        monkeypatch.setattr(httpx, "get", get)
        monkeypatch.setattr(time, "sleep", sleep)

        with pytest.raises(typer.Exit) as error:
            cmd_server.server_upgrade(version="2.0.0", skip_backup=True, dry_run=False, force=True)

        assert error.value.exit_code == 1
        assert get.call_count == 24
        assert sleep.call_count == 24
        assert run.call_args_list[2] == call(
            ["docker", "compose", "up", "-d"],
            cwd=prepared.compose,
            capture_output=True,
            timeout=300,
        )
        assert (prepared.compose / ".env").read_text() == "OBSERVAL_VERSION=1.0.0\n"
        prepared.release.assert_called_once_with(isolated_boundaries.tmp / "server.lock")
        assert "Health check failed! Rolling back" in isolated_boundaries.console.text()


def prepare_rollback(
    runtime: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
    *,
    current: str = "2.0.0",
) -> SimpleNamespace:
    compose = runtime.tmp / "compose"
    compose.mkdir(exist_ok=True)
    (compose / ".env").write_text(f"OBSERVAL_VERSION={current}\n")

    authorize = MagicMock()
    find_compose = MagicMock(return_value=compose)
    list_backups = MagicMock(return_value=[])
    restore_backup = MagicMock()
    acquire = MagicMock(return_value=runtime.tmp / "server.lock")
    release = MagicMock()

    monkeypatch.setattr(cmd_server, "_require_super_admin", authorize)
    monkeypatch.setattr(cmd_server, "_find_compose_dir", find_compose)
    monkeypatch.setattr(runtime.backup, "list_backups", list_backups)
    monkeypatch.setattr(runtime.backup, "restore_backup", restore_backup)
    monkeypatch.setattr(runtime.upgrade_lock, "acquire_lock", acquire)
    monkeypatch.setattr(runtime.upgrade_lock, "release_lock", release)

    return SimpleNamespace(
        compose=compose,
        authorize=authorize,
        find_compose=find_compose,
        list_backups=list_backups,
        restore_backup=restore_backup,
        acquire=acquire,
        release=release,
    )


class TestServerRollback:
    def test_no_backups_exits(self, isolated_boundaries: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> None:
        prepared = prepare_rollback(isolated_boundaries, monkeypatch)

        with pytest.raises(typer.Exit) as error:
            cmd_server.server_rollback(from_backup=None, force=True)

        assert error.value.exit_code == 1
        prepared.acquire.assert_not_called()
        assert "No backups found" in isolated_boundaries.console.text()

    def test_missing_explicit_backup_exits(
        self, isolated_boundaries: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        prepared = prepare_rollback(isolated_boundaries, monkeypatch)
        missing = isolated_boundaries.tmp / "v1.0.0-missing"

        with pytest.raises(typer.Exit) as error:
            cmd_server.server_rollback(from_backup=str(missing), force=True)

        assert error.value.exit_code == 1
        prepared.acquire.assert_not_called()
        assert f"Backup not found: {missing}" in isolated_boundaries.console.text()

    def test_declined_rollback_aborts_before_locking(
        self, isolated_boundaries: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        prepared = prepare_rollback(isolated_boundaries, monkeypatch)
        backup_dir = isolated_boundaries.tmp / "v1.4.0-20260101T120000"
        backup_dir.mkdir()
        prepared.list_backups.return_value = [{"path": str(backup_dir)}]
        confirm = MagicMock(return_value=False)
        monkeypatch.setattr(typer, "confirm", confirm)

        with pytest.raises(typer.Abort):
            cmd_server.server_rollback(from_backup=None, force=False)

        confirm.assert_called_once_with("\nProceed with rollback?")
        prepared.acquire.assert_not_called()
        output = isolated_boundaries.console.text()
        assert "Current:" in output
        assert "Rollback to:" in output
        assert "v1.4.0" in output
        assert str(backup_dir) in output

    def test_rollback_lock_error_is_visible(
        self, isolated_boundaries: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        prepared = prepare_rollback(isolated_boundaries, monkeypatch)
        backup_dir = isolated_boundaries.tmp / "v1.4.0-20260101T120000"
        backup_dir.mkdir()
        prepared.list_backups.return_value = [{"path": str(backup_dir)}]
        prepared.acquire.side_effect = isolated_boundaries.upgrade_lock.UpgradeLockError("rollback busy")

        with pytest.raises(typer.Exit) as error:
            cmd_server.server_rollback(from_backup=None, force=True)

        assert error.value.exit_code == 1
        prepared.acquire.assert_called_once_with("server")
        prepared.release.assert_not_called()
        assert "rollback busy" in isolated_boundaries.console.text()

    def test_successful_rollback_restores_backup_recreates_and_waits_for_health(
        self, isolated_boundaries: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        prepared = prepare_rollback(isolated_boundaries, monkeypatch)
        backup_dir = isolated_boundaries.tmp / "v1.4.0-20260101T120000"
        backup_dir.mkdir()
        prepared.list_backups.return_value = [{"path": str(backup_dir)}]
        run = MagicMock(return_value=completed())
        get = MagicMock(side_effect=[httpx.ConnectError("starting"), SimpleNamespace(status_code=200)])
        sleep = MagicMock()
        monkeypatch.setattr(cmd_server.subprocess, "run", run)
        monkeypatch.setattr(httpx, "get", get)
        monkeypatch.setattr(time, "sleep", sleep)

        cmd_server.server_rollback(from_backup=None, force=True)

        prepared.restore_backup.assert_called_once_with(backup_dir, prepared.compose)
        run.assert_called_once_with(
            ["docker", "compose", "up", "-d"],
            cwd=prepared.compose,
            capture_output=True,
            timeout=300,
        )
        assert get.call_count == 2
        assert sleep.call_args_list == [call(5), call(5)]
        assert (prepared.compose / ".env").read_text() == "OBSERVAL_VERSION=1.4.0\n"
        prepared.release.assert_called_once_with(isolated_boundaries.tmp / "server.lock")
        assert "Rolled back to v1.4.0" in isolated_boundaries.console.text()

    def test_unhealthy_rollback_finishes_with_log_guidance(
        self, isolated_boundaries: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        prepared = prepare_rollback(isolated_boundaries, monkeypatch)
        backup_dir = isolated_boundaries.tmp / "v1.3.0-20260101T120000"
        backup_dir.mkdir()
        run = MagicMock(return_value=completed())
        get = MagicMock(return_value=SimpleNamespace(status_code=503))
        sleep = MagicMock()
        monkeypatch.setattr(cmd_server.subprocess, "run", run)
        monkeypatch.setattr(httpx, "get", get)
        monkeypatch.setattr(time, "sleep", sleep)

        cmd_server.server_rollback(from_backup=str(backup_dir), force=True)

        prepared.restore_backup.assert_called_once_with(backup_dir, prepared.compose)
        assert get.call_count == 24
        assert sleep.call_count == 24
        prepared.release.assert_called_once_with(isolated_boundaries.tmp / "server.lock")
        output = isolated_boundaries.console.text()
        assert "Rollback complete but health check didn't pass" in output
        assert "docker compose logs -f" in output


class TestServerVersions:
    def test_versions_render_current_available_and_backup_sizes(
        self, isolated_boundaries: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        prepared = prepare_rollback(isolated_boundaries, monkeypatch, current="1.5.0")
        fetch = MagicMock(return_value=["2.0.0", "1.5.0", "1.4.0"])
        prepared.list_backups.return_value = [
            {"name": "v1.5.0-20260101T120000", "size_mb": 12},
            {"name": "v1.4.0-20251201T120000", "size_mb": 8},
        ]
        monkeypatch.setattr(isolated_boundaries.version_check, "fetch_available_server_images", fetch)

        cmd_server.server_versions()

        fetch.assert_called_once_with()
        output = isolated_boundaries.console.text()
        assert "Server Versions" in output
        assert "1.5.0" in output
        assert "current" in output
        assert "2.0.0" in output
        assert "1.4.0" in output
        assert "12 MB" in output
        assert "8 MB" in output
        assert "Current: v1.5.0" in output

    def test_versions_limit_registry_rows_when_current_is_unknown(
        self, isolated_boundaries: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        prepared = prepare_rollback(isolated_boundaries, monkeypatch, current="unused")
        (prepared.compose / ".env").write_text("OTHER=value\n")
        available = [f"release{i}" for i in range(12)]
        fetch = MagicMock(return_value=available)
        prepared.list_backups.return_value = [{"name": "vrelease1-copy", "size_mb": 3}]
        monkeypatch.setattr(isolated_boundaries.version_check, "fetch_available_server_images", fetch)

        cmd_server.server_versions()

        output = isolated_boundaries.console.text()
        assert "release0" in output
        assert "release9" in output
        assert "release10" not in output
        assert "3 MB" in output
        assert "Current: vunknown" in output
