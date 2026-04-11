"""Tests for the `observal pull` command."""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING
from unittest.mock import patch

import typer
import yaml
from typer.testing import CliRunner

from observal_cli.main import app as cli_app

if TYPE_CHECKING:
    from pathlib import Path

runner = CliRunner()

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _plain(text: str) -> str:
    """Strip ANSI escape codes from text."""
    return _ANSI_RE.sub("", text)


# ── Helpers ──────────────────────────────────────────────────

_FAKE_CONFIG = {"server_url": "http://localhost:8000", "api_key": "test-key"}


def _patch_config():
    """Patch config.get_or_exit so the CLI doesn't need real credentials."""
    return patch("observal_cli.config.get_or_exit", return_value=_FAKE_CONFIG)


def _patch_post(return_value: dict):
    """Patch client.post to return a canned response."""
    return patch("observal_cli.client.post", return_value=return_value)


# ── Fixtures for common server responses ─────────────────────


def _cursor_snippet() -> dict:
    return {
        "config_snippet": {
            "rules_file": {
                "path": ".cursor/rules/my-agent.md",
                "content": "# My Agent Rules\n\nDo the thing.\n",
            },
            "mcp_config": {
                "path": ".cursor/mcp.json",
                "content": {
                    "mcpServers": {
                        "my-server": {
                            "command": "npx",
                            "args": ["-y", "my-server"],
                        }
                    }
                },
            },
        }
    }


def _vscode_snippet() -> dict:
    return {
        "config_snippet": {
            "rules_file": {
                "path": ".vscode/rules/my-agent.md",
                "content": "# VSCode Agent\n",
            },
            "mcp_config": {
                "path": ".vscode/mcp.json",
                "content": {"mcpServers": {"vscode-srv": {"command": "node", "args": ["server.js"]}}},
            },
        }
    }


def _claude_code_snippet() -> dict:
    return {
        "config_snippet": {
            "rules_file": {
                "path": ".claude/rules/my-agent.md",
                "content": "# Claude Code Agent\n",
            },
            "mcp_config": {"name": {"command": "observal-mcp", "args": ["--agent", "abc"]}},
            "mcp_setup_commands": [["claude", "mcp", "add", "observal-mcp", "--", "observal-mcp", "--agent", "abc"]],
            "otlp_env": {
                "OTEL_EXPORTER_OTLP_ENDPOINT": "http://localhost:4318",
                "OTEL_SERVICE_NAME": "my-agent",
            },
        }
    }


def _gemini_snippet() -> dict:
    return {
        "config_snippet": {
            "rules_file": {
                "path": "GEMINI.md",
                "content": "# Gemini Agent\n",
            },
            "mcp_config": {
                "path": ".gemini/mcp.json",
                "content": {"mcpServers": {"gemini-srv": {"command": "python", "args": ["serve.py"]}}},
            },
        }
    }


def _kiro_snippet() -> dict:
    return {
        "config_snippet": {
            "agent_file": {
                "path": "~/.kiro/agents/my-agent.json",
                "content": {
                    "name": "my-agent",
                    "version": "1.0.0",
                    "tools": ["search"],
                },
            }
        }
    }


def _codex_snippet() -> dict:
    return {
        "config_snippet": {
            "rules_file": {
                "path": "AGENTS.md",
                "content": "# Codex Agent\n\nRules for Codex.\n",
            }
        }
    }


def _copilot_snippet() -> dict:
    return {
        "config_snippet": {
            "rules_file": {
                "path": ".github/copilot-instructions.md",
                "content": "# Copilot Instructions\n",
            }
        }
    }


# ═══════════════════════════════════════════════════════════════
# 1. Cursor / VSCode format
# ═══════════════════════════════════════════════════════════════


