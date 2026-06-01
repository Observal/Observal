# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Tests for component version publish and list commands."""

from __future__ import annotations

import json
from unittest.mock import patch

from typer.testing import CliRunner

from observal_cli.main import app

runner = CliRunner()

# ── component version publish ──────────────────────────────────


def test_version_publish_posts_to_api() -> None:
    """publish sends the correct payload to the versions endpoint."""
    listing_id = "hook-uuid-1234"
    version_result = {"version": "1.1.0", "status": "pending"}

    with (
        patch("observal_cli.config.resolve_alias", return_value=listing_id),
        patch("observal_cli.client.post", return_value=version_result) as mock_post,
    ):
        result = runner.invoke(
            app,
            [
                "registry",
                "version",
                "publish",
                "hook",
                listing_id,
                "--version",
                "1.1.0",
                "--description",
                "Fixed timeout handling",
            ],
        )

    assert result.exit_code == 0, result.output
    assert "1.1.0" in result.output

    post_call = mock_post.call_args
    assert "/api/v1/hooks/" in post_call[0][0]
    assert "/versions" in post_call[0][0]
    payload = post_call[0][1]
    assert payload["version"] == "1.1.0"
    assert payload["description"] == "Fixed timeout handling"


def test_version_publish_with_all_flags() -> None:
    """publish passes changelog, supported_ides, and extra when provided."""
    listing_id = "skill-uuid-5678"
    version_result = {"version": "2.0.0", "status": "pending"}

    with (
        patch("observal_cli.config.resolve_alias", return_value=listing_id),
        patch("observal_cli.client.post", return_value=version_result) as mock_post,
    ):
        result = runner.invoke(
            app,
            [
                "registry",
                "version",
                "publish",
                "skill",
                listing_id,
                "--version",
                "2.0.0",
                "--description",
                "Major update",
                "--changelog",
                "Breaking change",
                "--extra",
                '{"event": "PostToolUse"}',
            ],
        )

    assert result.exit_code == 0, result.output
    payload = mock_post.call_args[0][1]
    assert payload["changelog"] == "Breaking change"
    assert payload["extra"] == {"event": "PostToolUse"}


def test_version_publish_pluralizes_type_correctly() -> None:
    """publish uses the correct plural path for each component type."""
    cases = [
        ("mcp", "mcps"),
        ("skill", "skills"),
        ("hook", "hooks"),
        ("prompt", "prompts"),
        ("sandbox", "sandboxes"),
    ]
    for ctype, plural in cases:
        listing_id = f"{ctype}-uuid"
        with (
            patch("observal_cli.config.resolve_alias", return_value=listing_id),
            patch("observal_cli.client.post", return_value={"version": "1.0.0", "status": "pending"}) as mock_post,
        ):
            result = runner.invoke(
                app,
                [
                    "registry",
                    "version",
                    "publish",
                    ctype,
                    listing_id,
                    "--version",
                    "1.0.0",
                    "--description",
                    "test",
                ],
            )
        assert result.exit_code == 0, f"Failed for {ctype}: {result.output}"
        path = mock_post.call_args[0][0]
        assert f"/api/v1/{plural}/{listing_id}/versions" == path, f"Wrong path for {ctype}: {path}"


def test_version_publish_invalid_type_exits() -> None:
    """publish exits with error for an unknown component type."""
    result = runner.invoke(
        app,
        [
            "registry",
            "version",
            "publish",
            "unknown-type",
            "some-id",
            "--version",
            "1.0.0",
            "--description",
            "test",
        ],
    )
    assert result.exit_code != 0


def test_version_publish_invalid_extra_json_exits() -> None:
    """publish exits with error when --extra is not valid JSON."""
    with (
        patch("observal_cli.config.resolve_alias", return_value="hook-id"),
    ):
        result = runner.invoke(
            app,
            [
                "registry",
                "version",
                "publish",
                "hook",
                "hook-id",
                "--version",
                "1.0.0",
                "--description",
                "test",
                "--extra",
                "not-valid-json",
            ],
        )
    assert result.exit_code != 0


def test_version_publish_prompts_for_version_when_omitted() -> None:
    """publish fetches suggestions and prompts when --version is omitted."""
    listing_id = "hook-uuid-999"
    suggestions = {
        "current": "1.0.0",
        "suggestions": {"patch": "1.0.1", "minor": "1.1.0", "major": "2.0.0"},
    }
    version_result = {"version": "1.0.1", "status": "pending"}

    with (
        patch("observal_cli.config.resolve_alias", return_value=listing_id),
        patch("observal_cli.client.get", return_value=suggestions),
        patch("observal_cli.client.post", return_value=version_result),
    ):
        # Provide "1.0.1" as user input when prompted
        result = runner.invoke(
            app,
            [
                "registry",
                "version",
                "publish",
                "hook",
                listing_id,
                "--description",
                "patch fix",
            ],
            input="1.0.1\n",
        )

    assert result.exit_code == 0, result.output
    assert "1.0.1" in result.output


# ── component version list ─────────────────────────────────────


def test_version_list_renders_table() -> None:
    """list renders a table with version, status, date, and created-by."""
    listing_id = "mcp-uuid-abc"
    versions_response = {
        "items": [
            {
                "version": "1.2.0",
                "status": "approved",
                "created_at": "2026-04-28T10:00:00Z",
                "created_by_email": "alice@example.com",
            },
            {
                "version": "1.1.0",
                "status": "pending",
                "created_at": "2026-04-20T10:00:00Z",
                "created_by_email": "bob@example.com",
            },
        ],
        "total": 2,
        "page": 1,
        "page_size": 50,
    }

    with (
        patch("observal_cli.config.resolve_alias", return_value=listing_id),
        patch("observal_cli.client.get", return_value=versions_response) as mock_get,
    ):
        result = runner.invoke(app, ["registry", "version", "list", "mcp", listing_id])

    assert result.exit_code == 0, result.output
    assert "1.2.0" in result.output
    assert "1.1.0" in result.output
    assert "approved" in result.output.lower()
    assert "pending" in result.output.lower()

    mock_get.assert_called_once_with(
        f"/api/v1/mcps/{listing_id}/versions",
        params={"page": 1, "page_size": 50},
    )


def test_version_list_empty_shows_message() -> None:
    """list shows 'No versions found' when the response is empty."""
    listing_id = "prompt-uuid-empty"
    with (
        patch("observal_cli.config.resolve_alias", return_value=listing_id),
        patch("observal_cli.client.get", return_value={"items": [], "total": 0}),
    ):
        result = runner.invoke(app, ["registry", "version", "list", "prompt", listing_id])

    assert result.exit_code == 0, result.output
    assert "no versions" in result.output.lower()


def test_version_list_json_output() -> None:
    """list --output json dumps raw JSON."""
    listing_id = "sandbox-uuid-json"
    versions_response = {
        "items": [{"version": "1.0.0", "status": "approved", "created_at": None}],
        "total": 1,
        "page": 1,
        "page_size": 50,
    }

    with (
        patch("observal_cli.config.resolve_alias", return_value=listing_id),
        patch("observal_cli.client.get", return_value=versions_response),
    ):
        result = runner.invoke(app, ["registry", "version", "list", "sandbox", listing_id, "--output", "json"])

    assert result.exit_code == 0, result.output
    parsed = json.loads(result.output)
    assert isinstance(parsed, (dict, list))
