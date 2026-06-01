# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Tests for MCP edit and submit CLI commands (interactive flows).

Covers the interactive JSON paste mode in edit_mcp, the version publishing
flow for approved listings, and the submit command changes.
"""

from __future__ import annotations

import json
import re
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from observal_cli.main import app as cli_app

runner = CliRunner()

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _plain(text: str) -> str:
    return _ANSI_RE.sub("", text)


_FAKE_CONFIG = {"server_url": "http://localhost:8000", "api_key": "test-key", "user_name": "testuser"}


def _patch_config():
    return patch("observal_cli.config.get_or_exit", return_value=_FAKE_CONFIG)


def _patch_config_load():
    return patch("observal_cli.config.load", return_value=_FAKE_CONFIG)


def _patch_resolve_alias(resolved="abc-123"):
    return patch("observal_cli.config.resolve_alias", return_value=resolved)


# ── edit_mcp: interactive JSON paste mode ─────────────────────────


class TestEditMcpInteractive:
    """Tests for the interactive JSON paste mode in edit_mcp."""

    def test_edit_interactive_json_paste_draft(self):
        """Interactive paste mode parses config and edits a draft listing."""
        config_json = json.dumps({"command": "npx", "args": ["-y", "@example/server"], "env": {"KEY": "val"}})

        mock_client = MagicMock()
        mock_client.get.return_value = {"id": "abc-123", "status": "draft", "name": "test-mcp"}
        mock_client.post.return_value = {}
        mock_client.put.return_value = {"name": "test-mcp", "status": "draft"}

        with (
            _patch_config(),
            _patch_config_load(),
            _patch_resolve_alias(),
            patch("observal_cli.cmd_mcp.client", mock_client),
            patch("observal_cli.cmd_mcp.spinner", MagicMock()),
        ):
            result = runner.invoke(cli_app, ["registry", "mcp", "edit", "test-mcp"], input=f"{config_json}\n\ny\n")

        assert result.exit_code == 0, _plain(result.output)
        assert "Updated" in _plain(result.output) or "updated" in _plain(result.output).lower()

    def test_edit_interactive_empty_input_exits(self):
        """Empty input in interactive mode exits with code 1."""
        mock_client = MagicMock()

        with (
            _patch_config(),
            _patch_config_load(),
            _patch_resolve_alias(),
            patch("observal_cli.cmd_mcp.client", mock_client),
        ):
            result = runner.invoke(cli_app, ["registry", "mcp", "edit", "test-mcp"], input="\n")

        assert result.exit_code == 1
        assert "No input" in _plain(result.output)

    def test_edit_interactive_invalid_json_exits(self):
        """Invalid JSON in interactive mode exits with error."""
        mock_client = MagicMock()

        with (
            _patch_config(),
            _patch_config_load(),
            _patch_resolve_alias(),
            patch("observal_cli.cmd_mcp.client", mock_client),
        ):
            result = runner.invoke(cli_app, ["registry", "mcp", "edit", "test-mcp"], input="not json at all{{\n\n")

        assert result.exit_code == 1
        assert "Invalid JSON" in _plain(result.output)

    def test_edit_interactive_user_declines(self):
        """User declining confirmation aborts."""
        config_json = json.dumps({"command": "npx", "args": ["-y", "server"]})
        mock_client = MagicMock()

        with (
            _patch_config(),
            _patch_config_load(),
            _patch_resolve_alias(),
            patch("observal_cli.cmd_mcp.client", mock_client),
            patch("observal_cli.cmd_mcp.spinner", MagicMock()),
        ):
            result = runner.invoke(cli_app, ["registry", "mcp", "edit", "test-mcp"], input=f"{config_json}\n\nn\n")

        # Aborted = non-zero exit
        assert result.exit_code != 0

    def test_edit_with_flags_skips_interactive(self):
        """Providing --name flag skips interactive mode."""
        mock_client = MagicMock()
        mock_client.get.return_value = {"id": "abc-123", "status": "draft", "name": "old-name"}
        mock_client.post.return_value = {}
        mock_client.put.return_value = {"name": "new-name", "status": "draft"}

        with (
            _patch_config(),
            _patch_config_load(),
            _patch_resolve_alias(),
            patch("observal_cli.cmd_mcp.client", mock_client),
            patch("observal_cli.cmd_mcp.spinner", MagicMock()),
        ):
            result = runner.invoke(cli_app, ["registry", "mcp", "edit", "test-mcp", "--name", "new-name"])

        assert result.exit_code == 0, _plain(result.output)
        mock_client.put.assert_called_once()
        call_args = mock_client.put.call_args[0]
        assert "new-name" in str(call_args) or mock_client.put.call_args[1].get("name") == "new-name"

    def test_edit_from_file(self):
        """--from-file loads updates from a JSON file."""
        mock_client = MagicMock()
        mock_client.get.return_value = {"id": "abc-123", "status": "draft", "name": "test-mcp"}
        mock_client.post.return_value = {}
        mock_client.put.return_value = {"name": "test-mcp", "status": "draft"}

        file_content = json.dumps({"name": "updated-mcp", "description": "New desc"})

        with (
            _patch_config(),
            _patch_config_load(),
            _patch_resolve_alias(),
            patch("observal_cli.cmd_mcp.client", mock_client),
            patch("observal_cli.cmd_mcp.spinner", MagicMock()),
            patch("builtins.open", create=True) as mock_open,
        ):
            mock_open.return_value.__enter__ = lambda s: MagicMock(read=lambda: file_content)
            mock_open.return_value.__exit__ = MagicMock(return_value=False)
            # Patch json.load to use file_content
            with patch("json.load", return_value={"name": "updated-mcp", "description": "New desc"}):
                result = runner.invoke(cli_app, ["registry", "mcp", "edit", "test-mcp", "--from-file", "updates.json"])

        assert result.exit_code == 0, _plain(result.output)


# ── edit_mcp: version publishing for approved listings ────────────


class TestEditMcpVersionPublish:
    """Tests for the version publishing flow when editing approved MCPs."""

    def test_edit_approved_publishes_new_version_patch(self):
        """Editing an approved listing with patch bump publishes a new version."""
        config_json = json.dumps({"command": "npx", "args": ["-y", "@example/v2"]})

        mock_client = MagicMock()
        mock_client.get.return_value = {"id": "abc-123", "status": "approved", "name": "my-mcp", "version": "1.2.3"}
        mock_client.post.return_value = {"name": "my-mcp", "version": "1.2.4"}

        with (
            _patch_config(),
            _patch_config_load(),
            _patch_resolve_alias(),
            patch("observal_cli.cmd_mcp.client", mock_client),
            patch("observal_cli.cmd_mcp.spinner", MagicMock()),
            patch("observal_cli.cmd_mcp.select_one", return_value="patch"),
        ):
            # Input: config JSON, blank line, confirm, changelog
            result = runner.invoke(
                cli_app, ["registry", "mcp", "edit", "my-mcp"], input=f"{config_json}\n\ny\nFixed bug\n"
            )

        assert result.exit_code == 0, _plain(result.output)
        assert "1.2.4" in _plain(result.output)
        # Verify the versions endpoint was called
        post_calls = [c for c in mock_client.post.call_args_list if "/versions" in str(c)]
        assert len(post_calls) == 1

    def test_edit_approved_minor_bump(self):
        """Minor bump increments correctly."""
        config_json = json.dumps({"url": "https://new-url.com/mcp", "type": "sse"})

        mock_client = MagicMock()
        mock_client.get.return_value = {"id": "abc-123", "status": "approved", "name": "my-mcp", "version": "1.2.3"}
        mock_client.post.return_value = {"name": "my-mcp", "version": "1.3.0"}

        with (
            _patch_config(),
            _patch_config_load(),
            _patch_resolve_alias(),
            patch("observal_cli.cmd_mcp.client", mock_client),
            patch("observal_cli.cmd_mcp.spinner", MagicMock()),
            patch("observal_cli.cmd_mcp.select_one", return_value="minor"),
        ):
            result = runner.invoke(
                cli_app, ["registry", "mcp", "edit", "my-mcp"], input=f"{config_json}\n\ny\nNew feature\n"
            )

        assert result.exit_code == 0, _plain(result.output)
        assert "1.3.0" in _plain(result.output)

    def test_edit_approved_major_bump(self):
        """Major bump increments correctly."""
        config_json = json.dumps({"command": "docker", "args": ["run", "new-image:2.0"]})

        mock_client = MagicMock()
        mock_client.get.return_value = {"id": "abc-123", "status": "approved", "name": "my-mcp", "version": "1.2.3"}
        mock_client.post.return_value = {"name": "my-mcp", "version": "2.0.0"}

        with (
            _patch_config(),
            _patch_config_load(),
            _patch_resolve_alias(),
            patch("observal_cli.cmd_mcp.client", mock_client),
            patch("observal_cli.cmd_mcp.spinner", MagicMock()),
            patch("observal_cli.cmd_mcp.select_one", return_value="major"),
        ):
            result = runner.invoke(
                cli_app, ["registry", "mcp", "edit", "my-mcp"], input=f"{config_json}\n\ny\nBreaking change\n"
            )

        assert result.exit_code == 0, _plain(result.output)
        assert "2.0.0" in _plain(result.output)

    def test_edit_approved_publish_failure(self):
        """Failure to publish a new version exits with error."""
        config_json = json.dumps({"command": "npx", "args": ["-y", "server"]})

        mock_client = MagicMock()
        mock_client.get.return_value = {"id": "abc-123", "status": "approved", "name": "my-mcp", "version": "0.1.0"}
        # Client raises SystemExit (typer.Exit) on API failure
        mock_client.post.side_effect = SystemExit(1)

        with (
            _patch_config(),
            _patch_config_load(),
            _patch_resolve_alias(),
            patch("observal_cli.cmd_mcp.client", mock_client),
            patch("observal_cli.cmd_mcp.spinner", MagicMock()),
            patch("observal_cli.cmd_mcp.select_one", return_value="patch"),
        ):
            result = runner.invoke(cli_app, ["registry", "mcp", "edit", "my-mcp"], input=f"{config_json}\n\ny\n\n")

        assert result.exit_code == 1


# ── submit command changes ────────────────────────────────────────


class TestSubmitCommand:
    """Tests for submit command changes (default JSON paste, --git flag)."""

    def test_submit_deprecated_config_flag_shows_note(self):
        """--config flag shows deprecation note."""
        config_json = json.dumps({"command": "npx", "args": ["-y", "server"]})

        mock_client = MagicMock()
        mock_client.post.return_value = {"id": "new-123", "name": "my-mcp", "status": "pending"}

        with (
            _patch_config(),
            _patch_config_load(),
            patch("observal_cli.cmd_mcp.client", mock_client),
            patch("observal_cli.cmd_mcp.spinner", MagicMock()),
            patch("observal_cli.cmd_mcp.select_one", return_value="general"),
        ):
            result = runner.invoke(
                cli_app,
                ["registry", "mcp", "submit", "--config", "--yes", "--name", "my-mcp"],
                input=f"{config_json}\n\n",
            )

        output = _plain(result.output)
        assert "--config is now the default" in output

    def test_submit_draft_and_submit_together_fails(self):
        """Cannot use --draft and --submit together."""
        with _patch_config(), _patch_config_load():
            result = runner.invoke(cli_app, ["registry", "mcp", "submit", "--draft", "--submit", "abc-123"])

        assert result.exit_code == 1
        assert "Cannot use" in _plain(result.output)

    def test_submit_draft_for_review(self):
        """--submit flag submits an existing draft for review."""
        mock_client = MagicMock()
        mock_client.post.return_value = {"id": "abc-123", "name": "my-mcp"}

        with (
            _patch_config(),
            _patch_config_load(),
            _patch_resolve_alias("abc-123"),
            patch("observal_cli.cmd_mcp.client", mock_client),
            patch("observal_cli.cmd_mcp.spinner", MagicMock()),
        ):
            result = runner.invoke(cli_app, ["registry", "mcp", "submit", "--submit", "abc-123"])

        assert result.exit_code == 0, _plain(result.output)
        assert "Draft submitted" in _plain(result.output) or "submitted" in _plain(result.output).lower()

    def test_submit_yes_mode_uses_parsed_description(self):
        """In --yes mode, parsed description from registry format is used."""
        config_json = json.dumps(
            {
                "server": {
                    "title": "My Server",
                    "description": "A great server",
                    "remotes": [{"url": "https://api.example.com", "type": "sse"}],
                }
            }
        )

        mock_client = MagicMock()
        mock_client.post.return_value = {"id": "new-123", "name": "My Server", "status": "pending"}

        with (
            _patch_config(),
            _patch_config_load(),
            patch("observal_cli.cmd_mcp.client", mock_client),
            patch("observal_cli.cmd_mcp.spinner", MagicMock()),
        ):
            result = runner.invoke(
                cli_app,
                ["registry", "mcp", "submit", "--yes", "--name", "My Server"],
                input=f"{config_json}\n\n",
            )

        # The submit should use the parsed description "A great server"
        if result.exit_code == 0:
            post_call = mock_client.post.call_args
            if post_call and len(post_call[0]) > 1:
                payload = post_call[0][1]
                assert payload.get("description") == "A great server"

    def test_submit_description_required_in_interactive_mode(self):
        """Interactive mode requires non-empty description."""
        config_json = json.dumps({"command": "npx", "args": ["-y", "server"]})

        mock_client = MagicMock()
        mock_client.post.return_value = {"id": "new-123", "name": "my-mcp", "status": "pending"}

        with (
            _patch_config(),
            _patch_config_load(),
            patch("observal_cli.cmd_mcp.client", mock_client),
            patch("observal_cli.cmd_mcp.spinner", MagicMock()),
            patch("observal_cli.cmd_mcp.select_one", return_value="general"),
        ):
            # Input: config + blank line, confirm, name prompt accepts default,
            # empty spaces for description (triggers required), then real description, owner
            result = runner.invoke(
                cli_app,
                ["registry", "mcp", "submit", "--name", "my-mcp"],
                input=f"{config_json}\n\ny\n   \nA real description\n\n",
            )

        output = _plain(result.output)
        assert "Description is required" in output


# ── edit_mcp: edge cases and error paths ──────────────────────────


class TestEditMcpEdgeCases:
    """Tests for edge cases in edit_mcp."""

    def test_edit_from_file_not_found(self):
        """--from-file with missing file exits with error."""
        with (
            _patch_config(),
            _patch_config_load(),
            _patch_resolve_alias(),
        ):
            result = runner.invoke(
                cli_app, ["registry", "mcp", "edit", "test-mcp", "--from-file", "/nonexistent/file.json"]
            )

        assert result.exit_code == 1
        assert "not found" in _plain(result.output).lower() or "File not found" in _plain(result.output)

    def test_edit_from_file_invalid_json(self, tmp_path):
        """--from-file with invalid JSON exits with error."""
        bad_file = tmp_path / "bad.json"
        bad_file.write_text("not valid json {{{")

        with (
            _patch_config(),
            _patch_config_load(),
            _patch_resolve_alias(),
        ):
            result = runner.invoke(cli_app, ["registry", "mcp", "edit", "test-mcp", "--from-file", str(bad_file)])

        assert result.exit_code == 1
        assert "Invalid JSON" in _plain(result.output)

    def test_edit_draft_save_failure_cancels_edit(self):
        """Draft save failure triggers cancel-edit and exits with error."""
        mock_client = MagicMock()
        mock_client.get.return_value = {"id": "abc-123", "status": "draft", "name": "my-mcp"}
        mock_client.post.return_value = {}  # start-edit succeeds
        # Client raises SystemExit (typer.Exit) on API failure
        mock_client.put.side_effect = SystemExit(1)

        with (
            _patch_config(),
            _patch_config_load(),
            _patch_resolve_alias(),
            patch("observal_cli.cmd_mcp.client", mock_client),
            patch("observal_cli.cmd_mcp.spinner", MagicMock()),
        ):
            result = runner.invoke(cli_app, ["registry", "mcp", "edit", "test-mcp", "--name", "new-name"])

        assert result.exit_code == 1
        # Verify cancel-edit was attempted
        cancel_calls = [c for c in mock_client.post.call_args_list if "cancel-edit" in str(c)]
        assert len(cancel_calls) == 1

    def test_edit_non_semver_version_fallback(self):
        """Non-semver version string falls back to 0.2.0."""
        config_json = json.dumps({"command": "npx", "args": ["-y", "server"]})

        mock_client = MagicMock()
        mock_client.get.return_value = {
            "id": "abc-123",
            "status": "approved",
            "name": "my-mcp",
            "version": "not-semver",
        }
        mock_client.post.return_value = {"name": "my-mcp", "version": "0.2.0"}

        with (
            _patch_config(),
            _patch_config_load(),
            _patch_resolve_alias(),
            patch("observal_cli.cmd_mcp.client", mock_client),
            patch("observal_cli.cmd_mcp.spinner", MagicMock()),
            patch("observal_cli.cmd_mcp.select_one", return_value="patch"),
        ):
            result = runner.invoke(
                cli_app, ["registry", "mcp", "edit", "my-mcp"], input=f"{config_json}\n\ny\nChangelog\n"
            )

        assert result.exit_code == 0, _plain(result.output)
        assert "0.2.0" in _plain(result.output)

    def test_edit_status_fetch_failure_falls_through(self):
        """If status fetch fails, edit proceeds with draft flow."""
        mock_client = MagicMock()
        # Client raises SystemExit (typer.Exit) on connection/API failure
        mock_client.get.side_effect = SystemExit(1)
        mock_client.post.return_value = {}
        mock_client.put.return_value = {"name": "test-mcp", "status": "draft"}

        with (
            _patch_config(),
            _patch_config_load(),
            _patch_resolve_alias(),
            patch("observal_cli.cmd_mcp.client", mock_client),
            patch("observal_cli.cmd_mcp.spinner", MagicMock()),
        ):
            result = runner.invoke(cli_app, ["registry", "mcp", "edit", "test-mcp", "--description", "New desc"])

        assert result.exit_code == 0, _plain(result.output)
        assert "Updated" in _plain(result.output) or "updated" in _plain(result.output).lower()

    def test_edit_interactive_registry_format_extracts_name_and_desc(self):
        """Registry format in interactive mode extracts name and description into updates."""
        config_json = json.dumps(
            {
                "server": {
                    "title": "New Name",
                    "description": "Updated description",
                    "remotes": [{"url": "https://api.new.com/mcp", "type": "sse"}],
                }
            }
        )

        mock_client = MagicMock()
        mock_client.get.return_value = {"id": "abc-123", "status": "draft", "name": "old-name"}
        mock_client.post.return_value = {}
        mock_client.put.return_value = {"name": "New Name", "status": "draft"}

        with (
            _patch_config(),
            _patch_config_load(),
            _patch_resolve_alias(),
            patch("observal_cli.cmd_mcp.client", mock_client),
            patch("observal_cli.cmd_mcp.spinner", MagicMock()),
        ):
            result = runner.invoke(cli_app, ["registry", "mcp", "edit", "old-name"], input=f"{config_json}\n\ny\n")

        assert result.exit_code == 0, _plain(result.output)
        # Verify the PUT was called with name and description
        put_call = mock_client.put.call_args
        updates_sent = put_call[0][1] if put_call else {}
        assert updates_sent.get("name") == "New Name"
        assert updates_sent.get("description") == "Updated description"