class TestPullCursor:
    def test_writes_rules_and_mcp(self, tmp_path: Path):
        with _patch_config(), _patch_post(_cursor_snippet()):
            result = runner.invoke(cli_app, ["pull", "abc123", "--ide", "cursor", "--dir", str(tmp_path)])

        assert result.exit_code == 0, result.output

        rules = tmp_path / ".cursor" / "rules" / "my-agent.md"
        assert rules.exists()
        assert "My Agent Rules" in rules.read_text()

        mcp = tmp_path / ".cursor" / "mcp.json"
        assert mcp.exists()
        data = json.loads(mcp.read_text())
        assert "my-server" in data["mcpServers"]
        assert data["mcpServers"]["my-server"]["command"] == "npx"

    def test_output_lists_written_files(self, tmp_path: Path):
        with _patch_config(), _patch_post(_cursor_snippet()):
            result = runner.invoke(cli_app, ["pull", "abc123", "--ide", "cursor", "--dir", str(tmp_path)])

        assert "Pulled cursor config" in result.output
        # Rich may wrap long absolute paths; strip all whitespace for path checks
        flat = result.output.replace("\n", "").replace(" ", "")
        assert "my-agent.md" in flat
        assert "mcp.json" in flat


class TestPullVSCode:
    def test_writes_rules_and_mcp(self, tmp_path: Path):
        with _patch_config(), _patch_post(_vscode_snippet()):
            result = runner.invoke(cli_app, ["pull", "abc123", "--ide", "vscode", "--dir", str(tmp_path)])

        assert result.exit_code == 0, result.output
        assert (tmp_path / ".vscode" / "rules" / "my-agent.md").exists()
        assert (tmp_path / ".vscode" / "mcp.json").exists()


# ═══════════════════════════════════════════════════════════════
# 2. Claude Code format
# ═══════════════════════════════════════════════════════════════


class TestPullClaudeCode:
    def test_writes_rules_file(self, tmp_path: Path):
        with _patch_config(), _patch_post(_claude_code_snippet()):
            result = runner.invoke(cli_app, ["pull", "abc123", "--ide", "claude-code", "--dir", str(tmp_path)])

        assert result.exit_code == 0, result.output
        rules = tmp_path / ".claude" / "rules" / "my-agent.md"
        assert rules.exists()
        assert "Claude Code Agent" in rules.read_text()

    def test_shows_setup_commands(self, tmp_path: Path):
        with _patch_config(), _patch_post(_claude_code_snippet()):
            result = runner.invoke(cli_app, ["pull", "abc123", "--ide", "claude-code", "--dir", str(tmp_path)])

        assert "claude mcp add" in result.output

    def test_shows_otlp_env(self, tmp_path: Path):
        with _patch_config(), _patch_post(_claude_code_snippet()):
            result = runner.invoke(cli_app, ["pull", "abc123", "--ide", "claude-code", "--dir", str(tmp_path)])

        assert "OTEL_EXPORTER_OTLP_ENDPOINT" in result.output
        assert "OTEL_SERVICE_NAME" in result.output

    def test_mcp_config_without_path_not_written(self, tmp_path: Path):
        """Claude Code mcp_config has no 'path' key — should not write a file for it."""
        with _patch_config(), _patch_post(_claude_code_snippet()):
            result = runner.invoke(cli_app, ["pull", "abc123", "--ide", "claude-code", "--dir", str(tmp_path)])

        assert result.exit_code == 0
        # Only the rules file should be written, not an mcp_config file
        assert (tmp_path / ".claude" / "rules" / "my-agent.md").exists()
        # No .claude/mcp.json should exist — Claude Code uses setup commands instead
        assert not (tmp_path / ".claude" / "mcp.json").exists()


# ═══════════════════════════════════════════════════════════════
# 3. Gemini CLI format
# ═══════════════════════════════════════════════════════════════


class TestPullGemini:
    def test_writes_rules_and_mcp(self, tmp_path: Path):
        with _patch_config(), _patch_post(_gemini_snippet()):
            result = runner.invoke(cli_app, ["pull", "abc123", "--ide", "gemini-cli", "--dir", str(tmp_path)])

        assert result.exit_code == 0, result.output
        rules = tmp_path / "GEMINI.md"
        assert rules.exists()
        assert "Gemini Agent" in rules.read_text()

        mcp = tmp_path / ".gemini" / "mcp.json"
        assert mcp.exists()
        data = json.loads(mcp.read_text())
        assert "gemini-srv" in data["mcpServers"]


# ═══════════════════════════════════════════════════════════════
# 4. Kiro format (agent_file with ~/  path)
# ═══════════════════════════════════════════════════════════════


