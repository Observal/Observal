# SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Agent-to-agent delegation on the CLI side: tasks, isolation, headless runs, A2A client, MCP server."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import httpx
import pytest

from observal_cli import capability_lock
from observal_cli.cmd_pull import rewrite_observal_interpreter
from observal_cli.delegation import a2a_client, local, mcp_server, runner, service, tasks, workspace
from observal_cli.harness import NotSupportedError, ensure_loaded, get_adapter
from observal_cli.harness.protocol import HeadlessPlan, HeadlessRequest

AGENT_ID = "5f2c1a9e-8b1d-4d0c-9c4e-1f2a3b4c5d6e"
AGENT_URN = f"urn:air:observal.example.com:agent:{AGENT_ID}"
A2A_URN = "urn:air:agents.acme.com:a2a:incident-triage"
HAS_GIT = shutil.which("git") is not None


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(tasks, "STORE_DIR", tmp_path / "delegations")
    for name in ("OBSERVAL_DELEGATION_DEPTH", "OBSERVAL_DELEGATION_CHAIN", "OBSERVAL_DELEGATION_MAX_DEPTH"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(service, "SPAWN", None)


def _git(cwd: Path, *args: str) -> str:
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t"}
    env["GIT_COMMITTER_EMAIL"] = "t@t"
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, env=env, check=True).stdout


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    (repo / "app.py").write_text("print('v1')\n")
    (repo / ".gitignore").write_text("secret.env\n.claude/\n")
    _git(repo, "add", "-A")
    _git(repo, "-c", "commit.gpgsign=false", "commit", "-q", "-m", "init")
    return repo


# ── Tasks ────────────────────────────────────────────────────────────────


def test_task_round_trip_and_state_normalisation():
    task = tasks.new_task(message="review auth", observal={"target": AGENT_URN})
    tasks.save(task)
    loaded = tasks.load(task["id"])
    assert loaded["status"]["state"] == tasks.STATE_SUBMITTED
    assert tasks.message_text(loaded["history"][0]) == "review auth"
    assert loaded["history"][0]["role"] == "ROLE_USER"
    assert tasks.normalize_state("input-required") == tasks.STATE_INPUT_REQUIRED
    assert tasks.normalize_state("TASK_STATE_COMPLETED") == tasks.STATE_COMPLETED
    assert tasks.load("../../etc/passwd") is None  # ids are UUIDs, never paths


# ── Workspace isolation ──────────────────────────────────────────────────


@pytest.mark.skipif(not HAS_GIT, reason="git not installed")
def test_workspace_mirrors_the_callers_tree_and_returns_only_the_childs_changes(tmp_path):
    repo = _repo(tmp_path)
    (repo / "app.py").write_text("print('v2 uncommitted')\n")
    (repo / "notes.md").write_text("untracked notes\n")
    (repo / "secret.env").write_text("TOKEN=x\n")

    ws = workspace.create(repo)
    try:
        assert (ws.path / "app.py").read_text() == "print('v2 uncommitted')\n"
        assert (ws.path / "notes.md").exists()
        assert not (ws.path / "secret.env").exists()  # ignored files stay behind
        (ws.path / ".claude" / "agents").mkdir(parents=True)
        (ws.path / ".claude" / "agents" / "reviewer.md").write_text("config")
        (ws.path / "AGENT_CONFIG.json").write_text("{}")  # agent config written before the baseline
        workspace.mark_baseline(ws)

        (ws.path / "app.py").write_text("print('v3 from child')\n")
        (ws.path / "new_test.py").write_text("def test_x():\n    pass\n")
        patch = workspace.changes(ws)
    finally:
        workspace.destroy(ws)

    assert "v3 from child" in patch and "new_test.py" in patch
    assert "AGENT_CONFIG.json" not in patch
    # The caller's own tree is untouched and the worktree is gone.
    assert (repo / "app.py").read_text() == "print('v2 uncommitted')\n"
    assert not (repo / "new_test.py").exists()
    assert "observal-delegate" not in _git(repo, "worktree", "list")
    # The patch applies cleanly to the caller's tree.
    subprocess.run(["git", "-C", str(repo), "apply", "-"], input=patch, text=True, check=True)
    assert (repo / "app.py").read_text() == "print('v3 from child')\n"


