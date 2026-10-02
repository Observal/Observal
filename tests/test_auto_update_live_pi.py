# SPDX-License-Identifier: Apache-2.0

"""Opt-in, isolated real-process Pi RPC + CLI apply smoke test.

Run: OBSERVAL_RUN_LIVE_PI=1 PYTHONPATH=. .venv/bin/pytest tests/test_auto_update_live_pi.py -v
No Docker, cloud credentials, provider key, or real user home is touched.
"""

from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator

AGENT = "11111111-1111-4111-8111-111111111111"
EXTENSION = Path(__file__).resolve().parents[1] / "packages/pi-extension/extensions/observal.ts"
CLI = Path(sys.executable).parent / "observal"


class Registry(str):
    def __new__(cls, value: str) -> Registry:
        result = str.__new__(cls, value)
        result.pause = False
        result.unsafe = False
        result.started = threading.Event()
        result.release = threading.Event()
        return result


@pytest.fixture()
def registry() -> Iterator[Registry]:
    control: Registry | None = None

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args: object) -> None:
            pass

        def send(self, value: dict, code: int = 200) -> None:
            body = json.dumps(value).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            if self.path == "/api/v1/config/version":
                return self.send({"server_version": "dev"})
            if self.path == f"/api/v1/agents/{AGENT}":
                return self.send(
                    {"id": AGENT, "latest_approved_version": "2.0.0", "namespace": "alice", "slug": "reviewer"}
                )
            if self.path == f"/api/v1/agents/{AGENT}/versions/2.0.0":
                return self.send(
                    {
                        "version": "2.0.0",
                        "status": "approved",
                        "supported_harnesses": ["pi"],
                        "description": "Author release notes",
                        "components": [],
                    }
                )
            self.send({}, 404)

        def do_POST(self) -> None:
            if self.path == f"/api/v1/agents/{AGENT}/install":
                content = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                assert content["version"] == "2.0.0" and content["strict"] is True
                if control is not None and control.pause:
                    control.started.set()
                    control.release.wait(timeout=10)
                if control is not None and control.unsafe:
                    return self.send(
                        {"agent_id": AGENT, "harness": "pi", "version": "2.0.0", "warnings": ["review required"]}
                    )
                return self.send(
                    {
                        "agent_id": AGENT,
                        "harness": "pi",
                        "version": "2.0.0",
                        "config_snippet": {
                            "agent_profile": {"path": "~/.pi/agent/agents/reviewer/AGENTS.md", "content": "new profile"}
                        },
                        "lock": {"status": "locked", "digest": "new-digest", "components": [], "problems": []},
                    }
                )
            self.send({}, 404)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    control = Registry(f"http://127.0.0.1:{server.server_port}")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield control
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _rpc_session(home: Path, env: dict, *, expected: str) -> list[str]:
    pi = shutil.which("pi")
    assert pi
    proc = subprocess.Popen(
        [
            pi,
            "--mode",
            "rpc",
            "--no-session",
            "--offline",
            "--no-skills",
            "--no-context-files",
            "--no-extensions",
            "--extension",
            str(EXTENSION),
        ],
        cwd=home,
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert proc.stdin and proc.stdout and proc.stderr
    lines: queue.Queue[dict] = queue.Queue()

    def collect() -> None:
        for row in proc.stdout:
            lines.put(json.loads(row))

    reader = threading.Thread(target=collect, daemon=True)
    reader.start()
    messages = []
    try:
        until = time.monotonic() + 15
        while time.monotonic() < until:
            try:
                record = lines.get(timeout=0.3)
            except queue.Empty:
                continue
            if record.get("type") == "extension_ui_request" and record.get("method") == "notify":
                messages.append(record["message"])
                if expected in record["message"]:
                    break
        else:
            pytest.fail(f"Pi RPC did not deliver {expected!r}: {messages!r}")
    finally:
        proc.stdin.close()  # Orderly RPC shutdown writes the session marker.
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
        reader.join(timeout=2)
    assert proc.returncode == 0, proc.stderr.read().decode()[:1000]
    return messages


@pytest.mark.skipif(os.getenv("OBSERVAL_RUN_LIVE_PI") != "1", reason="explicit live Pi/RPC opt-in")
def test_frozen_then_real_apply_in_isolated_pi_rpc(tmp_path: Path, registry: Registry) -> None:
    if not shutil.which("pi") or not CLI.exists():
        pytest.skip("Requires installed Pi and editable Observal CLI")
    home = tmp_path / "home"
    home.mkdir()
    root = tmp_path / "project"
    root.mkdir()
    profile = home / ".pi/agent/agents/reviewer/AGENTS.md"
    profile.parent.mkdir(parents=True)
    profile.write_text("old profile")
    config = home / ".observal/config.json"
    config.parent.mkdir()
    config.write_text(json.dumps({"server_url": registry, "access_token": "local-token", "user_id": "alice"}))
    env = {
        **os.environ,
        "HOME": str(home),
        "XDG_CONFIG_HOME": str(home / ".config"),
        "PYTHONPATH": str(Path(__file__).resolve().parents[1]),
    }
    # Real CLI writes a v2 baseline, an installed lock, and scoped consent.
    bootstrap = f"""
from observal_cli import auto_update_policy as policy, lockfile, install_baseline
lockfile.upsert_agent('pi', name='reviewer', agent_id={AGENT!r}, version='1.0.0', scope='user',
    directory={str(root)!r}, components=[], namespace='alice', slug='reviewer',
    local_name='reviewer', lock_status='locked', lock_digest='old-digest')
install_baseline.capture(registry={registry!r}, harness='pi', agent_id={AGENT!r}, scope='user',
    root={str(root)!r}, version='1.0.0', lock_digest='old-digest', written_paths=[{str(profile)!r}])
"""
    subprocess.run([sys.executable, "-c", bootstrap], env=env, check=True, capture_output=True)
    # Real Pi RPC bridge invokes the isolated apply worker only in pilot mode;
    # the worker still requires account-scoped `observal unfreeze`.
    env["OBSERVAL_CLI_BIN"] = str(CLI)
    env["OBSERVAL_PI_AUTO_APPLY"] = "1"

    messages = _rpc_session(home, env, expected="update available")
    assert "Author release notes" in "\n".join(messages)
    assert profile.read_text() == "old profile", "frozen startup must not install"
    subprocess.run([str(CLI), "unfreeze"], cwd=home, env=env, check=True, capture_output=True)
    profile.write_text("local edit")
    messages = _rpc_session(home, env, expected="automatic update skipped")
    assert profile.read_text() == "local edit", "dirty managed files must not be overwritten"
    profile.write_text("old profile")  # Explicitly restore known baseline for this isolated test.

    # Pause the real registry's install response, close Pi while the worker is
    # waiting, then release it. Pi must exit without killing the worker; the
    # marker must prevent any new file replacement after the response arrives.
    registry.pause = True
    pi = shutil.which("pi")
    assert pi
    departed = subprocess.Popen(
        [
            pi,
            "--mode",
            "rpc",
            "--no-session",
            "--offline",
            "--no-skills",
            "--no-context-files",
            "--no-extensions",
            "--extension",
            str(EXTENSION),
        ],
        cwd=home,
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    try:
        assert registry.started.wait(10), "apply worker did not reach registry install"
        assert departed.stdin
        departed.stdin.close()
        assert departed.wait(timeout=4) == 0, "Pi waited for an in-flight install"
    finally:
        registry.release.set()
        registry.pause = False
        if departed.poll() is None:
            departed.kill()
            departed.wait(timeout=5)
    notices = home / ".observal/update-notices"
    until = time.monotonic() + 10
    while time.monotonic() < until:
        rows = [json.loads(file.read_text()) for file in notices.glob("*.json")]
        if any(item.get("status") == "skipped" for row in rows for item in row["items"]):
            break
        time.sleep(0.1)
    else:
        pytest.fail("departed worker did not persist its shutdown result")
    assert profile.read_text() == "old profile"

    registry.unsafe = True
    messages = _rpc_session(home, env, expected="automatic update skipped")
    assert profile.read_text() == "old profile", "unsafe install payload cannot change profile files"
    registry.unsafe = False
    messages = _rpc_session(home, env, expected="installed on disk")
    assert any("previous Pi session" in message and "automatic update skipped" in message for message in messages)
    assert "Re-select" in "\n".join(messages) or "re-select" in "\n".join(messages)
    assert profile.read_text() == "new profile"
    state = json.loads((home / ".observal/lockfile.json").read_text())
    assert state["registries"][registry]["harnesses"]["pi"]["agents"][0]["version"] == "2.0.0"