class TestPullKiro:
    def test_writes_agent_file(self, tmp_path: Path):
        with _patch_config(), _patch_post(_kiro_snippet()):
            result = runner.invoke(cli_app, ["pull", "abc123", "--ide", "kiro", "--dir", str(tmp_path)])

        assert result.exit_code == 0, result.output
        agent = tmp_path / ".kiro" / "agents" / "my-agent.json"
        assert agent.exists()
        data = json.loads(agent.read_text())
        assert data["name"] == "my-agent"
        assert data["tools"] == ["search"]


# ═══════════════════════════════════════════════════════════════
# 5. Codex format (rules_file only)
# ═══════════════════════════════════════════════════════════════


class TestPullCodex:
    def test_writes_agents_md(self, tmp_path: Path):
        with _patch_config(), _patch_post(_codex_snippet()):
            result = runner.invoke(cli_app, ["pull", "abc123", "--ide", "codex", "--dir", str(tmp_path)])

        assert result.exit_code == 0, result.output
        rules = tmp_path / "AGENTS.md"
        assert rules.exists()
        assert "Codex Agent" in rules.read_text()


# ═══════════════════════════════════════════════════════════════
# 6. Copilot format
# ═══════════════════════════════════════════════════════════════


class TestPullCopilot:
    def test_writes_copilot_instructions(self, tmp_path: Path):
        with _patch_config(), _patch_post(_copilot_snippet()):
            result = runner.invoke(cli_app, ["pull", "abc123", "--ide", "copilot", "--dir", str(tmp_path)])

        assert result.exit_code == 0, result.output
        rules = tmp_path / ".github" / "copilot-instructions.md"
        assert rules.exists()
        assert "Copilot Instructions" in rules.read_text()


# ═══════════════════════════════════════════════════════════════
# 7. MCP merge behaviour
# ═══════════════════════════════════════════════════════════════


class TestPullMcpMerge:
    def test_merge_preserves_existing_servers(self, tmp_path: Path):
        """Pre-existing mcpServers should not be overwritten."""
        mcp_path = tmp_path / ".cursor" / "mcp.json"
        mcp_path.parent.mkdir(parents=True)
        mcp_path.write_text(
            json.dumps({"mcpServers": {"existing-server": {"command": "old-cmd", "args": ["--old"]}}}, indent=2)
        )

        with _patch_config(), _patch_post(_cursor_snippet()):
            result = runner.invoke(cli_app, ["pull", "abc123", "--ide", "cursor", "--dir", str(tmp_path)])

        assert result.exit_code == 0, result.output
        data = json.loads(mcp_path.read_text())
        # Both servers must be present
        assert "existing-server" in data["mcpServers"]
        assert data["mcpServers"]["existing-server"]["command"] == "old-cmd"
        assert "my-server" in data["mcpServers"]
        assert data["mcpServers"]["my-server"]["command"] == "npx"

    def test_merge_overwrites_same_named_server(self, tmp_path: Path):
        """If the incoming server has the same name, it should update."""
        mcp_path = tmp_path / ".cursor" / "mcp.json"
        mcp_path.parent.mkdir(parents=True)
        mcp_path.write_text(json.dumps({"mcpServers": {"my-server": {"command": "old", "args": []}}}, indent=2))

        with _patch_config(), _patch_post(_cursor_snippet()):
            result = runner.invoke(cli_app, ["pull", "abc123", "--ide", "cursor", "--dir", str(tmp_path)])

        assert result.exit_code == 0, result.output
        data = json.loads(mcp_path.read_text())
        assert data["mcpServers"]["my-server"]["command"] == "npx"

    def test_merge_status_reported(self, tmp_path: Path):
        """Output should say 'merged' when existing mcp.json was merged."""
        mcp_path = tmp_path / ".cursor" / "mcp.json"
        mcp_path.parent.mkdir(parents=True)
        mcp_path.write_text(json.dumps({"mcpServers": {}}, indent=2))

        with _patch_config(), _patch_post(_cursor_snippet()):
            result = runner.invoke(cli_app, ["pull", "abc123", "--ide", "cursor", "--dir", str(tmp_path)])

        assert "merged" in result.output