def test_workspace_outside_git_is_an_empty_directory(tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    (plain / "file.txt").write_text("x")
    ws = workspace.create(plain)
    try:
        assert not ws.is_git and list(ws.path.iterdir()) == []
        assert workspace.changes(ws) == ""
    finally:
        workspace.destroy(ws)


# ── Local headless runs ──────────────────────────────────────────────────


class FakeAdapter:
    harness_name = "claude-code"

    def __init__(self, script: str) -> None:
        self.script = script

    def headless_command(self, request: HeadlessRequest) -> HeadlessPlan:
        return HeadlessPlan(argv=[sys.executable, "-c", self.script], stdin=request.message, session_id="child-1")

    def parse_headless_output(self, plan: HeadlessPlan, stdout: str):
        from observal_cli.harness.base import BaseAdapter

        return BaseAdapter.parse_headless_output(self, plan, stdout)


def _local_task(cwd: Path) -> dict:
    task = tasks.new_task(
        message="add a test",
        observal={"target": AGENT_URN, "kind": "agent", "agentId": AGENT_ID, "harness": "claude-code", "cwd": str(cwd)},
    )
    return tasks.save(task)


def _fake_materialize(task, ws, *, harness, adapter):
    (ws.path / "AGENT.md").write_text("agent profile")
    return "reviewer", {}, "Review carefully."


@pytest.mark.skipif(not HAS_GIT, reason="git not installed")
def test_local_run_returns_answer_and_patch_without_touching_the_caller(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    script = textwrap.dedent(
        """
        import os, sys
        brief = sys.stdin.read()
        open("app.py", "w").write("print('fixed')\\n")
        print("did it: " + brief + " depth=" + os.environ["OBSERVAL_DELEGATION_DEPTH"])
        """
    )
    monkeypatch.setattr(local, "get_adapter", lambda _h: FakeAdapter(script))
    monkeypatch.setattr(local, "materialize", _fake_materialize)
    task = local.run(_local_task(repo), save=tasks.save, should_cancel=lambda: False)

    assert task["status"]["state"] == tasks.STATE_COMPLETED, task["status"]
    result, patch = task["artifacts"]
    assert tasks.message_text(result) == "did it: add a test depth=1"
    assert patch["name"] == "changes.patch" and "print('fixed')" in tasks.message_text(patch)
    assert "AGENT.md" not in tasks.message_text(patch)
    m = tasks.meta(task)
    assert Path(m["patchPath"]).is_file() and m["childSessionId"] == "child-1"
    assert (repo / "app.py").read_text() == "print('v1')\n"


@pytest.mark.skipif(not HAS_GIT, reason="git not installed")
def test_local_run_can_be_canceled(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    monkeypatch.setattr(local, "get_adapter", lambda _h: FakeAdapter("import time; time.sleep(60)"))
    monkeypatch.setattr(local, "materialize", _fake_materialize)
    started = time.monotonic()
    calls = {"n": 0}

    def cancel_soon():
        calls["n"] += 1
        return calls["n"] > 1

    task = local.run(_local_task(repo), save=tasks.save, should_cancel=cancel_soon)
    assert task["status"]["state"] == tasks.STATE_CANCELED
    assert time.monotonic() - started < 30


@pytest.mark.skipif(not HAS_GIT, reason="git not installed")
def test_local_run_reports_a_failing_child(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    script = "import sys; sys.stderr.write('model quota exceeded'); sys.exit(3)"
    monkeypatch.setattr(local, "get_adapter", lambda _h: FakeAdapter(script))
    monkeypatch.setattr(local, "materialize", _fake_materialize)
    task = local.run(_local_task(repo), save=tasks.save, should_cancel=lambda: False)
    assert task["status"]["state"] == tasks.STATE_FAILED
    assert "model quota exceeded" in tasks.message_text(task["status"]["message"])


@pytest.mark.skipif(not HAS_GIT, reason="git not installed")
def test_local_run_with_no_answer_and_no_changes_fails_even_on_exit_zero(tmp_path, monkeypatch):
    # Kiro prints an expired-login error to stderr and exits 0.
    repo = _repo(tmp_path)
    script = "import sys; sys.stderr.write('\\x1b[38;5;9mAuthentication failed.\\x1b[0m')"
    monkeypatch.setattr(local, "get_adapter", lambda _h: FakeAdapter(script))
    monkeypatch.setattr(local, "materialize", _fake_materialize)
    task = local.run(_local_task(repo), save=tasks.save, should_cancel=lambda: False)
    assert task["status"]["state"] == tasks.STATE_FAILED
    assert tasks.message_text(task["status"]["message"]) == "Authentication failed."


def test_mcp_servers_come_from_either_snippet_shape():
    ensure_loaded()
    claude = get_adapter("claude-code")
    assert local.mcp_servers_from_snippet({"mcp_config": {"gh": {"command": "gh-mcp"}}}, claude) == {
        "gh": {"command": "gh-mcp"}
    }
    kiro = get_adapter("kiro")
    snippet = {"mcp_config": {"path": ".kiro/settings/mcp.json", "content": {"mcpServers": {"gh": {"command": "x"}}}}}
    assert local.mcp_servers_from_snippet(snippet, kiro) == {"gh": {"command": "x"}}


# ── Service guards ───────────────────────────────────────────────────────


def _agent_entry(**overrides) -> dict:
    entry = {
        "identifier": AGENT_URN,
        "displayName": "Security Reviewer",
        "type": service.MEDIA_AGENT,
        "version": "1.0.0",
        "obs:nativeRef": "acme/security-reviewer@1.0.0",
        "obs:lifecycle": "approved",
        "obs:delegable": True,
        "obs:supportedHarnesses": ["claude-code", "kiro"],
    }
    entry.update(overrides)
    return entry


def test_start_refuses_past_the_depth_limit(monkeypatch):
    monkeypatch.setenv("OBSERVAL_DELEGATION_DEPTH", "2")
    with pytest.raises(service.DelegationError, match="depth limit"):
        service.start(AGENT_URN, "do it")


def test_start_refuses_loops_and_unapproved_agents(monkeypatch):
    monkeypatch.setattr(service.client, "get", lambda *_a, **_k: _agent_entry())
    monkeypatch.setenv("OBSERVAL_DELEGATION_CHAIN", AGENT_URN)
    with pytest.raises(service.DelegationError, match="loop"):
        service.start(AGENT_URN, "do it")
    monkeypatch.delenv("OBSERVAL_DELEGATION_CHAIN")
    with pytest.raises(service.DelegationError, match="loop"):
        service.start(AGENT_URN, "do it", parent_agent_id=AGENT_ID)
    monkeypatch.setattr(service.client, "get", lambda *_a, **_k: _agent_entry(**{"obs:lifecycle": "pending"}))
    with pytest.raises(service.DelegationError, match="not approved"):
        service.start(AGENT_URN, "do it")


def test_choose_harness_prefers_the_caller_and_respects_support(monkeypatch):
    monkeypatch.setattr(service, "headless_harnesses", lambda: ["kiro", "claude-code", "codex"])
    assert service.choose_harness(["claude-code", "kiro"], "kiro") == "kiro"
    assert service.choose_harness(["claude-code"], "kiro") == "claude-code"
    assert service.choose_harness([], None) == "kiro"
    with pytest.raises(service.DelegationError, match="only kiro, claude-code, codex"):
        service.choose_harness(["goose"], None)
    monkeypatch.setattr(service, "headless_harnesses", lambda: [])
    with pytest.raises(service.DelegationError, match="No harness"):
        service.choose_harness([], None)


def test_start_records_the_delegation_and_runs_the_worker(tmp_path, monkeypatch):
    monkeypatch.setattr(service.client, "get", lambda *_a, **_k: _agent_entry())
    monkeypatch.setattr(service, "headless_harnesses", lambda: ["claude-code"])

    def fake_worker(task_id):
        task = tasks.load(task_id)
        task["artifacts"] = [tasks.text_artifact("result", "No auth bugs found.")]
        tasks.save(tasks.set_status(task, tasks.STATE_COMPLETED, "Done."))
        return None

    monkeypatch.setattr(service, "SPAWN", fake_worker)
    task = service.start(AGENT_URN, "Review src/auth", parent_harness="kiro", cwd=tmp_path, wait_seconds=5)
    assert task["status"]["state"] == tasks.STATE_COMPLETED
    m = tasks.meta(task)
    assert m["harness"] == "claude-code" and m["depth"] == 0 and m["agentId"] == AGENT_ID
    summary = service.summarize(task)
    assert "No auth bugs found." in summary and "TASK_STATE_COMPLETED" in summary

    uses = capability_lock.read_all()
    assert [(u.kind, u.mode, u.identifier, u.harness) for u in uses] == [("agent", "delegated", AGENT_URN, "kiro")]
    assert uses[0].extra["task_id"] == task["id"]


def test_dead_worker_is_reported_instead_of_hanging(monkeypatch, tmp_path):
    task = tasks.save(tasks.new_task(message="x", observal={"target": AGENT_URN}))
    tasks.task_dir(task["id"]).joinpath("worker.pid").write_text("999999")
    monkeypatch.setattr(service, "_pid_alive", lambda _pid: False)
    assert service.get(task["id"])["status"]["state"] == tasks.STATE_FAILED


# ── Remote A2A ───────────────────────────────────────────────────────────


def _a2a_entry(version="1.0", schemes=None) -> dict:
    return {
        "obs:a2aInterface": {
            "url": "https://agents.acme.com/a2a/v1",
            "protocolBinding": "JSONRPC",
            "protocolVersion": version,
        },
        "obs:agentCard": {"name": "Incident Triage", "securitySchemes": schemes or {}},
    }


def _a2a_task() -> dict:
    return tasks.save(tasks.new_task(message="triage INC-42", observal={"target": A2A_URN, "kind": "a2a"}))


def test_a2a_v1_send_then_poll_until_completed(monkeypatch):
    monkeypatch.setattr(a2a_client, "POLL_SECONDS", 0)
    monkeypatch.setenv("OBSERVAL_A2A_TOKEN_INCIDENT_TRIAGE", "tok")
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append({"method": body["method"], "headers": dict(request.headers), "params": body["params"]})
        if body["method"] == "SendMessage":
            task = {"id": "r-1", "contextId": "c-1", "status": {"state": "TASK_STATE_WORKING"}}
        else:
            task = {
                "id": "r-1",
                "contextId": "c-1",
                "status": {"state": "TASK_STATE_COMPLETED"},
                "artifacts": [{"artifactId": "a", "name": "report", "parts": [{"text": "Root cause: bad deploy"}]}],
            }
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": {"task": task}})

    entry = _a2a_entry(schemes={"bearer": {"httpAuthSecurityScheme": {"scheme": "Bearer"}}})
    task = a2a_client.run(
        _a2a_task(), entry=entry, save=tasks.save, should_cancel=lambda: False, transport=httpx.MockTransport(handler)
    )
    assert task["status"]["state"] == tasks.STATE_COMPLETED
    assert tasks.message_text(task["artifacts"][0]) == "Root cause: bad deploy"
    assert [s["method"] for s in seen] == ["SendMessage", "GetTask"]
    first = seen[0]
    assert first["headers"]["a2a-version"] == "1.0"
    assert first["headers"]["authorization"] == "Bearer tok"
    assert first["params"]["message"]["role"] == "ROLE_USER"
    assert first["params"]["message"]["parts"] == [{"text": "triage INC-42"}]
    assert first["params"]["configuration"] == {"returnImmediately": True}
    assert tasks.meta(task)["remoteTaskId"] == "r-1"


def test_a2a_v03_agent_uses_legacy_methods_and_can_ask_for_input():
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append(body["method"])
        assert body["params"]["message"]["parts"] == [{"kind": "text", "text": "triage INC-42"}]
        result = {
            "kind": "task",
            "id": "r-9",
            "contextId": "c-9",
            "status": {
                "state": "input-required",
                "message": {"role": "agent", "parts": [{"kind": "text", "text": "Which region?"}]},
            },
        }
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": result})

    task = a2a_client.run(
        _a2a_task(),
        entry=_a2a_entry(version="0.3.0"),
        save=tasks.save,
        should_cancel=lambda: False,
        transport=httpx.MockTransport(handler),
    )
    assert seen == ["message/send"]
    assert task["status"]["state"] == tasks.STATE_INPUT_REQUIRED
    assert "Which region?" in service.summarize(task)


def test_a2a_direct_message_answer_and_errors():
    def message_handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        msg = {"messageId": "m", "role": "ROLE_AGENT", "parts": [{"text": "Hi there"}]}
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": {"message": msg}})

    task = a2a_client.run(
        _a2a_task(),
        entry=_a2a_entry(),
        save=tasks.save,
        should_cancel=lambda: False,
        transport=httpx.MockTransport(message_handler),
    )
    assert task["status"]["state"] == tasks.STATE_COMPLETED
    assert tasks.message_text(task["artifacts"][0]) == "Hi there"

    def denied(_request):
        return httpx.Response(401, json={})

    task = a2a_client.run(
        _a2a_task(),
        entry=_a2a_entry(),
        save=tasks.save,
        should_cancel=lambda: False,
        transport=httpx.MockTransport(denied),
    )
    assert task["status"]["state"] == tasks.STATE_FAILED
    assert "OBSERVAL_A2A_TOKEN" in tasks.message_text(task["status"]["message"])


def test_api_key_scheme_uses_its_header(monkeypatch):
    monkeypatch.setenv("OBSERVAL_A2A_TOKEN", "k")
    card = {"securitySchemes": {"key": {"apiKeySecurityScheme": {"location": "header", "name": "X-Agent-Key"}}}}
    assert a2a_client.auth_headers(card, A2A_URN) == {"X-Agent-Key": "k"}
    assert a2a_client.auth_headers({"securitySchemes": {}}, A2A_URN) == {}


def test_runner_rejects_a_remote_agent_that_lost_approval(monkeypatch):
    task = _a2a_task()
    monkeypatch.setattr(runner.client, "get", lambda *_a, **_k: {"obs:lifecycle": "rejected"})
    done = runner.run_task(task["id"])
    assert done["status"]["state"] == tasks.STATE_REJECTED


# ── MCP server ───────────────────────────────────────────────────────────


def _rpc(server: mcp_server.Server, method: str, params: dict | None = None, req_id: int = 1) -> dict:
    return server.handle({"jsonrpc": "2.0", "id": req_id, "method": method, "params": params or {}})


def test_mcp_initialize_and_tools(monkeypatch):
    import io

    server = mcp_server.Server(harness="kiro", parent_id=AGENT_ID, out=io.StringIO())
    init = _rpc(server, "initialize", {"protocolVersion": "2025-03-26"})["result"]
    assert init["protocolVersion"] == "2025-03-26" and init["serverInfo"]["name"] == "observal-agents"
    names = [t["name"] for t in _rpc(server, "tools/list")["result"]["tools"]]
    assert names == ["find_agents", "delegate", "get_task", "cancel_task"]
    assert server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None

    monkeypatch.setattr(service, "find_agents", lambda text, limit: [{"identifier": AGENT_URN, "name": "Reviewer"}])
    found = _rpc(server, "tools/call", {"name": "find_agents", "arguments": {"task": "review"}})["result"]
    assert found["isError"] is False and AGENT_URN in found["content"][0]["text"]

    captured = {}

    def fake_start(agent, message, **kwargs):
        captured.update(kwargs, agent=agent)
        raise service.DelegationError("Delegation depth limit reached (2).")

    monkeypatch.setattr(service, "start", fake_start)
    refused = _rpc(server, "tools/call", {"name": "delegate", "arguments": {"agent": AGENT_URN, "message": "x"}})
    assert refused["result"]["isError"] is True and "depth limit" in refused["result"]["content"][0]["text"]
    assert captured["parent_harness"] == "kiro" and captured["parent_agent_id"] == AGENT_ID

    missing = _rpc(server, "tools/call", {"name": "delegate", "arguments": {"message": "x"}})["result"]
    assert missing["isError"] is True
    assert _rpc(server, "bogus")["error"]["code"] == -32601


def test_mcp_server_speaks_newline_json_on_stdio(tmp_path):
    lines = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    ]
    root = Path(__file__).resolve().parents[1]
    env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(root), str(root / "packages" / "observal-shared")])}
    proc = subprocess.run(
        [sys.executable, "-m", "observal_cli.delegation.mcp_server", "--harness", "claude-code"],
        input="".join(json.dumps(line) + "\n" for line in lines),
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
        cwd=str(tmp_path),
    )
    out = [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]
    assert [o["id"] for o in out] == [1, 2]
    assert out[0]["result"]["protocolVersion"] == "2025-06-18"
    assert len(out[1]["result"]["tools"]) == 4


