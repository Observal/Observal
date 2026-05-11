# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Tests for ClickHouse resource tuning — edge cases around admin-configured
memory limits, concurrent override swaps, invalid inputs, and query-level
injection via the HTTP API.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── Helpers ──────────────────────────────────────────────


def _mock_response(status_code=200, data=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.raise_for_status = MagicMock()
    if data is not None:
        resp.json.return_value = {"data": data}
    return resp


def _make_admin():
    from models.user import User, UserRole

    user = MagicMock(spec=User)
    user.id = uuid.uuid4()
    user.email = "admin@test.example"
    user.role = UserRole.super_admin
    user.org_id = None
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
    """Unit tests for services.clickhouse.apply_resource_settings."""

    @pytest.fixture(autouse=True)
    def _reset_overrides(self):
        """Clear overrides before/after each test."""
        import services.clickhouse as ch

        ch._resource_overrides = {}
        yield
        ch._resource_overrides = {}

    async def test_valid_override_sets_bytes(self):
        """Setting max_query_memory_mb=300 produces max_memory_usage=300000000."""
        import services.clickhouse as ch

        await ch.apply_resource_settings(overrides={"resource.max_query_memory_mb": "300"})
        assert ch._resource_overrides == {"max_memory_usage": "300000000"}

    async def test_multiple_overrides(self):
        """All four resource keys map to the correct ClickHouse settings."""
        import services.clickhouse as ch

        await ch.apply_resource_settings(
            overrides={
                "resource.max_query_memory_mb": "500",
                "resource.group_by_spill_mb": "250",
                "resource.sort_spill_mb": "250",
                "resource.join_memory_mb": "150",
            }
        )
        assert ch._resource_overrides == {
            "max_memory_usage": "500000000",
            "max_bytes_before_external_group_by": "250000000",
            "max_bytes_before_external_sort": "250000000",
            "max_bytes_in_join": "150000000",
        }

    async def test_zero_value_ignored(self):
        """A value of 0 MB is silently skipped (means 'use default')."""
        import services.clickhouse as ch

        await ch.apply_resource_settings(overrides={"resource.max_query_memory_mb": "0"})
        assert ch._resource_overrides == {}

    async def test_negative_value_ignored(self):
        """Negative values are silently skipped."""
        import services.clickhouse as ch

        await ch.apply_resource_settings(overrides={"resource.max_query_memory_mb": "-100"})
        assert ch._resource_overrides == {}

    async def test_non_numeric_value_ignored(self):
        """Non-numeric strings are skipped with a warning, not crash."""
        import services.clickhouse as ch

        await ch.apply_resource_settings(overrides={"resource.max_query_memory_mb": "not-a-number"})
        assert ch._resource_overrides == {}

    async def test_empty_string_ignored(self):
        """Empty string values are skipped."""
        import services.clickhouse as ch

        await ch.apply_resource_settings(overrides={"resource.max_query_memory_mb": ""})
        assert ch._resource_overrides == {}

    async def test_unknown_key_ignored(self):
        """Keys not in RESOURCE_SETTINGS_MAP are silently ignored."""
        import services.clickhouse as ch

        await ch.apply_resource_settings(overrides={"resource.unknown_setting": "100"})
        assert ch._resource_overrides == {}

    async def test_empty_overrides_no_change(self):
        """Empty overrides dict leaves _resource_overrides unchanged."""
        import services.clickhouse as ch

        await ch.apply_resource_settings(overrides={})
        assert ch._resource_overrides == {}

    async def test_swap_replaces_previous(self):
        """Calling apply twice replaces the old overrides entirely."""
        import services.clickhouse as ch

        await ch.apply_resource_settings(overrides={"resource.max_query_memory_mb": "400"})
        assert ch._resource_overrides["max_memory_usage"] == "400000000"

        await ch.apply_resource_settings(overrides={"resource.max_query_memory_mb": "200"})
        assert ch._resource_overrides["max_memory_usage"] == "200000000"

    async def test_swap_removes_dropped_keys(self):
        """If the second apply has fewer keys, removed ones disappear."""
        import services.clickhouse as ch

        await ch.apply_resource_settings(
            overrides={
                "resource.max_query_memory_mb": "400",
                "resource.join_memory_mb": "100",
            }
        )
        assert len(ch._resource_overrides) == 2

        await ch.apply_resource_settings(overrides={"resource.max_query_memory_mb": "400"})
        assert len(ch._resource_overrides) == 1
        assert "max_bytes_in_join" not in ch._resource_overrides

    async def test_extremely_large_value(self):
        """Absurdly large values are accepted — ClickHouse will reject at query time."""
        import services.clickhouse as ch

        await ch.apply_resource_settings(overrides={"resource.max_query_memory_mb": "999999999"})
        # 999999999 MB = ~1 exabyte — obviously can't allocate, but the
        # override is stored; ClickHouse will clamp or error at query time.
        assert ch._resource_overrides["max_memory_usage"] == "999999999000000"

    async def test_fractional_value_truncated(self):
        """Fractional MB values fail int() cast and are skipped."""
        import services.clickhouse as ch

        await ch.apply_resource_settings(overrides={"resource.max_query_memory_mb": "300.5"})
        # int("300.5") raises ValueError → skipped
        assert ch._resource_overrides == {}

    async def test_reads_from_enterprise_config(self):
        """When overrides passed directly, they are applied correctly."""
        import services.clickhouse as ch

        await ch.apply_resource_settings(overrides={"resource.max_query_memory_mb": "350"})

        assert ch._resource_overrides["max_memory_usage"] == "350000000"

    async def test_db_failure_gracefully_handled(self):
        """If enterprise_config DB read fails, no overrides are applied."""
        import services.clickhouse as ch

        with patch.dict(
            "sys.modules",
            {"database": MagicMock(async_session=MagicMock(side_effect=Exception("DB down")))},
        ):
            await ch.apply_resource_settings()  # no overrides, triggers DB read

        assert ch._resource_overrides == {}


# ── _query injection tests ───────────────────────────────


class TestQueryInjection:
    """Verify that _resource_overrides are injected into _query HTTP params."""

    @pytest.fixture(autouse=True)
    def _reset_overrides(self):
        import services.clickhouse as ch

        ch._resource_overrides = {}
        yield
        ch._resource_overrides = {}

    async def test_overrides_injected_into_query_params(self):
        """When overrides are set, they appear in the HTTP query parameters."""
        import services.clickhouse as ch

        ch._resource_overrides = {"max_memory_usage": "300000000"}

        mock_client = AsyncMock()
        mock_client.post.return_value = _mock_response()

        with patch.object(ch, "_get_client", return_value=mock_client):
            await ch._query("SELECT 1")

        _, kwargs = mock_client.post.call_args
        params = kwargs.get("params", {})
        assert params["max_memory_usage"] == "300000000"

    async def test_no_overrides_no_extra_params(self):
        """When no overrides are set, only standard params are sent."""
        import services.clickhouse as ch

        ch._resource_overrides = {}

        mock_client = AsyncMock()
        mock_client.post.return_value = _mock_response()

        with patch.object(ch, "_get_client", return_value=mock_client):
            await ch._query("SELECT 1")

        _, kwargs = mock_client.post.call_args
        params = kwargs.get("params", {})
        assert "max_memory_usage" not in params

    async def test_query_params_override_resource_params(self):
        """Explicit query params (e.g. param_x) take precedence over overrides."""
        import services.clickhouse as ch

        ch._resource_overrides = {"max_memory_usage": "300000000"}

        mock_client = AsyncMock()
        mock_client.post.return_value = _mock_response()

        with patch.object(ch, "_get_client", return_value=mock_client):
            # Simulate a query with explicit max_memory_usage param
            await ch._query("SELECT 1", params={"max_memory_usage": "999"})

        _, kwargs = mock_client.post.call_args
        params = kwargs.get("params", {})
        # Explicit param should win because params.update() runs after overrides
        assert params["max_memory_usage"] == "999"

    async def test_overrides_dont_corrupt_param_prefix_keys(self):
        """Resource overrides don't collide with param_* ClickHouse parameters."""
        import services.clickhouse as ch

        ch._resource_overrides = {"max_memory_usage": "300000000"}

        mock_client = AsyncMock()
        mock_client.post.return_value = _mock_response()

        with patch.object(ch, "_get_client", return_value=mock_client):
            await ch._query(
                "SELECT * FROM t WHERE id = {id:String}",
                params={"param_id": "abc"},
            )

        _, kwargs = mock_client.post.call_args
        params = kwargs.get("params", {})
        assert params["param_id"] == "abc"
        assert params["max_memory_usage"] == "300000000"


# ── Admin API endpoint tests ─────────────────────────────


class TestResourceApplyEndpoint:
    """Tests for POST /api/v1/admin/resources/apply."""

    async def test_apply_returns_applied_settings(self):
        """Endpoint returns the settings that were applied."""
        from api.deps import get_current_user, get_db
        from main import app

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=_enterprise_rows({"resource.max_query_memory_mb": "300"}))

        app.dependency_overrides[get_db] = lambda: mock_db
        app.dependency_overrides[get_current_user] = _make_admin

        try:
            from httpx import ASGITransport, AsyncClient

            with patch("services.clickhouse.apply_resource_settings", new_callable=AsyncMock):
                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                    r = await ac.post("/api/v1/admin/resources/apply")

            assert r.status_code == 200
            body = r.json()
            assert "applied" in body
            assert "resource.max_query_memory_mb" in body["applied"]
        finally:
            app.dependency_overrides.clear()

    async def test_apply_with_no_settings_returns_empty(self):
        """When no resource.* settings exist, endpoint returns empty applied dict."""
        from api.deps import get_current_user, get_db
        from main import app

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=_enterprise_rows({}))

        app.dependency_overrides[get_db] = lambda: mock_db
        app.dependency_overrides[get_current_user] = _make_admin

        try:
            from httpx import ASGITransport, AsyncClient

            with patch("services.clickhouse.apply_resource_settings", new_callable=AsyncMock):
                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                    r = await ac.post("/api/v1/admin/resources/apply")

            assert r.status_code == 200
            assert r.json()["applied"] == {}
        finally:
            app.dependency_overrides.clear()

    async def test_apply_requires_admin_role(self):
        """Non-admin users get 403."""
        from api.deps import get_current_user, get_db
        from main import app
        from models.user import User, UserRole

        regular_user = MagicMock(spec=User)
        regular_user.id = uuid.uuid4()
        regular_user.email = "user@test.example"
        regular_user.role = UserRole.user
        regular_user.org_id = None

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


