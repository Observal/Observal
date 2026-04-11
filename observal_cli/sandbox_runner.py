"""observal-sandbox-run: Docker sandbox executor with telemetry.

Runs a Docker container, captures stdout/stderr via container.logs(),
collects exit code and OOM status, and POSTs a sandbox_exec span to Observal.
"""

import json
import os
import sys
import time
import uuid
from datetime import UTC, datetime

import httpx

from observal_cli.config import load as load_config

MAX_LOG_BYTES = 64 * 1024  # 64KB truncation limit for logs


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def _send_span(server_url: str, api_key: str, span: dict):
    """Fire-and-forget POST span to ingest endpoint."""
    if not server_url or not api_key:
        return
    try:
        httpx.post(
            f"{server_url.rstrip('/')}/api/v1/telemetry/ingest",
            json={"traces": [], "spans": [span], "scores": []},
            headers={"X-API-Key": api_key},
            timeout=5,
        )
    except Exception:
        pass  # fire-and-forget


def run_sandbox(sandbox_id: str, image: str, command: str | None = None, timeout: int = 300, env: dict | None = None):
    """Run a Docker container and capture logs + metrics."""
    try:
        import docker
    except ImportError:
        import typer
        from rich import print as rprint

        rprint("[red]Docker SDK not found.[/red] Please install via: pip install observal-cli[sandbox]")
        raise typer.Exit(1)

    client = docker.from_env()
    start_time = _now_iso()
    wall_start = time.monotonic()

    container = None
    try:
        run_kwargs = {
            "image": image,
            "detach": True,
            "environment": env or {},
            "stdout": True,
            "stderr": True,
        }
        if command:
            run_kwargs["command"] = command

        container = client.containers.run(**run_kwargs)
        result = container.wait(timeout=timeout)
        wall_ms = int((time.monotonic() - wall_start) * 1000)

        exit_code = result.get("StatusCode", -1)
        logs = container.logs(stdout=True, stderr=True)
        if isinstance(logs, bytes):
            logs = logs.decode("utf-8", errors="replace")
        # Truncate
        if len(logs) > MAX_LOG_BYTES:
            logs = logs[:MAX_LOG_BYTES] + "\n... [truncated at 64KB]"

        # OOM detection
        container.reload()
        oom_killed = container.attrs.get("State", {}).get("OOMKilled", False)
        container_id = container.short_id

        # Print logs to stdout so caller can see them
        print(logs, end="")

        end_time = _now_iso()

        span = {
            "span_id": str(uuid.uuid4()),
            "trace_id": str(uuid.uuid4()),
            "parent_span_id": None,
            "type": "sandbox_exec",
            "name": f"sandbox:{image}",
            "method": "",
            "input": json.dumps({"image": image, "command": command, "sandbox_id": sandbox_id}),
            "output": logs,
            "error": None if exit_code == 0 else f"exit_code={exit_code}",
            "start_time": start_time,
            "end_time": end_time,
            "latency_ms": wall_ms,
            "status": "success" if exit_code == 0 else "error",
            "ide": "",
            "metadata": {},
            "container_id": container_id,
            "exit_code": exit_code,
            "oom_killed": oom_killed,
            "network_bytes_in": None,
            "network_bytes_out": None,
            "disk_read_bytes": None,
            "disk_write_bytes": None,
        }

        # Resolve auth
        api_key = os.environ.get("OBSERVAL_KEY", "")
        server_url = os.environ.get("OBSERVAL_SERVER", "")
        if not api_key or not server_url:
            cfg = load_config()
            api_key = api_key or cfg.get("api_key", "")
            server_url = server_url or cfg.get("server_url", "")

        _send_span(server_url, api_key, span)

        sys.exit(exit_code)

    except Exception as e:
        wall_ms = int((time.monotonic() - wall_start) * 1000)
        print(f"Error: {e}", file=sys.stderr)

        api_key = os.environ.get("OBSERVAL_KEY", "")
        server_url = os.environ.get("OBSERVAL_SERVER", "")
        if not api_key or not server_url:
            cfg = load_config()
            api_key = api_key or cfg.get("api_key", "")
            server_url = server_url or cfg.get("server_url", "")

        _send_span(
            server_url,
            api_key,
            {
                "span_id": str(uuid.uuid4()),
                "trace_id": str(uuid.uuid4()),
                "parent_span_id": None,
                "type": "sandbox_exec",
                "name": f"sandbox:{image}",
                "method": "",
                "input": json.dumps({"image": image, "command": command, "sandbox_id": sandbox_id}),
                "output": None,
                "error": str(e),
                "start_time": start_time,
                "end_time": _now_iso(),
                "latency_ms": wall_ms,
                "status": "error",
                "ide": "",
                "metadata": {},
                "container_id": None,
                "exit_code": -1,
                "oom_killed": False,
            },
        )
        sys.exit(1)
    finally:
        if container:
            try:
                container.remove(force=True)
            except Exception:
                pass


def main():
    """CLI entry point for observal-sandbox-run."""
    args = sys.argv[1:]
    sandbox_id = ""
    image = ""
    command = None
    timeout = 300
    env = {}

    i = 0
    while i < len(args):
        if args[i] == "--sandbox-id" and i + 1 < len(args):
            sandbox_id = args[i + 1]
            i += 2
        elif args[i] == "--image" and i + 1 < len(args):
            image = args[i + 1]
            i += 2
        elif args[i] == "--command" and i + 1 < len(args):
            command = args[i + 1]
            i += 2
        elif args[i] == "--timeout" and i + 1 < len(args):
            timeout = int(args[i + 1])
            i += 2
        elif args[i] == "--env" and i + 1 < len(args):
            k, _, v = args[i + 1].partition("=")
            env[k] = v
            i += 2
        elif args[i] == "--":
            # Everything after: is the command
            command = " ".join(args[i + 1 :])
            break
        else:
            i += 1

    if not image:
        print(
            "Usage: observal-sandbox-run --sandbox-id <id> --image <image> [--command <cmd>] [--timeout <s>]",
            file=sys.stderr,
        )
        sys.exit(1)

    run_sandbox(sandbox_id, image, command, timeout, env)


if __name__ == "__main__":
    main()
