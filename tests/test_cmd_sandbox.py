# SPDX-FileCopyrightText: 2026 Pyasma <pranyasharma55555@gamil.com>
# SPDX-License-Identifier: AGPL-3.0-only

from __future__ import annotations

import json as _json
from unittest.mock import mock_open, patch

import pytest
from typer.testing import CliRunner

from observal_cli.main import app

runner = CliRunner()


# Shared test data: a minimal sandbox payload used by from-file tests
@pytest.fixture()
def sandbox_payload() -> dict:
    return {
        "name": "analytics-sandbox",
        "version": "1.0.0",
        "description": "Sandbox for analytics workloads",
        "owner": "pyasma",
        "runtime_type": "docker",
        "image": "python:3.11-slim",
        "resource_limits": {"cpu": "1", "memory": "1Gi"},
    }


# ── sandbox submit ──────────────────────────────────────────────────────────


def test_submit_and_draft_together():
    """--draft and --submit are mutually exclusive, should error."""
    result = runner.invoke(app, ["sandbox", "submit", "--draft", "--submit", "sandbox-123"])
    assert result.exit_code == 1
    assert "Cannot use --draft and --submit together." in result.stdout


def test_submit_existing_draft():
    """--submit <id> POSTs to /submit, marks existing draft for review."""
    with patch("observal_cli.config.resolve_alias") as mock_resolve, patch("observal_cli.client.post") as mock_post:
        mock_resolve.return_value = "sandbox-123"
        mock_post.return_value = {"id": "sandbox-123"}

        result = runner.invoke(app, ["sandbox", "submit", "--submit", "my-draft"])

        assert result.exit_code == 0
        mock_resolve.assert_called_once_with("my-draft")
        mock_post.assert_called_once_with("/api/v1/sandboxes/sandbox-123/submit")
        assert "Draft submitted for review! ID: sandbox-123" in result.stdout


def test_load_from_file(sandbox_payload: dict):
    """--from-file reads JSON and POSTs to /submit."""
    with (
        patch("builtins.open", mock_open(read_data=_json.dumps(sandbox_payload))),
        patch("observal_cli.client.post") as mock_post,
    ):
        mock_post.return_value = {"id": "sandbox-123"}
        result = runner.invoke(app, ["sandbox", "submit", "--from-file", "sandbox.json"])

        assert result.exit_code == 0
        mock_post.assert_called_once_with("/api/v1/sandboxes/submit", sandbox_payload)


def test_load_from_file_invalid_json():
    """Malformed JSON in --from-file prints error and exits 1."""
    invalid_json = '{"name": "sandbox", invalid}'

    with patch("builtins.open", mock_open(read_data=invalid_json)):
        result = runner.invoke(app, ["sandbox", "submit", "--from-file", "sandbox.json"])
        assert result.exit_code == 1
        assert "Invalid JSON in sandbox.json" in result.stdout


def test_load_from_file_not_found():
    """Missing --from-file path prints error and exits 1."""
    with patch("builtins.open", side_effect=FileNotFoundError()):
        result = runner.invoke(app, ["sandbox", "submit", "--from-file", "nonexistent.json"])
        assert result.exit_code == 1
        assert "File not found: nonexistent.json" in result.stdout


def test_draft():
    """--draft POSTs to /draft; output says 'Draft saved!'."""
    payload = {"name": "draft-sandbox", "runtime_type": "docker"}

    with (
        patch("builtins.open", mock_open(read_data=_json.dumps(payload))),
        patch("observal_cli.client.post") as mock_post,
    ):
        mock_post.return_value = {"id": "draft-123"}
        result = runner.invoke(app, ["sandbox", "submit", "--draft", "--from-file", "sandbox.json"])

    assert result.exit_code == 0
    mock_post.assert_called_once_with("/api/v1/sandboxes/draft", payload)
    assert "Draft saved! ID: draft-123" in result.stdout


