# SPDX-FileCopyrightText: 2026 Observal contributors
# SPDX-FileCopyrightText: 2026 Srihari <sriharilegend23@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Tests for DuckDB analytics resource tuning and maintenance.

Admin-configured memory limits and thread counts are validated on the API side
and pushed to the DuckDB service as connection pragmas; per-query injection no
longer exists because the service owns its connections.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

# ── Helpers ──────────────────────────────────────────────


def _mock_response(status_code=200, data=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {"data": data or []}
    return resp


def _make_admin():
    from models.user import User, UserRole

    user = MagicMock(spec=User)
    user.id = uuid.uuid4()
    user.email = "admin@test.example"
    user.role = UserRole.super_admin
    return user


def _enterprise_rows(rows: dict[str, str]):
    """Create mock EnterpriseConfig scalar results."""
    items = []
    for key, value in rows.items():
        item = MagicMock()
        item.key = key
        item.value = value
        items.append(item)
    result = MagicMock()
    result.scalars.return_value.all.return_value = items
    return result


# ── apply_resource_settings unit tests ───────────────────


class TestApplyResourceSettings:
    """Unit tests for services.analytics.duckdb.apply_resource_settings."""

    @pytest.fixture(autouse=True)
    def _reset_overrides(self):
        """Clear overrides before/after each test and stub the HTTP push."""
        import services.analytics.duckdb._settings as settings_mod

        settings_mod._resource_overrides.clear()
        with patch("services.analytics.duckdb.schema._client._apply_pragmas", new_callable=AsyncMock) as push:
            self.push = push
            yield
        settings_mod._resource_overrides.clear()

    async def test_memory_limit_is_pushed_in_megabytes(self):
        import services.analytics.duckdb as ch

        applied = await ch.apply_resource_settings(overrides={"resource.max_query_memory_mb": "300"})

        assert applied == {"memory_limit": "300MB"}
        self.push.assert_awaited_once_with({"memory_limit": "300MB"})

    async def test_threads_and_temp_directory_are_pushed(self):
        import services.analytics.duckdb as ch

        applied = await ch.apply_resource_settings(
            overrides={"resource.threads": "8", "resource.temp_directory": "/data/tmp"}
        )

        assert applied == {"threads": "8", "temp_directory": "/data/tmp"}

    async def test_zero_and_negative_values_ignored(self):
        import services.analytics.duckdb as ch

        assert await ch.apply_resource_settings(overrides={"resource.max_query_memory_mb": "0"}) == {}
        assert await ch.apply_resource_settings(overrides={"resource.max_query_memory_mb": "-100"}) == {}
        self.push.assert_not_awaited()

    async def test_non_numeric_value_ignored(self):
        import services.analytics.duckdb as ch

        assert await ch.apply_resource_settings(overrides={"resource.max_query_memory_mb": "not-a-number"}) == {}
        assert await ch.apply_resource_settings(overrides={"resource.threads": "many"}) == {}

    async def test_empty_and_unknown_keys_ignored(self):
        import services.analytics.duckdb as ch

        assert await ch.apply_resource_settings(overrides={"resource.max_query_memory_mb": ""}) == {}
        assert await ch.apply_resource_settings(overrides={"resource.unknown_setting": "100"}) == {}
        assert await ch.apply_resource_settings(overrides={}) == {}

    async def test_swap_replaces_previous(self):
        import services.analytics.duckdb as ch
        import services.analytics.duckdb._settings as settings_mod

        await ch.apply_resource_settings(overrides={"resource.max_query_memory_mb": "400"})
        assert settings_mod._resource_overrides == {"memory_limit": "400MB"}

        await ch.apply_resource_settings(overrides={"resource.max_query_memory_mb": "200"})
        assert settings_mod._resource_overrides == {"memory_limit": "200MB"}
        assert self.push.await_args_list[-1] == call({"memory_limit": "200MB"})

    async def test_swap_removes_dropped_keys(self):
        import services.analytics.duckdb as ch
        import services.analytics.duckdb._settings as settings_mod

        await ch.apply_resource_settings(overrides={"resource.max_query_memory_mb": "400", "resource.threads": "4"})
        assert set(settings_mod._resource_overrides) == {"memory_limit", "threads"}

        await ch.apply_resource_settings(overrides={"resource.max_query_memory_mb": "400"})
        assert set(settings_mod._resource_overrides) == {"memory_limit"}

    async def test_fractional_value_rejected_by_validation(self):
        import services.analytics.duckdb as duckdb_client

        # int("300.5") raises, so the override is dropped rather than truncated.
        assert await duckdb_client.apply_resource_settings(overrides={"resource.max_query_memory_mb": "300.5"}) == {}

    async def test_db_failure_gracefully_handled(self):
        import services.analytics.duckdb as ch

        with patch.dict(
            "sys.modules",
            {"database": MagicMock(async_session=MagicMock(side_effect=Exception("DB down")))},
        ):
            await ch.apply_resource_settings()  # no overrides, triggers DB read

        assert await ch.apply_resource_settings(overrides={}) == {}


# ── pragma push client tests ─────────────────────────────


class TestPragmaPush:
    """The client pushes pragmas to POST /admin/pragmas."""

    async def test_apply_pragmas_posts_to_admin_endpoint(self):
        import services.analytics.duckdb.client as client_mod

        mock_client = AsyncMock()
        mock_client.post.return_value = _mock_response()

        with patch.object(client_mod, "_get_client", return_value=mock_client):
            await client_mod._apply_pragmas({"memory_limit": "300MB"})

        url = mock_client.post.await_args.args[0]
        assert url.endswith("/admin/pragmas")
        assert mock_client.post.await_args.kwargs["json"] == {"pragmas": {"memory_limit": "300MB"}}

    async def test_apply_pragmas_noop_on_empty_dict(self):
        import services.analytics.duckdb.client as client_mod

        mock_client = AsyncMock()
        with patch.object(client_mod, "_get_client", return_value=mock_client):
            await client_mod._apply_pragmas({})

        mock_client.post.assert_not_called()


# ── Admin API endpoint tests ─────────────────────────────


class TestResourceApplyEndpoint:
    """Tests for POST /api/v1/admin/resources/apply."""

    async def test_apply_returns_applied_settings(self):
        from api.deps import get_current_user, get_db
        from main import app

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=_enterprise_rows({"resource.max_query_memory_mb": "300"}))

        app.dependency_overrides[get_db] = lambda: mock_db
        app.dependency_overrides[get_current_user] = _make_admin

        try:
            from httpx import ASGITransport, AsyncClient

            with patch(
                "services.analytics.duckdb.apply_resource_settings",
                AsyncMock(return_value={"memory_limit": "300MB"}),
            ):
                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                    r = await ac.post("/api/v1/admin/resources/apply")

            assert r.status_code == 200
            assert r.json()["applied"] == {"resource.max_query_memory_mb": "300"}
        finally:
            app.dependency_overrides.clear()

    async def test_apply_requires_admin_role(self):
        from api.deps import get_current_user, get_db
        from main import app
        from models.user import User, UserRole

        regular_user = MagicMock(spec=User)
        regular_user.id = uuid.uuid4()
        regular_user.email = "user@test.example"
        regular_user.role = UserRole.user

        mock_db = AsyncMock()
        app.dependency_overrides[get_db] = lambda: mock_db
        app.dependency_overrides[get_current_user] = lambda: regular_user

        try:
            from httpx import ASGITransport, AsyncClient

            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                r = await ac.post("/api/v1/admin/resources/apply")

            assert r.status_code == 403
        finally:
            app.dependency_overrides.clear()


