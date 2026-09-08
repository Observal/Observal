# SPDX-FileCopyrightText: 2026 Observal Contributors
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
import subprocess
import sys

import pytest

from observal_cli.discovery.models import DiagnosticCode
from observal_cli.discovery.providers._utils import (
    MAX_CAPTURED_OUTPUT_BYTES,
    MAX_METADATA_FILE_BYTES,
    CommandOutput,
    run_bounded,
)
from observal_cli.discovery.providers.npm import discover_npm


def _runner(output: bytes, *, returncode: int = 0, oversized: bool = False):
    calls = []

    def run(command, timeout):
        calls.append((tuple(command), timeout))
        return CommandOutput(output, returncode=returncode, oversized=oversized)

    run.calls = calls
    return run


def _package(root, relative: str, data: dict) -> None:
    package = root / relative
    package.mkdir(parents=True)
    (package / "package.json").write_text(json.dumps(data))
    declared_bin = data.get("bin")
    targets = (
        [declared_bin]
        if isinstance(declared_bin, str)
        else list(declared_bin.values())
        if isinstance(declared_bin, dict)
        else []
    )
    for target in targets:
        if isinstance(target, str):
            script = package / target
            script.parent.mkdir(parents=True, exist_ok=True)
            script.touch()


def test_npm_discovers_top_level_scoped_packages_and_multiple_binaries(tmp_path) -> None:
    root = tmp_path / "node_modules"
    root.mkdir()
    _package(
        root,
        "@scope/server",
        {
            "name": "@Scope/Server",
            "version": "1.2.3",
            "description": "safe",
            "bin": {"server": "cli.js", "server-admin": "admin.js"},
        },
    )
    _package(root, "plain", {"name": "plain", "version": "2", "bin": "cli.js"})
    _package(root, "plain/node_modules/ignored", {"name": "ignored", "version": "9"})
    runner = _runner(f"{root}\n".encode())

    result = discover_npm(runner=runner, home=tmp_path)

    assert [(item.package_name, item.package_version, item.launch.binary) for item in result.evidence] == [
        ("@scope/server", "1.2.3", "server"),
        ("@scope/server", "1.2.3", "server-admin"),
        ("plain", "2", "plain"),
    ]
    assert all("ignored" not in (item.package_name or "") for item in result.evidence)
    assert runner.calls == [(("npm", "root", "--global"), 5.0)]


def test_npm_is_deterministic_and_enforces_top_level_item_limit(tmp_path) -> None:
    root = tmp_path / "node_modules"
    root.mkdir()
    _package(root, "zeta", {"name": "zeta"})
    _package(root, "alpha", {"name": "alpha"})

    result = discover_npm(runner=_runner(str(root).encode()), max_records=1)

    assert [item.package_name for item in result.evidence] == ["alpha"]
    assert [item.code for item in result.diagnostics] == [DiagnosticCode.ITEM_LIMIT_REACHED]


def test_npm_rejects_symlink_escape_and_oversized_metadata(tmp_path) -> None:
    root = tmp_path / "node_modules"
    root.mkdir()
    outside = tmp_path / "outside"
    _package(tmp_path, "outside", {"name": "escaped"})
    (root / "escaped").symlink_to(outside, target_is_directory=True)
    huge = root / "huge"
    huge.mkdir()
    (huge / "package.json").write_bytes(b"x" * (MAX_METADATA_FILE_BYTES + 1))

    result = discover_npm(runner=_runner(str(root).encode()))

    assert result.evidence == []
    assert {item.code for item in result.diagnostics} == {
        DiagnosticCode.METADATA_TOO_LARGE,
        DiagnosticCode.SYMLINK_ESCAPE,
    }


def test_npm_decodes_invalid_utf8_metadata_with_replacement(tmp_path) -> None:
    root = tmp_path / "node_modules"
    package = root / "server"
    package.mkdir(parents=True)
    (package / "package.json").write_bytes(b'{"name":"server","description":"bad \xff"}')

    result = discover_npm(runner=_runner(str(root).encode()))

    assert [item.package_name for item in result.evidence] == ["server"]
    assert result.diagnostics == []


def test_default_command_runner_bounds_combined_output_memory() -> None:
    output = run_bounded(
        (sys.executable, "-c", f"import sys; sys.stdout.write('x' * {MAX_CAPTURED_OUTPUT_BYTES + 100})"),
        5.0,
    )

    assert output.oversized
    assert len(output.stdout) + len(output.stderr) <= MAX_CAPTURED_OUTPUT_BYTES + 1


@pytest.mark.parametrize(
    ("runner", "code"),
    [
        (_runner(b"", returncode=2), DiagnosticCode.SUBPROCESS_FAILED),
        (_runner(b"x" * (MAX_CAPTURED_OUTPUT_BYTES + 1)), DiagnosticCode.OUTPUT_TOO_LARGE),
        (_runner(b"", oversized=True), DiagnosticCode.OUTPUT_TOO_LARGE),
    ],
)
def test_npm_reports_command_failures(runner, code) -> None:
    result = discover_npm(runner=runner)

    assert result.evidence == []
    assert [item.code for item in result.diagnostics] == [code]


def test_npm_provider_deadline_prevents_command_execution() -> None:
    moments = iter((0.0, 16.0))
    called = False

    def runner(command, timeout):
        nonlocal called
        called = True
        return CommandOutput(b"")

    result = discover_npm(runner=runner, clock=lambda: next(moments))

    assert not called
    assert [item.code for item in result.diagnostics] == [DiagnosticCode.ADAPTER_DEADLINE_EXCEEDED]


def test_npm_does_not_return_untrusted_secret_like_metadata(tmp_path) -> None:
    root = tmp_path / "node_modules"
    package = root / "unsafe"
    package.mkdir(parents=True)
    secret = "super-secret-token-value"
    (package / "package.json").write_text(
        json.dumps({"name": "unsafe", "version": secret, "bin": {f"token={secret}": "cli.js"}})
    )

    result = discover_npm(runner=_runner(str(root).encode()), home=tmp_path)

    assert secret not in repr(result)
    assert result.evidence[0].package_version is None
    assert result.evidence[0].launch.binary is None


def test_default_runner_rejects_an_unresolved_executable(monkeypatch) -> None:
    monkeypatch.setattr("observal_cli.discovery.providers._utils.shutil.which", lambda _command: None)

    result = discover_npm()

    assert [item.code for item in result.diagnostics] == [DiagnosticCode.EXECUTABLE_MISSING]


def test_npm_reports_missing_executable_and_timeout() -> None:
    def missing(command, timeout):
        raise FileNotFoundError

    def timeout(command, timeout):
        raise subprocess.TimeoutExpired(command, timeout)

    assert [item.code for item in discover_npm(runner=missing).diagnostics] == [DiagnosticCode.EXECUTABLE_MISSING]
    assert [item.code for item in discover_npm(runner=timeout).diagnostics] == [DiagnosticCode.SUBPROCESS_TIMEOUT]
