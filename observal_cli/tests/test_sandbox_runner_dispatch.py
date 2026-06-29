# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

from __future__ import annotations

import pytest


def test_wasm_dispatch_builds_wasmtime_command(monkeypatch):
    from observal_cli import sandbox_runner

    calls = []

    monkeypatch.setattr(sandbox_runner.shutil, "which", lambda name: f"/bin/{name}")

    def fake_run(argv, capture_output, text, timeout):
        calls.append(argv)

        class Result:
            stdout = "ok"
            stderr = ""
            returncode = 0

        return Result()

    monkeypatch.setattr(sandbox_runner.subprocess, "run", fake_run)

    with pytest.raises(SystemExit) as exc:
        sandbox_runner.run_sandbox("s-123", "runner.wasm", "--help", 30, runtime_type="wasm")

    assert exc.value.code == 0
    assert calls[0][:3] == ["/bin/wasmtime", "run", "--dir"]
    assert "runner.wasm" in calls[0]


def test_missing_lxc_runtime_exits_127(monkeypatch, capsys):
    from observal_cli import sandbox_runner

    monkeypatch.setattr(sandbox_runner.shutil, "which", lambda name: None)

    with pytest.raises(SystemExit) as exc:
        sandbox_runner.run_sandbox("s-123", "ubuntu:22.04", "echo hi", 30, runtime_type="lxc")

    assert exc.value.code == 127
    assert "local-runtime-missing" in capsys.readouterr().err
