# SPDX-FileCopyrightText: 2026 Naraen Rammoorthi
# SPDX-License-Identifier: Apache-2.0

"""Phase 3 component observability API: auth, bounds, coverage and scoping."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.deps import get_current_user, get_db
from api.routes import component_activity as route
from models.user import UserRole
from services.component_activity import coverage, queries

OWNER_ID = uuid.uuid4()
LISTING_ID = uuid.uuid4()
VERSION_ID = uuid.uuid4()


def _user(role=UserRole.user, user_id=None):
    return SimpleNamespace(id=user_id or uuid.uuid4(), role=role)


def _listing(co_authors=()):
    return SimpleNamespace(
        id=LISTING_ID, submitted_by=OWNER_ID, co_authors=list(co_authors), namespace="team", slug="probe"
    )


_SUMMARY = {
    "present_sessions": 2,
    "present_users": 1,
    "observed_sessions": 1,
    "observed_calls": 3,
    "result_states": {"success": 1, "error": 1, "unknown": 1},
    "harness_distribution": {"claude-code": 2},
    "activation_actions": {"context_sessions": 0, "next_session_sessions": 1},
    "coverage": coverage.build_coverage(
        {"present_sessions": 2, "present_users": 1},
        {"supported_present_sessions": 2, "projection_complete_sessions": 2, "observed_sessions": 1},
        257,
    ),
}


@pytest.fixture
def api(monkeypatch):
    app = FastAPI()
    app.include_router(route.router)
    state = {"user": _user(user_id=OWNER_ID), "listing": _listing(), "version_found": True}
    db = SimpleNamespace(scalar=AsyncMock(side_effect=lambda *_a, **_k: VERSION_ID if state["version_found"] else None))
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: state["user"]
    resolve = AsyncMock(side_effect=lambda *_a, **_k: state["listing"])
    summary = AsyncMock(return_value=_SUMMARY)
    sessions = AsyncMock(return_value=([], None))
    monkeypatch.setattr(route, "resolve_visible_listing", resolve)
    monkeypatch.setattr(queries, "activity_summary", summary)
    monkeypatch.setattr(queries, "activity_sessions", sessions)
    return SimpleNamespace(
        client=TestClient(app), state=state, resolve=resolve, summary=summary, sessions=sessions, db=db
    )


@pytest.mark.parametrize(
    "actor",
    [
        _user(user_id=OWNER_ID),
        _user(role=UserRole.admin),
        _user(role=UserRole.super_admin),
    ],
    ids=["owner", "admin", "super-admin"],
)
def test_owner_and_admin_may_read_summary(api, actor):
    api.state["user"] = actor
    response = api.client.get("/api/v1/components/mcp/team/probe/activity/summary")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["component"]["qualified_name"] == "team/probe"
    assert body["coverage"]["attribution_state"] == "observed"
    assert "last_event_time in [start, end)" in body["time_basis"]
    assert api.resolve.await_args.args[1] == "team/probe"  # namespace/slug resolved by the shared loader


def test_co_author_allowed_viewer_forbidden_private_non_member_not_found(api):
    co_author = _user()
    api.state["listing"] = _listing(co_authors=[co_author.id])
    api.state["user"] = co_author
    assert api.client.get(f"/api/v1/components/mcp/{LISTING_ID}/activity/summary").status_code == 200

    api.state["listing"] = _listing()
    api.state["user"] = _user(role=UserRole.reviewer)
    response = api.client.get(f"/api/v1/components/mcp/{LISTING_ID}/activity/summary")
    assert response.status_code == 403

    api.state["listing"] = None  # resolve_visible_listing hides private listings from non-members
    assert api.client.get(f"/api/v1/components/mcp/{LISTING_ID}/activity/sessions").status_code == 404
    api.summary.assert_awaited_once()  # denied callers never reach a telemetry query
    api.sessions.assert_not_awaited()


def test_unauthenticated_uses_existing_auth_dependency(api):
    def deny():
        from fastapi import HTTPException

        raise HTTPException(status_code=401, detail="Not authenticated")

    api.client.app.dependency_overrides[get_current_user] = deny
    assert api.client.get(f"/api/v1/components/mcp/{LISTING_ID}/activity/summary").status_code == 401
    api.summary.assert_not_awaited()


def test_version_must_belong_to_listing_and_is_forwarded(api):
    url = f"/api/v1/components/mcp/{LISTING_ID}/activity/summary"
    assert api.client.get(url, params={"component_version_id": "not-a-uuid"}).status_code == 422
    api.state["version_found"] = False
    assert api.client.get(url, params={"component_version_id": str(uuid.uuid4())}).status_code == 404
    api.summary.assert_not_awaited()
    api.state["version_found"] = True
    assert api.client.get(url, params={"component_version_id": str(VERSION_ID)}).status_code == 200
    assert api.summary.await_args.args[3] == str(VERSION_ID)


@pytest.mark.parametrize("kind", ["skill", "hook"])
def test_skill_and_hook_are_explicitly_unsupported_not_zero(api, kind):
    for endpoint in ("summary", "sessions"):
        response = api.client.get(f"/api/v1/components/{kind}/{LISTING_ID}/activity/{endpoint}")
        assert response.status_code == 501
        assert response.json()["status"] == "unsupported" and "present_sessions" not in response.json()
    api.resolve.assert_not_awaited()


def test_unknown_type_and_period_and_limit_bounds(api):
    assert api.client.get(f"/api/v1/components/prompt/{LISTING_ID}/activity/summary").status_code == 422
    base = f"/api/v1/components/mcp/{LISTING_ID}/activity"
    for days in (0, 91):
        assert api.client.get(f"{base}/summary", params={"period_days": days}).status_code == 422
    for limit in (0, 101):
        assert api.client.get(f"{base}/sessions", params={"limit": limit}).status_code == 422
    assert api.client.get(f"{base}/sessions", params={"cursor": "%%%"}).status_code == 422
    assert api.client.get(f"{base}/summary", params={"period_days": 90}).status_code == 200
    assert api.client.get(f"{base}/sessions", params={"limit": 100}).status_code == 200
    api.resolve.assert_awaited()


def test_cursor_round_trip_pins_window_end_and_rejects_tampering(api):
    end = datetime(2026, 1, 15, tzinfo=UTC)
    row = {"last_event_time": "2026-01-10 00:00:00.000", "user_id": "u", "harness": "claude-code", "session_id": "s"}
    cursor = queries.encode_cursor(row, end)
    pinned, key = queries.decode_cursor(cursor)
    assert pinned == end and key == ["2026-01-10 00:00:00.000", "u", "claude-code", "s"]
    response = api.client.get(
        f"/api/v1/components/mcp/{LISTING_ID}/activity/sessions", params={"cursor": cursor, "period_days": 7}
    )
    assert response.status_code == 200
    kwargs, args = api.sessions.await_args.kwargs, api.sessions.await_args.args
    assert kwargs["cursor"] == key and args[4] == (end - timedelta(days=7), end)
    for bad in ("", "e30", queries.encode_cursor(row, end)[:-3] + "AAA"):
        with pytest.raises(ValueError):
            queries.decode_cursor(bad)


def test_coverage_distinguishes_no_observed_calls_from_attribution_not_possible():
    processed = coverage.build_coverage(
        {"present_sessions": 3}, {"supported_present_sessions": 3, "projection_complete_sessions": 2}, 257
    )
    assert processed.attribution_state == "no_observed_calls" and processed.usage_rate == 0
    assert processed.usage_rate_denominator_sessions == 2
    pending = coverage.build_coverage(
        {"present_sessions": 3},
        {"supported_present_sessions": 1, "unsupported_present_sessions": 2, "projection_pending_sessions": 1},
        257,
    )
    assert pending.attribution_state == "attribution_not_possible" and pending.usage_rate is None
    assert {"unsupported_harness_sessions", "projection_pending_sessions"} <= set(pending.reasons)
    empty = coverage.build_coverage({}, {}, 257)
    assert empty.attribution_state == "attribution_not_possible" and "no_present_sessions" in empty.reasons
    observed = coverage.build_coverage(
        {"present_sessions": 4}, {"projection_complete_sessions": 4, "observed_sessions": 1}, 257
    )
    assert observed.attribution_state == "observed" and observed.usage_rate == 0.25
    assert any("sender_cached_hash_not_proven_stable" in item for item in observed.limitations)
    assert any("historical_final_push_unproven" in item for item in observed.limitations)


@pytest.mark.asyncio
async def test_activity_sql_binds_scoped_key_current_version_and_component(monkeypatch):
    captured = []

    async def fake_query(sql, params):
        captured.append((sql, params))
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {"data": []})

    monkeypatch.setattr(queries.clickhouse, "_query", fake_query)
    monkeypatch.setattr(queries, "presence_coverage", AsyncMock(return_value={}))
    period = (datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 1, 2, tzinfo=UTC))
    await queries.activity_summary("proj", "mcp", str(LISTING_ID), None, period)
    await queries.activity_sessions("proj", "mcp", str(LISTING_ID), None, period, limit=5, cursor=None)
    for sql, params in captured:
        assert "'proj'" not in sql and str(LISTING_ID) not in sql  # parameterized only
        assert params["param_project_id"] == "proj"
    summary_sql = captured[0][0]
    for join in (
        "c.user_id = p.user_id AND c.harness = p.harness AND c.session_id = p.session_id",
        "c.user_id = a.user_id AND c.harness = a.harness AND c.session_id = a.session_id",
        "a.projection_generation = latest.generation",
    ):
        assert join in summary_sql
    assert "a.component_id = {component_id:String}" in summary_sql
    assert "countIf(status = 'failed') = 0" in summary_sql
    assert captured[0][1]["param_projection_version"] == queries.publication_version()
    assert captured[0][1]["param_supported"] == "['claude-code']"
    page_sql, page_params = captured[-1]
    # Source availability reads only sizes/flags server-side; raw text is never selected.
    assert "empty(raw_line)" in page_sql
    assert "raw_line," not in page_sql and "raw_line AS" not in page_sql and page_params["param_limit"] == 6
    assert "s.user_id" in page_sql and "'source_too_large'" in page_sql
    assert any("session_capabilities FINAL" in sql for sql, _ in captured)
    with pytest.raises(ValueError):
        await queries.activity_sessions("proj", "mcp", str(LISTING_ID), None, period, limit=101, cursor=None)


@pytest.mark.asyncio
async def test_session_page_hides_non_complete_counts_and_emits_cursor_only_when_more(monkeypatch):
    rows = [
        {
            "user_id": "u",
            "harness": "claude-code",
            "session_id": f"s{i}",
            "last_event_time": f"2026-01-01 00:00:0{i}.000",
            "projection_state": state,
            "calls": 2,
            "successes": 1,
            "errors": 1,
            "unknowns": 0,
            "refs": [[4, "id:a", "success"], [5, "id:b", "error"]],
        }
        for i, state in enumerate(["complete", "pending", "complete"])
    ]
    monkeypatch.setattr(queries, "_rows", AsyncMock(return_value=rows))
    period = (datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 1, 2, tzinfo=UTC))
    sessions, cursor = await queries.activity_sessions("p", "mcp", str(LISTING_ID), None, period, limit=2, cursor=None)
    assert [s["session_id"] for s in sessions] == ["s0", "s1"]
    assert sessions[0]["observed_calls"] == 2 and sessions[0]["source_references"][0]["source_block_key"] == "id:a"
    assert sessions[1]["observed_calls"] == 0 and sessions[1]["source_references"] == []
    assert queries.decode_cursor(cursor)[1] == ["2026-01-01 00:00:01.000", "u", "claude-code", "s1"]


def test_source_availability_reasons_are_distinct_and_never_no_observed_calls():
    from services.component_activity.coverage import build_coverage

    presence = {"present_sessions": 4, "present_users": 1}
    activity = {
        "supported_present_sessions": 4,
        "source_missing_sessions": 1,
        "source_unavailable_sessions": 1,
        "source_incomplete_sessions": 1,
        "source_too_large_sessions": 1,
    }
    coverage = build_coverage(presence, activity, 257)
    assert coverage.attribution_state == "attribution_not_possible"
    assert coverage.usage_rate is None and coverage.usage_rate_denominator_sessions == 0
    for reason in (
        "source_missing_sessions",
        "source_unavailable_sessions",
        "source_incomplete_sessions",
        "source_too_large_sessions",
    ):
        assert reason in coverage.reasons
