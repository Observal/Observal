# SPDX-FileCopyrightText: 2026 Abdul Moiz Hussain <abdulmoizx97@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Tests for the sandbox registry CLI commands.

Cover the most important scenarios:
* submit from file, interactive, and draft workflows
* list with filters, empty results, and output formats
* show with different input types and missing fields
* install with raw and pretty output, deprecation warning
* delete with and without confirmation
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from observal_cli.main import app as cli_app

if TYPE_CHECKING:
    from pathlib import Path

runner = CliRunner()


def _patch_resolve_alias():
    """Helper to patch resolve_alias to return input unchanged."""
    return patch("observal_cli.config.resolve_alias", side_effect=lambda value: value)


@pytest.fixture()
def sandbox_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Isolate CLI tests from real home directory."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    return tmp_path


class TestSandboxSubmit:
    """Tests for the sandbox submit command."""

    def test_submit_from_file(self, tmp_path: Path, sandbox_home: Path) -> None:
        sandbox_file = tmp_path / "sandbox.json"
        payload = {
            "name": "python-sandbox",
            "version": "1.0.0",
            "description": "Python execution environment",
            "owner": "testuser",
            "runtime_type": "docker",
            "image": "python:3.12",
            "resource_limits": {"cpu": 2, "memory": "2Gi"},
        }
        sandbox_file.write_text(json.dumps(payload))

        with patch("observal_cli.client.post", return_value={"id": "sandbox-123"}) as mock_post:
            result = runner.invoke(cli_app, ["sandbox", "submit", "--from-file", str(sandbox_file)])

        assert result.exit_code == 0, result.output
        assert "Sandbox submitted!" in result.output
        assert "sandbox-123" in result.output
        mock_post.assert_called_once_with("/api/v1/sandboxes/submit", payload)

    def test_submit_existing_draft(self, sandbox_home: Path) -> None:
        with (
            patch("observal_cli.config.resolve_alias", return_value="draft-123") as mock_resolve,
            patch("observal_cli.client.post", return_value={"id": "submitted-123"}) as mock_post,
        ):
            result = runner.invoke(cli_app, ["sandbox", "submit", "--submit", "draft-123"])

        assert result.exit_code == 0, result.output
        assert "Draft submitted for review!" in result.output
        mock_resolve.assert_called_once_with("draft-123")
        mock_post.assert_called_once_with("/api/v1/sandboxes/draft-123/submit")

    def test_submit_from_file_missing(self, sandbox_home: Path) -> None:
        result = runner.invoke(cli_app, ["sandbox", "submit", "--from-file", "missing.json"])

        assert result.exit_code == 1, result.output
        assert "File not found" in result.output

    def test_submit_from_file_invalid_json(self, tmp_path: Path, sandbox_home: Path) -> None:
        sandbox_file = tmp_path / "sandbox.json"
        sandbox_file.write_text("{broken json")

        result = runner.invoke(cli_app, ["sandbox", "submit", "--from-file", str(sandbox_file)])

        assert result.exit_code == 1, result.output
        assert "Invalid JSON" in result.output

    def test_submit_draft_interactive(self, sandbox_home: Path) -> None:
        inputs = "dev-sandbox\n1.0.0\nDevelopment environment\ntestuser\ndocker\npython:3.12\n{\"cpu\": 1}\n"

        with patch("observal_cli.client.post", return_value={"id": "draft-123"}) as mock_post:
            result = runner.invoke(cli_app, ["sandbox", "submit", "--draft"], input=inputs)

        assert result.exit_code == 0, result.output
        assert "Draft saved!" in result.output
        url, submitted_payload = mock_post.call_args.args
        assert url == "/api/v1/sandboxes/draft"
        assert submitted_payload["name"] == "dev-sandbox"
        assert submitted_payload["runtime_type"] == "docker"
        assert submitted_payload["resource_limits"] == {"cpu": 1}

    def test_submit_interactive_direct(self, sandbox_home: Path) -> None:
        inputs = "dev-sandbox\n1.0.0\nDevelopment environment\ntestuser\ndocker\npython:3.12\n{\"cpu\": 1}\n"

        with patch("observal_cli.client.post", return_value={"id": "sandbox-456"}) as mock_post:
            result = runner.invoke(cli_app, ["sandbox", "submit"], input=inputs)

        assert result.exit_code == 0, result.output
        assert "Sandbox submitted!" in result.output
        mock_post.assert_called_once()
        url, submitted_payload = mock_post.call_args.args
        assert url == "/api/v1/sandboxes/submit"
        assert submitted_payload["name"] == "dev-sandbox"

    def test_submit_rejects_draft_and_submit_together(self, sandbox_home: Path) -> None:
        result = runner.invoke(cli_app, ["sandbox", "submit", "--draft", "--submit", "sandbox-123"])

        assert result.exit_code == 1, result.output
        assert "Cannot use --draft and --submit together" in result.output


