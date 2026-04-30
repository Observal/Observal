"""Tests for agent release, versions, and pull commands."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest
import yaml
from typer.testing import CliRunner

from observal_cli.main import app

if TYPE_CHECKING:
    from pathlib import Path

runner = CliRunner()

# ── Shared fixtures ────────────────────────────────────────────


@pytest.fixture()
def agent_yaml_dir(tmp_path: Path) -> Path:
    """Write a minimal observal-agent.yaml into tmp_path and return the dir."""
    data = {
        "name": "my-agent",
        "version": "1.2.0",
        "description": "A test agent",
        "owner": "team-alpha",
        "model_name": "claude-sonnet-4",
        "prompt": "You are a helpful agent.",
        "supported_ides": ["claude-code"],
        "components": [{"component_type": "mcp", "component_id": "abc-123"}],
        "goal_template": {"description": "Do things", "sections": [{"name": "default", "description": "default"}]},
    }
    (tmp_path / "observal-agent.yaml").write_text(yaml.dump(data))
    return tmp_path


# ── agent release ──────────────────────────────────────────────


def test_agent_release_bumps_version(agent_yaml_dir: Path) -> None:
    """release bumps version via version-suggestions and POSTs to /versions."""
    agent_id = "agent-uuid-1234"
    suggestions = {
        "current": "1.2.0",
        "suggestions": {"patch": "1.2.1", "minor": "1.3.0", "major": "2.0.0"},
    }
    version_result = {
        "version": "1.3.0",
        "status": "pending",
        "pending_version_count": 0,
    }

    with (
        patch("observal_cli.config.resolve_alias", return_value=agent_id),
        patch("observal_cli.client.get") as mock_get,
        patch("observal_cli.client.post", return_value=version_result) as mock_post,
    ):
        # GET /agents?search=my-agent → list result
        # GET /agents/{id}/version-suggestions → suggestions
        mock_get.side_effect = [
            [{"id": agent_id, "name": "my-agent"}],
            suggestions,
        ]

        result = runner.invoke(
            app,
            ["agent", "release", "my-agent", "--bump", "minor", "--dir", str(agent_yaml_dir)],
        )

    assert result.exit_code == 0, result.output
    assert "1.2.0" in result.output
    assert "1.3.0" in result.output

    # Verify POST was called with correct path and version
    post_call = mock_post.call_args
    assert f"/api/v1/agents/{agent_id}/versions" in post_call[0][0]
    payload = post_call[0][1]
    assert payload["version"] == "1.3.0"
    assert payload["yaml_snapshot"] is not None


def test_agent_release_updates_local_yaml(agent_yaml_dir: Path) -> None:
    """release writes the new version back into observal-agent.yaml."""
    agent_id = "agent-uuid-5678"
    suggestions = {
        "current": "1.2.0",
        "suggestions": {"patch": "1.2.1", "minor": "1.3.0", "major": "2.0.0"},
    }
    version_result = {"version": "1.2.1", "status": "pending", "pending_version_count": 0}

    with (
        patch("observal_cli.config.resolve_alias", return_value=agent_id),
        patch("observal_cli.client.get") as mock_get,
        patch("observal_cli.client.post", return_value=version_result),
    ):
        mock_get.side_effect = [
            [{"id": agent_id, "name": "my-agent"}],
            suggestions,
        ]
        result = runner.invoke(
            app,
            ["agent", "release", "my-agent", "--bump", "patch", "--dir", str(agent_yaml_dir)],
        )

    assert result.exit_code == 0, result.output
    saved = yaml.safe_load((agent_yaml_dir / "observal-agent.yaml").read_text())
    assert saved["version"] == "1.2.1"


def test_agent_release_shows_pending_warning(agent_yaml_dir: Path) -> None:
    """release shows a warning when pending_version_count > 0."""
    agent_id = "agent-uuid-9999"
    suggestions = {
        "current": "1.2.0",
        "suggestions": {"patch": "1.2.1", "minor": "1.3.0", "major": "2.0.0"},
    }
    version_result = {"version": "1.3.0", "status": "pending", "pending_version_count": 2}

    with (
        patch("observal_cli.config.resolve_alias", return_value=agent_id),
        patch("observal_cli.client.get") as mock_get,
        patch("observal_cli.client.post", return_value=version_result),
    ):
        mock_get.side_effect = [
            [{"id": agent_id, "name": "my-agent"}],
            suggestions,
        ]
        result = runner.invoke(
            app,
            ["agent", "release", "my-agent", "--bump", "minor", "--dir", str(agent_yaml_dir)],
        )

    assert result.exit_code == 0, result.output
    assert "pending" in result.output.lower()
    assert "2" in result.output


# ── agent versions ─────────────────────────────────────────────


def test_agent_versions_table_output() -> None:
    """versions renders a table with VERSION, STATUS, DATE, COMPONENTS columns."""
    agent_id = "agent-uuid-abc"
    versions_response = {
        "items": [
            {
                "version": "1.3.0",
                "status": "pending",
                "created_at": "2026-04-30T10:00:00Z",
                "created_by_email": "alice@example.com",
                "component_count": 5,
            },
            {
                "version": "1.2.0",
                "status": "approved",
                "created_at": "2026-04-20T10:00:00Z",
                "created_by_email": "bob@example.com",
                "component_count": 4,
            },
        ],
        "total": 2,
        "page": 1,
        "page_size": 50,
    }

    with (
        patch("observal_cli.config.resolve_alias", return_value=agent_id),
        patch("observal_cli.client.get", return_value=versions_response) as mock_get,
    ):
        result = runner.invoke(app, ["agent", "versions", "my-agent"])

    assert result.exit_code == 0, result.output
    assert "1.3.0" in result.output
    assert "1.2.0" in result.output
    assert "pending" in result.output.lower()
    assert "approved" in result.output.lower()

    # Verify correct API was called
    mock_get.assert_called_once_with(
        f"/api/v1/agents/{agent_id}/versions",
        params={"page": 1, "page_size": 50},
    )


def test_agent_versions_json_output() -> None:
    """versions --output json dumps raw JSON."""
    agent_id = "agent-uuid-def"
    versions_response = {
        "items": [{"version": "1.0.0", "status": "approved", "created_at": None, "component_count": 0}],
        "total": 1,
        "page": 1,
        "page_size": 50,
    }

    with (
        patch("observal_cli.config.resolve_alias", return_value=agent_id),
        patch("observal_cli.client.get", return_value=versions_response),
    ):
        result = runner.invoke(app, ["agent", "versions", "my-agent", "--output", "json"])

    assert result.exit_code == 0, result.output
    # Output must be valid JSON
    parsed = json.loads(result.output)
    assert isinstance(parsed, (dict, list))


# ── agent pull ─────────────────────────────────────────────────


def test_agent_pull_writes_files(tmp_path: Path) -> None:
    """pull writes each entry in the files dict to disk."""
    agent_id = "agent-uuid-pull"
    agent_detail = {
        "id": agent_id,
        "name": "my-agent",
        "latest_version": "1.2.0",
        "latest_approved_version": "1.2.0",
    }
    ide_config = {
        "files": {
            ".claude/agents/my-agent/settings.json": '{"key": "value"}',
            ".claude/agents/my-agent/AGENTS.md": "# My Agent\n",
        }
    }

    with (
        patch("observal_cli.config.resolve_alias", return_value=agent_id),
        patch("observal_cli.client.get") as mock_get,
    ):
        mock_get.side_effect = [agent_detail, ide_config]

        result = runner.invoke(
            app,
            ["agent", "pull", "my-agent", "--ide", "claude-code", "--dir", str(tmp_path)],
        )

    assert result.exit_code == 0, result.output

    settings_path = tmp_path / ".claude" / "agents" / "my-agent" / "settings.json"
    agents_md_path = tmp_path / ".claude" / "agents" / "my-agent" / "AGENTS.md"
    assert settings_path.exists(), f"Expected {settings_path} to exist"
    assert agents_md_path.exists(), f"Expected {agents_md_path} to exist"
    assert settings_path.read_text() == '{"key": "value"}'
    assert agents_md_path.read_text() == "# My Agent\n"

    # Output should mention the written files
    assert "settings.json" in result.output or ".claude" in result.output


def test_agent_pull_explicit_version(tmp_path: Path) -> None:
    """pull --version uses the specified version instead of latest."""
    agent_id = "agent-uuid-ver"
    agent_detail = {
        "id": agent_id,
        "name": "my-agent",
        "latest_version": "1.3.0",
        "latest_approved_version": "1.3.0",
    }
    ide_config = {
        "files": {
            ".claude/agents/my-agent/AGENTS.md": "# pinned version\n",
        }
    }

    with (
        patch("observal_cli.config.resolve_alias", return_value=agent_id),
        patch("observal_cli.client.get") as mock_get,
    ):
        mock_get.side_effect = [agent_detail, ide_config]

        result = runner.invoke(
            app,
            ["agent", "pull", "my-agent", "--ide", "claude-code", "--version", "1.2.0", "--dir", str(tmp_path)],
        )

    assert result.exit_code == 0, result.output

    # Second GET call must use the explicit version, not latest
    second_call = mock_get.call_args_list[1]
    called_path = second_call[0][0]
    assert "1.2.0" in called_path


def test_agent_pull_raw_config_fallback(tmp_path: Path) -> None:
    """pull handles a raw config dict (no 'files' key) by writing a single file."""
    agent_id = "agent-uuid-raw"
    agent_detail = {
        "id": agent_id,
        "name": "my-agent",
        "latest_version": "1.0.0",
        "latest_approved_version": "1.0.0",
    }
    # No 'files' key — just a plain config dict
    ide_config = {"mcpServers": {"my-agent": {"command": "npx", "args": ["-y", "@my-agent"]}}}

    with (
        patch("observal_cli.config.resolve_alias", return_value=agent_id),
        patch("observal_cli.client.get") as mock_get,
    ):
        mock_get.side_effect = [agent_detail, ide_config]

        result = runner.invoke(
            app,
            ["agent", "pull", "my-agent", "--ide", "claude-code", "--dir", str(tmp_path)],
        )

    assert result.exit_code == 0, result.output
    # A fallback file should have been written
    written = list(tmp_path.rglob("*"))
    assert any(f.is_file() for f in written), "Expected at least one file to be written"
