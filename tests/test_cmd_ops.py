# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Behavioral tests for the operations, admin, trace, and self CLI commands."""

from __future__ import annotations

from contextlib import nullcontext
from io import StringIO
from pathlib import Path
from types import SimpleNamespace

import pytest
import typer
from rich.console import Console

from observal_cli import cmd_ops as ops
from observal_cli.install_detector import InstallInfo, InstallMethod
from observal_cli.upgrade_lock import UpgradeLockError


class FakeConsole:
    def __init__(self) -> None:
        self.renderables: list[object] = []
        self.clear_count = 0

    def print(self, renderable: object) -> None:
        self.renderables.append(renderable)

    def clear(self) -> None:
        self.clear_count += 1


@pytest.fixture
def cli(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Isolate command rendering and every external client boundary."""
    lines: list[str] = []
    json_values: list[object] = []
    saved_results: list[object] = []
    fake_console = FakeConsole()

    def blocked(name: str):
        def fail(*args, **kwargs):
            raise AssertionError(f"unmocked boundary: {name}, args={args}, kwargs={kwargs}")

        return fail

    monkeypatch.setattr(ops, "rprint", lambda *values, **kwargs: lines.append(" ".join(map(str, values))))
    monkeypatch.setattr(ops, "output_json", json_values.append)
    monkeypatch.setattr(ops, "console", fake_console)
    monkeypatch.setattr(ops, "spinner", lambda *args, **kwargs: nullcontext())
    monkeypatch.setattr(ops, "relative_time", lambda value: f"relative:{value}")
    monkeypatch.setattr(ops.config, "resolve_alias", lambda value: value)
    monkeypatch.setattr(ops.config, "save_last_results", saved_results.append)
    monkeypatch.setattr(ops, "password_input", blocked("password_input"))
    monkeypatch.setattr(ops.typer, "confirm", blocked("confirm"))
    monkeypatch.setattr(ops.time, "sleep", blocked("sleep"))
    for method in ("get", "post", "put", "delete"):
        monkeypatch.setattr(ops.client, method, blocked(f"client.{method}"))

    return SimpleNamespace(
        lines=lines,
        json=json_values,
        saved=saved_results,
        console=fake_console,
        text=lambda: "\n".join(lines),
    )


def render(renderable: object) -> str:
    stream = StringIO()
    Console(file=stream, color_system=None, width=180).print(renderable)
    return stream.getvalue()


def test_review_list_filters_caches_and_renders_rows(cli, monkeypatch):
    calls = []
    reviews = [
        {
            "id": "component-123456789",
            "type": "mcp",
            "name": "search",
            "version": "1.2.3",
            "submitted_by": "alice",
            "created_at": "created",
        },
        {
            "id": "agent-987654321",
            "listing_type": "agent",
            "name": "builder",
            "submitted_at": "submitted",
        },
    ]

    def fake_get(path, params=None):
        calls.append((path, params))
        return reviews

    monkeypatch.setattr(ops.client, "get", fake_get)

    ops.review_list("mcp", "components", "table")

    assert calls == [("/api/v1/review", {"type": "mcp", "tab": "components"})]
    assert cli.saved == [reviews]
    table = cli.console.renderables[0]
    assert table.title == "Pending Reviews (2)"
    assert table.columns[1]._cells == ["mcp", "agent"]
    assert table.columns[2]._cells == ["search", "builder"]
    assert table.columns[5]._cells == ["relative:created", "relative:submitted"]
    assert table.columns[6]._cells == ["component-12", "agent-987654"]


def test_review_list_supports_json_and_empty_results(cli, monkeypatch):
    responses = iter([[{"id": "one"}], []])
    calls = []

    def fake_get(path, params=None):
        calls.append((path, params))
        return next(responses)

    monkeypatch.setattr(ops.client, "get", fake_get)

    ops.review_list(None, None, "json")
    ops.review_list(None, None, "table")

    assert calls == [("/api/v1/review", None), ("/api/v1/review", None)]
    assert cli.json == [[{"id": "one"}]]
    assert "No pending reviews" in cli.text()


def test_review_show_resolves_and_renders_validation_details(cli, monkeypatch):
    item = {
        "id": "review-id",
        "name": "filesystem",
        "type": "mcp",
        "status": "rejected",
        "version": "2.0",
        "owner": "team",
        "submitted_by": "alice",
        "created_at": "created",
        "git_url": "https://example.test/repo",
        "description": "",
        "rejection_reason": "unsafe",
        "mcp_validated": False,
        "validation_results": [
            {"stage": "clone", "passed": True},
            {"stage": "scan", "passed": False},
        ],
    }
    calls = []
    monkeypatch.setattr(ops.config, "resolve_alias", lambda value: f"resolved-{value}")
    monkeypatch.setattr(ops.client, "get", lambda path: calls.append(path) or item)

    ops.review_show("1", "table")

    assert calls == ["/api/v1/review/resolved-1"]
    output = render(cli.console.renderables[0])
    assert "filesystem" in output
    assert "Rejection Reason" in output
    assert "Not validated" in output
    assert "clone" in output and "pass" in output
    assert "scan" in output and "fail" in output


def test_review_show_supports_json(cli, monkeypatch):
    item = {"id": "review-id"}
    monkeypatch.setattr(ops.client, "get", lambda path: item)

    ops.review_show("review-id", "json")

    assert cli.json == [item]
    assert cli.console.renderables == []


@pytest.mark.parametrize(
    ("agent", "bundle", "path", "result", "message"),
    [
        (False, False, "/api/v1/review/item/approve", {"name": "component"}, "Approved: component"),
        (True, False, "/api/v1/review/agents/item/approve", {}, "Approved: item"),
        (
            False,
            True,
            "/api/v1/review/bundles/item/approve",
            {"name": "bundle", "approved_count": 3},
            "Bundle approved: bundle (3 components)",
        ),
    ],
)
def test_review_approve_selects_the_expected_endpoint(cli, monkeypatch, agent, bundle, path, result, message):
    calls = []
    monkeypatch.setattr(ops.client, "post", lambda actual: calls.append(actual) or result)

    ops.review_approve("item", agent, bundle)

    assert calls == [path]
    assert message in cli.text()


def test_review_reject_rejects_blank_reasons(cli):
    with pytest.raises(typer.Exit) as exc_info:
        ops.review_reject("item", "   ", False, False)

    assert exc_info.value.exit_code == 1
    assert "cannot be empty" in cli.text()


@pytest.mark.parametrize(
    ("agent", "bundle", "path", "result", "message"),
    [
        (False, False, "/api/v1/review/item/reject", {"name": "component"}, "Rejected: component"),
        (True, False, "/api/v1/review/agents/item/reject", {}, "Rejected: item"),
        (
            False,
            True,
            "/api/v1/review/bundles/item/reject",
            {"name": "bundle", "rejected_count": 2},
            "Bundle rejected: bundle (2 components)",
        ),
    ],
)
def test_review_reject_posts_the_reason(cli, monkeypatch, agent, bundle, path, result, message):
    calls = []
    monkeypatch.setattr(ops.client, "post", lambda actual, body: calls.append((actual, body)) or result)

    ops.review_reject("item", "policy violation", agent, bundle)

    assert calls == [(path, {"reason": "policy violation"})]
    assert message in cli.text()


def test_telemetry_status_reports_server_and_outbox_state(cli, monkeypatch):
    from observal_cli import telemetry_buffer

    monkeypatch.setattr(
        ops.client,
        "get",
        lambda path: {"status": "ok", "tool_call_events": 8, "agent_interaction_events": 5},
    )
    monkeypatch.setattr(
        telemetry_buffer,
        "stats",
        lambda: {
            "pending": 2,
            "bytes": 1536,
            "oldest_pending": "2026-01-01",
            "last_sync": "2026-01-02",
            "total": 0,
        },
    )

    ops.telemetry_status()

    output = cli.text()
    assert "Status:       [green]ok" in output
    assert "Tool calls:   8" in output
    assert "Pending:      2 batches" in output
    assert "Disk:         1.5 KiB" in output
    assert "Oldest:       2026-01-01 UTC" in output
    assert "Last sync:    2026-01-02 UTC" in output
    assert "Outbox is empty" in output


def test_telemetry_status_tolerates_unavailable_local_stats(cli, monkeypatch):
    from observal_cli import telemetry_buffer

    monkeypatch.setattr(ops.client, "get", lambda path: {})
    monkeypatch.setattr(telemetry_buffer, "stats", lambda: (_ for _ in ()).throw(OSError("unavailable")))

    ops.telemetry_status()

    assert "unknown" in cli.text()
    assert "Durable Session Outbox" not in cli.text()


def test_telemetry_test_posts_a_synthetic_tool_call(cli, monkeypatch):
    calls = []
    monkeypatch.setattr(ops.client, "post", lambda path, body: calls.append((path, body)) or {"ingested": 1})

    ops.telemetry_test()

    assert calls[0][0] == "/api/v1/telemetry/events"
    assert calls[0][1]["tool_calls"] == [
        {
            "mcp_server_id": "test-mcp",
            "tool_name": "test_tool",
            "status": "success",
            "latency_ms": 42,
            "harness": "test",
        }
    ]
    assert "Ingested: 1" in cli.text()


def test_metrics_renders_agent_metrics_and_resolves_alias(cli, monkeypatch):
    calls = []
    monkeypatch.setattr(ops.config, "resolve_alias", lambda value: "agent-id")
    monkeypatch.setattr(
        ops.client,
        "get",
        lambda path: (
            calls.append(path)
            or {
                "total_interactions": 12,
                "total_downloads": 9,
                "acceptance_rate": 0.8,
                "avg_tool_calls": 2.5,
                "avg_latency_ms": 19.6,
            }
        ),
    )

    ops._metrics("alias", "agent", "table", False)
    ops._metrics_impl("alias", "agent", "json", False)

    assert calls == ["/api/v1/agents/agent-id/metrics", "/api/v1/agents/agent-id/metrics"]
    assert cli.json == [
        {
            "total_interactions": 12,
            "total_downloads": 9,
            "acceptance_rate": 0.8,
            "avg_tool_calls": 2.5,
            "avg_latency_ms": 19.6,
        }
    ]
    output = cli.text()
    assert "Interactions:   12" in output
    assert "Downloads:      9" in output
    assert "Acceptance:     [green]80.0%" in output
    assert "Avg latency:    20ms" in output


def test_metrics_renders_mcp_metrics_and_supports_json(cli, monkeypatch):
    responses = [
        {
            "total_downloads": 4,
            "total_calls": 10,
            "error_rate": 0.02,
            "avg_latency_ms": 7.8,
            "p50_latency_ms": 3,
            "p90_latency_ms": 8,
            "p99_latency_ms": 20,
        },
        {"total_calls": 11},
    ]
    calls = []
    monkeypatch.setattr(ops.client, "get", lambda path: calls.append(path) or responses.pop(0))

    ops._metrics_impl("mcp-id", "mcp", "table", False)
    ops._metrics_impl("mcp-id", "mcp", "json", False)

    assert calls == ["/api/v1/mcps/mcp-id/metrics", "/api/v1/mcps/mcp-id/metrics"]
    assert "Total calls: 10" in cli.text()
    assert "Error rate:  [yellow]2.00%" in cli.text()
    assert "Latency p50/p90/p99: 3/8/20ms" in cli.text()
    assert cli.json == [{"total_calls": 11}]


def test_metrics_watch_refreshes_until_interrupted(cli, monkeypatch):
    monkeypatch.setattr(ops.client, "get", lambda path: {"total_calls": 1})
    monkeypatch.setattr(ops.time, "sleep", lambda seconds: (_ for _ in ()).throw(KeyboardInterrupt()))

    ops._metrics_impl("mcp-id", "mcp", "table", True)

    assert cli.console.clear_count == 1
    assert "Watching metrics for mcp-id" in cli.text()
    assert "Stopped" in cli.text()


def test_top_renders_tables_json_and_empty_states(cli, monkeypatch):
    responses = {
        "/api/v1/overview/top-mcps": [{"id": "abcdefghijk", "name": "search", "value": 4.9}],
        "/api/v1/overview/top-agents": [{"id": "agent", "name": "builder", "value": 3}],
    }
    monkeypatch.setattr(ops.client, "get", lambda path: responses[path])

    ops._top("mcp", "table")
    ops._top_impl("agent", "json")
    responses["/api/v1/overview/top-agents"] = []
    ops._top_impl("agent", "table")

    table = cli.console.renderables[0]
    assert table.title == "Top MCP Servers"
    assert table.columns[1]._cells == ["search"]
    assert table.columns[2]._cells == ["4"]
    assert cli.json == [[{"id": "agent", "name": "builder", "value": 3}]]
    assert "No agent data yet" in cli.text()


def test_rate_accepts_uuid_without_lookup(cli, monkeypatch):
    listing_id = "11111111-1111-1111-1111-111111111111"
    calls = []
    monkeypatch.setattr(ops.client, "post", lambda path, body: calls.append((path, body)) or {})

    ops._rate(listing_id, 5, "mcp", "excellent", True)

    assert calls == [
        (
            "/api/v1/feedback",
            {
                "listing_id": listing_id,
                "listing_type": "mcp",
                "rating": 5,
                "comment": "excellent",
                "anonymous": True,
            },
        )
    ]
    assert "Rated" in cli.text()


@pytest.mark.parametrize(
    ("listing_type", "endpoint"),
    [("agent", "/api/v1/agents/builder"), ("skill", "/api/v1/skills/builder")],
)
def test_resolve_listing_id_looks_up_non_uuid_names(cli, monkeypatch, listing_type, endpoint):
    calls = []
    monkeypatch.setattr(ops.client, "get", lambda path: calls.append(path) or {"id": "resolved-id"})

    assert ops._resolve_listing_id("builder", listing_type) == "resolved-id"
    assert calls == [endpoint]


def test_resolve_listing_id_reports_lookup_failures(cli, monkeypatch):
    monkeypatch.setattr(ops.client, "get", lambda path: (_ for _ in ()).throw(RuntimeError("missing")))

    with pytest.raises(typer.Exit) as exc_info:
        ops._resolve_listing_id("missing", "prompt")

    assert exc_info.value.exit_code == 1
    assert "Could not find prompt named 'missing'" in cli.text()


def test_rate_update_fetches_the_review_and_only_sends_supplied_fields(cli, monkeypatch):
    listing_id = "11111111-1111-1111-1111-111111111111"
    calls = []
    monkeypatch.setattr(ops.client, "get", lambda path: calls.append(("get", path)) or {"id": "review-id"})
    monkeypatch.setattr(ops.client, "put", lambda path, body: calls.append(("put", path, body)) or {})

    ops._rate_update(listing_id, "mcp", 4, "revised", False)

    assert calls == [
        ("get", f"/api/v1/feedback/mine/mcp/{listing_id}"),
        ("put", "/api/v1/feedback/review-id", {"rating": 4, "comment": "revised", "anonymous": False}),
    ]
    assert "Review updated" in cli.text()


def test_rate_update_requires_at_least_one_change(cli, monkeypatch):
    listing_id = "11111111-1111-1111-1111-111111111111"
    monkeypatch.setattr(ops.client, "get", lambda path: {"id": "review-id"})

    with pytest.raises(typer.Exit) as exc_info:
        ops._rate_update(listing_id, "mcp", None, None, None)

    assert exc_info.value.exit_code == 1
    assert "Nothing to update" in cli.text()


def test_rate_delete_fetches_then_deletes_the_review(cli, monkeypatch):
    listing_id = "11111111-1111-1111-1111-111111111111"
    calls = []
    monkeypatch.setattr(ops.client, "get", lambda path: calls.append(("get", path)) or {"id": "review-id"})
    monkeypatch.setattr(ops.client, "delete", lambda path: calls.append(("delete", path)))

    ops._rate_delete(listing_id, "mcp")

    assert calls == [
        ("get", f"/api/v1/feedback/mine/mcp/{listing_id}"),
        ("delete", "/api/v1/feedback/review-id"),
    ]
    assert "Review deleted" in cli.text()


def test_feedback_renders_summary_and_review_comments(cli, monkeypatch):
    calls = []

    def fake_get(path):
        calls.append(path)
        if path.startswith("/api/v1/feedback/summary"):
            return {"average_rating": 4.4, "total_reviews": 2}
        return [{"rating": 5, "comment": "great"}, {"rating": 3, "comment": None}]

    monkeypatch.setattr(ops.client, "get", fake_get)

    ops._feedback("item", "mcp", "table")

    assert calls == ["/api/v1/feedback/mcp/item", "/api/v1/feedback/summary/item"]
    assert "[bold]4.4[/bold]/5 (2 reviews)" in cli.text()
    assert "great" in cli.text()


def test_feedback_supports_json_and_empty_results(cli, monkeypatch):
    responses = iter(
        [
            [{"rating": 4}],
            {"average_rating": 4, "total_reviews": 1},
            [],
            {"average_rating": 0, "total_reviews": 0},
        ]
    )
    monkeypatch.setattr(ops.client, "get", lambda path: next(responses))

    ops._feedback_impl("item", "agent", "json")
    ops._feedback_impl("item", "agent", "table")

    assert cli.json == [{"summary": {"average_rating": 4, "total_reviews": 1}, "reviews": [{"rating": 4}]}]
    assert "No feedback yet" in cli.text()


def test_admin_settings_handles_table_json_and_empty_states(cli, monkeypatch):
    responses = iter(
        [
            [{"key": "retention", "value": "30"}],
            [{"key": "mode", "value": "strict"}],
            [],
        ]
    )
    monkeypatch.setattr(ops.client, "get", lambda path: next(responses))

    ops.admin_settings("table")
    ops.admin_settings("json")
    ops.admin_settings("table")

    table = cli.console.renderables[0]
    assert table.title == "Admin Settings"
    assert table.columns[0]._cells == ["retention"]
    assert cli.json == [[{"key": "mode", "value": "strict"}]]
    assert "No settings configured" in cli.text()


def test_admin_set_updates_the_named_setting(cli, monkeypatch):
    calls = []
    monkeypatch.setattr(ops.client, "put", lambda path, body: calls.append((path, body)))

    ops.admin_set("retention", "90")

    assert calls == [("/api/v1/admin/settings/retention", {"value": "90"})]
    assert "retention = 90" in cli.text()


def test_admin_users_renders_all_roles_and_supports_json(cli, monkeypatch):
    users = [
        {"id": "admin-id", "email": "a@example.test", "name": "A", "role": "admin"},
        {"id": "developer-id", "email": "d@example.test", "name": "D", "role": "developer"},
        {"id": "user-id", "email": "u@example.test", "name": "U", "role": "user"},
    ]
    monkeypatch.setattr(ops.client, "get", lambda path: users)

    ops.admin_users("table")
    ops.admin_users("json")

    table = cli.console.renderables[0]
    assert table.title == "Users (3)"
    assert table.columns[1]._cells == ["a@example.test", "d@example.test", "u@example.test"]
    assert table.columns[3]._cells == ["[green]admin[/green]", "[cyan]developer[/cyan]", "[white]user[/white]"]
    assert cli.json == [users]


def test_admin_create_user_posts_optional_fields_and_prints_one_time_password(cli, monkeypatch):
    calls = []
    response = {
        "id": "user-id",
        "email": "alice@example.test",
        "name": "Alice",
        "username": "alice",
        "role": "admin",
        "password": "generated-secret",
    }
    monkeypatch.setattr(ops.client, "post", lambda path, body: calls.append((path, body)) or response)

    ops.admin_create_user("alice@example.test", "Alice", "alice", "admin", "chosen-secret", "table")

    assert calls == [
        (
            "/api/v1/admin/users",
            {
                "email": "alice@example.test",
                "name": "Alice",
                "role": "admin",
                "username": "alice",
                "password": "chosen-secret",
            },
        )
    ]
    assert "Username:" in cli.text()
    assert "generated-secret" in cli.text()


def test_admin_create_user_json_omits_unsupplied_optional_fields(cli, monkeypatch):
    calls = []
    response = {"id": "user-id"}
    monkeypatch.setattr(ops.client, "post", lambda path, body: calls.append((path, body)) or response)

    ops.admin_create_user("alice@example.test", "Alice", None, "reviewer", None, "json")

    assert calls == [("/api/v1/admin/users", {"email": "alice@example.test", "name": "Alice", "role": "reviewer"})]
    assert cli.json == [response]


def test_admin_reset_password_reports_missing_users(cli, monkeypatch):
    monkeypatch.setattr(ops.client, "get", lambda path: [])

    with pytest.raises(typer.Exit) as exc_info:
        ops.admin_reset_password("missing@example.test", True)

    assert exc_info.value.exit_code == 1
    assert "User not found" in cli.text()


def test_admin_reset_password_can_generate_a_password(cli, monkeypatch):
    calls = []
    monkeypatch.setattr(
        ops.client,
        "get",
        lambda path: [{"id": "user-id", "email": "alice@example.test"}],
    )
    monkeypatch.setattr(
        ops.client,
        "put",
        lambda path, body: (
            calls.append((path, body)) or {"message": "Password reset", "generated_password": "new-secret"}
        ),
    )

    ops.admin_reset_password(" ALICE@example.test ", True)

    assert calls == [("/api/v1/admin/users/user-id/password", {"generate": True})]
    assert "Password reset" in cli.text()
    assert "new-secret" in cli.text()


def test_admin_reset_password_validates_interactive_confirmation(cli, monkeypatch):
    monkeypatch.setattr(
        ops.client,
        "get",
        lambda path: [{"id": "user-id", "email": "alice@example.test"}],
    )
    passwords = iter(["first", "second"])
    monkeypatch.setattr(ops, "password_input", lambda prompt: next(passwords))

    with pytest.raises(typer.Exit) as exc_info:
        ops.admin_reset_password("alice@example.test", False)

    assert exc_info.value.exit_code == 1
    assert "Passwords do not match" in cli.text()


def test_admin_reset_password_submits_matching_interactive_password(cli, monkeypatch):
    calls = []
    monkeypatch.setattr(
        ops.client,
        "get",
        lambda path: [{"id": "user-id", "email": "alice@example.test"}],
    )
    monkeypatch.setattr(ops, "password_input", lambda prompt: "same-secret")
    monkeypatch.setattr(
        ops.client,
        "put",
        lambda path, body: calls.append((path, body)) or {"message": "Password reset"},
    )

    ops.admin_reset_password("alice@example.test", False)

    assert calls == [("/api/v1/admin/users/user-id/password", {"new_password": "same-secret"})]


def test_admin_delete_user_reports_missing_users(cli, monkeypatch):
    monkeypatch.setattr(ops.client, "get", lambda path: [])

    with pytest.raises(typer.Exit) as exc_info:
        ops.admin_delete_user("missing@example.test", True)

    assert exc_info.value.exit_code == 1
    assert "User not found" in cli.text()


def test_admin_delete_user_confirms_and_deletes_the_matching_user(cli, monkeypatch):
    calls = []
    confirmations = []
    user = {"id": "user-id", "email": "alice@example.test", "name": "Alice", "role": "reviewer"}
    monkeypatch.setattr(ops.client, "get", lambda path: [user])
    monkeypatch.setattr(ops.client, "delete", lambda path: calls.append(path))
    monkeypatch.setattr(ops.typer, "confirm", lambda prompt, abort: confirmations.append((prompt, abort)))

    ops.admin_delete_user(" ALICE@example.test ", False)

    assert confirmations == [("\nPermanently delete this user?", True)]
    assert calls == ["/api/v1/admin/users/user-id"]
    assert "Deleted user alice@example.test" in cli.text()


def test_admin_diagnostics_renders_health_checks_and_configuration_issues(cli, monkeypatch):
    data = {
        "status": "degraded",
        "checks": {
            "database": {"status": "ok", "users": 7},
            "jwt_keys": {"status": "error", "algorithm": "ES256"},
            "runtime_config": {"issues": ["missing key", "weak setting"]},
        },
    }
    monkeypatch.setattr(ops.client, "get", lambda path: data)

    ops.admin_diagnostics("table")

    output = cli.text()
    assert "Overall: [yellow]degraded" in output
    assert "Database: [green]ok" in output
    assert "Users: 7" in output
    assert "JWT:     [red]error" in output
    assert "Algorithm: ES256" in output
    assert "missing key" in output and "weak setting" in output


def test_admin_diagnostics_supports_json_and_healthy_runtime_config(cli, monkeypatch):
    responses = iter(
        [
            {"status": "ok", "checks": {"runtime_config": {"issues": []}}},
            {"status": "unhealthy", "checks": {}},
        ]
    )
    monkeypatch.setattr(ops.client, "get", lambda path: next(responses))

    ops.admin_diagnostics("table")
    ops.admin_diagnostics("json")

    assert "Configuration: [green]ok" in cli.text()
    assert cli.json == [{"status": "unhealthy", "checks": {}}]


def test_admin_saml_config_handles_unconfigured_json_and_configured_values(cli, monkeypatch):
    configured = {
        "configured": True,
        "idp_entity_id": "idp",
        "idp_sso_url": "https://idp.test/sso",
        "idp_slo_url": None,
        "sp_entity_id": "sp",
        "saml_active": True,
        "jit_provisioning": False,
    }
    responses = iter([{}, configured, configured])
    monkeypatch.setattr(ops.client, "get", lambda path: next(responses))

    ops.admin_saml_config("table")
    ops.admin_saml_config("json")
    ops.admin_saml_config("table")

    output = cli.text()
    assert "SAML SSO is not configured" in output
    assert "idp_entity_id: idp" in output
    assert "saml_active: [green]Yes" in output
    assert "jit_provisioning: [red]No" in output
    assert cli.json == [configured]


def test_admin_saml_config_set_sends_all_supplied_values(cli, monkeypatch):
    calls = []
    result = {
        "sp_entity_id": "sp-result",
        "sp_acs_url": "https://app.test/acs",
        "sp_metadata_url": "https://app.test/metadata",
    }
    monkeypatch.setattr(ops.client, "put", lambda path, body: calls.append((path, body)) or result)

    ops.admin_saml_config_set("idp", "https://idp.test/sso", "https://idp.test/slo", "cert", "sp", False, True)

    assert calls == [
        (
            "/api/v1/admin/saml-config",
            {
                "saml_active": True,
                "jit_provisioning": False,
                "idp_entity_id": "idp",
                "idp_sso_url": "https://idp.test/sso",
                "idp_slo_url": "https://idp.test/slo",
                "idp_x509_cert": "cert",
                "sp_entity_id": "sp",
            },
        )
    ]
    output = cli.text()
    assert "sp-result" in output
    assert "https://app.test/acs" in output
    assert "https://app.test/metadata" in output


def test_admin_saml_config_delete_confirms_and_deletes(cli, monkeypatch):
    confirmations = []
    calls = []
    monkeypatch.setattr(ops.typer, "confirm", lambda prompt, abort: confirmations.append((prompt, abort)))
    monkeypatch.setattr(ops.client, "delete", calls.append)

    ops.admin_saml_config_delete(False)

    assert confirmations == [("This will disable SAML SSO for all users. Continue?", True)]
    assert calls == ["/api/v1/admin/saml-config"]
    assert "configuration deleted" in cli.text()


def test_admin_scim_tokens_handles_table_json_and_empty_states(cli, monkeypatch):
    tokens = [
        {
            "id": "abcdefghijk",
            "token_prefix": "obs_a",
            "description": "Okta",
            "active": True,
            "created_at": "2026-06-01T12:00:00Z",
        },
        {"id": "second", "token_prefix": "obs_b", "active": False},
    ]
    responses = iter([tokens, tokens, []])
    monkeypatch.setattr(ops.client, "get", lambda path: next(responses))

    ops.admin_scim_tokens("table")
    ops.admin_scim_tokens("json")
    ops.admin_scim_tokens("table")

    table = cli.console.renderables[0]
    assert table.title == "SCIM Tokens"
    assert table.columns[1]._cells == ["obs_a", "obs_b"]
    assert table.columns[3]._cells == ["[green]Yes[/green]", "[red]No[/red]"]
    assert table.columns[4]._cells == ["2026-06-01", "-"]
    assert cli.json == [tokens]
    assert "No SCIM tokens configured" in cli.text()


def test_admin_scim_token_create_posts_description_and_displays_token(cli, monkeypatch):
    calls = []
    monkeypatch.setattr(
        ops.client,
        "post",
        lambda path, body: calls.append((path, body)) or {"token": "secret-token", "description": "Okta"},
    )

    ops.admin_scim_token_create("Okta")

    assert calls == [("/api/v1/admin/scim-tokens", {"description": "Okta"})]
    assert "secret-token" in cli.text()
    assert "Description: Okta" in cli.text()


def test_admin_scim_token_revoke_confirms_and_deletes(cli, monkeypatch):
    confirmations = []
    calls = []
    monkeypatch.setattr(ops.typer, "confirm", lambda prompt, abort: confirmations.append((prompt, abort)))
    monkeypatch.setattr(ops.client, "delete", calls.append)

    ops.admin_scim_token_revoke("abcdefgh-1234", False)

    assert confirmations == [("Revoke SCIM token abcdefgh...?", True)]
    assert calls == ["/api/v1/admin/scim-tokens/abcdefgh-1234"]
    assert "abcdefgh... revoked" in cli.text()


def test_admin_security_events_encodes_filters_and_renders_event_styles(cli, monkeypatch):
    calls = []
    events = [
        {
            "timestamp": "2026-06-01T12:00:00Z",
            "event_type": "login",
            "severity": "critical",
            "actor_email": "alice@example.test",
            "outcome": "failure",
            "detail": "x" * 50,
        },
        {
            "created_at": "2026-06-02T12:00:00Z",
            "event_type": "role.change",
            "severity": "warning",
            "outcome": "success",
        },
        {"event_type": "view", "severity": "info", "outcome": "unknown", "detail": None},
        {"event_type": "other", "severity": "custom", "outcome": "other"},
    ]
    monkeypatch.setattr(ops.client, "get", lambda path: calls.append(path) or {"events": events})

    ops.admin_security_events("login", "critical", "alice@example.test", 25, "table")

    assert calls == [
        "/api/v1/admin/security-events?limit=25&event_type=login&severity=critical&actor_email=alice%40example.test"
    ]
    table = cli.console.renderables[0]
    assert table.title == "Security Events (4)"
    assert table.columns[2]._cells == [
        "[red]critical[/red]",
        "[yellow]warning[/yellow]",
        "[dim]info[/dim]",
        "[white]custom[/white]",
    ]
    assert table.columns[4]._cells == [
        "[red]failure[/red]",
        "[green]success[/green]",
        "[white]unknown[/white]",
        "[white]other[/white]",
    ]
    assert table.columns[5]._cells[0] == "x" * 40


def test_admin_security_events_supports_json_and_empty_results(cli, monkeypatch):
    responses = iter([{"events": []}, []])
    monkeypatch.setattr(ops.client, "get", lambda path: next(responses))

    ops.admin_security_events(None, None, None, 50, "json")
    ops.admin_security_events(None, None, None, 50, "table")

    assert cli.json == [{"events": []}]
    assert "No security events found" in cli.text()


def test_admin_audit_log_encodes_filters_and_renders_resources(cli, monkeypatch):
    calls = []
    entries = [
        {
            "timestamp": "2026-06-01T12:00:00Z",
            "actor_email": "alice@example.test",
            "action": "agent.update",
            "resource_type": "agent",
            "resource_name": "builder",
            "ip_address": "127.0.0.1",
            "detail": "d" * 40,
        },
        {"created_at": "2026-06-02T12:00:00Z", "action": "login", "resource_type": "user"},
    ]
    monkeypatch.setattr(ops.client, "get", lambda path: calls.append(path) or entries)

    ops.admin_audit_log("agent.update", "alice@example.test", "agent", 10, "table")

    assert calls == [
        "/api/v1/admin/audit-log?limit=10&action=agent.update&actor_email=alice%40example.test&resource_type=agent"
    ]
    table = cli.console.renderables[0]
    assert table.title == "Audit Log (2 entries)"
    assert table.columns[3]._cells == ["agent/builder", "user"]
    assert table.columns[5]._cells[0] == "d" * 30


def test_admin_audit_log_supports_json_and_empty_results(cli, monkeypatch):
    responses = iter([[{"action": "login"}], []])
    monkeypatch.setattr(ops.client, "get", lambda path: next(responses))

    ops.admin_audit_log(None, None, None, 50, "json")
    ops.admin_audit_log(None, None, None, 50, "table")

    assert cli.json == [[{"action": "login"}]]
    assert "No audit log entries found" in cli.text()


def test_admin_audit_log_export_prints_or_writes_csv(cli, monkeypatch):
    responses = iter(["a,b\n1,2\n", {"fallback": True}])
    calls = []
    writes = []
    monkeypatch.setattr(ops.client, "get", lambda path: calls.append(path) or next(responses))
    monkeypatch.setattr(Path, "write_text", lambda self, data: writes.append((str(self), data)))

    ops.admin_audit_log_export("login", "alice@example.test", None)
    ops.admin_audit_log_export(None, None, "audit.csv")

    assert calls == [
        "/api/v1/admin/audit-log/export?action=login&actor_email=alice%40example.test",
        "/api/v1/admin/audit-log/export",
    ]
    assert "a,b\n1,2\n" in cli.lines
    assert writes == [("audit.csv", "{'fallback': True}")]
    assert "Audit log exported to audit.csv" in cli.text()


@pytest.mark.parametrize(("enabled", "label"), [(True, "enabled"), (False, "disabled")])
def test_admin_trace_privacy_reports_current_state(cli, monkeypatch, enabled, label):
    monkeypatch.setattr(ops.client, "get", lambda path: {"trace_privacy": enabled})

    ops.admin_trace_privacy()

    assert label in cli.text()


@pytest.mark.parametrize(("enabled", "returned", "label"), [(True, True, "enabled"), (True, False, "disabled")])
def test_admin_trace_privacy_set_uses_the_server_result(cli, monkeypatch, enabled, returned, label):
    calls = []
    monkeypatch.setattr(
        ops.client,
        "put",
        lambda path, body: calls.append((path, body)) or {"trace_privacy": returned},
    )

    ops.admin_trace_privacy_set(enabled)

    assert calls == [("/api/v1/admin/trace-privacy", {"trace_privacy": enabled})]
    assert label in cli.text()


def test_admin_cache_clear_posts_to_the_clear_endpoint(cli, monkeypatch):
    calls = []
    monkeypatch.setattr(ops.client, "post", lambda path: calls.append(path))

    ops.admin_cache_clear()

    assert calls == ["/api/v1/admin/cache/clear"]
    assert "All caches cleared" in cli.text()


def test_admin_set_role_reports_missing_users(cli, monkeypatch):
    monkeypatch.setattr(ops.client, "get", lambda path: [])

    with pytest.raises(typer.Exit) as exc_info:
        ops.admin_set_role("missing@example.test", "admin")

    assert exc_info.value.exit_code == 1
    assert "User not found" in cli.text()


def test_admin_set_role_updates_the_matching_user(cli, monkeypatch):
    calls = []
    monkeypatch.setattr(
        ops.client,
        "get",
        lambda path: [{"id": "user-id", "email": "alice@example.test"}],
    )
    monkeypatch.setattr(
        ops.client,
        "put",
        lambda path, body: calls.append((path, body)) or {"email": "alice@example.test", "role": "admin"},
    )

    ops.admin_set_role(" ALICE@example.test ", "admin")

    assert calls == [("/api/v1/admin/users/user-id/role", {"role": "admin"})]
    assert "alice@example.test is now admin" in cli.text()


def test_graphql_query_builds_payload_with_optional_variables(cli, monkeypatch):
    calls = []
    monkeypatch.setattr(ops.client, "post", lambda path, body: calls.append((path, body)) or {"ok": True})

    assert ops._graphql_query("query One") == {"ok": True}
    assert ops._graphql_query("query Two", {"id": "trace"}) == {"ok": True}
    assert calls == [
        ("/api/v1/graphql", {"query": "query One"}),
        ("/api/v1/graphql", {"query": "query Two", "variables": {"id": "trace"}}),
    ]


def test_traces_passes_filters_and_supports_json(cli, monkeypatch):
    sessions = [{"session_id": "one"}]
    calls = []
    monkeypatch.setattr(ops.client, "get", lambda path, params=None: calls.append((path, params)) or sessions)

    ops._traces("kiro", 7, 5, False, False, "json")

    assert calls == [("/api/v1/sessions", {"limit": 5, "platform": "kiro", "days": 7})]
    assert cli.json == [sessions]


def test_traces_handles_empty_results_and_routes_detail_view(cli, monkeypatch):
    responses = iter([[], [{"session_id": "one"}]])
    details = []
    monkeypatch.setattr(ops.client, "get", lambda path, params=None: next(responses))
    monkeypatch.setattr(ops, "_render_sessions_detail", lambda sessions, full: details.append((sessions, full)))

    ops._traces_impl(None, None, 20, False, False, "table")
    ops._traces_impl(None, None, 20, True, True, "table")

    assert "No traces found" in cli.text()
    assert details == [([{"session_id": "one"}], True)]


def test_render_sessions_summary_formats_counts_and_tokens(cli, monkeypatch):
    sessions = [
        {
            "prompt_count": 1,
            "user_name": "Alice",
            "platform": "kiro",
            "tool_result_count": 2,
            "total_input_tokens": 13800,
            "total_output_tokens": 137,
            "first_event_time": "first",
        },
        {"prompt_count": 2, "last_event_time": "last"},
    ]

    calls = []
    monkeypatch.setattr(ops.client, "get", lambda path, params=None: calls.append((path, params)) or sessions)

    ops._traces_impl(None, None, 20, False, False, "table")

    assert calls == [("/api/v1/sessions", {"limit": 20})]
    table = cli.console.renderables[0]
    assert table.title == "Sessions (2)"
    assert table.columns[1]._cells == ["1 prompt", "2 prompts"]
    assert table.columns[4]._cells == ["1", "2"]
    assert table.columns[6]._cells == ["13.8k / 137", "0 / 0"]
    assert table.columns[7]._cells == ["relative:first", "relative:last"]


def test_render_sessions_detail_handles_failures_empty_sessions_events_and_subagents(cli, monkeypatch):
    sessions = [
        {
            "session_id": "failed-session",
            "prompt_count": 2,
            "tool_result_count": 1,
            "total_input_tokens": 1000,
            "total_output_tokens": 20,
            "platform": "kiro",
            "user_name": "Alice",
            "first_event_time": "first",
            "model": "model-a",
        },
        {
            "session_id": "empty-session",
            "prompt_count": 0,
            "tool_result_count": 0,
            "platform": "cursor",
            "first_event_time": "second",
        },
        {
            "session_id": "full-session",
            "prompt_count": 1,
            "tool_result_count": 2,
            "platform": "codex",
            "first_event_time": "third",
        },
    ]
    details = {
        "empty-session": {"events": []},
        "full-session": {
            "events": [
                {"event_name": "user_prompt", "body": "p" * 101},
                {"event_name": "assistant_response", "body": "a" * 151},
                {"event_name": "tool_call", "body": "ignored", "attributes": {"tool_name": "search"}},
                {"event_name": "hook_pretooluse", "body": "fallback-tool", "attributes": {}},
                {"event_name": "tool_result", "body": "r" * 101},
            ],
            "subagent_sessions": [
                {
                    "events": [
                        {"event_name": "human_turn", "body": "sub prompt"},
                        {"event_name": "tool_call", "body": "sub fallback", "attributes": {}},
                    ]
                }
            ],
        },
    }

    def fake_get(path):
        session_id = path.rsplit("/", 1)[1]
        if session_id == "failed-session":
            raise RuntimeError("detail unavailable")
        return details[session_id]

    monkeypatch.setattr(ops.client, "get", fake_get)

    ops._render_sessions_detail(sessions, full=True)

    output = render(cli.console.renderables[0])
    assert "2 prompts" in output
    assert "prompts: 2, tools: 1" in output
    assert "tokens: 1.0k / 20" in output
    assert "model: model-a" in output
    assert "prompts: 0, tools: 0" in output
    assert "search" in output
    assert "fallback-tool" in output
    assert "subagent (2 events)" in output
    assert "sub prompt" in output
    assert "sub fallback" in output
    assert "…" in output


@pytest.mark.parametrize(
    ("input_tokens", "output_tokens", "expected"),
    [(1_200_000, 1_500, "1.2M / 1.5k"), (999, 0, "999 / 0")],
)
def test_format_tokens_compacts_large_counts(input_tokens, output_tokens, expected):
    assert ops._format_tokens(input_tokens, output_tokens) == expected


def test_spans_reports_missing_traces(cli, monkeypatch):
    monkeypatch.setattr(ops, "_graphql_query", lambda query, variables: {"data": {"trace": None}})

    with pytest.raises(typer.Exit) as exc_info:
        ops._spans("missing", "table")

    assert exc_info.value.exit_code == 1
    assert "Trace missing not found" in cli.text()


def test_spans_supports_json_and_empty_span_lists(cli, monkeypatch):
    traces = iter(
        [
            {"traceId": "trace", "name": "one", "spans": [{"spanId": "span"}]},
            {"traceId": "trace", "name": "empty", "spans": []},
        ]
    )
    monkeypatch.setattr(
        ops,
        "_graphql_query",
        lambda query, variables: {"data": {"trace": next(traces)}},
    )

    ops._spans_impl("trace", "json")
    ops._spans_impl("trace", "table")

    assert cli.json == [{"traceId": "trace", "name": "one", "spans": [{"spanId": "span"}]}]
    assert "No spans" in cli.text()


def test_spans_renders_schema_latency_and_status_variants(cli, monkeypatch):
    trace = {
        "traceId": "trace-id",
        "name": "workflow",
        "spans": [
            {
                "spanId": "span-success-123456",
                "type": "tool",
                "name": "search",
                "method": "call",
                "latencyMs": 12,
                "status": "success",
                "toolSchemaValid": True,
            },
            {
                "spanId": "span-error-123456",
                "type": "tool",
                "name": "write",
                "method": None,
                "latencyMs": 0,
                "status": "error",
                "toolSchemaValid": False,
            },
            {
                "spanId": "span-other-123456",
                "type": "agent",
                "name": "think",
                "status": "pending",
            },
        ],
    }
    monkeypatch.setattr(ops, "_graphql_query", lambda query, variables: {"data": {"trace": trace}})

    ops._spans_impl("trace-id", "table")

    table = cli.console.renderables[0]
    assert table.columns[4]._cells == ["call", "--", "--"]
    assert table.columns[5]._cells == ["12ms", "--", "--"]
    assert table.columns[6]._cells == ["[green]success[/green]", "[red]error[/red]", "pending"]
    assert table.columns[7]._cells == ["[green]✓[/green]", "[red]✗[/red]", "[dim]--[/dim]"]


def test_do_install_delegates_to_upgrade_executor(cli, monkeypatch):
    from observal_cli import upgrade_executor

    calls = []
    install = object()
    monkeypatch.setattr(
        upgrade_executor,
        "execute",
        lambda info, target, direction, spinner: calls.append((info, target, direction, spinner)),
    )

    ops._do_install(install, "2.0.0", "upgrade")

    assert calls == [(install, "2.0.0", "upgrade", ops.spinner)]


def install_info(method: InstallMethod = InstallMethod.UV_TOOL, managed_by: str | None = "uv") -> InstallInfo:
    return InstallInfo(method=method, path=Path("/mock/observal"), writable=True, managed_by=managed_by)


def test_upgrade_rejects_invalid_versions(cli, monkeypatch):
    from observal_cli import install_detector, version_check

    monkeypatch.setattr(version_check, "get_current_version", lambda: "1.0.0")
    monkeypatch.setattr(install_detector, "detect", lambda: install_info())

    with pytest.raises(typer.Exit) as exc_info:
        ops.upgrade("not-a-version", False, True)

    assert exc_info.value.exit_code == 1
    assert "Invalid version" in cli.text()


def test_upgrade_reports_release_lookup_failures(cli, monkeypatch):
    from observal_cli import install_detector, version_check

    monkeypatch.setattr(version_check, "get_current_version", lambda: "1.0.0")
    monkeypatch.setattr(install_detector, "detect", lambda: install_info())
    monkeypatch.setattr(version_check, "_fetch_from_github", lambda include_pre: None)

    with pytest.raises(typer.Exit) as exc_info:
        ops.upgrade(None, True, True)

    assert exc_info.value.exit_code == 1
    assert "Failed to fetch latest release" in cli.text()


def test_upgrade_honors_declined_confirmation(cli, monkeypatch):
    from observal_cli import install_detector, version_check

    confirmations = []
    monkeypatch.setattr(version_check, "get_current_version", lambda: "1.0.0")
    monkeypatch.setattr(install_detector, "detect", lambda: install_info())
    monkeypatch.setattr(ops.typer, "confirm", lambda prompt: confirmations.append(prompt) or False)

    with pytest.raises(typer.Abort):
        ops.upgrade("1.1.0", False, False)

    assert confirmations == ["\nProceed with upgrade?"]
    assert "Current:" in cli.text() and "Target:" in cli.text()


def test_upgrade_reports_lock_contention(cli, monkeypatch):
    from observal_cli import install_detector, upgrade_lock, version_check

    monkeypatch.setattr(version_check, "get_current_version", lambda: "1.0.0")
    monkeypatch.setattr(install_detector, "detect", lambda: install_info())
    monkeypatch.setattr(upgrade_lock, "acquire_lock", lambda scope: (_ for _ in ()).throw(UpgradeLockError("busy")))

    with pytest.raises(typer.Exit) as exc_info:
        ops.upgrade("1.1.0", False, True)

    assert exc_info.value.exit_code == 1
    assert "busy" in cli.text()


def test_upgrade_installs_and_releases_the_lock_with_nonstandard_current_version(cli, monkeypatch):
    from observal_cli import install_detector, upgrade_lock, version_check

    calls = []
    info = install_info()
    monkeypatch.setattr(version_check, "get_current_version", lambda: "development")
    monkeypatch.setattr(install_detector, "detect", lambda: info)
    monkeypatch.setattr(upgrade_lock, "acquire_lock", lambda scope: calls.append(("acquire", scope)) or "lock")
    monkeypatch.setattr(upgrade_lock, "release_lock", lambda lock: calls.append(("release", lock)))
    monkeypatch.setattr(ops, "_do_install", lambda actual, target, direction: calls.append((actual, target, direction)))

    ops.upgrade("1.2.0", False, True)

    assert calls == [
        ("acquire", "cli"),
        (info, "1.2.0", "upgrade"),
        ("release", "lock"),
    ]


def test_downgrade_reports_empty_release_lists(cli, monkeypatch):
    from observal_cli import version_check

    monkeypatch.setattr(version_check, "get_current_version", lambda: "2.0.0")
    monkeypatch.setattr(version_check, "fetch_all_releases", lambda: [])

    with pytest.raises(typer.Exit) as exc_info:
        ops.downgrade(None, True, True)

    assert exc_info.value.exit_code == 1
    assert "Failed to fetch releases" in cli.text()


def test_downgrade_list_marks_the_current_release(cli, monkeypatch):
    from observal_cli import version_check

    tables = []
    monkeypatch.setattr(version_check, "get_current_version", lambda: "2.0.0")
    monkeypatch.setattr(
        version_check,
        "fetch_all_releases",
        lambda: [
            {"version": "2.0.0", "published_at": "2026-06-02"},
            {"version": "1.9.0", "published_at": "2026-06-01"},
        ],
    )
    monkeypatch.setattr(Console, "print", lambda self, table: tables.append(table))

    with pytest.raises(typer.Exit) as exc_info:
        ops.downgrade(None, True, True)

    assert exc_info.value.exit_code == 0
    assert tables[0].columns[0]._cells == ["2.0.0", "1.9.0"]
    assert tables[0].columns[2]._cells == ["← current", ""]


@pytest.mark.parametrize(
    ("version", "message"),
    [("invalid", "Invalid version"), ("0.9.0", "Cannot downgrade below")],
)
def test_downgrade_validates_target_versions(cli, monkeypatch, version, message):
    from observal_cli import version_check

    monkeypatch.setattr(version_check, "get_current_version", lambda: "2.0.0")

    with pytest.raises(typer.Exit) as exc_info:
        ops.downgrade(version, False, True)

    assert exc_info.value.exit_code == 1
    assert message in cli.text()


def test_downgrade_blocks_managed_installations(cli, monkeypatch):
    from observal_cli import install_detector, version_check

    monkeypatch.setattr(version_check, "get_current_version", lambda: "2.0.0")
    monkeypatch.setattr(
        install_detector,
        "detect",
        lambda: install_info(InstallMethod.SYSTEM_PACKAGE, "apt"),
    )

    with pytest.raises(typer.Exit) as exc_info:
        ops.downgrade("1.10.4", False, True)

    assert exc_info.value.exit_code == 1
    assert "managed by apt" in cli.text()


def test_downgrade_honors_declined_confirmation(cli, monkeypatch):
    from observal_cli import install_detector, version_check

    monkeypatch.setattr(version_check, "get_current_version", lambda: "2.0.0")
    monkeypatch.setattr(install_detector, "detect", lambda: install_info())
    monkeypatch.setattr(ops.typer, "confirm", lambda prompt: False)

    with pytest.raises(typer.Abort):
        ops.downgrade("1.10.4", False, False)


def test_downgrade_reports_lock_contention(cli, monkeypatch):
    from observal_cli import install_detector, upgrade_lock, version_check

    monkeypatch.setattr(version_check, "get_current_version", lambda: "2.0.0")
    monkeypatch.setattr(install_detector, "detect", lambda: install_info())
    monkeypatch.setattr(upgrade_lock, "acquire_lock", lambda scope: (_ for _ in ()).throw(UpgradeLockError("busy")))

    with pytest.raises(typer.Exit) as exc_info:
        ops.downgrade("1.10.4", False, True)

    assert exc_info.value.exit_code == 1
    assert "busy" in cli.text()


def test_downgrade_installs_when_current_version_is_nonstandard(cli, monkeypatch):
    from observal_cli import install_detector, upgrade_lock, version_check

    calls = []
    info = install_info()
    monkeypatch.setattr(version_check, "get_current_version", lambda: "development")
    monkeypatch.setattr(install_detector, "detect", lambda: info)
    monkeypatch.setattr(upgrade_lock, "acquire_lock", lambda scope: "lock")
    monkeypatch.setattr(upgrade_lock, "release_lock", lambda lock: calls.append(("release", lock)))
    monkeypatch.setattr(ops, "_do_install", lambda actual, target, direction: calls.append((actual, target, direction)))

    ops.downgrade("1.10.4", False, True)

    assert calls == [(info, "1.10.4", "downgrade"), ("release", "lock")]


def backup_root(monkeypatch, exists: bool):
    backup = SimpleNamespace(exists=lambda: exists)

    class Root:
        def __truediv__(self, part):
            assert part == "bin"
            return Bin()

    class Bin:
        def __truediv__(self, part):
            assert part == "observal.prev"
            return backup

    monkeypatch.setattr(ops.config, "CONFIG_DIR", Root())
    return backup


def test_rollback_reports_missing_backups(cli, monkeypatch):
    from observal_cli import install_detector

    backup_root(monkeypatch, False)
    monkeypatch.setattr(install_detector, "detect", lambda: install_info(InstallMethod.BINARY, "curl"))

    with pytest.raises(typer.Exit) as exc_info:
        ops.rollback()

    assert exc_info.value.exit_code == 1
    assert "No backup found" in cli.text()


def test_rollback_rejects_non_binary_installs(cli, monkeypatch):
    from observal_cli import install_detector

    backup_root(monkeypatch, True)
    monkeypatch.setattr(install_detector, "detect", lambda: install_info())

    with pytest.raises(typer.Exit) as exc_info:
        ops.rollback()

    assert exc_info.value.exit_code == 1
    assert "only supported for binary installs" in cli.text()


def test_rollback_honors_declined_confirmation(cli, monkeypatch):
    from observal_cli import install_detector

    backup_root(monkeypatch, True)
    monkeypatch.setattr(install_detector, "detect", lambda: install_info(InstallMethod.BINARY, "curl"))
    monkeypatch.setattr(ops.typer, "confirm", lambda prompt: False)

    with pytest.raises(typer.Abort):
        ops.rollback()


def test_rollback_copies_backup_and_restores_executable_mode(cli, monkeypatch):
    import os
    import shutil

    from observal_cli import install_detector

    backup = backup_root(monkeypatch, True)
    info = install_info(InstallMethod.BINARY, "curl")
    calls = []
    monkeypatch.setattr(install_detector, "detect", lambda: info)
    monkeypatch.setattr(ops.typer, "confirm", lambda prompt: True)
    monkeypatch.setattr(shutil, "copy2", lambda source, target: calls.append(("copy", source, target)))
    monkeypatch.setattr(os, "chmod", lambda target, mode: calls.append(("chmod", target, mode)))

    ops.rollback()

    assert calls == [
        ("copy", str(backup), str(info.path)),
        ("chmod", str(info.path), 0o755),
    ]
    assert "Rolled back to previous version" in cli.text()


@pytest.mark.parametrize(
    ("release", "newer", "message"),
    [
        ({"latest_version": "2.0.0"}, True, "update available"),
        ({"latest_version": "1.0.0"}, False, "up to date"),
        (None, False, "could not reach GitHub"),
    ],
)
def test_status_reports_update_availability(cli, monkeypatch, release, newer, message):
    from observal_cli import install_detector, version_check

    monkeypatch.setattr(version_check, "get_current_version", lambda: "1.0.0")
    monkeypatch.setattr(version_check, "_fetch_from_github", lambda: release)
    monkeypatch.setattr(version_check, "_is_newer", lambda latest, current: newer)
    monkeypatch.setattr(install_detector, "detect", lambda: install_info())

    ops.status()

    output = cli.text()
    assert "Version:  [bold]v1.0.0" in output
    assert "uv_tool" in output
    assert message in output
