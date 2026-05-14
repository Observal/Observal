# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""E2E tests for MCP CLI commands (submit and list).

These use typer CliRunner with mocked client calls to verify CLI output
without requiring a running server.
"""

from __future__ import annotations

import json
import re
from unittest.mock import patch

from typer.testing import CliRunner

from observal_cli.main import app as cli_app

runner = CliRunner()

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _plain(text: str) -> str:
    return _ANSI_RE.sub("", text)


_FAKE_CONFIG = {"server_url": "http://localhost:8000", "api_key": "test-key"}


def _patch_config():
    return patch("observal_cli.config.get_or_exit", return_value=_FAKE_CONFIG)


class TestMcpSubmitCli:
    """observal mcp submit outputs 'submitted' or success indicator."""

    def test_submit_via_git_url_success(self):
        submit_response = {
            "id": "abc-123",
            "name": "my-test-mcp",
            "version": "1.0.0",
            "status": "pending",
            "description": "Test MCP",
            "owner": "admin",
            "category": "developer-tools",
        }
        with (
            _patch_config(),
            patch("observal_cli.client.post", return_value=submit_response),
            patch(
                "observal_cli.cmd_mcp.analyze_local",
                return_value={
                    "name": "my-test-mcp",
                    "description": "Test MCP",
                    "command": "node",
                    "args": ["index.js"],
                    "framework": "mcp-framework",
                    "entry_point": "index.js",
                    "tools": [{"name": "tool1"}],
                    "issues": [],
                },
            ),
        ):
            result = runner.invoke(
                cli_app,
                [
                    "mcp",
                    "submit",
                    "--git",
                    "https://github.com/example/repo.git",
                    "--name",
                    "my-test-mcp",
                    "--category",
                    "developer-tools",
                    "--yes",
                ],
            )
        output = _plain(result.output)
        assert result.exit_code == 0, f"Exit code {result.exit_code}: {output}"
        # Should indicate successful submission
        assert any(word in output.lower() for word in ("submitted", "success", "pending", "review"))


class TestMcpListCli:
    """observal mcp list --output json returns valid JSON array."""

    def test_list_json_output(self):
        list_response = [
            {"id": "1", "name": "mcp-a", "version": "1.0.0", "category": "developer-tools", "owner": "alice"},
            {"id": "2", "name": "mcp-b", "version": "2.1.0", "category": "data", "owner": "bob"},
        ]
        with (
            _patch_config(),
            patch("observal_cli.client.get", return_value=list_response),
        ):
            result = runner.invoke(cli_app, ["mcp", "list", "--output", "json"])
        assert result.exit_code == 0, f"Exit code {result.exit_code}: {result.output}"
        parsed = json.loads(result.output)
        assert isinstance(parsed, list)
        assert len(parsed) == 2
        assert parsed[0]["name"] == "mcp-a"

    def test_list_table_output(self):
        list_response = [
            {"id": "1", "name": "mcp-a", "version": "1.0.0", "category": "developer-tools", "owner": "alice"},
        ]
        with (
            _patch_config(),
            patch("observal_cli.client.get", return_value=list_response),
        ):
            result = runner.invoke(cli_app, ["mcp", "list"])
        assert result.exit_code == 0
        output = _plain(result.output)
        assert "mcp-a" in output