# ═══════════════════════════════════════════════════════════════
# 8. Dry-run
# ═══════════════════════════════════════════════════════════════


class TestPullDryRun:
    def test_dry_run_does_not_write_files(self, tmp_path: Path):
        with _patch_config(), _patch_post(_cursor_snippet()):
            result = runner.invoke(cli_app, ["pull", "abc123", "--ide", "cursor", "--dir", str(tmp_path), "--dry-run"])

        assert result.exit_code == 0, result.output
        assert "Dry run" in result.output
        assert "would write" in result.output

        # No files should exist
        assert not (tmp_path / ".cursor" / "rules" / "my-agent.md").exists()
        assert not (tmp_path / ".cursor" / "mcp.json").exists()

    def test_dry_run_still_shows_paths(self, tmp_path: Path):
        with _patch_config(), _patch_post(_cursor_snippet()):
            result = runner.invoke(cli_app, ["pull", "abc123", "--ide", "cursor", "--dir", str(tmp_path), "--dry-run"])

        # Rich may wrap long absolute paths; strip all whitespace for path checks
        flat = result.output.replace("\n", "").replace(" ", "")
        assert "my-agent.md" in flat
        assert "mcp.json" in flat

    def test_dry_run_kiro(self, tmp_path: Path):
        with _patch_config(), _patch_post(_kiro_snippet()):
            result = runner.invoke(cli_app, ["pull", "abc123", "--ide", "kiro", "--dir", str(tmp_path), "--dry-run"])

        assert result.exit_code == 0
        assert "would write" in result.output
        assert not (tmp_path / ".kiro" / "agents" / "my-agent.json").exists()


# ═══════════════════════════════════════════════════════════════
# 9. Edge cases and argument validation
# ═══════════════════════════════════════════════════════════════


class TestPullEdgeCases:
    def test_missing_ide_flag_fails(self):
        """--ide is required; omitting it should exit non-zero."""
        with _patch_config():
            result = runner.invoke(cli_app, ["pull", "abc123"])
        assert result.exit_code != 0

    def test_missing_agent_id_fails(self):
        """Agent ID is a required argument."""
        with _patch_config():
            result = runner.invoke(cli_app, ["pull", "--ide", "cursor"])
        assert result.exit_code != 0

    def test_empty_snippet_exits(self, tmp_path: Path):
        """An empty config_snippet from the server should exit non-zero."""
        with _patch_config(), _patch_post({"config_snippet": {}}):
            result = runner.invoke(cli_app, ["pull", "abc123", "--ide", "cursor", "--dir", str(tmp_path)])
        assert result.exit_code != 0
        assert "empty config snippet" in result.output.lower()

    def test_resolve_alias_is_called(self, tmp_path: Path):
        """The command should call config.resolve_alias for the agent_id."""
        with (
            _patch_config(),
            _patch_post(_codex_snippet()),
            patch("observal_cli.cmd_pull.config.resolve_alias", return_value="real-uuid") as mock_resolve,
        ):
            result = runner.invoke(cli_app, ["pull", "@myagent", "--ide", "codex", "--dir", str(tmp_path)])

        assert result.exit_code == 0, result.output
        mock_resolve.assert_called_once_with("@myagent")


# ═══════════════════════════════════════════════════════════════
# 10. Help text
# ═══════════════════════════════════════════════════════════════


class TestPullHelp:
    def test_help_flag(self):
        result = runner.invoke(cli_app, ["pull", "--help"])
        assert result.exit_code == 0
        out = _plain(result.output)
        assert "Fetch agent config" in out
        assert "--ide" in out
        assert "--dir" in out
        assert "--dry-run" in out


# ═══════════════════════════════════════════════════════════════
# Agent authoring CLI tests
# ═══════════════════════════════════════════════════════════════


def _make_agent_yaml(tmp_path: Path, **overrides) -> Path:
    """Write a minimal observal-agent.yaml and return its path."""
    data = {
        "name": "test-agent",
        "version": "1.0.0",
        "description": "A test agent",
        "owner": "test-team",
        "model_name": "claude-sonnet-4",
        "prompt": "You are helpful.",
        "components": [],
        "goal_template": {
            "description": "Goals for test-agent",
            "sections": [{"name": "default", "description": "Default goal section"}],
        },
    }
    data.update(overrides)
    yaml_path = tmp_path / "observal-agent.yaml"
    yaml_path.write_text(yaml.dump(data, default_flow_style=False, sort_keys=False))
    return yaml_path


