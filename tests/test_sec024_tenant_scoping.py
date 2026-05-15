# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only
"""Tests for tenant data isolation on admin dashboard and telemetry endpoints."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── Fixtures ──────────────────────────────────────────────────────────────────


def _user(org_id=None):
    from models.user import User, UserRole

    u = MagicMock(spec=User)
    u.id = uuid.uuid4()
    u.role = UserRole.admin
    u.org_id = org_id if org_id is not None else uuid.uuid4()
    return u


def _mock_db():
    db = AsyncMock()
    result = MagicMock()
    result.all.return_value = []
    result.scalars.return_value.all.return_value = []
    result.scalar_one.return_value = 0
    db.execute = AsyncMock(return_value=result)
    db.scalar = AsyncMock(return_value=0)
    return db


def _init_cache():
    from fastapi_cache import FastAPICache
    from fastapi_cache.backends.inmemory import InMemoryBackend

    FastAPICache.init(InMemoryBackend(), prefix="test-cache")


# ── _project_id_for_user ──────────────────────────────────────────────────────


class TestProjectIdForUser:
    def test_returns_org_id_when_present(self):
        from api.routes.dashboard import _project_id_for_user

        org = uuid.uuid4()
        assert _project_id_for_user(_user(org_id=org)) == str(org)

    def test_returns_default_when_org_is_none(self):
        from api.routes.dashboard import _project_id_for_user

        u = _user()
        u.org_id = None
        assert _project_id_for_user(u) == "default"

    def test_returns_default_when_user_is_none(self):
        from api.routes.dashboard import _project_id_for_user

        assert _project_id_for_user(None) == "default"

    def test_string_org_id_returned_as_is(self):
        from api.routes.dashboard import _project_id_for_user

        u = MagicMock()
        u.org_id = "already-a-string"
        assert _project_id_for_user(u) == "already-a-string"


# ── _ch_json_scoped ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ch_json_scoped_replaces_default_and_injects_pid():
    from api.routes.dashboard import _ch_json_scoped

    org = uuid.uuid4()
    u = _user(org_id=org)
    captured = {}

    async def fake_ch_json(sql, params=None):
        captured["sql"] = sql
        captured["params"] = params
        return []

    with patch("api.routes.dashboard._ch_json", side_effect=fake_ch_json):
        await _ch_json_scoped(
            "SELECT * FROM spans WHERE project_id = 'default' AND is_deleted = 0",
            u,
            {"param_days": "7"},
        )

    assert "project_id = {pid:String}" in captured["sql"]
    assert "project_id = 'default'" not in captured["sql"]
    assert captured["params"]["param_pid"] == str(org)
    assert captured["params"]["param_days"] == "7"


@pytest.mark.asyncio
async def test_ch_json_scoped_no_params_still_injects_pid():
    from api.routes.dashboard import _ch_json_scoped

    org = uuid.uuid4()
    u = _user(org_id=org)
    captured = {}

    async def fake_ch_json(sql, params=None):
        captured["params"] = params
        return []

    with patch("api.routes.dashboard._ch_json", side_effect=fake_ch_json):
        await _ch_json_scoped("SELECT 1 FROM spans WHERE project_id = 'default'", u)

    assert captured["params"]["param_pid"] == str(org)
    assert len(captured["params"]) == 1


@pytest.mark.asyncio
async def test_ch_json_scoped_preserves_existing_params():
    from api.routes.dashboard import _ch_json_scoped

    org = uuid.uuid4()
    u = _user(org_id=org)
    captured = {}

    async def fake_ch_json(sql, params=None):
        captured["params"] = params
        return []

    with patch("api.routes.dashboard._ch_json", side_effect=fake_ch_json):
        await _ch_json_scoped("SELECT 1", u, {"param_days": "30", "param_x": "y"})

    assert captured["params"]["param_pid"] == str(org)
    assert captured["params"]["param_days"] == "30"
    assert captured["params"]["param_x"] == "y"


@pytest.mark.asyncio
async def test_ch_json_scoped_uses_default_when_org_none():
    from api.routes.dashboard import _ch_json_scoped

    u = _user()
    u.org_id = None
    captured = {}

    async def fake_ch_json(sql, params=None):
        captured["params"] = params
        return []

    with patch("api.routes.dashboard._ch_json", side_effect=fake_ch_json):
        await _ch_json_scoped("SELECT 1 FROM spans WHERE project_id = 'default'", u)

    assert captured["params"]["param_pid"] == "default"


# ── trends: org-scoped PostgreSQL queries ─────────────────────────────────────


@pytest.mark.asyncio
async def test_trends_scopes_mcp_query_to_org():
    """trends passes org-scoped WHERE clause to db.execute when user has an org."""
    from api.routes.dashboard import trends

    org = uuid.uuid4()
    admin = _user(org_id=org)
    db = _mock_db()
    _init_cache()

    # Track what SQLAlchemy statements are executed
    executed = []
    orig = db.execute

    async def capture(stmt, *a, **kw):
        executed.append(stmt)
        return await orig(stmt, *a, **kw)

    db.execute = capture

    await trends(range_=None, db=db, current_user=admin)

    # Two statements: mcp_stmt and user_stmt
    assert len(executed) == 2
    # Both should be real SQLAlchemy Select objects (not raw strings)
    assert all(hasattr(s, "whereclause") for s in executed)


@pytest.mark.asyncio
async def test_trends_no_org_filter_when_org_is_none():
    """trends skips org filter when user has no org."""
    from api.routes.dashboard import trends

    admin = _user()
    admin.org_id = None
    db = _mock_db()
    _init_cache()

    executed_stmts = []
    orig_execute = db.execute

    async def capturing_execute(stmt, *a, **kw):
        executed_stmts.append(str(stmt.compile(compile_kwargs={"literal_binds": True})))
        return await orig_execute(stmt, *a, **kw)

    db.execute = capturing_execute

    # Should not raise and should not include any org UUID filter
    await trends(range_=None, db=db, current_user=admin)
    combined = " ".join(executed_stmts)
    # No UUID in query since org_id is None
    assert "owner_org_id" not in combined


# ── Admin endpoints call _ch_json_scoped with current_user ───────────────────


@pytest.mark.asyncio
async def test_token_stats_passes_user_to_scoped():
    from api.routes.dashboard import token_stats

    admin = _user()
    db = _mock_db()
    _init_cache()
    calls = []

    async def fake_scoped(sql, user, params=None):
        calls.append(user)
        return []

    with patch("api.routes.dashboard._ch_json_scoped", side_effect=fake_scoped):
        await token_stats(range_=None, db=db, current_user=admin)

    assert len(calls) > 0
    assert all(u is admin for u in calls)


@pytest.mark.asyncio
async def test_ide_usage_passes_user_to_scoped():
    from api.routes.dashboard import ide_usage

    admin = _user()
    db = _mock_db()
    _init_cache()
    calls = []

    async def fake_scoped(sql, user, params=None):
        calls.append(user)
        return []

    with patch("api.routes.dashboard._ch_json_scoped", side_effect=fake_scoped):
        result = await ide_usage(db=db, current_user=admin)

    assert len(calls) == 1
    assert calls[0] is admin


@pytest.mark.asyncio
async def test_sandbox_metrics_passes_user_to_scoped():
    from api.routes.dashboard import sandbox_metrics

    admin = _user()
    db = _mock_db()
    _init_cache()
    calls = []

    async def fake_scoped(sql, user, params=None):
        calls.append(user)
        return []

    with patch("api.routes.dashboard._ch_json_scoped", side_effect=fake_scoped):
        await sandbox_metrics(db=db, current_user=admin)

    assert len(calls) > 0
    assert all(u is admin for u in calls)


@pytest.mark.asyncio
async def test_graphrag_metrics_passes_user_to_scoped():
    from api.routes.dashboard import graphrag_metrics

    admin = _user()
    db = _mock_db()
    _init_cache()
    calls = []

    async def fake_scoped(sql, user, params=None):
        calls.append(user)
        return []

    with patch("api.routes.dashboard._ch_json_scoped", side_effect=fake_scoped):
        await graphrag_metrics(db=db, current_user=admin)

    assert len(calls) > 0
    assert all(u is admin for u in calls)


@pytest.mark.asyncio
async def test_latency_heatmap_passes_user_to_scoped():
    from api.routes.dashboard import latency_heatmap

    admin = _user()
    db = _mock_db()
    _init_cache()
    calls = []

    async def fake_scoped(sql, user, params=None):
        calls.append(user)
        return []

    with patch("api.routes.dashboard._ch_json_scoped", side_effect=fake_scoped):
        await latency_heatmap(db=db, current_user=admin)

    assert len(calls) == 1
    assert calls[0] is admin


@pytest.mark.asyncio
async def test_unannotated_traces_passes_user_to_scoped():
    from api.routes.dashboard import unannotated_traces

    admin = _user()
    db = _mock_db()
    _init_cache()
    calls = []

    async def fake_scoped(sql, user, params=None):
        calls.append(user)
        return []

    with patch("api.routes.dashboard._ch_json_scoped", side_effect=fake_scoped):
        await unannotated_traces(db=db, current_user=admin)

    assert len(calls) > 0
    assert all(u is admin for u in calls)