class TestSandboxList:
    """Tests for the sandbox list command."""

    def test_list_empty_results(self, sandbox_home: Path) -> None:
        with (
            patch("observal_cli.client.get", return_value=[]) as mock_get,
            patch("observal_cli.config.save_last_results") as mock_save,
            patch("observal_cli.cmd_sandbox.output_json") as mock_output,
            patch("observal_cli.cmd_sandbox.console.print") as mock_print,
        ):
            result = runner.invoke(cli_app, ["sandbox", "list"])

        assert result.exit_code == 0, result.output
        assert "No sandboxes found." in result.output
        mock_get.assert_called_once_with("/api/v1/sandboxes", params={})
        mock_save.assert_not_called()
        mock_output.assert_not_called()
        mock_print.assert_not_called()

    def test_list_no_filters_sends_empty_params(self, sandbox_home: Path) -> None:
        sandboxes = [{"id": "s1", "name": "python", "version": "1.0.0", "status": "approved", "owner": "user"}]

        with (
            patch("observal_cli.client.get", return_value=sandboxes) as mock_get,
            patch("observal_cli.config.save_last_results"),
            patch("observal_cli.cmd_sandbox.Table") as mock_table,
            patch("observal_cli.cmd_sandbox.console.print"),
        ):
            result = runner.invoke(cli_app, ["sandbox", "list"])

        assert result.exit_code == 0, result.output
        mock_get.assert_called_once_with("/api/v1/sandboxes", params={})
        mock_table.assert_called_once_with(title="Sandboxes (1)", show_lines=False, padding=(0, 1))

    def test_list_json_with_filters(self, sandbox_home: Path) -> None:
        sandboxes = [{"id": "s1", "name": "python", "version": "1.0.0", "status": "approved", "owner": "user"}]

        with (
            patch("observal_cli.client.get", return_value=sandboxes) as mock_get,
            patch("observal_cli.config.save_last_results"),
            patch("observal_cli.cmd_sandbox.output_json") as mock_output,
        ):
            result = runner.invoke(
                cli_app,
                ["sandbox", "list", "--runtime", "docker", "--search", "python", "--output", "json"],
            )

        assert result.exit_code == 0, result.output
        mock_get.assert_called_once_with(
            "/api/v1/sandboxes", params={"runtime": "docker", "search": "python"}
        )
        mock_output.assert_called_once_with(sandboxes)

    def test_list_runtime_filter_only(self, sandbox_home: Path) -> None:
        sandboxes = [{"id": "s1", "name": "python", "version": "1.0.0", "status": "approved", "owner": "user"}]

        with (
            patch("observal_cli.client.get", return_value=sandboxes) as mock_get,
            patch("observal_cli.config.save_last_results"),
            patch("observal_cli.cmd_sandbox.Table"),
            patch("observal_cli.cmd_sandbox.console.print"),
        ):
            result = runner.invoke(cli_app, ["sandbox", "list", "--runtime", "docker"])

        assert result.exit_code == 0, result.output
        mock_get.assert_called_once_with("/api/v1/sandboxes", params={"runtime": "docker"})

    def test_list_search_filter_only(self, sandbox_home: Path) -> None:
        sandboxes = [{"id": "s1", "name": "python", "version": "1.0.0", "status": "approved", "owner": "user"}]

        with (
            patch("observal_cli.client.get", return_value=sandboxes) as mock_get,
            patch("observal_cli.config.save_last_results"),
            patch("observal_cli.cmd_sandbox.Table"),
            patch("observal_cli.cmd_sandbox.console.print"),
        ):
            result = runner.invoke(cli_app, ["sandbox", "list", "--search", "python"])

        assert result.exit_code == 0, result.output
        mock_get.assert_called_once_with("/api/v1/sandboxes", params={"search": "python"})

    def test_list_plain_output(self, sandbox_home: Path) -> None:
        sandboxes = [{"id": "s1", "name": "python", "version": "1.0.0", "status": "approved", "owner": "user"}]

        with (
            patch("observal_cli.client.get", return_value=sandboxes) as mock_get,
            patch("observal_cli.config.save_last_results"),
            patch("observal_cli.cmd_sandbox.rprint") as mock_rprint,
            patch("observal_cli.cmd_sandbox.Table"),
            patch("observal_cli.cmd_sandbox.console.print"),
        ):
            result = runner.invoke(cli_app, ["sandbox", "list", "--output", "plain"])

        assert result.exit_code == 0, result.output
        mock_get.assert_called_once_with("/api/v1/sandboxes", params={})
        mock_rprint.assert_any_call("s1  python  v1.0.0")

    def test_list_default_table_output(self, sandbox_home: Path) -> None:
        sandboxes = [{"id": "s1", "name": "python", "version": "1.0.0", "status": "approved", "owner": "user"}]

        with (
            patch("observal_cli.client.get", return_value=sandboxes) as mock_get,
            patch("observal_cli.config.save_last_results"),
            patch("observal_cli.cmd_sandbox.Table") as mock_table,
            patch("observal_cli.cmd_sandbox.console.print") as mock_print,
        ):
            result = runner.invoke(cli_app, ["sandbox", "list"])

        assert result.exit_code == 0, result.output
        mock_get.assert_called_once_with("/api/v1/sandboxes", params={})
        mock_table.assert_called_once_with(title="Sandboxes (1)", show_lines=False, padding=(0, 1))
        mock_print.assert_called_once()


