# SPDX-FileCopyrightText: 2026 Nithin <nithin30302@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Tests for the `observal prompt` commands."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

from unittest.mock import patch

from typer.testing import CliRunner

from observal_cli import cmd_prompt  # noqa: F401
from observal_cli.main import app as cli_app

runner = CliRunner()


def _patch_config_load():
    return patch("observal_cli.config.load", return_value={"user_name": "testuser"})


def _patch_resolve_alias():
    return patch("observal_cli.config.resolve_alias", side_effect=lambda x: x)


def _patch_get(return_value):
    return patch("observal_cli.client.get", return_value=return_value)


def _patch_post(return_value):
    return patch("observal_cli.client.post", return_value=return_value)


def _patch_put(return_value):
    return patch("observal_cli.client.put", return_value=return_value)


def _patch_delete(return_value=None):
    return patch("observal_cli.client.delete", return_value=return_value)


class TestPromptSubmit:
    def test_submit_interactive(self):
        """Test prompt submit with interactive inputs, ensuring payload validation (name, category, etc)."""
        # Inputs: name, version, description, owner, category, template
        inputs = "my-prompt\n1.0.0\nMy description\ntestowner\ngeneral\nHello {{name}}!\n"
        with _patch_config_load(), _patch_post({"id": "prompt-123"}) as mock_post:
            result = runner.invoke(cli_app, ["registry", "prompt", "submit"], input=inputs)

            assert result.exit_code == 0
            assert "Prompt submitted!" in result.output
            assert "prompt-123" in result.output

            mock_post.assert_called_once()
            url, payload = mock_post.call_args[0]
            assert url == "/api/v1/prompts/submit"
            # Validate metadata schema constraints
            assert payload["name"] == "my-prompt"
            assert payload["version"] == "1.0.0"
            assert payload["description"] == "My description"
            assert payload["owner"] == "testowner"
            assert payload["category"] == "general"
            assert payload["template"] == "Hello {{name}}!"

    def test_submit_draft(self):
        """Test prompt submit --draft saves a draft."""
        inputs = "draft-prompt\n1.0.0\nDraft desc\ntestowner\ngeneral\nDraft template\n"
        with _patch_config_load(), _patch_post({"id": "draft-123"}) as mock_post:
            result = runner.invoke(cli_app, ["registry", "prompt", "submit", "--draft"], input=inputs)

            assert result.exit_code == 0
            assert "Draft saved!" in result.output

            mock_post.assert_called_once()
            url, payload = mock_post.call_args[0]
            assert url == "/api/v1/prompts/draft"
            assert payload["name"] == "draft-prompt"

    def test_submit_from_file_json(self, tmp_path: Path):
        """Test prompt submit --from-file with a JSON file, validating metadata loads correctly."""
        prompt_json = tmp_path / "prompt.json"
        payload = {
            "name": "json-prompt",
            "version": "2.0.0",
            "description": "JSON desc",
            "owner": "jsonowner",
            "category": "utility",
            "template": "JSON {{template}}",
        }
        prompt_json.write_text(json.dumps(payload))

        with _patch_config_load(), _patch_post({"id": "prompt-json-123"}) as mock_post:
            result = runner.invoke(cli_app, ["registry", "prompt", "submit", "--from-file", str(prompt_json)])

            assert result.exit_code == 0
            assert "Prompt submitted!" in result.output

            mock_post.assert_called_once()
            url, submitted_payload = mock_post.call_args[0]
            assert url == "/api/v1/prompts/submit"
            assert submitted_payload["name"] == "json-prompt"
            assert submitted_payload["category"] == "utility"
            assert submitted_payload["template"] == "JSON {{template}}"


class TestPromptList:
    def test_list_prompts(self):
        """Test prompt list command output."""
        mock_data = [
            {"id": "p1", "name": "prompt-one", "version": "1.0.0", "status": "approved", "owner": "user1"},
            {"id": "p2", "name": "prompt-two", "version": "1.1.0", "status": "approved", "owner": "user2"},
        ]
        with _patch_get(mock_data), patch("observal_cli.config.save_last_results"):
            result = runner.invoke(cli_app, ["registry", "prompt", "list"])

            assert result.exit_code == 0
            assert "prompt-one" in result.output
            assert "prompt-two" in result.output


class TestPromptShow:
    def test_show_prompt(self):
        """Test prompt show command fetches details correctly."""
        mock_data = {
            "id": "p123",
            "name": "test-prompt",
            "version": "1.0.0",
            "status": "approved",
            "owner": "testuser",
            "description": "A test prompt",
            "category": "coding",
            "created_at": "2026-05-14T00:00:00Z",
            "template": "Hello {{world}}",
        }
        with _patch_resolve_alias(), _patch_get(mock_data):
            result = runner.invoke(cli_app, ["registry", "prompt", "show", "p123"])

            assert result.exit_code == 0
            assert "test-prompt" in result.output
            assert "Hello {{world}}" in result.output


