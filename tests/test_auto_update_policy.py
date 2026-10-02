# SPDX-License-Identifier: Apache-2.0

"""Freeze/unfreeze policy contracts; no automatic installer is active yet."""

from __future__ import annotations

import json
import multiprocessing
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

import pytest
import typer
from typer.testing import CliRunner

from observal_cli import auto_update_policy as policy
from observal_cli import config
from observal_cli.cmd_freeze import register_freeze
from observal_cli.errors import ErrorHandlingGroup, ExitCode

REGISTRY = "https://example.test"


@pytest.fixture()
def isolated_policy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(policy, "POLICY_PATH", tmp_path / "auto-update-policy.json")
    monkeypatch.setattr(policy, "GATE_DIR", tmp_path / "gates")
    credentials = {"server_url": REGISTRY + "/", "user_id": "alice", "access_token": "alice-token"}
    monkeypatch.setattr(config, "load", lambda: dict(credentials))
    monkeypatch.setattr(config, "load_persisted", lambda: dict(credentials))
    return tmp_path


@pytest.fixture()
def cli() -> typer.Typer:
    app = typer.Typer(name="observal", cls=ErrorHandlingGroup)

    @app.callback()
    def root() -> None:
        pass

    register_freeze(app)
    return app


def call(cli: typer.Typer, *args: str) -> tuple[int, dict]:
    result = CliRunner().invoke(cli, [*args, "--output", "json"])
    payload = json.loads(result.stdout) if result.stdout else json.loads(result.stderr)
    return result.exit_code, payload


def test_default_frozen_and_independent_registries(isolated_policy: Path, cli: typer.Typer) -> None:
    assert policy.policy_status(REGISTRY)["effective"] is False
    code, enabled = call(cli, "unfreeze")
    assert code == 0
    assert enabled == {
        "registry": REGISTRY,
        "scope": "user",
        "project": None,
        "auto_update": True,
        "effective": True,
    }
    assert policy.policy_status("https://elsewhere.test")["effective"] is False
    assert call(cli, "unfreeze") == (0, enabled)  # idempotent
    code, frozen = call(cli, "freeze")
    assert code == 0
    assert frozen["effective"] is False
    assert policy.policy_status(REGISTRY)["effective"] is False
    assert policy.POLICY_PATH.stat().st_mode & 0o077 == 0


def test_project_grant_requires_global_opt_in_and_is_exact(isolated_policy: Path, cli: typer.Typer) -> None:
    root = isolated_policy / "project"
    nested = root / "nested"
    nested.mkdir(parents=True)
    code, granted = call(cli, "unfreeze", "--project", "--dir", str(root))
    assert code == 0
    assert granted["auto_update"] is True
    assert granted["effective"] is False
    assert policy.policy_status(REGISTRY, root=str(nested))["effective"] is False
    assert call(cli, "unfreeze")[0] == 0
    assert policy.policy_status(REGISTRY, root=str(root))["effective"] is True
    assert policy.policy_status(REGISTRY, root=str(nested))["effective"] is False
    assert call(cli, "freeze")[0] == 0
    assert policy.policy_status(REGISTRY, root=str(root))["auto_update"] is True
    assert policy.policy_status(REGISTRY, root=str(root))["effective"] is False
    assert call(cli, "unfreeze")[0] == 0
    assert call(cli, "freeze", "--project", "--dir", str(root))[1]["effective"] is False
    assert policy.policy_status(REGISTRY)["effective"] is True


def test_invalid_dir_and_malformed_policy_fail_closed(isolated_policy: Path, cli: typer.Typer) -> None:
    assert call(cli, "unfreeze", "--dir", str(isolated_policy))[0] == ExitCode.VALIDATION
    assert call(cli, "unfreeze", "--project", "--dir", str(isolated_policy / "missing"))[0] == ExitCode.VALIDATION
    policy.POLICY_PATH.write_text("{not json")
    assert policy.policy_status(REGISTRY)["effective"] is False
    assert "warning" in policy.policy_status(REGISTRY)
    code, error = call(cli, "unfreeze")
    assert code == ExitCode.VALIDATION
    assert error["error"]["category"] == "validation"
    assert policy.POLICY_PATH.read_text() == "{not json"


def test_gate_prevents_freeze_from_returning_before_inflight_install(
    isolated_policy: Path,
) -> None:
    policy.set_policy(REGISTRY, enabled=True)
    entered = threading.Event()
    finish = threading.Event()
    finished = threading.Event()

    def simulated_install() -> None:
        with policy.registry_gate(REGISTRY):
            assert policy.policy_status(REGISTRY)["effective"] is True
            entered.set()
            assert finish.wait(timeout=5)
        finished.set()

    with ThreadPoolExecutor(max_workers=2) as executor:
        installing = executor.submit(simulated_install)
        assert entered.wait(timeout=5)
        with pytest.raises(policy.GateBusyError):
            policy.set_policy(REGISTRY, enabled=False, timeout=0.05)
        assert policy.policy_status(REGISTRY)["effective"] is True
        freezing = executor.submit(policy.set_policy, REGISTRY, enabled=False)
        time.sleep(0.08)
        assert not freezing.done()
        finish.set()
        installing.result(timeout=5)
        assert finished.is_set()
        assert freezing.result(timeout=5)["effective"] is False
    assert policy.policy_status(REGISTRY)["effective"] is False


