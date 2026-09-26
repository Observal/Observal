# SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Find agents to delegate to, start a delegation, and follow it.

Used by ``observal delegate`` and by the observal-agents MCP server. Every
start is checked before anything runs:

- only approved, delegable entries (``obs:delegable`` from ARD search);
- depth: a delegated agent may delegate again, up to
  ``OBSERVAL_DELEGATION_MAX_DEPTH`` levels (default 2);
- cycles: an agent already in the chain, or the caller itself, is refused.

The work itself runs in a detached worker (``delegation.runner``) so a task
outlives the MCP call or CLI process that started it; callers wait as long as
they like and pick the result up later by task id.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING

from observal_cli import capability_lock, client
from observal_cli.delegation import tasks

if TYPE_CHECKING:
    from collections.abc import Callable

MEDIA_AGENT = "application/vnd.observal.agent+json"
MEDIA_A2A = "application/a2a-agent-card+json"
DEFAULT_MAX_DEPTH = 2
MAX_WAIT_SECONDS = 30 * 60
WAIT_POLL_SECONDS = 0.5
MAX_MESSAGE_CHARS = 100_000
# A delegated agent runs headless with no permission prompt, so its fan-out is capped.
MAX_CHILD_TASKS = 3

# Tests replace this to run the worker inline instead of detaching a process.
SPAWN: Callable[[str], int | None] | None = None


