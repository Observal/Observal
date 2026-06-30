# SPDX-FileCopyrightText: 2026 Pyasma <pranyasharma55555@gamil.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Tests for the sandbox registry CLI commands."""

from __future__ import annotations

import json
from unittest.mock import mock_open, patch

from typer.testing import CliRunner

from observal_cli.main import app

runner = CliRunner()


def _make_sandbox_payload(*, name: str = "analytics-sandbox") -> dict:
    return {
        "name": name,
        "version": "1.0.0",
        "description": "Sandbox for analytics workloads",
        "owner": "pyasma",
        "runtime_type": "docker",
        "image": "python:3.11-slim",
        "resource_limits": {"cpu": "1", "memory": "1Gi"},
    }


def _make_sandbox_item(
    *,
    sandbox_id: str = "sandbox-123",
    name: str = "analytics",
    version: str = "1.0",
    status: str = "approved",
) -> dict:
    return {
        "id": sandbox_id,
        "name": name,
        "version": version,
        "owner": "pyasma",
        "status": status,
        "runtime_type": "docker",
        "image": "python:3.11",
        "description": "Analytics sandbox",
        "created_at": "2026-01-01T00:00:00Z",
    }


class TestSandboxSubmit:
    """Tests for sandbox submission commands."""

    def test_draft_and_submit_together_exits_with_error(self) -> None:
        result = runner.invoke(app, ["registry", "sandbox", "submit", "--draft", "--submit", "sandbox-123"])

        assert result.exit_code == 1, result.output
        assert "Cannot use --draft and --submit together." in result.output

    def test_submit_existing_draft_posts_to_submit_endpoint(self) -> None:
        with (
            patch("observal_cli.config.resolve_alias", return_value="sandbox-123") as mock_resolve,
            patch("observal_cli.client.post", return_value={"id": "sandbox-123"}) as mock_post,
        ):
            result = runner.invoke(app, ["registry", "sandbox", "submit", "--submit", "my-draft"])

        assert result.exit_code == 0, result.output
        mock_resolve.assert_called_once_with("my-draft")
        mock_post.assert_called_once_with("/api/v1/sandboxes/sandbox-123/submit")
        assert "Draft submitted for review! ID: sandbox-123" in result.output

    def test_submit_from_file_posts_payload_to_submit_endpoint(self) -> None:
        payload = _make_sandbox_payload()

        with (
            patch("builtins.open", mock_open(read_data=json.dumps(payload))) as mock_file,
            patch("observal_cli.client.post", return_value={"id": "sandbox-123"}) as mock_post,
        ):
            result = runner.invoke(app, ["registry", "sandbox", "submit", "--from-file", "sandbox.json"])

        assert result.exit_code == 0, result.output
        mock_file.assert_called_once_with("sandbox.json")
        mock_post.assert_called_once_with("/api/v1/sandboxes/submit", payload)
        assert "Sandbox submitted! ID: sandbox-123" in result.output

    def test_submit_from_file_with_invalid_json_exits_with_error(self) -> None:
        with patch("builtins.open", mock_open(read_data='{"name": "sandbox", invalid}')):
            result = runner.invoke(app, ["registry", "sandbox", "submit", "--from-file", "sandbox.json"])

        assert result.exit_code == 1, result.output
        assert "Invalid JSON in sandbox.json" in result.output

    def test_submit_from_file_missing_file_exits_with_error(self) -> None:
        with patch("builtins.open", side_effect=FileNotFoundError()):
            result = runner.invoke(app, ["registry", "sandbox", "submit", "--from-file", "sandbox.json"])

        assert result.exit_code == 1, result.output
        assert "File not found: sandbox.json" in result.output

    def test_draft_from_file_posts_to_draft_endpoint(self) -> None:
        payload = _make_sandbox_payload(name="draft-sandbox")

        with (
            patch("builtins.open", mock_open(read_data=json.dumps(payload))) as mock_file,
            patch("observal_cli.client.post", return_value={"id": "draft-123"}) as mock_post,
        ):
            result = runner.invoke(app, ["registry", "sandbox", "submit", "--draft", "--from-file", "sandbox.json"])

        assert result.exit_code == 0, result.output
        mock_file.assert_called_once_with("sandbox.json")
        mock_post.assert_called_once_with("/api/v1/sandboxes/draft", payload)
        assert "Draft saved! ID: draft-123" in result.output

    def test_plain_submit_from_file_posts_to_submit_endpoint(self) -> None:
        payload = payload = _make_sandbox_payload(name="submitted-sandbox")

        with (
            patch("builtins.open", mock_open(read_data=json.dumps(payload))) as mock_file,
            patch("observal_cli.client.post", return_value={"id": "submit-456"}) as mock_post,
        ):
            result = runner.invoke(app, ["registry", "sandbox", "submit", "--from-file", "sandbox.json"])

        assert result.exit_code == 0, result.output
        mock_file.assert_called_once_with("sandbox.json")
        mock_post.assert_called_once_with("/api/v1/sandboxes/submit", payload)
        assert "Sandbox submitted! ID: submit-456" in result.output