def test_submit():
    """Plain submit (no --draft) POSTs to /submit; output says 'Sandbox submitted!'."""
    payload = {"name": "submitted-sandbox", "runtime_type": "docker"}

    with (
        patch("builtins.open", mock_open(read_data=_json.dumps(payload))),
        patch("observal_cli.client.post") as mock_post,
    ):
        mock_post.return_value = {"id": "submit-456"}
        result = runner.invoke(app, ["sandbox", "submit", "--from-file", "sandbox.json"])

    assert result.exit_code == 0
    mock_post.assert_called_once_with("/api/v1/sandboxes/submit", payload)
    assert "Sandbox submitted! ID: submit-456" in result.stdout


# ── sandbox list ────────────────────────────────────────────────────────────


def test_sandbox_list_no_results():
    """Empty list from API produces 'No sandboxes found.' message."""
    with patch("observal_cli.client.get") as mock_get:
        mock_get.return_value = []
        result = runner.invoke(app, ["sandbox", "list"])
        assert result.exit_code == 0
        assert "No sandboxes found." in result.stdout


def test_sandbox_list_passes_filters():
    """--runtime and --search are forwarded as query params."""
    mock_data = [
        {
            "id": "123",
            "name": "analytics",
            "version": "1.0",
            "owner": "pyasma",
            "status": "approved",
        }
    ]

    with patch("observal_cli.client.get", return_value=mock_data) as mock_get:
        result = runner.invoke(
            app,
            [
                "sandbox",
                "list",
                "--runtime",
                "docker",
                "--search",
                "analytics",
            ],
        )

    assert result.exit_code == 0

    mock_get.assert_called_once_with(
        "/api/v1/sandboxes",
        params={
            "runtime": "docker",
            "search": "analytics",
        },
    )
    assert "analytics" in result.stdout


def test_sandbox_list_output_json():
    """--output json prints raw JSON array."""
    mock_data = [
        {
            "id": "123",
            "name": "analytics",
            "version": "1.0",
            "owner": "pyasma",
            "status": "approved",
        }
    ]

    with patch("observal_cli.client.get", return_value=mock_data) as mock_get:
        result = runner.invoke(app, ["sandbox", "list", "--output", "json"])

    assert result.exit_code == 0
    mock_get.assert_called_once_with("/api/v1/sandboxes", params={})
    assert _json.loads(result.stdout) == mock_data


def test_sandbox_list_output_plain():
    """--output plain prints id, name, version columns."""
    mock_data = [
        {
            "id": "123",
            "name": "analytics",
            "version": "1.0",
            "owner": "pyasma",
            "status": "approved",
        }
    ]

    with patch("observal_cli.client.get", return_value=mock_data) as mock_get:
        result = runner.invoke(app, ["sandbox", "list", "--output", "plain"])
    assert result.exit_code == 0
    mock_get.assert_called_once_with("/api/v1/sandboxes", params={})
    assert "123" in result.output
    assert "analytics" in result.output
    assert "v1.0" in result.output


# ── sandbox show ────────────────────────────────────────────────────────────


def test_sandbox_show():
    """show resolves alias, fetches detail, prints key fields."""
    mock_item = {
        "id": "sandbox-123",
        "name": "analytics",
        "version": "1.0",
        "status": "approved",
        "runtime_type": "docker",
        "image": "python:3.11",
        "owner": "pyasma",
        "description": "Analytics sandbox",
        "created_at": "2026-01-01T00:00:00Z",
    }

    with (
        patch("observal_cli.config.resolve_alias") as mock_resolve,
        patch("observal_cli.client.get") as mock_get,
    ):
        mock_resolve.return_value = "sandbox-123"
        mock_get.return_value = mock_item

        result = runner.invoke(app, ["sandbox", "show", "analytics"])

    assert result.exit_code == 0

    mock_resolve.assert_called_once_with("analytics")

    mock_get.assert_called_once_with("/api/v1/sandboxes/sandbox-123")

    assert "analytics" in result.output
    assert "docker" in result.output
    assert "python:3.11" in result.output
    assert "Analytics sandbox" in result.output