# ── Harness adapters ─────────────────────────────────────────────────────


def _request(tmp_path: Path, **overrides) -> HeadlessRequest:
    values = {
        "agent_name": "security-reviewer",
        "instructions": "You review code for auth bugs.",
        "message": "-- review src/auth",
        "workdir": tmp_path,
        "scratch_dir": tmp_path,
        "session_id": "11111111-1111-1111-1111-111111111111",
        "mcp_servers": {"github": {"command": "gh-mcp"}},
    }
    values.update(overrides)
    return HeadlessRequest(**values)


def test_claude_code_headless_command_and_output(tmp_path):
    ensure_loaded()
    adapter = get_adapter("claude-code")
    plan = adapter.headless_command(_request(tmp_path))
    assert plan.argv[:4] == ["claude", "-p", "--agent", "security-reviewer"]
    assert plan.stdin == "-- review src/auth"  # never on argv, so it cannot be read as a flag
    assert "--strict-mcp-config" in plan.argv and "mcp__github" in plan.argv
    assert json.loads((tmp_path / "mcp.json").read_text()) == {"mcpServers": {"github": {"command": "gh-mcp"}}}
    result = adapter.parse_headless_output(
        plan, '{"type":"result","result":"All clear","is_error":false,"session_id":"abc"}\n'
    )
    assert (result.text, result.session_id, result.error) == ("All clear", "abc", None)
    failed = adapter.parse_headless_output(plan, '{"type":"result","result":"","is_error":true}')
    assert failed.error


