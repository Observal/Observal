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
    }

    with (
        patch("observal_cli.config.resolve_alias", return_value=agent_id),
        patch("observal_cli.client.get") as mock_get,
        patch("observal_cli.client.post", return_value=version_result) as mock_post,
    ):
        # GET /agents/{id} → single agent dict
        # GET /agents/{id}/version-suggestions → suggestions
        mock_get.side_effect = [
            {"id": agent_id, "name": "my-agent"},
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
    version_result = {"version": "1.2.1", "status": "pending"}

    with (
        patch("observal_cli.config.resolve_alias", return_value=agent_id),
        patch("observal_cli.client.get") as mock_get,
        patch("observal_cli.client.post", return_value=version_result),
    ):
        mock_get.side_effect = [
            {"id": agent_id, "name": "my-agent"},
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
    """release shows a warning when the server returns warnings."""
    agent_id = "agent-uuid-9999"
    suggestions = {
        "current": "1.2.0",
        "suggestions": {"patch": "1.2.1", "minor": "1.3.0", "major": "2.0.0"},
    }
    version_result = {
        "version": "1.3.0",
        "status": "pending",
        "warnings": ["This agent already has 2 pending version(s)"],
    }

    with (
        patch("observal_cli.config.resolve_alias", return_value=agent_id),
        patch("observal_cli.client.get") as mock_get,
        patch("observal_cli.client.post", return_value=version_result),
    ):
        mock_get.side_effect = [
            {"id": agent_id, "name": "my-agent"},
            suggestions,
        ]
        result = runner.invoke(
            app,
            ["agent", "release", "my-agent", "--bump", "minor", "--dir", str(agent_yaml_dir)],
        )

    assert result.exit_code == 0, result.output
    assert "This agent already has 2 pending version(s)" in result.output


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


def test_agent_pull_writes_rules_and_mcp(tmp_path: Path) -> None:
    """pull writes rules_file and mcp_config from install endpoint."""
    agent_id = "agent-uuid-pull"
    agent_detail = {
        "id": agent_id,
        "name": "my-agent",
        "mcp_links": [],
        "component_links": [],
    }
    install_result = {
        "config_snippet": {
            "rules_file": {
                "path": ".claude/rules.md",
                "content": "# Rules\nBe helpful.",
            },
            "mcp_config": {
                "path": ".claude/mcp.json",
                "content": {"mcpServers": {"my-server": {"command": "npx"}}},
            },
        }
    }

    with (
        patch("observal_cli.config.resolve_alias", return_value=agent_id),
        patch("observal_cli.client.get", return_value=agent_detail),
        patch("observal_cli.client.post", return_value=install_result),
    ):
        result = runner.invoke(
            app,
            ["agent", "pull", agent_id, "--ide", "claude-code", "--dir", str(tmp_path), "--no-prompt"],
        )

    assert result.exit_code == 0, result.output

    rules_path = tmp_path / ".claude" / "rules.md"
    mcp_path = tmp_path / ".claude" / "mcp.json"
    assert rules_path.exists()
    assert "Be helpful" in rules_path.read_text()
    assert mcp_path.exists()
    assert "my-server" in mcp_path.read_text()


def test_agent_pull_dry_run(tmp_path: Path) -> None:
    """pull --dry-run previews files without writing."""
    agent_id = "agent-uuid-dry"
    agent_detail = {"id": agent_id, "name": "my-agent", "mcp_links": [], "component_links": []}
    install_result = {
        "config_snippet": {
            "rules_file": {"path": ".claude/rules.md", "content": "# Rules"},
        }
    }

    with (
        patch("observal_cli.config.resolve_alias", return_value=agent_id),
        patch("observal_cli.client.get", return_value=agent_detail),
        patch("observal_cli.client.post", return_value=install_result),
    ):
        result = runner.invoke(
            app,
            ["agent", "pull", agent_id, "--ide", "claude-code", "--dir", str(tmp_path), "--dry-run", "--no-prompt"],
        )

    assert result.exit_code == 0, result.output
    assert "dry run" in result.output.lower() or "would write" in result.output.lower()
    # File should NOT be written
    assert not (tmp_path / ".claude" / "rules.md").exists()


def test_agent_pull_steering_file(tmp_path: Path) -> None:
    """pull writes steering_file (Kiro) from install endpoint."""
    agent_id = "agent-uuid-kiro"
    agent_detail = {"id": agent_id, "name": "my-agent", "mcp_links": [], "component_links": []}
    install_result = {
        "config_snippet": {
            "steering_file": {"path": ".kiro/steering.md", "content": "# Steering"},
        }
    }

    with (
        patch("observal_cli.config.resolve_alias", return_value=agent_id),
        patch("observal_cli.client.get", return_value=agent_detail),
        patch("observal_cli.client.post", return_value=install_result),
    ):
        result = runner.invoke(
            app,
            ["agent", "pull", agent_id, "--ide", "kiro", "--dir", str(tmp_path), "--no-prompt"],
        )

    assert result.exit_code == 0, result.output
    assert (tmp_path / ".kiro" / "steering.md").exists()


def test_agent_pull_path_traversal_rejected(tmp_path: Path) -> None:
    """pull rejects file paths that escape target directory."""
    agent_id = "agent-uuid-evil"
    agent_detail = {"id": agent_id, "name": "evil-agent", "mcp_links": [], "component_links": []}
    install_result = {
        "config_snippet": {
            "rules_file": {"path": "../../etc/evil.txt", "content": "pwned"},
        }
    }

    with (
        patch("observal_cli.config.resolve_alias", return_value=agent_id),
        patch("observal_cli.client.get", return_value=agent_detail),
        patch("observal_cli.client.post", return_value=install_result),
    ):
        result = runner.invoke(
            app,
            ["agent", "pull", agent_id, "--ide", "claude-code", "--dir", str(tmp_path), "--no-prompt"],
        )

    # Should fail due to path escape
    assert result.exit_code == 1
    assert not (tmp_path / ".." / ".." / "etc" / "evil.txt").resolve().exists()
