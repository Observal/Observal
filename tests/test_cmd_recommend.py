# SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""`observal registry recommend`: personal recommendations from the CLI.

The value of this command depends on it never overstating what it knows, so
most of these tests are about the wording of the cold-start cases rather than
the happy path.
"""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from observal_cli.cmd_recommend import recommend_app
from observal_cli.main import app as cli_app

runner = CliRunner()

COMPONENT_ID = "0f2b8a1c-2f4d-4c0e-9f7a-1b2c3d4e5f60"


@pytest.fixture(autouse=True)
def _wide_terminal(monkeypatch):
    """Assert on copy, not on where Rich happens to wrap an 80-column table."""
    from observal_cli import render

    monkeypatch.setenv("COLUMNS", "200")
    monkeypatch.setattr(render.console, "_width", 200)


def _flat(output: str) -> str:
    """Collapse Rich's line wrapping so assertions test copy, not terminal width."""
    return " ".join(output.split())


def _item(**overrides) -> dict:
    item = {
        "type": "mcp",
        "id": COMPONENT_ID,
        "name": "postgres",
        "namespace": "super",
        "slug": "postgres",
        "qualified_name": "super/postgres",
        "description": "Query Postgres from your agent.",
        "category": "databases",
        "latest_version": "2.1.0",
        "download_count": 37,
        "matched_on": ["postgres", "sql"],
        "score": 9.5,
        "reason": "Matches your work on postgres, sql",
    }
    item.update(overrides)
    return item


def _install(monkeypatch, payload: dict):
    captured: dict = {}

    def fake_get(path: str, params: dict | None = None):
        captured["path"] = path
        captured["params"] = params
        return payload

    monkeypatch.setattr("observal_cli.cmd_recommend.client.get", fake_get)
    return captured


class TestListing:
    def test_personalised_result_cites_sessions_and_topics(self, monkeypatch):
        _install(
            monkeypatch,
            {"items": [_item()], "personalized": True, "profile_sessions": 33, "topics": ["databases", "devops"]},
        )

        result = runner.invoke(recommend_app, [])

        assert result.exit_code == 0, result.output
        assert "Recommended for you" in result.output
        assert "Based on 33 sessions" in result.output
        assert "databases, devops" in result.output
        assert "super/postgres" in result.output
        assert "Matches your work on postgres" in _flat(result.output)

    def test_single_session_reads_correctly(self, monkeypatch):
        _install(
            monkeypatch,
            {"items": [_item()], "personalized": True, "profile_sessions": 1, "topics": []},
        )

        result = runner.invoke(recommend_app, [])

        assert "Based on 1 session." in result.output

    def test_cold_start_never_claims_personalisation(self, monkeypatch):
        _install(
            monkeypatch,
            {
                "items": [_item(reason="Popular in your registry")],
                "personalized": False,
                "profile_sessions": 0,
                "topics": [],
            },
        )

        result = runner.invoke(recommend_app, [])

        assert result.exit_code == 0, result.output
        assert "Popular in your registry" in result.output
        assert "Recommended for you" not in result.output
        assert "No session history yet" in result.output

    def test_empty_result_explains_itself(self, monkeypatch):
        _install(monkeypatch, {"items": [], "personalized": True, "profile_sessions": 12, "topics": ["frontend"]})

        result = runner.invoke(recommend_app, [])

        assert result.exit_code == 0, result.output
        assert "Nothing to recommend right now" in result.output
        assert "already installed or dismissed them all" in _flat(result.output)

    def test_json_output_adds_the_standard_list_envelope(self, monkeypatch):
        payload = {"items": [_item()], "personalized": True, "profile_sessions": 4, "topics": ["databases"]}
        _install(monkeypatch, payload)

        result = runner.invoke(recommend_app, ["--output", "json"])

        assert result.exit_code == 0, result.output
        assert json.loads(result.output) == {**payload, "total": 1, "page": 1, "page_size": 1}

    def test_list_subcommand_matches_the_bare_invocation(self, monkeypatch):
        payload = {"items": [_item()], "personalized": True, "profile_sessions": 4, "topics": []}
        _install(monkeypatch, payload)

        bare = runner.invoke(recommend_app, ["--output", "json"])
        explicit = runner.invoke(recommend_app, ["list", "--output", "json"])

        assert json.loads(bare.output) == json.loads(explicit.output)

    def test_filters_are_forwarded_to_the_server(self, monkeypatch):
        captured = _install(monkeypatch, {"items": [], "personalized": False, "profile_sessions": 0, "topics": []})

        result = runner.invoke(recommend_app, ["--limit", "12", "--type", "mcps", "--refresh"])

        assert result.exit_code == 0, result.output
        assert captured["path"] == "/api/v1/recommendations/me"
        # Plural in, singular out: the API only accepts the canonical form.
        assert captured["params"] == {"limit": 12, "type": "mcp", "refresh": True}

    def test_refresh_is_omitted_unless_asked_for(self, monkeypatch):
        captured = _install(monkeypatch, {"items": [], "personalized": False, "profile_sessions": 0, "topics": []})

        runner.invoke(recommend_app, [])

        assert captured["params"] == {"limit": 8}

    def test_limit_bounds_are_enforced_locally(self, monkeypatch):
        _install(monkeypatch, {"items": [], "personalized": False, "profile_sessions": 0, "topics": []})

        assert runner.invoke(recommend_app, ["--limit", "0"]).exit_code != 0
        assert runner.invoke(recommend_app, ["--limit", "99"]).exit_code != 0

    def test_unknown_type_is_rejected_before_any_request(self, monkeypatch):
        def explode(*args, **kwargs):
            raise AssertionError("must not reach the server")

        monkeypatch.setattr("observal_cli.cmd_recommend.client.get", explode)

        result = runner.invoke(recommend_app, ["--type", "../../etc/passwd"])

        assert result.exit_code == 7
        assert "Unknown component type" in result.output