def _patch_get(return_value):
    return patch("observal_cli.client.get", return_value=return_value)


def _patch_put(return_value):
    return patch("observal_cli.client.put", return_value=return_value)


class TestAgentInit:
    def test_creates_yaml_with_correct_fields(self, tmp_path: Path):
        """Interactive prompts produce a valid YAML file."""
        inputs = "my-agent\n1.0.0\nA cool agent\nmy-team\nclaude-sonnet-4\nDo helpful things\n"
        result = runner.invoke(
            cli_app,
            ["agent", "init", "--dir", str(tmp_path)],
            input=inputs,
        )
        assert result.exit_code == 0, result.output
        assert "Created" in result.output

        yaml_path = tmp_path / "observal-agent.yaml"
        assert yaml_path.exists()

        data = yaml.safe_load(yaml_path.read_text())
        assert data["name"] == "my-agent"
        assert data["version"] == "1.0.0"
        assert data["description"] == "A cool agent"
        assert data["owner"] == "my-team"
        assert data["model_name"] == "claude-sonnet-4"
        assert data["prompt"] == "Do helpful things"
        assert data["components"] == []
        assert data["goal_template"]["description"] == "Goals for my-agent"
        assert data["goal_template"]["sections"][0]["name"] == "default"

    def test_aborts_if_file_exists_and_user_declines(self, tmp_path: Path):
        """If YAML already exists and user says no, exit code != 0."""
        _make_agent_yaml(tmp_path)
        # "n" to decline overwrite
        result = runner.invoke(
            cli_app,
            ["agent", "init", "--dir", str(tmp_path)],
            input="n\n",
        )
        assert result.exit_code != 0
        assert "Aborted" in result.output

    def test_overwrites_if_user_confirms(self, tmp_path: Path):
        """If YAML exists and user says yes, proceed with new data."""
        _make_agent_yaml(tmp_path)
        inputs = "y\nnew-agent\n2.0.0\nNew desc\nnew-team\nclaude-sonnet-4\nNew prompt\n"
        result = runner.invoke(
            cli_app,
            ["agent", "init", "--dir", str(tmp_path)],
            input=inputs,
        )
        assert result.exit_code == 0, result.output
        data = yaml.safe_load((tmp_path / "observal-agent.yaml").read_text())
        assert data["name"] == "new-agent"


class TestAgentAdd:
    def test_adds_component_to_yaml(self, tmp_path: Path):
        """A valid component is appended to the components list."""
        _make_agent_yaml(tmp_path)
        result = runner.invoke(
            cli_app,
            ["agent", "add", "mcp", "aaaa-bbbb-cccc", "--dir", str(tmp_path)],
        )
        assert result.exit_code == 0, result.output
        assert "Added" in result.output

        data = yaml.safe_load((tmp_path / "observal-agent.yaml").read_text())
        assert len(data["components"]) == 1
        assert data["components"][0]["component_type"] == "mcp"
        assert data["components"][0]["component_id"] == "aaaa-bbbb-cccc"

    def test_rejects_invalid_component_type(self, tmp_path: Path):
        """Invalid component_type exits non-zero."""
        _make_agent_yaml(tmp_path)
        result = runner.invoke(
            cli_app,
            ["agent", "add", "widget", "some-id", "--dir", str(tmp_path)],
        )
        assert result.exit_code != 0
        assert "Invalid component type" in result.output

    def test_prevents_duplicate_component(self, tmp_path: Path):
        """Adding the same component twice exits non-zero."""
        _make_agent_yaml(
            tmp_path,
            components=[
                {"component_type": "skill", "component_id": "abc-123"},
            ],
        )
        result = runner.invoke(
            cli_app,
            ["agent", "add", "skill", "abc-123", "--dir", str(tmp_path)],
        )
        assert result.exit_code != 0
        assert "already exists" in result.output

    def test_fails_if_no_yaml(self, tmp_path: Path):
        """Fails if observal-agent.yaml does not exist."""
        result = runner.invoke(
            cli_app,
            ["agent", "add", "mcp", "some-id", "--dir", str(tmp_path)],
        )
        assert result.exit_code != 0
        assert "not found" in result.output