class TestPromptMy:
    def test_my_prompts(self):
        """Test prompt my command."""
        mock_data = [
            {"id": "p1", "name": "my-first-prompt", "version": "1.0.0", "status": "approved", "owner": "testuser"}
        ]
        with _patch_get(mock_data), patch("observal_cli.config.save_last_results"):
            result = runner.invoke(cli_app, ["registry", "prompt", "my"])

            assert result.exit_code == 0
            assert "my-first-prompt" in result.output
            assert "My Prompts" in result.output


class TestPromptRender:
    def test_render_prompt(self):
        """Test prompt render command with variables."""
        with _patch_resolve_alias(), _patch_post({"rendered": "Hello Earth!"}) as mock_post:
            result = runner.invoke(cli_app, ["registry", "prompt", "render", "p123", "--var", "target=Earth"])

            assert result.exit_code == 0
            assert "Hello Earth!" in result.output

            mock_post.assert_called_once()
            url, payload = mock_post.call_args[0]
            assert url == "/api/v1/prompts/p123/render"
            assert payload["variables"] == {"target": "Earth"}


class TestPromptInstall:
    def test_install_prompt(self):
        """Test prompt install command."""
        mock_data = {"config_snippet": {"key": "value"}}
        with _patch_resolve_alias(), _patch_post(mock_data) as mock_post:
            result = runner.invoke(cli_app, ["registry", "prompt", "install", "p123", "--ide", "vscode"])

            assert result.exit_code == 0
            assert "Config for vscode:" in result.output

            mock_post.assert_called_once()
            url, payload = mock_post.call_args[0]
            assert url == "/api/v1/prompts/p123/install"
            assert payload["ide"] == "vscode"


class TestPromptEdit:
    def test_edit_prompt(self):
        """Test prompt edit command."""
        mock_data = {"name": "edited-prompt", "status": "draft"}
        with _patch_resolve_alias(), _patch_post({"status": "ok"}) as mock_post, _patch_put(mock_data) as mock_put:
            result = runner.invoke(cli_app, ["registry", "prompt", "edit", "p123", "--name", "edited-prompt"])

            assert result.exit_code == 0
            assert "Updated edited-prompt" in result.output

            mock_post.assert_called_once_with("/api/v1/prompts/p123/start-edit")
            mock_put.assert_called_once()
            url, payload = mock_put.call_args[0]
            assert url == "/api/v1/prompts/p123/draft"
            assert payload["name"] == "edited-prompt"


class TestPromptDelete:
    def test_delete_prompt(self):
        """Test prompt delete command."""
        mock_data = {"id": "p123", "name": "prompt-to-delete"}
        with _patch_resolve_alias(), _patch_get(mock_data), _patch_delete() as mock_delete:
            result = runner.invoke(cli_app, ["registry", "prompt", "delete", "p123", "--yes"])

            assert result.exit_code == 0
            assert "Deleted p123" in result.output

            mock_delete.assert_called_once_with("/api/v1/prompts/p123")


class TestPromptEdgeCases:
    def test_mutually_exclusive_flags(self):
        """Using --draft and --submit together should fail fast."""
        result = runner.invoke(cli_app, ["registry", "prompt", "submit", "--draft", "--submit", "p1"])
        assert result.exit_code == 1
        assert "Cannot use --draft and --submit together" in result.output

    def test_list_empty_results(self):
        """List should handle empty result set gracefully."""
        with _patch_get([]), patch("observal_cli.config.save_last_results"):
            result = runner.invoke(cli_app, ["registry", "prompt", "list"])

            assert result.exit_code == 0
            assert "No prompts found." in result.output

    def test_edit_file_not_found(self):
        """Editing from a non-existent file should show a clear error and exit 1."""
        with _patch_resolve_alias():
            result = runner.invoke(cli_app, ["registry", "prompt", "edit", "p123", "--from-file", "nope.json"])

            assert result.exit_code == 1
            assert "File not found" in result.output

    def test_install_api_error(self):
        """API errors during install should propagate as failures (non-zero exit)."""

        def _raise(*_a, **_kw):
            raise Exception("500 Internal")

        with _patch_resolve_alias(), patch("observal_cli.client.post", side_effect=_raise):
            result = runner.invoke(cli_app, ["registry", "prompt", "install", "p123", "--ide", "vscode"])

            assert result.exit_code == 1
            assert "500 Internal" in (result.output or str(result.exception))

    def test_select_one_integration_gap(self):
        """Document that category passed via CLI is not validated client-side (integration gap).

        The CLI currently forwards whatever `--category` value is provided to the server
        without validating it against `VALID_PROMPT_CATEGORIES`. This test asserts the
        client call contains the provided (invalid) category value.
        """
        mock_data = []
        with _patch_get(mock_data) as mock_get, patch("observal_cli.config.save_last_results"):
            result = runner.invoke(cli_app, ["registry", "prompt", "list", "--category", "invalid-category"])

            assert result.exit_code == 0
            mock_get.assert_called_once()
            _, kwargs = mock_get.call_args
            params = kwargs.get("params") or {}
            assert params.get("category") == "invalid-category"