class DelegationError(Exception):
    """A refusal or failure whose message is safe to show the calling agent."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


# ── Chain ────────────────────────────────────────────────────────────────


def current_depth() -> int:
    try:
        return max(0, int(os.environ.get("OBSERVAL_DELEGATION_DEPTH", "0")))
    except ValueError:
        return 0


def max_depth() -> int:
    try:
        return max(0, int(os.environ.get("OBSERVAL_DELEGATION_MAX_DEPTH", str(DEFAULT_MAX_DEPTH))))
    except ValueError:
        return DEFAULT_MAX_DEPTH


def current_chain() -> list[str]:
    return [c for c in os.environ.get("OBSERVAL_DELEGATION_CHAIN", "").split(",") if c]


# ── Find ─────────────────────────────────────────────────────────────────


def _kind(entry: dict) -> str:
    return "a2a" if entry.get("type") == MEDIA_A2A else "agent"


def find_agents(text: str, *, limit: int = 5) -> list[dict]:
    """Approved agents (registry and remote A2A) that can take a task, best match first."""
    text = (text or "").strip()
    if not text:
        raise DelegationError("Describe the task to find an agent for it.")
    body = {
        "query": {"text": text[:2000], "filter": {"type": [MEDIA_AGENT, MEDIA_A2A], "obs:lifecycle": ["approved"]}},
        "federation": "none",
        "pageSize": min(100, max(limit * 3, 10)),
    }
    data = client.post("/api/v1/ard/search", body, operation="Find agents to delegate to", resource="discovery search")
    results = [r for r in (data.get("results") or []) if r.get("obs:delegable")]
    return [
        {
            "identifier": r.get("identifier"),
            "name": r.get("displayName"),
            "kind": _kind(r),
            "description": r.get("description"),
            "score": r.get("score"),
            "version": r.get("version"),
            "harnesses": r.get("obs:supportedHarnesses") or [],
            "ref": r.get("obs:nativeRef"),
        }
        for r in results[:limit]
    ]


# ── Resolve ──────────────────────────────────────────────────────────────


def _entry_for(reference: str) -> dict:
    ref = reference.strip()
    if ref.startswith(("urn:air:", "urn:ai:")):
        return client.get(f"/api/v1/ard/entries/{ref}", operation="Delegate to agent", resource=ref)
    # A registry reference (namespace/slug, UUID, alias): shape the agent detail like an entry.
    agent_id = client.resolve_registry_reference("agent", ref)
    detail = client.get(f"/api/v1/agents/{agent_id}", operation="Delegate to agent", resource=ref)
    status = str(detail.get("status") or "")
    return {
        "identifier": None,
        "displayName": detail.get("name"),
        "type": MEDIA_AGENT,
        "version": detail.get("latest_approved_version") or detail.get("version"),
        "obs:kind": "agent",
        "obs:nativeRef": f"{detail.get('qualified_name') or ref}@{detail.get('version', '')}",
        "obs:lifecycle": "approved" if status == "approved" or detail.get("latest_approved_version") else status,
        "obs:supportedHarnesses": detail.get("supported_harnesses") or detail.get("inferred_supported_harnesses") or [],
        "obs:delegable": True,
        "_agentId": str(detail.get("id") or agent_id),
    }


def _agent_id(entry: dict) -> str | None:
    if entry.get("_agentId"):
        return entry["_agentId"]
    identifier = entry.get("identifier") or ""
    parts = identifier.split(":")
    if len(parts) == 5 and parts[3] == "agent":
        return parts[4]
    return None


def headless_harnesses() -> list[str]:
    """Harnesses that can run a delegated agent on this machine right now."""
    from observal_cli.harness import ensure_loaded, get_all_adapters
    from observal_shared.harness_registry import HARNESS_REGISTRY

    ensure_loaded()
    out = []
    for name, adapter in get_all_adapters().items():
        binary = getattr(adapter, "headless_binary", None)
        if HARNESS_REGISTRY.get(name, {}).get("headless_run") and binary and shutil.which(binary):
            out.append(name)
    return out


def choose_harness(supported: list[str], preferred: str | None) -> str:
    available = headless_harnesses()
    ordered = ([preferred] if preferred else []) + [h for h in available if h != preferred]
    for harness in ordered:
        if harness in available and (not supported or harness in supported):
            return harness
    if not available:
        raise DelegationError(
            "No harness on this machine can run an agent headless. Install one of: Claude Code, Kiro CLI, "
            "Cursor CLI, Codex, OpenCode, Copilot CLI or Antigravity."
        )
    raise DelegationError(
        f"The agent supports {', '.join(supported)}, but only {', '.join(available)} can run headless here."
    )


# ── Worker ───────────────────────────────────────────────────────────────


def _pid_alive(pid: int | None) -> bool:
    if not pid:
        return False
    if sys.platform == "win32":
        import ctypes

        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, int(pid))  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        code = ctypes.c_ulong()
        ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
        ctypes.windll.kernel32.CloseHandle(handle)
        return code.value == 259  # STILL_ACTIVE
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _spawn(task_id: str) -> int | None:
    if SPAWN is not None:
        return SPAWN(task_id)
    log = tasks.task_dir(task_id) / "worker.log"
    kwargs: dict = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = (
            subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
        )
    else:
        kwargs["start_new_session"] = True
    with log.open("ab") as handle:
        proc = subprocess.Popen(
            [sys.executable, "-m", "observal_cli.delegation.runner", task_id],
            stdin=subprocess.DEVNULL,
            stdout=handle,
            stderr=subprocess.STDOUT,
            close_fds=True,
            **kwargs,
        )
    return proc.pid


def _worker_pid(task_id: str) -> int | None:
    try:
        return int((tasks.store_dir() / task_id / "worker.pid").read_text().strip())
    except (OSError, ValueError):
        return None


def _launch(task: dict) -> None:
    tasks.clear_cancel(task["id"])
    tasks.save(task)
    pid = _spawn(task["id"])
    if pid:
        # A side file, not the task: the worker owns the task file once it starts.
        tasks.task_dir(task["id"]).joinpath("worker.pid").write_text(str(pid), encoding="utf-8")


# ── Start, follow, cancel ────────────────────────────────────────────────


def start(
    target: str,
    message: str,
    *,
    harness: str | None = None,
    parent_harness: str | None = None,
    parent_agent_id: str | None = None,
    cwd: str | Path | None = None,
    wait_seconds: float = 0,
) -> dict:
    message = (message or "").strip()
    if not message:
        raise DelegationError("A delegation needs a message describing the task.")
    if len(message) > MAX_MESSAGE_CHARS:
        raise DelegationError(f"The message is longer than {MAX_MESSAGE_CHARS} characters.")
    depth = current_depth()
    if depth >= max_depth():
        raise DelegationError(f"Delegation depth limit reached ({max_depth()}). Do this part of the task yourself.")
    parent_task = os.environ.get("OBSERVAL_DELEGATION_TASK_ID") or None
    if parent_task and tasks.count_children(parent_task) >= MAX_CHILD_TASKS:
        raise DelegationError(
            f"A delegated agent can start at most {MAX_CHILD_TASKS} tasks of its own. Do the rest of this task yourself."
        )

    entry = _entry_for(target)
    if entry.get("obs:lifecycle") != "approved":
        raise DelegationError(f"{entry.get('displayName') or target} is not approved, so it cannot be delegated to.")
    if not entry.get("obs:delegable", True):
        raise DelegationError(f"{entry.get('displayName') or target} cannot take delegated tasks.")

    kind = _kind(entry)
    identifier = entry.get("identifier") or ""
    agent_id = _agent_id(entry)
    chain = current_chain()
    if (identifier and identifier in chain) or (agent_id and (agent_id == parent_agent_id or agent_id in chain)):
        raise DelegationError(
            f"{entry.get('displayName') or target} is already working on this task higher up the chain; "
            "delegating to it again would loop."
        )

    observal: dict = {
        "target": identifier or entry.get("obs:nativeRef") or target,
        "targetName": entry.get("displayName"),
        "kind": kind,
        "version": entry.get("version"),
        "nativeRef": entry.get("obs:nativeRef"),
        "parentHarness": parent_harness,
        "parentAgentId": parent_agent_id,
        "parentTaskId": parent_task,
        "depth": depth,
        "chain": chain,
        "cwd": str(Path(cwd or Path.cwd()).resolve()),
    }
    if kind == "agent":
        if not agent_id:
            raise DelegationError("Could not tell which registry agent that identifier names.")
        observal["agentId"] = agent_id
        observal["harness"] = choose_harness(list(entry.get("obs:supportedHarnesses") or []), harness or parent_harness)
    else:
        observal["remoteUrl"] = (entry.get("obs:a2aInterface") or {}).get("url")

    task = tasks.new_task(message=message, observal=observal)
    with contextlib.suppress(OSError, ValueError):
        capability_lock.record(
            kind="external" if kind == "a2a" else "agent",
            mode=capability_lock.MODE_DELEGATED,
            source="delegate",
            harness=parent_harness,
            cwd=observal["cwd"],
            identifier=identifier or None,
            component_id=agent_id,
            native_ref=entry.get("obs:nativeRef"),
            version=entry.get("version"),
            digest=entry.get("obs:artifactDigest"),
            extra={"task_id": task["id"], "child_harness": observal.get("harness")},
        )
    _launch(task)
    return wait(task["id"], wait_seconds)


def reply(task_id: str, message: str, *, wait_seconds: float = 0) -> dict:
    """Answer a remote task that asked for more input, and resume it."""
    task = get(task_id)
    state = (task.get("status") or {}).get("state")
    if tasks.meta(task).get("kind") != "a2a" or state not in tasks.INTERRUPTED_STATES:
        raise DelegationError("Only a remote task that is waiting for input can take a reply.")
    message = (message or "").strip()
    if not message:
        raise DelegationError("The reply is empty.")
    tasks.task_dir(task_id).joinpath("reply.txt").write_text(message, encoding="utf-8")
    task.setdefault("history", []).append(tasks.text_message("ROLE_USER", message, task_id=task_id))
    tasks.set_status(task, tasks.STATE_SUBMITTED)
    _launch(task)
    return wait(task_id, wait_seconds)


def get(task_id: str) -> dict:
    task = tasks.load(task_id)
    if task is None:
        raise DelegationError(f"No delegated task with id {task_id}.")
    # A worker that died without writing a final state would leave the task stuck.
    pid = _worker_pid(task_id)
    if not tasks.is_final(task) and pid and not _pid_alive(pid):
        task = tasks.load(task_id) or task
        if not tasks.is_final(task):
            tasks.set_status(task, tasks.STATE_FAILED, "The delegation worker stopped unexpectedly.")
            tasks.save(task)
    return task


def wait(task_id: str, seconds: float) -> dict:
    deadline = time.monotonic() + max(0.0, min(float(seconds or 0), MAX_WAIT_SECONDS))
    task = get(task_id)
    while not tasks.is_final(task) and time.monotonic() < deadline:
        time.sleep(WAIT_POLL_SECONDS)
        task = get(task_id)
    return task


def cancel(task_id: str) -> dict:
    task = get(task_id)
    if tasks.is_final(task):
        return task
    tasks.request_cancel(task_id)
    if not _pid_alive(_worker_pid(task_id)):
        tasks.set_status(task, tasks.STATE_CANCELED, "Canceled by the caller.")
        tasks.save(task)
        return task
    return wait(task_id, 15)


# ── Presenting results to a model ────────────────────────────────────────


def summarize(task: dict) -> str:
    """A compact, model-readable account of a task: state, answer, and what to do next."""
    m = tasks.meta(task)
    status = task.get("status") or {}
    state = status.get("state", "")
    lines = [
        f"task_id: {task.get('id')}",
        f"agent: {m.get('targetName') or m.get('target')} ({m.get('kind')}"
        + (f" via {m['harness']}" if m.get("harness") else "")
        + ")",
        f"state: {state}",
    ]
    note = tasks.message_text(status.get("message"))
    if note:
        lines.append(f"status: {note}")
    for artifact in task.get("artifacts") or []:
        name = artifact.get("name") or artifact.get("artifactId") or "artifact"
        text = tasks.message_text(artifact)
        if name == "changes.patch":
            lines.append(f"\n## Proposed changes ({m.get('patchPath')})\n```diff\n{text}\n```")
        else:
            lines.append(f"\n## {name}\n{text}")
    for extra in m.get("notes") or []:
        lines.append(f"note: {extra}")
    if state in (tasks.STATE_SUBMITTED, tasks.STATE_WORKING):
        lines.append(
            "\nStill running. Call get_task with this task_id (optionally wait_seconds) to collect the result."
        )
    elif state in tasks.INTERRUPTED_STATES:
        lines.append("\nThe agent needs more input. Call delegate again with task_id and your answer as the message.")
    elif m.get("patchPath"):
        lines.append(
            "\nThe changes were made in an isolated copy and have NOT been applied. Review them; to apply, run "
            f"`git apply {m['patchPath']}` in the repository."
        )
    return "\n".join(lines)