class TestSandboxShow:
    """Tests for the sandbox show command."""

    def test_show_resolves_alias(self, sandbox_home: Path) -> None:
        sandbox = {
            "id": "s1",
            "name": "python",
            "version": "1.0.0",
            "status": "approved",
            "runtime_type": "docker",
            "image": "python:3.12",
            "owner": "user",
            "description": "A sandbox",
            "created_at": "2026-05-14T00:00:00Z",
        }

        with _patch_resolve_alias() as mock_resolve, patch("observal_cli.client.get", return_value=sandbox) as mock_get:
            result = runner.invoke(cli_app, ["sandbox", "show", "@python"])

        assert result.exit_code == 0, result.output
        assert "python v1.0.0" in result.output
        mock_resolve.assert_called_once_with("@python")
        mock_get.assert_called_once_with("/api/v1/sandboxes/@python")

    def test_show_json_output(self, sandbox_home: Path) -> None:
        sandbox = {"id": "s1", "name": "python"}

        with (
            _patch_resolve_alias() as mock_resolve,
            patch("observal_cli.client.get", return_value=sandbox) as mock_get,
            patch("observal_cli.cmd_sandbox.output_json") as mock_output,
            patch("observal_cli.cmd_sandbox.status_badge") as mock_badge,
            patch("observal_cli.cmd_sandbox.relative_time") as mock_time,
        ):
            result = runner.invoke(cli_app, ["sandbox", "show", "python", "--output", "json"])

        assert result.exit_code == 0, result.output
        mock_resolve.assert_called_once_with("python")
        mock_get.assert_called_once_with("/api/v1/sandboxes/python")
        mock_output.assert_called_once_with(sandbox)
        mock_badge.assert_not_called()
        mock_time.assert_not_called()

    def test_show_accepts_row_number(self, sandbox_home: Path) -> None:
        sandbox = {"id": "s2", "name": "row-sandbox", "version": "2.0.0", "status": "approved"}

        with _patch_resolve_alias() as mock_resolve, patch("observal_cli.client.get", return_value=sandbox) as mock_get:
            result = runner.invoke(cli_app, ["sandbox", "show", "1"])

        assert result.exit_code == 0, result.output
        assert "row-sandbox v2.0.0" in result.output
        mock_resolve.assert_called_once_with("1")
        mock_get.assert_called_once_with("/api/v1/sandboxes/1")

    def test_show_accepts_name(self, sandbox_home: Path) -> None:
        sandbox = {"id": "s3", "name": "python", "version": "3.0.0", "status": "approved"}

        with _patch_resolve_alias() as mock_resolve, patch("observal_cli.client.get", return_value=sandbox) as mock_get:
            result = runner.invoke(cli_app, ["sandbox", "show", "python"])

        assert result.exit_code == 0, result.output
        assert "python v3.0.0" in result.output
        mock_resolve.assert_called_once_with("python")
        mock_get.assert_called_once_with("/api/v1/sandboxes/python")

    def test_show_accepts_uuid(self, sandbox_home: Path) -> None:
        sandbox_id = "abc123-def456"
        sandbox = {"id": sandbox_id, "name": "uuid-sandbox", "version": "1.0.0", "status": "approved"}

        with _patch_resolve_alias() as mock_resolve, patch("observal_cli.client.get", return_value=sandbox) as mock_get:
            result = runner.invoke(cli_app, ["sandbox", "show", sandbox_id])

        assert result.exit_code == 0, result.output
        assert "uuid-sandbox v1.0.0" in result.output
        mock_resolve.assert_called_once_with(sandbox_id)
        mock_get.assert_called_once_with(f"/api/v1/sandboxes/{sandbox_id}")

    def test_show_handles_missing_fields(self, sandbox_home: Path) -> None:
        sandbox = {"id": "s4", "name": "minimal"}

        with (
            patch("observal_cli.config.resolve_alias", side_effect=lambda value: value),
            patch("observal_cli.client.get", return_value=sandbox),
            patch("observal_cli.cmd_sandbox.status_badge", return_value="[green]✓ approved[/green]") as mock_badge,
            patch("observal_cli.cmd_sandbox.relative_time", return_value="--") as mock_time,
        ):
            result = runner.invoke(cli_app, ["sandbox", "show", "minimal"])

        assert result.exit_code == 0, result.output
        assert "minimal" in result.output
        mock_badge.assert_called_once_with("")
        mock_time.assert_called_once_with(None)