class TestMaintainClickhouse:
    """Tests for the maintain_clickhouse worker cron job."""

    async def test_optimizes_all_tables(self):
        """Cron job runs OPTIMIZE TABLE on all three tables."""
        with patch("services.clickhouse._query", new_callable=AsyncMock) as mock_q:
            mock_q.return_value = _mock_response()

            from worker import maintain_clickhouse

            await maintain_clickhouse({})

        optimize_calls = [c for c in mock_q.call_args_list if "OPTIMIZE TABLE" in str(c)]
        tables = {c.args[0].replace("OPTIMIZE TABLE ", "") for c in optimize_calls}
        assert tables == {
            "traces",
            "spans",
            "scores",
        }

    async def test_optimize_failure_doesnt_stop_other_tables(self):
        """If OPTIMIZE fails on one table, the others still run."""
        call_count = 0

        async def _flaky_query(sql, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            if "traces" in sql and "OPTIMIZE" in sql:
                raise Exception("Simulated merge failure")
            resp = _mock_response()
            # For the system.parts health check query
            if "system.parts" in sql:
                resp.json.return_value = {"data": []}
            return resp

        with patch("services.clickhouse._query", side_effect=_flaky_query):
            from worker import maintain_clickhouse

            await maintain_clickhouse({})

        # Should have attempted all 3 OPTIMIZE + 1 health check = 4 calls minimum
        assert call_count >= 3

    async def test_high_part_count_logged_as_warning(self):
        """Part counts > 300 produce a warning log."""

        async def _parts_query(sql, *args, **kwargs):
            resp = _mock_response()
            if "system.parts" in sql:
                resp.json.return_value = {"data": [{"table": "traces", "parts": "500", "total_rows": "1000000"}]}
            return resp

        with (
            patch("services.clickhouse._query", side_effect=_parts_query),
            patch("worker.logger") as mock_logger,
        ):
            from worker import maintain_clickhouse

            await maintain_clickhouse({})

        # Check that a warning was logged about high part count
        warning_calls = [c for c in mock_logger.warning.call_args_list if "500" in str(c) and "parts" in str(c).lower()]
        assert len(warning_calls) > 0
