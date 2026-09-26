# SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Drive observal_cli.sandbox_mcp over real stdio pipes using MCP's newline-delimited framing."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

SANDBOX = {"id": "sb-123", "name": "python-pytest", "image": "python:3.12-slim", "timeout": 5, "entrypoint": "pytest"}

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="fake runner relies on a shebang script")


@pytest.fixture
def fake_runner_path(tmp_path):
    """Put a stand-in `observal-sandbox-run` on PATH that echoes its argv as JSON."""
    runner = tmp_path / "observal-sandbox-run"
    runner.write_text(f"#!{sys.executable}\nimport json, sys\nprint(json.dumps(sys.argv[1:]))\n")
    runner.chmod(0o755)
    return f"{tmp_path}{os.pathsep}{os.environ.get('PATH', '')}"


def _run_session(messages: list[dict], path: str) -> list[dict]:
    stdin = "".join(json.dumps(m) + "\n" for m in messages)
    proc = subprocess.run(
        [sys.executable, "-m", "observal_cli.sandbox_mcp", "--sandboxes", json.dumps([SANDBOX])],
        input=stdin,
        capture_output=True,
        text=True,
        timeout=30,
        cwd=ROOT,
        env={**os.environ, "PATH": path},
    )
    assert proc.returncode == 0, proc.stderr
    lines = proc.stdout.splitlines()
    assert all(line.startswith("{") for line in lines), proc.stdout
    return [json.loads(line) for line in lines]


def _initialize(req_id: int, version: str) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "method": "initialize",
        "params": {"protocolVersion": version, "capabilities": {}, "clientInfo": {"name": "pytest", "version": "0"}},
    }


def test_initialize_list_and_call_over_newline_framing(fake_runner_path):
    replies = _run_session(
        [
            _initialize(1, "2025-06-18"),
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "run_sandbox_python_pytest", "arguments": {"command": "pytest -q"}},
            },
        ],
        fake_runner_path,
    )

    # The notification gets no reply, so exactly one line per request, in order
    assert [r["id"] for r in replies] == [1, 2, 3]
    init, listed, called = replies

    assert init["result"]["protocolVersion"] == "2025-06-18"
    assert init["result"]["capabilities"] == {"tools": {}}

    assert [t["name"] for t in listed["result"]["tools"]] == ["run_sandbox_python_pytest"]

    assert called["result"]["isError"] is False
    argv = json.loads(called["result"]["content"][0]["text"])
    assert argv[argv.index("--sandbox-id") + 1] == "sb-123"
    assert argv[argv.index("--image") + 1] == "python:3.12-slim"
    assert argv[argv.index("--command") + 1] == "pytest -q"


def test_unsupported_protocol_version_falls_back_to_latest(fake_runner_path):
    from observal_cli.sandbox_mcp import SUPPORTED_PROTOCOL_VERSIONS

    (reply,) = _run_session([_initialize(1, "1999-01-01")], fake_runner_path)

    assert reply["result"]["protocolVersion"] == SUPPORTED_PROTOCOL_VERSIONS[0]