class TestSandboxInstall:
    """Tests for the sandbox install command."""

    def test_install_raw_config(self, sandbox_home: Path) -> None:
        config_snippet = {"image": "python:3.12", "resources": {"cpu": 1}}

        with _patch_resolve_alias(), patch("observal_cli.client.post", return_value={"config_snippet": config_snippet}) as mock_post:
            result = runner.invoke(cli_app, ["sandbox", "install", "s1", "--ide", "cursor", "--raw"])

        assert result.exit_code == 0, result.output
        assert '"image": "python:3.12"' in result.output
        mock_post.assert_called_once_with("/api/v1/sandboxes/s1/install", {"ide": "cursor"})

    def test_install_default_pretty_output(self, sandbox_home: Path) -> None:
        config_snippet = {"image": "python:3.12", "resources": {"cpu": 1}}

        with (
            _patch_resolve_alias(),
            patch("observal_cli.client.post", return_value={"config_snippet": config_snippet}) as mock_post,
            patch("observal_cli.cmd_sandbox.console.print_json") as mock_print_json,
        ):
            result = runner.invoke(cli_app, ["sandbox", "install", "s1", "--ide", "cursor"])

        assert result.exit_code == 0, result.output
        assert "Standalone sandbox install is deprecated." in result.output
        assert "Config for cursor:" in result.output
        mock_post.assert_called_once_with("/api/v1/sandboxes/s1/install", {"ide": "cursor"})
        mock_print_json.assert_called_once()

    def test_install_uses_result_when_config_snippet_missing(self, sandbox_home: Path) -> None:
        result_payload = {"image": "python:3.12", "resources": {"cpu": 2}}

        with (
            _patch_resolve_alias(),
            patch("observal_cli.client.post", return_value=result_payload) as mock_post,
            patch("observal_cli.cmd_sandbox.console.print_json") as mock_print_json,
        ):
            result = runner.invoke(cli_app, ["sandbox", "install", "my-sandbox", "--ide", "cursor"])

        assert result.exit_code == 0, result.output
        mock_post.assert_called_once_with("/api/v1/sandboxes/my-sandbox/install", {"ide": "cursor"})
        mock_print_json.assert_called_once()

    def test_install_accepts_alias(self, sandbox_home: Path) -> None:
        config_snippet = {"image": "python:3.12"}

        with (
            patch("observal_cli.config.resolve_alias", return_value="alias-id") as mock_resolve,
            patch("observal_cli.client.post", return_value={"config_snippet": config_snippet}) as mock_post,
            patch("observal_cli.cmd_sandbox.console.print_json"),
        ):
            result = runner.invoke(cli_app, ["sandbox", "install", "@dev", "--ide", "cursor"])

        assert result.exit_code == 0, result.output
        mock_resolve.assert_called_once_with("@dev")
        mock_post.assert_called_once_with("/api/v1/sandboxes/alias-id/install", {"ide": "cursor"})

    def test_install_accepts_row_number(self, sandbox_home: Path) -> None:
        config_snippet = {"image": "python:3.12"}

        with (
            patch("observal_cli.config.resolve_alias", return_value="row-id") as mock_resolve,
            patch("observal_cli.client.post", return_value={"config_snippet": config_snippet}) as mock_post,
            patch("observal_cli.cmd_sandbox.console.print_json"),
        ):
            result = runner.invoke(cli_app, ["sandbox", "install", "1", "--ide", "cursor"])

        assert result.exit_code == 0, result.output
        mock_resolve.assert_called_once_with("1")
        mock_post.assert_called_once_with("/api/v1/sandboxes/row-id/install", {"ide": "cursor"})