@pytest.mark.parametrize(
    ("harness", "binary", "inlined"),
    [
        ("kiro", "kiro-cli", False),
        ("cursor", "cursor-agent", True),
        ("codex", "codex", True),
        ("opencode", "opencode", False),
        ("antigravity", "agy", True),
        ("copilot-cli", "copilot", False),
    ],
)
def test_other_headless_commands(tmp_path, harness, binary, inlined):
    ensure_loaded()
    adapter = get_adapter(harness)
    plan = adapter.headless_command(_request(tmp_path))
    assert plan.argv[0] == binary == adapter.headless_binary
    joined = "\n".join(plan.argv)
    assert ("<agent-instructions>" in joined) is inlined
    assert "-- review src/auth" in joined


@pytest.mark.parametrize("harness", ["goose", "pi", "copilot"])
def test_harnesses_without_verified_headless_mode_refuse(tmp_path, harness):
    ensure_loaded()
    with pytest.raises(NotSupportedError):
        get_adapter(harness).headless_command(_request(tmp_path))


def test_codex_answer_is_read_from_its_output_file(tmp_path):
    ensure_loaded()
    adapter = get_adapter("codex")
    plan = adapter.headless_command(_request(tmp_path))
    plan.output_file.write_text("final answer\n")
    assert adapter.parse_headless_output(plan, "noise").text == "final answer"


def test_rewrite_observal_interpreter_handles_entries_and_argv():
    snippet = {
        "mcp_config": {"observal-agents": {"command": "python3", "args": ["-m", "observal_cli.delegation.mcp_server"]}},
        "mcp_setup_commands": [["claude", "mcp", "add", "x", "--", "python3", "-m", "observal_cli.sandbox_mcp"]],
        "other": {"command": "python3", "args": ["-m", "http.server"]},
    }
    out = rewrite_observal_interpreter(snippet)
    assert out["mcp_config"]["observal-agents"]["command"] == sys.executable
    assert out["mcp_setup_commands"][0][5] == sys.executable
    assert out["other"]["command"] == "python3"
