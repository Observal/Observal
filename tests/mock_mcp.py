#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Minimal MCP server for testing the observal-shim."""

import json
import sys


def respond(msg_id, result):
    resp = json.dumps({"jsonrpc": "2.0", "id": msg_id, "result": result})
    sys.stdout.write(resp + "\n")
    sys.stdout.flush()


def main():
    sys.stderr.write("mock-mcp: started\n")
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue

        method = msg.get("method", "")
        msg_id = msg.get("id")

        if method == "initialize":
            respond(
                msg_id,
                {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "mock-mcp", "version": "0.1.0"},
                },
            )
        elif method == "tools/list":
            respond(
                msg_id,
                {
                    "tools": [
                        {
                            "name": "echo",
                            "description": "Echo input back",
                            "inputSchema": {
                                "type": "object",
                                "properties": {"text": {"type": "string"}},
                                "required": ["text"],
                            },
                        },
                        {
                            "name": "add",
                            "description": "Add two numbers",
                            "inputSchema": {
                                "type": "object",
                                "properties": {"a": {"type": "number"}, "b": {"type": "number"}},
                                "required": ["a", "b"],
                            },
                        },
                    ]
                },
            )
        elif method == "tools/call":
            tool_name = msg.get("params", {}).get("name", "")
            args = msg.get("params", {}).get("arguments", {})
            if tool_name == "echo":
                respond(msg_id, {"content": [{"type": "text", "text": args.get("text", "")}]})
            elif tool_name == "add":
                respond(msg_id, {"content": [{"type": "text", "text": str(args.get("a", 0) + args.get("b", 0))}]})
            else:
                sys.stdout.write(
                    json.dumps(
                        {
                            "jsonrpc": "2.0",
                            "id": msg_id,
                            "error": {"code": -32601, "message": f"Unknown tool: {tool_name}"},
                        }
                    )
                    + "\n"
                )
                sys.stdout.flush()
        elif method == "ping":
            respond(msg_id, {})
        else:
            respond(msg_id, {})


if __name__ == "__main__":
    main()