class TestSandboxDelete:
    """Tests for the sandbox delete command."""

    def test_delete_with_yes_skips_confirmation(self, sandbox_home: Path) -> None:
        with (
            patch("observal_cli.config.resolve_alias", return_value="sandbox-123") as mock_resolve,
            patch("observal_cli.client.delete") as mock_delete,
            patch("observal_cli.cmd_sandbox.typer.confirm") as mock_confirm,
        ):
            result = runner.invoke(cli_app, ["sandbox", "delete", "sandbox-123", "--yes"])

        assert result.exit_code == 0, result.output
        assert "Deleted sandbox-123" in result.output
        mock_resolve.assert_called_once_with("sandbox-123")
        mock_delete.assert_called_once_with("/api/v1/sandboxes/sandbox-123")
        mock_confirm.assert_not_called()

    def test_delete_prompts_for_confirmation(self, sandbox_home: Path) -> None:
        sandbox = {"id": "sandbox-123", "name": "python-sandbox"}

        with (
            patch("observal_cli.config.resolve_alias", return_value="sandbox-123") as mock_resolve,
            patch("observal_cli.client.get", return_value=sandbox) as mock_get,
            patch("observal_cli.cmd_sandbox.typer.confirm", return_value=True) as mock_confirm,
            patch("observal_cli.client.delete") as mock_delete,
        ):
            result = runner.invoke(cli_app, ["sandbox", "delete", "sandbox-123"])

        assert result.exit_code == 0, result.output
        assert "Deleted sandbox-123" in result.output
        mock_resolve.assert_called_once_with("sandbox-123")
        mock_get.assert_called_once_with("/api/v1/sandboxes/sandbox-123")
        mock_confirm.assert_called_once_with("Delete [bold]python-sandbox[/bold] (sandbox-123)?")
        mock_delete.assert_called_once_with("/api/v1/sandboxes/sandbox-123")

    def test_delete_aborts_when_not_confirmed(self, sandbox_home: Path) -> None:
        sandbox = {"id": "sandbox-123", "name": "python-sandbox"}

        with (
            patch("observal_cli.config.resolve_alias", return_value="sandbox-123"),
            patch("observal_cli.client.get", return_value=sandbox),
            patch("observal_cli.cmd_sandbox.typer.confirm", return_value=False),
            patch("observal_cli.client.delete") as mock_delete,
        ):
            result = runner.invoke(cli_app, ["sandbox", "delete", "sandbox-123"])

        assert result.exit_code == 1, result.output
        mock_delete.assert_not_called()
