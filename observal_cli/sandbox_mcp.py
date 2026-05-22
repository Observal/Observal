# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Observal Sandbox MCP Server.

A lightweight MCP server that exposes registered sandboxes as tools.
When an agent has sandbox components, this server is auto-injected into
the agent's MCP config — giving the agent a `run_sandbox` tool it can
call naturally without prompt engineering.

Usage:
    observal-sandbox-mcp --sandboxes '<json>'

The --sandboxes arg is a JSON array of sandbox specs:
    [{"id": "uuid", "name": "python-pytest", "image": "python:3.12-slim",
      "timeout": 60, "entrypoint": "pytest", "network_policy": "none"}]
"""

from __future__ import annotations

import json
import subprocess
import sys

# Minimal JSON-RPC stdio MCP implementation (no dependencies beyond stdlib)


def _read_message() -> dict | None:
    """Read a JSON-RPC message from stdin (Content-Length framing)."""
    headers = {}
    while True:
        line = sys.stdin.buffer.readline()
        if not line or line == b"\r\n" or line == b"\n":
            break
        if b":" in line:
            key, value = line.decode().split(":", 1)
            headers[key.strip().lower()] = value.strip()
    content_length = int(headers.get("content-length", 0))
    if content_length == 0:
        return None
    body = sys.stdin.buffer.read(content_length)
    return json.loads(body)


def _send_message(msg: dict) -> None:
    """Send a JSON-RPC message to stdout."""
    body = json.dumps(msg).encode()
    sys.stdout.buffer.write(f"Content-Length: {len(body)}\r\n\r\n".encode())
    sys.stdout.buffer.write(body)
    sys.stdout.buffer.flush()


def _make_response(req_id, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _make_error(req_id, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


def main():
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--sandboxes", required=True, help="JSON array of sandbox specs")
    args = parser.parse_args()

    sandboxes = json.loads(args.sandboxes)
    sandbox_map = {s["name"]: s for s in sandboxes}

    # Build tool definitions
    tools = []
    for sb in sandboxes:
        tool_name = f"run_sandbox_{sb['name'].replace('-', '_')}"
        tools.append({
            "name": tool_name,
            "description": (
                f"Run a command in the '{sb['name']}' sandbox "
                f"(Docker: {sb['image']}, timeout: {sb.get('timeout', 300)}s, "
                f"network: {sb.get('network_policy', 'none')}). "
                f"Default command: {sb.get('entrypoint', 'bash')}"
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": f"Command to run inside the container. Default: {sb.get('entrypoint', 'bash')}",
                    },
                },
                "required": [],
            },
        })

    while True:
        msg = _read_message()
        if msg is None:
            break

        method = msg.get("method", "")
        req_id = msg.get("id")

        if method == "initialize":
            _send_message(_make_response(req_id, {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "observal-sandbox", "version": "1.0.0"},
            }))
        elif method == "notifications/initialized":
            pass  # no response needed
        elif method == "tools/list":
            _send_message(_make_response(req_id, {"tools": tools}))
        elif method == "tools/call":
            params = msg.get("params", {})
            tool_name = params.get("name", "")
            arguments = params.get("arguments", {})

            # Extract sandbox name from tool name
            sb_name = tool_name.replace("run_sandbox_", "").replace("_", "-")
            sb = sandbox_map.get(sb_name)
            if not sb:
                _send_message(_make_response(req_id, {
                    "content": [{"type": "text", "text": f"Unknown sandbox: {sb_name}"}],
                    "isError": True,
                }))
                continue

            command = arguments.get("command") or sb.get("entrypoint") or "bash"
            timeout = sb.get("timeout", 300)
            image = sb["image"]
            sandbox_id = sb["id"]

            # Run the sandbox
            try:
                result = subprocess.run(
                    [
                        "observal-sandbox-run",
                        "--sandbox-id", sandbox_id,
                        "--image", image,
                        "--timeout", str(timeout),
                        "--command", command,
                    ],
                    capture_output=True,
                    text=True,
                    timeout=timeout + 10,
                )
                output = result.stdout
                if result.stderr:
                    output += f"\n[stderr]\n{result.stderr}"
                if result.returncode != 0:
                    output += f"\n[exit code: {result.returncode}]"
                _send_message(_make_response(req_id, {
                    "content": [{"type": "text", "text": output or "(no output)"}],
                    "isError": result.returncode != 0,
                }))
            except subprocess.TimeoutExpired:
                _send_message(_make_response(req_id, {
                    "content": [{"type": "text", "text": f"Sandbox timed out after {timeout}s"}],
                    "isError": True,
                }))
            except FileNotFoundError:
                _send_message(_make_response(req_id, {
                    "content": [{"type": "text", "text": "observal-sandbox-run not found. Install: pip install 'observal-cli[sandbox]'"}],
                    "isError": True,
                }))
            except Exception as e:
                _send_message(_make_response(req_id, {
                    "content": [{"type": "text", "text": f"Error: {e}"}],
                    "isError": True,
                }))
        elif req_id is not None:
            _send_message(_make_error(req_id, -32601, f"Method not found: {method}"))


if __name__ == "__main__":
    main()