def test_sandbox_show_output_json():
    """--output json returns raw item dict."""
    mock_item = {
        "id": "sandbox-123",
        "name": "analytics",
        "version": "1.0",
        "status": "approved",
        "runtime_type": "docker",
        "image": "python:3.11",
        "owner": "pyasma",
        "description": "Analytics sandbox",
        "created_at": "2026-01-01T00:00:00Z",
    }

    with (
        patch("observal_cli.config.resolve_alias") as mock_resolve,
        patch("observal_cli.client.get") as mock_get,
    ):
        mock_resolve.return_value = "sandbox-123"
        mock_get.return_value = mock_item

        result = runner.invoke(app, ["sandbox", "show", "analytics", "--output", "json"])

    assert result.exit_code == 0
    assert _json.loads(result.output) == mock_item


# ── sandbox install ─────────────────────────────────────────────────────────


def test_sandbox_install():
    """install POSTs to /install endpoint and prints config."""
    mock_result = {
        "config_snippet": {
            "image": "python:3.11",
            "runtime": "docker",
        }
    }

    with (
        patch("observal_cli.config.resolve_alias") as mock_resolve,
        patch("observal_cli.client.post") as mock_post,
    ):
        mock_resolve.return_value = "sandbox-123"
        mock_post.return_value = mock_result

        result = runner.invoke(app, ["sandbox", "install", "analytics", "--ide", "vscode"])

    assert result.exit_code == 0

    mock_resolve.assert_called_once_with("analytics")

    mock_post.assert_called_once_with(
        "/api/v1/sandboxes/sandbox-123/install",
        {"ide": "vscode"},
    )

    assert "Config for vscode" in result.output
    assert "python:3.11" in result.output


def test_sandbox_install_raw_json():
    """--raw prints only the config_snippet JSON, no extra formatting."""
    mock_result = {
        "config_snippet": {
            "image": "python:3.11",
            "runtime": "docker",
        }
    }

    with (
        patch("observal_cli.config.resolve_alias") as mock_resolve,
        patch("observal_cli.client.post") as mock_post,
    ):
        mock_resolve.return_value = "sandbox-123"
        mock_post.return_value = mock_result

        result = runner.invoke(app, ["sandbox", "install", "analytics", "--raw", "--ide", "vscode"])

    assert result.exit_code == 0

    mock_resolve.assert_called_once_with("analytics")

    mock_post.assert_called_once_with(
        "/api/v1/sandboxes/sandbox-123/install",
        {"ide": "vscode"},
    )
    parsed = _json.loads(result.output)
    assert parsed == {"image": "python:3.11", "runtime": "docker"}


# ── sandbox edit ────────────────────────────────────────────────────────────