class TestDismiss:
    def test_dismiss_resolves_a_qualified_name_and_posts(self, monkeypatch):
        posted: dict = {}

        monkeypatch.setattr(
            "observal_cli.cmd_recommend.client.resolve_registry_reference",
            lambda item_type, reference: (posted.setdefault("resolve", (item_type, reference)), COMPONENT_ID)[1],
        )

        def fake_post(path: str, body: dict | None = None):
            posted["path"] = path
            posted["body"] = body
            return {}

        monkeypatch.setattr("observal_cli.cmd_recommend.client.post", fake_post)

        result = runner.invoke(recommend_app, ["dismiss", "skill", "super/terraform-plan-review"])

        assert result.exit_code == 0, result.output
        # Resolution needs the plural collection name, the API needs singular.
        assert posted["resolve"] == ("skills", "super/terraform-plan-review")
        assert posted["path"] == "/api/v1/recommendations/feedback"
        assert posted["body"] == {
            "component_type": "skill",
            "component_id": COMPONENT_ID,
            "action": "dismissed",
        }
        assert "no longer be recommended" in result.output

    def test_installed_action_is_reported_differently(self, monkeypatch):
        posted: dict = {}
        monkeypatch.setattr(
            "observal_cli.cmd_recommend.client.resolve_registry_reference",
            lambda item_type, reference: COMPONENT_ID,
        )
        monkeypatch.setattr(
            "observal_cli.cmd_recommend.client.post",
            lambda path, body=None: posted.update(body=body) or {},
        )

        result = runner.invoke(recommend_app, ["dismiss", "mcp", "super/postgres", "--action", "installed"])

        assert result.exit_code == 0, result.output
        assert posted["body"]["action"] == "installed"
        assert "as installed" in result.output

    def test_unknown_action_is_rejected_before_any_request(self, monkeypatch):
        def explode(*args, **kwargs):
            raise AssertionError("must not reach the server")

        monkeypatch.setattr("observal_cli.cmd_recommend.client.resolve_registry_reference", explode)
        monkeypatch.setattr("observal_cli.cmd_recommend.client.post", explode)

        result = runner.invoke(recommend_app, ["dismiss", "skill", "super/x", "--action", "delete-everything"])

        assert result.exit_code == 7
        assert "Unknown recommendation action" in result.output

    def test_unknown_type_is_rejected_before_any_request(self, monkeypatch):
        def explode(*args, **kwargs):
            raise AssertionError("must not reach the server")

        monkeypatch.setattr("observal_cli.cmd_recommend.client.resolve_registry_reference", explode)
        monkeypatch.setattr("observal_cli.cmd_recommend.client.post", explode)

        result = runner.invoke(recommend_app, ["dismiss", "sandbo", "super/x"])

        assert result.exit_code == 7
        assert "Unknown component type" in result.output

    def test_sandbox_survives_type_normalisation(self, monkeypatch):
        # "sandbox".rstrip("s") == "sandbo"; the alias map exists to avoid that.
        posted: dict = {}
        monkeypatch.setattr(
            "observal_cli.cmd_recommend.client.resolve_registry_reference",
            lambda item_type, reference: (posted.setdefault("resolve", item_type), COMPONENT_ID)[1],
        )
        monkeypatch.setattr(
            "observal_cli.cmd_recommend.client.post",
            lambda path, body=None: posted.update(body=body) or {},
        )

        result = runner.invoke(recommend_app, ["dismiss", "sandbox", "super/runner"])

        assert result.exit_code == 0, result.output
        assert posted["resolve"] == "sandboxes"
        assert posted["body"]["component_type"] == "sandbox"


class TestMarkupSafety:
    """Descriptions and reasons are free text, not Rich markup."""

    HOSTILE = "Clean up [/tmp] and index array[0] with [bold] markers"

    def test_bracketed_reason_renders_literally(self, monkeypatch):
        _install(
            monkeypatch,
            {
                "items": [_item(description=self.HOSTILE, reason=self.HOSTILE)],
                "personalized": True,
                "profile_sessions": 3,
                "topics": [],
            },
        )

        result = runner.invoke(recommend_app, [])

        assert result.exit_code == 0, result.output
        assert self.HOSTILE in _flat(result.output)


def test_dismiss_json_returns_stable_feedback(monkeypatch):
    monkeypatch.setattr(
        "observal_cli.cmd_recommend.client.resolve_registry_reference",
        lambda item_type, reference: COMPONENT_ID,
    )
    monkeypatch.setattr("observal_cli.cmd_recommend.client.post", lambda path, body=None: {})

    result = runner.invoke(
        cli_app,
        [
            "registry",
            "recommend",
            "dismiss",
            "mcp",
            "super/postgres",
            "--action",
            "installed",
            "--output",
            "json",
        ],
    )

    assert result.exit_code == 0, result.stderr
    assert json.loads(result.stdout) == {
        "component_type": "mcp",
        "component_id": COMPONENT_ID,
        "action": "installed",
    }


def test_recommend_json_validation_uses_shared_error_boundary(monkeypatch):
    def get(*_args, **_kwargs):
        raise AssertionError("must not request")

    monkeypatch.setattr("observal_cli.cmd_recommend.client.get", get)

    result = runner.invoke(
        cli_app,
        ["registry", "recommend", "list", "--type", "unknown", "--output", "json"],
    )

    assert result.exit_code == 7
    assert result.stdout == ""
    assert json.loads(result.stderr)["error"]["category"] == "validation"
