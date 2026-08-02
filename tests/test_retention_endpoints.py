# SPDX-FileCopyrightText: 2026 Kaushik Kumar <kaushikrjpm10@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Focused checks for deployment-wide retention administration."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

import api.routes.admin.retention as retention
from models.user import User, UserRole


def _user(role: UserRole) -> MagicMock:
    user = MagicMock(spec=User)
    user.id = "admin"
    user.email = "admin@example.com"
    user.role = role
    return user


def _settings(*, enabled: bool, trace: int = 0, score: int = 0, maximum: int = 0, ttl: int = 90):
    values = {
        "retention.enabled": enabled,
        "retention.trace_days": trace,
        "retention.score_days": score,
        "retention.max_trace_count": maximum,
        "data.retention_days": ttl,
    }
    return AsyncMock(side_effect=lambda key, default=None: values.get(key, default or 0))


@pytest.mark.asyncio
async def test_get_retention_reads_deployment_settings():
    with (
        patch.object(retention.ds, "get_bool", new=AsyncMock(return_value=True)),
        patch.object(retention.ds, "get_int", new=_settings(enabled=True, trace=14, score=30, maximum=5000)),
    ):
        response = await retention.get_retention_config(_user(UserRole.admin))

    assert response.retention_enabled is True
    assert response.data_retention_days == 14
    assert response.score_retention_days == 30
    assert response.max_trace_count == 5000
    assert response.global_retention_days == 90


@pytest.mark.asyncio
async def test_update_retention_writes_deployment_settings():
    db = AsyncMock()
    db.add = MagicMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    db.execute.return_value = result
    body = retention.RetentionConfigUpdate(
        retention_enabled=True,
        data_retention_days=14,
        score_retention_days=30,
        max_trace_count=5000,
    )

    with (
        patch.object(retention.ds, "get_bool", new=AsyncMock(return_value=True)),
        patch.object(retention.ds, "get_int", new=_settings(enabled=True, trace=14, score=30, maximum=5000)),
        patch.object(retention.ds, "invalidate", new=AsyncMock()),
        patch.object(retention.ds, "refresh_sync_cache", new=AsyncMock()),
        patch.object(retention, "emit_security_event", new=AsyncMock()),
    ):
        response = await retention.update_retention_config(body, db, _user(UserRole.super_admin))

    assert response.data_retention_days == 14
    assert db.add.call_count == 4
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_preview_uses_default_project():
    db = AsyncMock()
    db.execute.return_value.scalar.return_value = 0
    ch_response = MagicMock(status_code=200)
    ch_response.json.return_value = {"data": [{"cnt": "42"}]}

    with patch("services.clickhouse._query", new=AsyncMock(return_value=ch_response)) as query:
        result = await retention.preview_retention(14, db, _user(UserRole.super_admin))

    assert result["session_events"] == 42
    assert query.await_args.args[1]["param_pid"] == "default"


@pytest.mark.asyncio
async def test_preview_rejects_short_period():
    with pytest.raises(HTTPException):
        await retention.preview_retention(3, AsyncMock(), _user(UserRole.super_admin))


@pytest.mark.asyncio
async def test_stats_disabled_has_no_telemetry_counts():
    with (
        patch.object(retention.ds, "get_bool", new=AsyncMock(return_value=False)),
        patch.object(retention.ds, "get_int", new=_settings(enabled=False)),
    ):
        result = await retention.get_retention_stats(_user(UserRole.admin))

    assert result["retention_enabled"] is False
    assert result["total_traces"] == 0


@pytest.mark.asyncio
async def test_warnings_are_deployment_wide():
    db = AsyncMock()
    result = MagicMock()
    result.all.return_value = []
    db.execute.return_value = result

    with (
        patch.object(retention.ds, "get_bool", new=AsyncMock(return_value=True)),
        patch.object(retention.ds, "get_int", new=_settings(enabled=True, trace=14)),
    ):
        response = await retention.get_retention_warnings(db, _user(UserRole.admin))

    assert response["warnings"] == []


def test_retention_routes_have_no_legacy_scope_prefix():
    paths = {route.path for route in retention.router.routes}
    assert "/api/v1/admin/retention" in paths