def test_sandbox_edit():
    """edit acquires edit lock then PUTs updated fields to /draft."""
    mock_result = {
        "name": "new-name",
        "description": "test_description",
        "version": "v1.0.0",
        "runtime_type": "docker",
        "image": "python:3.11",
    }

    with (
        patch("observal_cli.config.resolve_alias") as mock_resolve,
        patch("observal_cli.client.post") as mock_post,
        patch("observal_cli.client.put") as mock_put,
    ):
        mock_resolve.return_value = "sandbox-123"
        mock_put.return_value = mock_result

        result = runner.invoke(
            app,
            [
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

    assert result.exit_code == 0
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


def test_sandbox_no_updates():
    """edit with no field flags prints error and exits 1."""
    result = runner.invoke(app, ["sandbox", "edit", "analytics"])

    assert result.exit_code == 1

    assert "No changes specified" in result.output


def test_sandbox_edit_conflict():
    """start-edit 409 prints 'Cannot edit' and exits 1."""
    with (
        patch("observal_cli.config.resolve_alias") as mock_resolve,
        patch("observal_cli.client.post") as mock_post,
    ):
        mock_resolve.return_value = "sandbox-123"

        mock_post.side_effect = Exception("409 currently being edited")

        result = runner.invoke(app, ["sandbox", "edit", "analytics", "--name", "new-name"])

    assert result.exit_code == 1

    assert "✗ Cannot edit" in result.output


def test_sandbox_saving_changes():
    """edit with one flag acquires lock and PUTs just that field."""
    mock_result = {
        "name": "new-name",
        "status": "draft",
    }
    with (
        patch("observal_cli.config.resolve_alias") as mock_resolve,
        patch("observal_cli.client.post") as mock_post,
        patch("observal_cli.client.put") as mock_put,
    ):
        mock_resolve.return_value = "sandbox-123"
        mock_post.return_value = {
            "id": "sandbox-123",
        }
        mock_put.return_value = mock_result

        result = runner.invoke(app, ["sandbox", "edit", "analytics", "--name", "new-name"])

    assert result.exit_code == 0

    mock_put.assert_called_once_with(
        "/api/v1/sandboxes/sandbox-123/draft",
        {
            "name": "new-name",
        },
    )
    mock_post.assert_called_once_with("/api/v1/sandboxes/sandbox-123/start-edit")

    assert "✓ Updated" in result.output


def test_sandbox_failed_update():
    """PUT failure prints error and exits 1 (lock is released server-side)."""
    with (
        patch("observal_cli.config.resolve_alias") as mock_resolve,
        patch("observal_cli.client.put") as mock_put,
    ):
        mock_resolve.return_value = "sandbox-123"
        mock_put.side_effect = Exception("Failed to update")

        result = runner.invoke(
            app,
            [
                "sandbox",
                "edit",
                "analytics",
                "--name",
                "new-name",
            ],
        )
    assert result.exit_code == 1

    assert "Failed to update:" in result.output


# ── sandbox delete ──────────────────────────────────────────────────────────


def test_sandbox_delete():
    """delete fetches item, prompts confirm, then DELETEs on yes."""
    payload = {
        "name": "demo-sandbox",
    }
    with (
        patch("observal_cli.config.resolve_alias") as mock_resolve,
        patch("observal_cli.client.get") as mock_get,
        patch("typer.confirm") as mock_confirm,
        patch("observal_cli.client.delete") as mock_delete,
    ):
        mock_resolve.return_value = "sandbox-123"
        mock_get.return_value = payload
        mock_confirm.return_value = True

        result = runner.invoke(
            app,
            [
                "sandbox",
                "delete",
                "analytics",
            ],
        )
    assert result.exit_code == 0

    mock_get.assert_called_once_with("/api/v1/sandboxes/sandbox-123")
    mock_delete.assert_called_once_with("/api/v1/sandboxes/sandbox-123")

    assert "✓ Deleted" in result.output


def test_sandbox_delete_aborted():
    """delete exits 1 without calling DELETE when user says no."""
    payload = {
        "name": "test-sandbox",
    }
    with (
        patch("observal_cli.config.resolve_alias") as mock_resolve,
        patch("observal_cli.client.get") as mock_get,
        patch("typer.confirm") as mock_confirm,
        patch("observal_cli.client.delete") as mock_delete,
    ):
        mock_resolve.return_value = "sandbox-123"
        mock_get.return_value = payload

        mock_confirm.return_value = False

        result = runner.invoke(app, ["sandbox", "delete", "analytics"])

    assert result.exit_code == 1
    mock_delete.assert_not_called()


def test_sandbox_delete_skip_confirmation():
    """--yes skips confirmation prompt and deletes directly."""
    payload = {
        "name": "test-sandbox",
    }
    with (
        patch("observal_cli.config.resolve_alias") as mock_resolve,
        patch("observal_cli.client.get") as mock_get,
        patch("typer.confirm") as mock_confirm,
        patch("observal_cli.client.delete") as mock_delete,
    ):
        mock_resolve.return_value = "sandbox-123"
        mock_get.return_value = payload

        result = runner.invoke(app, ["sandbox", "delete", "analytics", "--yes"])

    assert result.exit_code == 0
    mock_confirm.assert_not_called()
    mock_delete.assert_called_once_with("/api/v1/sandboxes/sandbox-123")