class TestSandboxList:
    """Tests for sandbox listing commands."""

    def test_empty_list_prints_no_results_message(self) -> None:
        with patch("observal_cli.client.get", return_value=[]) as mock_get:
            result = runner.invoke(app, ["registry", "sandbox", "list"])

        assert result.exit_code == 0, result.output
        mock_get.assert_called_once_with("/api/v1/sandboxes", params={})
        assert "No sandboxes found." in result.output

    def test_filters_are_forwarded_to_the_api(self) -> None:
        mock_data = [_make_sandbox_item()]

        with patch("observal_cli.client.get", return_value=mock_data) as mock_get:
            result = runner.invoke(
                app,
                [
                    "registry",
                    "sandbox",
                    "list",
                    "--runtime",
                    "docker",
                    "--search",
                    "analytics",
                ],
            )

        assert result.exit_code == 0, result.output
        mock_get.assert_called_once_with(
            "/api/v1/sandboxes",
            params={
                "runtime": "docker",
                "search": "analytics",
            },
        )
        assert "analytics" in result.output

    def test_json_output_returns_raw_json_array(self) -> None:
        mock_data = [_make_sandbox_item()]

        with patch("observal_cli.client.get", return_value=mock_data) as mock_get:
            result = runner.invoke(app, ["registry", "sandbox", "list", "--output", "json"])

        assert result.exit_code == 0, result.output
        mock_get.assert_called_once_with("/api/v1/sandboxes", params={})
        assert json.loads(result.output) == mock_data

    def test_plain_output_prints_basic_columns(self) -> None:
        mock_data = [_make_sandbox_item()]

        with patch("observal_cli.client.get", return_value=mock_data) as mock_get:
            result = runner.invoke(app, ["registry", "sandbox", "list", "--output", "plain"])

        assert result.exit_code == 0, result.output
        mock_get.assert_called_once_with("/api/v1/sandboxes", params={})
        assert "sandbox-123" in result.output
        assert "analytics" in result.output
        assert "v1.0" in result.output


class TestSandboxShow:
    """Tests for sandbox detail commands."""

    def test_show_renders_sandbox_details(self) -> None:
        mock_item = _make_sandbox_item()

        with (
            patch("observal_cli.config.resolve_alias", return_value="sandbox-123") as mock_resolve,
            patch("observal_cli.client.get", return_value=mock_item) as mock_get,
        ):
            result = runner.invoke(app, ["registry", "sandbox", "show", "analytics"])

        assert result.exit_code == 0, result.output
        mock_resolve.assert_called_once_with("analytics")
        mock_get.assert_called_once_with("/api/v1/sandboxes/sandbox-123")
        assert "analytics" in result.output
        assert "docker" in result.output
        assert "python:3.11" in result.output
        assert "Analytics sandbox" in result.output

    def test_show_json_output_returns_raw_item(self) -> None:
        mock_item = _make_sandbox_item()

        with (
            patch("observal_cli.config.resolve_alias", return_value="sandbox-123"),
            patch("observal_cli.client.get", return_value=mock_item),
        ):
            result = runner.invoke(app, ["registry", "sandbox", "show", "analytics", "--output", "json"])

        assert result.exit_code == 0, result.output
        assert json.loads(result.output) == mock_item


