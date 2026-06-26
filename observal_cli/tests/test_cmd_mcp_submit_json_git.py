# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

from __future__ import annotations

import json
from unittest.mock import patch

from typer.testing import CliRunner

from observal_cli.main import app

runner = CliRunner()


def test_mcp_submit_git_keeps_json_paste_required():
    config = {
        "mcpServers": {
            "local-mcp": {
                "command": "docker",
                "args": ["run", "-i", "--rm", "local-mcp:latest"],
            }
        }
    }

    with (
        patch("observal_cli.config.load", return_value={"username": "me"}),
        patch(
            "observal_cli.cmd_mcp.analyze_local",
            return_value={
                "name": "local-mcp",
                "version": "0.1.0",
                "tools": [],
                "docker_image": "local-mcp:latest",
                "setup_instructions": "docker build -t local-mcp:latest .",
            },
        ),
        patch("observal_cli.client.post", return_value={"id": "mcp-1", "status": "pending"}) as post,
    ):
        result = runner.invoke(
            app,
            [
                "registry",
                "mcp",
                "submit",
                "--git",
                "https://github.com/org/local-mcp",
                "--name",
                "local-mcp",
                "--category",
                "developer-tools",
                "--yes",
            ],
            input=json.dumps(config) + "\n\n",
        )

    assert result.exit_code == 0, result.output
    payload = post.call_args[0][1]
    assert payload["git_url"] == "https://github.com/org/local-mcp"
    assert payload["command"] == "docker"
    assert payload["setup_instructions"] == "docker build -t local-mcp:latest ."