# ── Maintenance cron job tests ───────────────────────────


class TestMaintainAnalytics:
    """Tests for the maintain_analytics worker cron job."""

    async def test_runs_checkpoint_and_reports_tables(self):
        with (
            patch("services.analytics.duckdb.client._checkpoint", new_callable=AsyncMock) as checkpoint,
            patch("services.analytics.duckdb.client._query", new_callable=AsyncMock) as mock_q,
        ):
            mock_q.return_value = _mock_response(data=[{"table_name": "session_events", "rows": 10}])

            from worker import maintain_analytics

            await maintain_analytics({})

        checkpoint.assert_awaited_once()
        assert "duckdb_tables()" in mock_q.await_args.args[0]

    async def test_checkpoint_failure_is_logged_not_raised(self):
        with patch(
            "services.analytics.duckdb.client._checkpoint",
            AsyncMock(side_effect=RuntimeError("checkpoint failed")),
        ):
            from worker import maintain_analytics

            await maintain_analytics({})  # must not raise

    async def test_table_size_failure_is_swallowed(self):
        with (
            patch("services.analytics.duckdb.client._checkpoint", new_callable=AsyncMock),
            patch("services.analytics.duckdb.client._query", AsyncMock(side_effect=RuntimeError("boom"))),
        ):
            from worker import maintain_analytics

            await maintain_analytics({})  # must not raise