class TestSandboxEdit:
    """Tests for sandbox edit command behavior."""

    def test_edit_with_all_fields_updates_the_draft(self) -> None:
        mock_result = {
            "name": "new-name",
            "description": "test_description",
            "version": "v1.0.0",
            "runtime_type": "docker",
            "image": "python:3.11",
        }

        with (
            patch("observal_cli.config.resolve_alias", return_value="sandbox-123") as mock_resolve,
            patch("observal_cli.client.post") as mock_post,
            patch("observal_cli.client.put", return_value=mock_result) as mock_put,
        ):
            result = runner.invoke(
                app,
                [
                    "registry",
                    "sandbox",
                    "edit",
                    "analytics",
                    "--name",
                    "new-name",
                    "--description",
                    "test_description",
                    "--version",
                    "v1.0.0",
                    "--runtime-type",
                    "docker",
                    "--image",
                    "python:3.11",
                ],
            )

        assert result.exit_code == 0, result.output
        mock_resolve.assert_called_once_with("analytics")
        mock_post.assert_called_once_with("/api/v1/sandboxes/sandbox-123/start-edit")
        mock_put.assert_called_once_with(
            "/api/v1/sandboxes/sandbox-123/draft",
            {
                "name": "new-name",
                "description": "test_description",
                "version": "v1.0.0",
                "runtime_type": "docker",
                "image": "python:3.11",
            },
        )
        assert "✓ Updated new-name" in result.output

    def test_edit_without_updates_exits_with_error(self) -> None:
        result = runner.invoke(app, ["registry", "sandbox", "edit", "analytics"])

        assert result.exit_code == 1, result.output
        assert "No changes specified" in result.output

    def test_edit_conflict_exits_with_cannot_edit_message(self) -> None:
        with (
            patch("observal_cli.config.resolve_alias", return_value="sandbox-123"),
            patch("observal_cli.client.post", side_effect=Exception("409 currently being edited")),
        ):
            result = runner.invoke(app, ["registry", "sandbox", "edit", "analytics", "--name", "new-name"])

        assert result.exit_code == 1, result.output
        assert "✗ Cannot edit" in result.output

    def test_edit_with_single_field_updates_only_that_field(self) -> None:
        mock_result = {
            "name": "new-name",
            "status": "draft",
        }

        with (
            patch("observal_cli.config.resolve_alias", return_value="sandbox-123") as mock_resolve,
            patch("observal_cli.client.post", return_value={"id": "sandbox-123"}) as mock_post,
            patch("observal_cli.client.put", return_value=mock_result) as mock_put,
        ):
            result = runner.invoke(app, ["registry", "sandbox", "edit", "analytics", "--name", "new-name"])

        assert result.exit_code == 0, result.output
        mock_resolve.assert_called_once_with("analytics")
        mock_post.assert_called_once_with("/api/v1/sandboxes/sandbox-123/start-edit")
        mock_put.assert_called_once_with(
            "/api/v1/sandboxes/sandbox-123/draft",
            {
                "name": "new-name",
            },
        )
        assert "✓ Updated" in result.output

    def test_edit_put_failure_exits_with_error(self) -> None:
        with (
            patch("observal_cli.config.resolve_alias", return_value="sandbox-123") as mock_resolve,
            patch("observal_cli.client.put", side_effect=Exception("Failed to update")),
        ):
            result = runner.invoke(app, ["registry", "sandbox", "edit", "analytics", "--name", "new-name"])

        assert result.exit_code == 1, result.output
        mock_resolve.assert_called_once_with("analytics")
        assert "Failed to update:" in result.output


class TestSandboxDelete:
    """Tests for sandbox deletion behavior."""

    def test_delete_prompts_before_deleting(self) -> None:
        payload = {"name": "demo-sandbox"}

        with (
            patch("observal_cli.config.resolve_alias", return_value="sandbox-123") as mock_resolve,
            patch("observal_cli.client.get", return_value=payload) as mock_get,
            patch("typer.confirm", return_value=True) as mock_confirm,
            patch("observal_cli.client.delete") as mock_delete,
        ):
            result = runner.invoke(app, ["registry", "sandbox", "delete", "analytics"])

        assert result.exit_code == 0, result.output
        mock_resolve.assert_called_once_with("analytics")
        mock_get.assert_called_once_with("/api/v1/sandboxes/sandbox-123")
        mock_confirm.assert_called_once()
        mock_delete.assert_called_once_with("/api/v1/sandboxes/sandbox-123")
        assert "✓ Deleted sandbox-123" in result.output

    def test_delete_aborted_when_user_declines_confirmation(self) -> None:
        payload = {"name": "test-sandbox"}

        with (
            patch("observal_cli.config.resolve_alias", return_value="sandbox-123"),
            patch("observal_cli.client.get", return_value=payload),
            patch("typer.confirm", return_value=False),
            patch("observal_cli.client.delete") as mock_delete,
        ):
            result = runner.invoke(app, ["registry", "sandbox", "delete", "analytics"])

        assert result.exit_code == 1, result.output
        mock_delete.assert_not_called()

    def test_delete_with_yes_skips_confirmation(self) -> None:
        payload = {"name": "test-sandbox"}

        with (
            patch("observal_cli.config.resolve_alias", return_value="sandbox-123") as mock_resolve,
            patch("observal_cli.client.get", return_value=payload) as mock_get,
            patch("typer.confirm") as mock_confirm,
            patch("observal_cli.client.delete") as mock_delete,
        ):
            result = runner.invoke(app, ["registry", "sandbox", "delete", "analytics", "--yes"])

        assert result.exit_code == 0, result.output
        mock_resolve.assert_called_once_with("analytics")
        mock_get.assert_not_called()
        mock_confirm.assert_not_called()
        mock_delete.assert_called_once_with("/api/v1/sandboxes/sandbox-123")
