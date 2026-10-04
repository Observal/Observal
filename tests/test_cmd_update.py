# SPDX-FileCopyrightText: 2026 Observal Contributors
# SPDX-License-Identifier: Apache-2.0

"""The explicit batch runner reuses CLI installers without trusting printed commands."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import typer
from typer.testing import CliRunner

from observal_cli import cmd_update
from observal_cli.errors import ErrorHandlingGroup


def item(tmp_path: Path, kind: str = "agent", scope: str = "user") -> dict:
    root = str(tmp_path) if scope == "project" or kind == "agent" else None
    components = [{"type": "skill", "id": "skill-id", "version": "1.0"}] if kind == "agent" else None
    release = {"components": [{"component_type": "skill", "component_id": "skill-id", "resolved_version": "2.0"}]}
    return {
        "id": f"{kind}-id",
        "name": kind,
        "qualified_name": f"alice/{kind}",
        "type": kind,
        "harness": "pi" if kind != "hook" else "claude-code",
        "scope": scope,
        "directory": root,
        "current_version": "1.0",
        "latest_version": "2.0",
        "outdated": True,
        "status": "outdated",
        "release_verified": True,
        "release": release,
        "requested_version": None,
        "components": components,
        "lock_status": "locked" if kind == "agent" else None,
        "lock_digest": "old-digest" if kind == "agent" else None,
    }


def inventory(monkeypatch: pytest.MonkeyPatch, rows: list[dict]) -> None:
    monkeypatch.setattr(cmd_update, "_entries", lambda _harness: rows)
    monkeypatch.setattr(cmd_update.installed_updates, "compare", lambda entries, **_kwargs: entries)


def test_plan_does_not_execute_suggested_command_and_preserves_agent_scope(tmp_path: Path) -> None:
    candidate = item(tmp_path)
    candidate["upgrade_command"] = "sh -c 'touch /tmp/not-from-registry'"
    argv, reason, cwd = cmd_update._plan(candidate, project=None)
    assert reason is None and cwd == tmp_path
    assert argv == [
        cmd_update.sys.executable,
        "-m",
        "observal_cli",
        "agent",
        "pull",
        "agent-id",
        "--harness",
        "pi",
        "--scope",
        "user",
        "--dir",
        str(tmp_path),
        "--version",
        "2.0",
        "--strict",
        "--no-prompt",
        "--output",
        "json",
    ]
    assert "sh -c" not in " ".join(argv)


@pytest.mark.parametrize(
    "change",
    [
        {"requested_version": "1.0"},
        {"release_verified": False},
        {"directory": None},
    ],
)
def test_unsafe_agent_is_never_planned(tmp_path: Path, change: dict) -> None:
    candidate = {**item(tmp_path), **change}
    argv, reason, _cwd = cmd_update._plan(candidate, project=None)
    assert argv is None and reason


def test_explicit_batch_allows_agent_component_changes_but_verifies_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    candidate = item(tmp_path)
    candidate["release"]["components"] = [
        {"component_type": "mcp", "component_id": "new-id", "resolved_version": "2.0"}
    ]
    argv, reason, _ = cmd_update._plan(candidate, project=None)
    assert reason is None and argv is not None and argv[3:5] == ["agent", "pull"]
    # Even when the CLI reports success, a stale component lock is not a verified update.
    monkeypatch.setattr(cmd_update, "_entries", lambda _harness: [{**candidate, "current_version": "2.0"}])
    assert cmd_update._verify(candidate) is False
    monkeypatch.setattr(
        cmd_update,
        "_entries",
        lambda _harness: [
            {
                **candidate,
                "current_version": "2.0",
                "components": [{"type": "mcp", "id": "new-id", "version": "2.0"}],
            }
        ],
    )
    assert cmd_update._verify(candidate) is True


def test_agent_lock_with_duplicate_or_missing_pins_is_not_verified(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    candidate = item(tmp_path)
    installed = {
        **candidate,
        "current_version": "2.0",
        "components": [
            {"type": "skill", "id": "skill-id", "version": "2.0"},
            {"type": "skill", "id": "skill-id", "version": "2.0"},
        ],
    }
    monkeypatch.setattr(cmd_update, "_entries", lambda _harness: [installed])
    assert cmd_update._verify(candidate) is False
    installed["components"] = []
    assert cmd_update._verify(candidate) is False


def test_project_context_is_exact_and_agent_project_pin_is_not_overridden(tmp_path: Path) -> None:
    project = item(tmp_path, "agent", "project")
    assert cmd_update._plan(project, project=tmp_path)[0] is None
    assert "observal.lock" in cmd_update._plan(project, project=tmp_path)[1]
    other = tmp_path / "nested"
    other.mkdir()
    assert cmd_update._plan(project, project=other)[0] is None
    hook = item(tmp_path, "hook", "project")
    argv, reason, root = cmd_update._plan(hook, project=tmp_path)
    assert reason is None and root == tmp_path and argv[-2:] == ["--dir", str(tmp_path)]
    assert cmd_update._plan(hook, project=None)[0] is None


def test_mcp_is_notice_only_even_if_recorded(tmp_path: Path) -> None:
    argv, reason, _ = cmd_update._plan(item(tmp_path, "mcp"), project=None)
    assert argv is None and "snippet" in reason


def test_success_requires_fresh_exact_lock_and_unpinned_skill(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    skill = item(tmp_path, "skill")
    rows = [skill]
    inventory(monkeypatch, rows)
    monkeypatch.chdir(tmp_path)
    invoked = []

    def install(argv, *, cwd, env, stdin, stdout, stderr, check):
        invoked.append((argv, cwd, env))
        assert stdin == stdout == stderr == subprocess.DEVNULL and check is False
        rows[0] = {**skill, "current_version": "2.0"}
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(cmd_update.subprocess, "run", install)
    result = cmd_update.run_updates(harness="pi", project=None, apply=True)
    assert result[0]["status"] == "updated"
    assert invoked[0][2]["OBSERVAL_UPDATE_EXACT_TARGET"] == "1"
    assert invoked[0][0][:6] == [cmd_update.sys.executable, "-m", "observal_cli", "registry", "skill", "install"]
    assert "--version" in invoked[0][0]
    assert invoked[0][1] == tmp_path


def test_agent_batch_uses_exact_target_without_creating_user_pin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    candidate = item(tmp_path)
    rows = [candidate]
    inventory(monkeypatch, rows)

    def install(_argv, **kwargs):
        assert kwargs["env"]["OBSERVAL_UPDATE_EXACT_TARGET"] == "1"
        rows[0] = {
            **candidate,
            "current_version": "2.0",
            "components": [{"type": "skill", "id": "skill-id", "version": "2.0"}],
        }
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(cmd_update.subprocess, "run", install)
    assert cmd_update.run_updates(harness="pi", project=None, apply=True)[0]["status"] == "updated"


def test_exit_zero_without_installed_version_is_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    skill = item(tmp_path, "skill")
    inventory(monkeypatch, [skill])
    run = MagicMock(return_value=SimpleNamespace(returncode=0))
    monkeypatch.setattr(cmd_update.subprocess, "run", run)
    result = cmd_update.run_updates(harness=None, project=None, apply=True)
    assert result[0]["status"] == "failed"
    assert "could not be verified" in result[0]["reason"]


def test_preview_never_calls_installer(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    inventory(monkeypatch, [item(tmp_path)])
    run = MagicMock(side_effect=AssertionError("preview wrote files"))
    monkeypatch.setattr(cmd_update.subprocess, "run", run)
    result = cmd_update.run_updates(harness=None, project=None, apply=False)
    assert result[0]["status"] == "available"
    run.assert_not_called()


def test_real_cli_reinstalls_unpinned_skill_in_isolated_home(tmp_path: Path) -> None:
    skill_id = "22222222-2222-4222-8222-222222222222"

    class Registry(BaseHTTPRequestHandler):
        def log_message(self, *_args: object) -> None:
            pass

        def respond(self, value: dict) -> None:
            body = json.dumps(value).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            if self.path == "/api/v1/config/version":
                return self.respond({"server_version": "dev"})
            if self.path == f"/api/v1/skills/{skill_id}":
                return self.respond(
                    {"id": skill_id, "name": "review", "namespace": "alice", "slug": "review", "version": "2.0.0"}
                )
            if self.path == f"/api/v1/skills/{skill_id}/versions/2.0.0":
                return self.respond(
                    {
                        "version": "2.0.0",
                        "status": "approved",
                        "supported_harnesses": ["pi"],
                        "description": "Author review notes",
                    }
                )
            self.send_error(404)

        def do_POST(self) -> None:
            if self.path == f"/api/v1/skills/{skill_id}/install":
                request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                assert request["version"] == "2.0.0" and request["harness"] == "pi"
                return self.respond(
                    {
                        "version": "2.0.0",
                        "digest": "target-digest",
                        "config_snippet": {
                            "skill": {
                                "id": skill_id,
                                "name": "review",
                                "delivery_mode": "registry_direct",
                                "skill_md_content": "new skill",
                            }
                        },
                    }
                )
            self.send_error(404)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Registry)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    home = tmp_path / "home"
    home.mkdir()
    config = home / ".observal/config.json"
    config.parent.mkdir()
    registry = f"http://127.0.0.1:{server.server_port}"
    config.write_text(json.dumps({"server_url": registry, "user_id": "alice", "access_token": "test-token"}))
    skill = home / ".pi/agent/skills/review/SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("old skill")
    env = {
        **os.environ,
        "HOME": str(home),
        "XDG_CONFIG_HOME": str(home / ".config"),
        "PYTHONPATH": os.pathsep.join(
            [
                str(Path(__file__).resolve().parents[1]),
                str(Path(__file__).resolve().parents[1] / "packages/observal-shared"),
            ]
        ),
    }
    bootstrap = (
        "from observal_cli import lockfile; "
        f"lockfile.upsert_standalone('pi', component_type='skill', name='review', component_id={skill_id!r}, "
        "version='1.0.0', scope='user', namespace='alice', slug='review')"
    )
    try:
        subprocess.run([sys.executable, "-c", bootstrap], env=env, cwd=tmp_path, check=True, capture_output=True)
        preview = subprocess.run(
            [sys.executable, "-m", "observal_cli", "update", "--all", "--output", "json"],
            env=env,
            cwd=tmp_path,
            check=True,
            capture_output=True,
            text=True,
        )
        assert json.loads(preview.stdout)["summary"]["available"] == 1
        assert skill.read_text() == "old skill"
        applied = subprocess.run(
            [sys.executable, "-m", "observal_cli", "update", "--all", "--yes", "--output", "json"],
            env=env,
            cwd=tmp_path,
            check=True,
            capture_output=True,
            text=True,
        )
        data = json.loads(applied.stdout)
        assert data["summary"]["updated"] == 1, data
        assert skill.read_text() == "new skill"
        after = subprocess.run(
            [
                sys.executable,
                "-c",
                "import json; from observal_cli.lockfile import get_all_entries; "
                "print(json.dumps(get_all_entries('pi')))",
            ],
            env=env,
            cwd=tmp_path,
            check=True,
            capture_output=True,
            text=True,
        )
        recorded = json.loads(after.stdout)[0]
        assert recorded["version"] == "2.0.0" and "requested_version" not in recorded
        assert data["items"][0]["description"] == "Author review notes"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_cli_requires_explicit_all_and_yes_and_keeps_json_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    app = typer.Typer(name="observal", cls=ErrorHandlingGroup)
    app.callback()(lambda: None)
    cmd_update.register_update(app)
    result = CliRunner().invoke(app, ["update", "--output", "json"])
    assert result.exit_code != 0
    monkeypatch.setattr(
        cmd_update,
        "run_updates",
        lambda **kwargs: [
            {
                "name": "alice/agent",
                "current_version": "1.0",
                "target_version": "2.0",
                "status": "available" if not kwargs["apply"] else "updated",
                "reason": None,
            }
        ],
    )
    preview = CliRunner().invoke(app, ["update", "--all", "--output", "json"])
    assert preview.exit_code == 0 and json.loads(preview.stdout)["summary"]["available"] == 1
    applied = CliRunner().invoke(app, ["update", "--all", "--yes", "--output", "json"])
    assert applied.exit_code == 0 and json.loads(applied.stdout)["summary"]["updated"] == 1