class TestAgentBuild:
    def test_validates_components_against_server(self, tmp_path: Path):
        """Components are validated via GET calls; output shows results."""
        _make_agent_yaml(
            tmp_path,
            components=[
                {"component_type": "mcp", "component_id": "id-1"},
                {"component_type": "skill", "component_id": "id-2"},
            ],
        )

        def mock_get(path, **kwargs):
            return {"id": "id-1", "name": "test"}

        with _patch_config(), patch("observal_cli.client.get", side_effect=mock_get):
            result = runner.invoke(
                cli_app,
                ["agent", "build", "--dir", str(tmp_path)],
            )
        assert result.exit_code == 0, result.output
        assert "All components valid" in result.output

    def test_reports_invalid_components(self, tmp_path: Path):
        """Components that fail GET show as errors."""
        _make_agent_yaml(
            tmp_path,
            components=[
                {"component_type": "mcp", "component_id": "bad-id"},
            ],
        )

        def mock_get(path, **kwargs):
            raise typer.Exit(code=1)

        with _patch_config(), patch("observal_cli.client.get", side_effect=mock_get):
            result = runner.invoke(
                cli_app,
                ["agent", "build", "--dir", str(tmp_path)],
            )
        assert result.exit_code != 0
        assert "failed validation" in result.output

    def test_fails_if_no_yaml(self, tmp_path: Path):
        """Fails if observal-agent.yaml does not exist."""
        result = runner.invoke(
            cli_app,
            ["agent", "build", "--dir", str(tmp_path)],
        )
        assert result.exit_code != 0
        assert "not found" in result.output


class TestAgentPublish:
    def test_creates_agent_via_post(self, tmp_path: Path):
        """publish sends correct payload via POST."""
        _make_agent_yaml(tmp_path)
        mock_result = {"id": "new-agent-uuid", "name": "test-agent"}

        with _patch_config(), _patch_post(mock_result) as mock_post_fn:
            result = runner.invoke(
                cli_app,
                ["agent", "publish", "--dir", str(tmp_path)],
            )
        assert result.exit_code == 0, result.output
        assert "Agent created" in result.output
        assert "new-agent-uuid" in result.output

        # Verify the POST payload
        call_args = mock_post_fn.call_args
        payload = call_args[0][1] if len(call_args[0]) > 1 else call_args[1].get("json_data")
        assert payload["name"] == "test-agent"
        assert payload["version"] == "1.0.0"
        assert payload["model_name"] == "claude-sonnet-4"

    def test_updates_existing_agent_with_update_flag(self, tmp_path: Path):
        """--update finds agent by name then PUTs."""
        _make_agent_yaml(tmp_path)
        search_results = [{"id": "existing-uuid", "name": "test-agent"}]
        put_result = {"id": "existing-uuid", "name": "test-agent"}

        with _patch_config(), _patch_get(search_results) as mock_get_fn, _patch_put(put_result) as mock_put_fn:
            result = runner.invoke(
                cli_app,
                ["agent", "publish", "--dir", str(tmp_path), "--update"],
            )

        assert result.exit_code == 0, result.output
        assert "Agent updated" in result.output
        assert "existing-uuid" in result.output

        # Verify GET was called with search param
        mock_get_fn.assert_called_once()
        get_call = mock_get_fn.call_args
        assert get_call[1].get("params", {}).get("search") == "test-agent"

        # Verify PUT was called with correct endpoint
        mock_put_fn.assert_called_once()
        put_call = mock_put_fn.call_args
        assert "existing-uuid" in put_call[0][0]

    def test_fails_if_no_yaml(self, tmp_path: Path):
        """Fails if observal-agent.yaml does not exist."""
        with _patch_config():
            result = runner.invoke(
                cli_app,
                ["agent", "publish", "--dir", str(tmp_path)],
            )
        assert result.exit_code != 0
        assert "not found" in result.output