def _hold_gate_in_process(gate_dir: str, entered, release) -> None:
    from pathlib import Path

    from observal_cli import auto_update_policy as worker_policy

    worker_policy.GATE_DIR = Path(gate_dir)
    with worker_policy.registry_gate(REGISTRY):
        entered.set()
        release.wait(timeout=5)


def _hold_apply_worker_gate(gate_dir: str, entered, release) -> None:
    from pathlib import Path

    from observal_cli import auto_update_policy as worker_policy

    worker_policy.GATE_DIR = Path(gate_dir)
    with worker_policy.apply_worker_gate(REGISTRY, "alice"):
        entered.set()
        release.wait(timeout=5)


def test_apply_worker_gate_is_account_scoped_and_cross_process(isolated_policy: Path) -> None:
    context = multiprocessing.get_context("spawn")
    entered = context.Event()
    release = context.Event()
    worker = context.Process(target=_hold_apply_worker_gate, args=(str(policy.GATE_DIR), entered, release))
    worker.start()
    try:
        assert entered.wait(timeout=5)
        with pytest.raises(policy.GateBusyError), policy.apply_worker_gate(REGISTRY, "alice", timeout=0.05):
            pytest.fail("two workers for the same account passed the admission gate")
        with policy.apply_worker_gate(REGISTRY, "bob", timeout=0.05):
            pass
        # Freeze takes only the policy gate; it must not wait for the outer
        # worker gate (an installer holding both is covered elsewhere).
        with policy.registry_gate(REGISTRY, timeout=0.05):
            pass
        release.set()
        worker.join(timeout=5)
        assert worker.exitcode == 0
        with policy.apply_worker_gate(REGISTRY, "alice", timeout=0.05):
            pass
    finally:
        release.set()
        if worker.is_alive():
            worker.terminate()
        worker.join(timeout=5)


def test_gate_is_shared_across_processes(isolated_policy: Path) -> None:
    context = multiprocessing.get_context("spawn")
    entered = context.Event()
    release = context.Event()
    worker = context.Process(target=_hold_gate_in_process, args=(str(policy.GATE_DIR), entered, release))
    worker.start()
    try:
        assert entered.wait(timeout=5)
        with pytest.raises(policy.GateBusyError):
            policy.set_policy(REGISTRY, enabled=True, timeout=0.05)
        release.set()
        worker.join(timeout=5)
        assert worker.exitcode == 0
        assert policy.set_policy(REGISTRY, enabled=True)["effective"] is True
    finally:
        release.set()
        if worker.is_alive():
            worker.terminate()
        worker.join(timeout=5)


def test_account_switch_token_override_and_logout_fail_closed(
    isolated_policy: Path, cli: typer.Typer, monkeypatch: pytest.MonkeyPatch
) -> None:
    accounts = {"server_url": REGISTRY, "user_id": "alice", "access_token": "alice-token"}
    monkeypatch.setattr(config, "load_persisted", lambda: dict(accounts))
    monkeypatch.setattr(config, "load", lambda: dict(accounts))
    assert call(cli, "unfreeze")[1]["effective"] is True
    accounts.update(user_id="bob", access_token="bob-token")
    assert policy.policy_status(REGISTRY)["effective"] is False
    assert call(cli, "unfreeze")[1]["effective"] is True
    accounts.update(user_id="alice", access_token="alice-token")
    assert policy.policy_status(REGISTRY)["effective"] is True
    monkeypatch.setattr(config, "load", lambda: {**accounts, "access_token": "other-account-token"})
    assert policy.policy_status(REGISTRY)["effective"] is False
    assert call(cli, "unfreeze")[0] == ExitCode.AUTH
    accounts.pop("access_token")
    monkeypatch.setattr(config, "load", lambda: dict(accounts))
    assert policy.policy_status(REGISTRY)["effective"] is False


def test_legacy_unscoped_consent_is_discarded(isolated_policy: Path, cli: typer.Typer) -> None:
    policy.POLICY_PATH.write_text(
        json.dumps(
            {
                "version": 1,
                "registries": {REGISTRY: {"enabled": True, "projects": {str(isolated_policy): True}}},
            }
        )
    )
    assert policy.policy_status(REGISTRY)["effective"] is False
    assert "Legacy" in policy.policy_status(REGISTRY)["warning"]
    assert call(cli, "freeze")[1]["effective"] is False
    assert json.loads(policy.POLICY_PATH.read_text())["version"] == 2
    assert call(cli, "unfreeze")[1]["effective"] is True
    assert policy.policy_status(REGISTRY, root=str(isolated_policy))["effective"] is False


def test_help_and_missing_registry(isolated_policy: Path, cli: typer.Typer, monkeypatch: pytest.MonkeyPatch) -> None:
    assert "observal freeze" in CliRunner().invoke(cli, ["freeze", "--help"]).output
    assert "observal unfreeze" in CliRunner().invoke(cli, ["unfreeze", "--help"]).output
    monkeypatch.setattr(config, "load", lambda: {"server_url": ""})
    assert call(cli, "freeze")[0] == ExitCode.AUTH
