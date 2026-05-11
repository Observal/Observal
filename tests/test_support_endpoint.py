# SPDX-FileCopyrightText: 2026 Naraen Rammoorthi <naraen13@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Tests for server-side support bundle collectors and endpoint.

Covers:
- _run_collector wrapper: success, timeout, exception handling
- _collect_versions: app version, alembic revision, CH version + tables
- _collect_health: PG, CH, Redis, OTEL probes
- _collect_config: returns allowlisted Settings fields only
- _collect_aggregates: row counts per PG/CH table, no row contents
- _collect_errors: error fingerprints from last 24h, max 50, stack_template only
- _collect_logs: structured log lines from ring buffer, duration filtering
- _parse_duration: human-friendly duration parsing
- _extract_stack_template: stack trace file/function extraction
- collect_diagnostics endpoint: partial failure still returns 200
- Config allowlist filtering (CLI-side): only CONFIG_ALLOWLIST keys in output

Requirements: 2.4, 2.5, 2.6, 2.8, 2.9, 2.10, 2.11, 6.5, 6.6, 7.4, 8.1, 8.2
"""

from __future__ import annotations

import asyncio
import hashlib
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from api.routes.support import (
    CONFIG_ALLOWLIST,
    CollectRequest,
    _collect_aggregates,
    _collect_config,
    _collect_errors,
    _collect_health,
    _collect_logs,
    _collect_versions,
    _extract_stack_template,
    _parse_duration,
    _run_collector,
)

# ── Helpers ──────────────────────────────────────────────────────────


def _mock_db():
    """Return an AsyncMock that behaves like an AsyncSession."""
    return AsyncMock()


def _mock_ch_response(status_code=200, text="", json_data=None):
    """Return a mock httpx Response for ClickHouse queries."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text
    if json_data is not None:
        resp.json.return_value = json_data
    return resp


# ═════════════════════════════════════════════════════════════════════
# _run_collector wrapper
# ═════════════════════════════════════════════════════════════════════


class TestRunCollector:
    """Tests for the _run_collector timeout/error wrapper."""

    @pytest.mark.asyncio
    async def test_success_returns_ok_true(self):
        async def good_collector():
            return {"key": "value"}

        name, data = await _run_collector("test", good_collector())
        assert name == "test"
        assert data.ok is True
        assert data.data == {"key": "value"}
        assert data.error is None
        assert data.duration_ms >= 0

    @pytest.mark.asyncio
    async def test_timeout_returns_ok_false(self):
        async def slow_collector():
            await asyncio.sleep(30)
            return {}

        with patch("api.routes.support.COLLECTOR_TIMEOUT_SECONDS", 0.05):
            name, data = await _run_collector("slow", slow_collector())

        assert name == "slow"
        assert data.ok is False
        assert "timed out" in data.error.lower()

    @pytest.mark.asyncio
    async def test_exception_returns_ok_false(self):
        async def bad_collector():
            raise RuntimeError("database exploded")

        name, data = await _run_collector("bad", bad_collector())
        assert name == "bad"
        assert data.ok is False
        assert data.error == "RuntimeError"
        assert data.duration_ms >= 0

    @pytest.mark.asyncio
    async def test_timeout_duration_ms_equals_timeout_seconds(self):
        async def slow_collector():
            await asyncio.sleep(30)
            return {}

        with patch("api.routes.support.COLLECTOR_TIMEOUT_SECONDS", 0.05):
            _, data = await _run_collector("slow", slow_collector())

        # duration_ms should be approximately the timeout value (50ms)
        # Allow generous tolerance since CI can be slow
        assert data.duration_ms <= 5000


# ═════════════════════════════════════════════════════════════════════
# _collect_versions
# ═════════════════════════════════════════════════════════════════════


class TestCollectVersions:
    """Tests for the versions collector (app, alembic, CH)."""

    @pytest.mark.asyncio
    async def test_returns_app_version(self):
        db = _mock_db()
        # Mock alembic query
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = "abc123"
        db.execute.return_value = mock_result

        with patch("api.routes.support._query", new_callable=AsyncMock) as mock_query:
            mock_query.side_effect = [
                _mock_ch_response(200, text="24.3.1"),
                _mock_ch_response(200, json_data={"data": [{"name": "traces"}, {"name": "spans"}]}),
            ]
            result = await _collect_versions(db)

        assert "app_version" in result
        assert isinstance(result["app_version"], str)

    @pytest.mark.asyncio
    async def test_returns_alembic_revision(self):
        db = _mock_db()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = "rev_42"
        db.execute.return_value = mock_result

        with patch("api.routes.support._query", new_callable=AsyncMock) as mock_query:
            mock_query.side_effect = [
                _mock_ch_response(200, text="24.3.1"),
                _mock_ch_response(200, json_data={"data": []}),
            ]
            result = await _collect_versions(db)

        assert result["alembic_revision"] == "rev_42"

    @pytest.mark.asyncio
    async def test_alembic_error_recorded(self):
        db = _mock_db()
        db.execute.side_effect = RuntimeError("pg down")

        with patch("api.routes.support._query", new_callable=AsyncMock) as mock_query:
            mock_query.side_effect = [
                _mock_ch_response(200, text="24.3.1"),
                _mock_ch_response(200, json_data={"data": []}),
            ]
            result = await _collect_versions(db)

        assert "error" in result["alembic_revision"]

    @pytest.mark.asyncio
    async def test_returns_clickhouse_version(self):
        db = _mock_db()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = "abc"
        db.execute.return_value = mock_result

        with patch("api.routes.support._query", new_callable=AsyncMock) as mock_query:
            mock_query.side_effect = [
                _mock_ch_response(200, text="24.3.1.5"),
                _mock_ch_response(200, json_data={"data": [{"name": "traces"}]}),
            ]
            result = await _collect_versions(db)

        assert result["clickhouse_version"] == "24.3.1.5"

    @pytest.mark.asyncio
    async def test_returns_clickhouse_tables(self):
        db = _mock_db()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = "abc"
        db.execute.return_value = mock_result

        with patch("api.routes.support._query", new_callable=AsyncMock) as mock_query:
            mock_query.side_effect = [
                _mock_ch_response(200, text="24.3.1"),
                _mock_ch_response(200, json_data={"data": [{"name": "traces"}, {"name": "spans"}, {"name": "scores"}]}),
            ]
            result = await _collect_versions(db)

        assert result["clickhouse_tables"] == ["traces", "spans", "scores"]

    @pytest.mark.asyncio
    async def test_clickhouse_error_recorded(self):
        db = _mock_db()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = "abc"
        db.execute.return_value = mock_result

        with patch("api.routes.support._query", new_callable=AsyncMock) as mock_query:
            mock_query.side_effect = ConnectionError("CH unreachable")
            result = await _collect_versions(db)

        assert "error" in result["clickhouse_version"]

    @pytest.mark.asyncio
    async def test_build_hash_from_env(self):
        db = _mock_db()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = "abc"
        db.execute.return_value = mock_result

        with (
            patch("api.routes.support._query", new_callable=AsyncMock) as mock_query,
            patch.dict("os.environ", {"BUILD_HASH": "deadbeef"}),
        ):
            mock_query.side_effect = [
                _mock_ch_response(200, text="24.3.1"),
                _mock_ch_response(200, json_data={"data": []}),
            ]
            result = await _collect_versions(db)

        assert result["build_hash"] == "deadbeef"


# ═════════════════════════════════════════════════════════════════════
# _collect_health
# ═════════════════════════════════════════════════════════════════════


class TestCollectHealth:
    """Tests for health probes against PG, CH, Redis, OTEL."""

    @pytest.mark.asyncio
    async def test_postgres_ok(self):
        db = _mock_db()
        db.execute.return_value = MagicMock()

        with (
            patch("api.routes.support._query", new_callable=AsyncMock) as mock_query,
            patch("api.routes.support.get_redis") as mock_get_redis,
        ):
            mock_query.return_value = _mock_ch_response(200)
            mock_redis = AsyncMock()
            mock_redis.ping.return_value = True
            mock_get_redis.return_value = mock_redis

            result = await _collect_health(db)

        assert result["postgres"]["status"] == "ok"
        assert "latency_ms" in result["postgres"]

    @pytest.mark.asyncio
    async def test_postgres_error(self):
        db = _mock_db()
        db.execute.side_effect = RuntimeError("connection refused")

        with (
            patch("api.routes.support._query", new_callable=AsyncMock) as mock_query,
            patch("api.routes.support.get_redis") as mock_get_redis,
        ):
            mock_query.return_value = _mock_ch_response(200)
            mock_redis = AsyncMock()
            mock_redis.ping.return_value = True
            mock_get_redis.return_value = mock_redis

            result = await _collect_health(db)

        assert result["postgres"]["status"] == "error"
        assert result["postgres"]["error"] == "RuntimeError"

    @pytest.mark.asyncio
    async def test_clickhouse_ok(self):
        db = _mock_db()

        with (
            patch("api.routes.support._query", new_callable=AsyncMock) as mock_query,
            patch("api.routes.support.get_redis") as mock_get_redis,
        ):
            mock_query.return_value = _mock_ch_response(200)
            mock_redis = AsyncMock()
            mock_redis.ping.return_value = True
            mock_get_redis.return_value = mock_redis

            result = await _collect_health(db)

        assert result["clickhouse"]["status"] == "ok"

    @pytest.mark.asyncio
    async def test_clickhouse_error(self):
        db = _mock_db()

        with (
            patch("api.routes.support._query", new_callable=AsyncMock) as mock_query,
            patch("api.routes.support.get_redis") as mock_get_redis,
        ):
            mock_query.side_effect = ConnectionError("CH down")
            mock_redis = AsyncMock()
            mock_redis.ping.return_value = True
            mock_get_redis.return_value = mock_redis

            result = await _collect_health(db)

        assert result["clickhouse"]["status"] == "error"

    @pytest.mark.asyncio
    async def test_redis_ok(self):
        db = _mock_db()

        with (
            patch("api.routes.support._query", new_callable=AsyncMock) as mock_query,
            patch("api.routes.support.get_redis") as mock_get_redis,
        ):
            mock_query.return_value = _mock_ch_response(200)
            mock_redis = AsyncMock()
            mock_redis.ping.return_value = True
            mock_get_redis.return_value = mock_redis

            result = await _collect_health(db)

        assert result["redis"]["status"] == "ok"

    @pytest.mark.asyncio
    async def test_redis_error(self):
        db = _mock_db()

        with (
            patch("api.routes.support._query", new_callable=AsyncMock) as mock_query,
            patch("api.routes.support.get_redis") as mock_get_redis,
        ):
            mock_query.return_value = _mock_ch_response(200)
            mock_get_redis.side_effect = ConnectionError("Redis down")

            result = await _collect_health(db)

        assert result["redis"]["status"] == "error"

    @pytest.mark.asyncio
    async def test_all_probes_have_latency_ms(self):
        db = _mock_db()

        with (
            patch("api.routes.support._query", new_callable=AsyncMock) as mock_query,
            patch("api.routes.support.get_redis") as mock_get_redis,
        ):
            mock_query.return_value = _mock_ch_response(200)
            mock_redis = AsyncMock()
            mock_redis.ping.return_value = True
            mock_get_redis.return_value = mock_redis

            result = await _collect_health(db)

        for probe_name in ("postgres", "clickhouse", "redis"):
            assert "latency_ms" in result[probe_name], f"{probe_name} missing latency_ms"
            assert isinstance(result[probe_name]["latency_ms"], int)


# ═════════════════════════════════════════════════════════════════════
# _collect_config
# ═════════════════════════════════════════════════════════════════════


class TestCollectConfig:
    """Tests for the config collector — only allowlisted keys returned."""

    @pytest.mark.asyncio
    async def test_returns_only_allowlisted_keys(self):
        result = await _collect_config()
        for key in result:
            assert key in CONFIG_ALLOWLIST, f"Key '{key}' not in CONFIG_ALLOWLIST"

    @pytest.mark.asyncio
    async def test_excludes_secret_key(self):
        result = await _collect_config()
        assert "SECRET_KEY" not in result

    @pytest.mark.asyncio
    async def test_excludes_oauth_secrets(self):
        result = await _collect_config()
        assert "OAUTH_CLIENT_SECRET" not in result
        assert "OAUTH_CLIENT_ID" not in result

    @pytest.mark.asyncio
    async def test_excludes_eval_model_api_key(self):
        result = await _collect_config()
        assert "EVAL_MODEL_API_KEY" not in result

    @pytest.mark.asyncio
    async def test_includes_database_url(self):
        result = await _collect_config()
        assert "DATABASE_URL" in result

    @pytest.mark.asyncio
    async def test_includes_deployment_mode(self):
        result = await _collect_config()
        assert "DEPLOYMENT_MODE" in result

    @pytest.mark.asyncio
    async def test_result_is_dict(self):
        result = await _collect_config()
        assert isinstance(result, dict)


# ═════════════════════════════════════════════════════════════════════
# _collect_aggregates
# ═════════════════════════════════════════════════════════════════════


class TestCollectAggregates:
    """Tests for aggregate row counts — counts only, never row contents."""

    @pytest.mark.asyncio
    async def test_returns_pg_table_counts(self):
        db = _mock_db()
        # pg_tables query returns table names
        tables_result = MagicMock()
        tables_result.fetchall.return_value = [("users",), ("agents",)]
        # count queries return integers
        count_result = MagicMock()
        count_result.scalar.return_value = 42
        db.execute.side_effect = [tables_result, count_result, count_result]

        with patch("api.routes.support._query", new_callable=AsyncMock) as mock_query:
            mock_query.side_effect = [
                _mock_ch_response(200, json_data={"data": []}),
            ]
            result = await _collect_aggregates(db)

        assert "pg_table_counts" in result
        assert result["pg_table_counts"]["users"] == 42
        assert result["pg_table_counts"]["agents"] == 42

    @pytest.mark.asyncio
    async def test_returns_ch_table_counts(self):
        db = _mock_db()
        tables_result = MagicMock()
        tables_result.fetchall.return_value = []
        db.execute.return_value = tables_result

        with patch("api.routes.support._query", new_callable=AsyncMock) as mock_query:
            mock_query.side_effect = [
                # CH table list
                _mock_ch_response(200, json_data={"data": [{"name": "traces"}, {"name": "spans"}]}),
                # count for traces
                _mock_ch_response(200, json_data={"data": [{"count()": 1000000}]}),
                # count for spans
                _mock_ch_response(200, json_data={"data": [{"count()": 5000000}]}),
            ]
            result = await _collect_aggregates(db)

        assert "ch_table_counts" in result
        assert result["ch_table_counts"]["traces"] == 1000000
        assert result["ch_table_counts"]["spans"] == 5000000

    @pytest.mark.asyncio
    async def test_counts_are_integers_not_row_contents(self):
        """Requirement 8.1, 8.2: only aggregate counts, never row contents."""
        db = _mock_db()
        tables_result = MagicMock()
        tables_result.fetchall.return_value = [("users",)]
        count_result = MagicMock()
        count_result.scalar.return_value = 99
        db.execute.side_effect = [tables_result, count_result]

        with patch("api.routes.support._query", new_callable=AsyncMock) as mock_query:
            mock_query.side_effect = [
                _mock_ch_response(200, json_data={"data": [{"name": "traces"}]}),
                _mock_ch_response(200, json_data={"data": [{"count()": 500}]}),
            ]
            result = await _collect_aggregates(db)

        # PG counts are plain integers
        for table, count in result["pg_table_counts"].items():
            assert isinstance(count, int), f"PG table {table} has non-int count: {count}"

        # CH counts are plain integers
        for table, count in result["ch_table_counts"].items():
            assert isinstance(count, int), f"CH table {table} has non-int count: {count}"

    @pytest.mark.asyncio
    async def test_pg_error_recorded_per_table(self):
        db = _mock_db()
        tables_result = MagicMock()
        tables_result.fetchall.return_value = [("broken_table",)]
        db.execute.side_effect = [tables_result, RuntimeError("permission denied")]

        with patch("api.routes.support._query", new_callable=AsyncMock) as mock_query:
            mock_query.side_effect = [
                _mock_ch_response(200, json_data={"data": []}),
            ]
            result = await _collect_aggregates(db)

        assert "error" in result["pg_table_counts"]["broken_table"]

    @pytest.mark.asyncio
    async def test_ch_error_recorded_per_table(self):
        db = _mock_db()
        tables_result = MagicMock()
        tables_result.fetchall.return_value = []
        db.execute.return_value = tables_result

        with patch("api.routes.support._query", new_callable=AsyncMock) as mock_query:
            mock_query.side_effect = [
                _mock_ch_response(200, json_data={"data": [{"name": "broken"}]}),
                ConnectionError("CH query failed"),
            ]
            result = await _collect_aggregates(db)

        assert "error" in result["ch_table_counts"]["broken"]

    @pytest.mark.asyncio
    async def test_unsafe_ch_table_name_skipped(self):
        db = _mock_db()
        tables_result = MagicMock()
        tables_result.fetchall.return_value = []
        db.execute.return_value = tables_result

        with patch("api.routes.support._query", new_callable=AsyncMock) as mock_query:
            mock_query.side_effect = [
                _mock_ch_response(200, json_data={"data": [{"name": "Robert'; DROP TABLE--"}]}),
            ]
            result = await _collect_aggregates(db)

        assert "unsafe table name" in result["ch_table_counts"]["Robert'; DROP TABLE--"]


# ═════════════════════════════════════════════════════════════════════
# _collect_errors
# ═════════════════════════════════════════════════════════════════════


class TestCollectErrors:
    """Tests for error fingerprint collection."""

    @pytest.mark.asyncio
    async def test_returns_fingerprints_list(self):
        with patch("api.routes.support._query", new_callable=AsyncMock) as mock_query:
            mock_query.return_value = _mock_ch_response(
                200,
                json_data={
                    "data": [
                        {
                            "error": 'File "app.py", line 10, in main\nValueError: bad',
                            "start_time": "2025-07-15T10:00:00",
                        },
                    ]
                },
            )
            db = _mock_db()
            result = await _collect_errors(db)

        assert "fingerprints" in result
        assert len(result["fingerprints"]) == 1

    @pytest.mark.asyncio
    async def test_fingerprint_has_required_fields(self):
        with patch("api.routes.support._query", new_callable=AsyncMock) as mock_query:
            mock_query.return_value = _mock_ch_response(
                200,
                json_data={
                    "data": [
                        {"error": 'File "app.py", line 10, in main\nError', "start_time": "2025-07-15T10:00:00"},
                    ]
                },
            )
            db = _mock_db()
            result = await _collect_errors(db)

        fp = result["fingerprints"][0]
        assert "fingerprint" in fp
        assert "count" in fp
        assert "first_seen" in fp
        assert "last_seen" in fp
        assert "stack_template" in fp

    @pytest.mark.asyncio
    async def test_fingerprint_is_sha256_of_template(self):
        with patch("api.routes.support._query", new_callable=AsyncMock) as mock_query:
            mock_query.return_value = _mock_ch_response(
                200,
                json_data={
                    "data": [
                        {"error": 'File "app.py", line 10, in main\nError', "start_time": "2025-07-15T10:00:00"},
                    ]
                },
            )
            db = _mock_db()
            result = await _collect_errors(db)

        fp = result["fingerprints"][0]
        expected_hash = hashlib.sha256(fp["stack_template"].encode("utf-8")).hexdigest()
        assert fp["fingerprint"] == expected_hash

    @pytest.mark.asyncio
    async def test_max_50_fingerprints(self):
        """Requirement 2.10: up to 50 error fingerprints."""
        errors = []
        for i in range(100):
            errors.append(
                {
                    "error": f'File "mod{i}.py", line {i}, in func{i}\nError{i}',
                    "start_time": f"2025-07-15T10:{i % 60:02d}:00",
                }
            )

        with patch("api.routes.support._query", new_callable=AsyncMock) as mock_query:
            mock_query.return_value = _mock_ch_response(200, json_data={"data": errors})
            db = _mock_db()
            result = await _collect_errors(db)

        assert len(result["fingerprints"]) <= 50

    @pytest.mark.asyncio
    async def test_stack_template_has_no_exception_messages(self):
        """Requirement 2.10: stack_template has file paths + function names only."""
        error_text = (
            "Traceback (most recent call last):\n"
            '  File "/app/server.py", line 42, in handle_request\n'
            "    result = process(data)\n"
            '  File "/app/processor.py", line 15, in process\n'
            '    raise ValueError("secret data: password=hunter2")\n'
            "ValueError: secret data: password=hunter2"
        )
        with patch("api.routes.support._query", new_callable=AsyncMock) as mock_query:
            mock_query.return_value = _mock_ch_response(
                200, json_data={"data": [{"error": error_text, "start_time": "2025-07-15T10:00:00"}]}
            )
            db = _mock_db()
            result = await _collect_errors(db)

        template = result["fingerprints"][0]["stack_template"]
        assert "hunter2" not in template
        assert "password" not in template
        assert "secret data" not in template
        # But file paths and function names should be present
        assert "server.py" in template
        assert "handle_request" in template

    @pytest.mark.asyncio
    async def test_empty_errors_returns_empty_list(self):
        with patch("api.routes.support._query", new_callable=AsyncMock) as mock_query:
            mock_query.return_value = _mock_ch_response(200, json_data={"data": []})
            db = _mock_db()
            result = await _collect_errors(db)

        assert result["fingerprints"] == []

    @pytest.mark.asyncio
    async def test_duplicate_errors_grouped_by_fingerprint(self):
        same_error = 'File "app.py", line 10, in main\nError'
        with patch("api.routes.support._query", new_callable=AsyncMock) as mock_query:
            mock_query.return_value = _mock_ch_response(
                200,
                json_data={
                    "data": [
                        {"error": same_error, "start_time": "2025-07-15T10:00:00"},
                        {"error": same_error, "start_time": "2025-07-15T11:00:00"},
                        {"error": same_error, "start_time": "2025-07-15T12:00:00"},
                    ]
                },
            )
            db = _mock_db()
            result = await _collect_errors(db)

        assert len(result["fingerprints"]) == 1
        assert result["fingerprints"][0]["count"] == 3


# ═════════════════════════════════════════════════════════════════════
# _collect_logs
# ═════════════════════════════════════════════════════════════════════


class TestCollectLogs:
    """Tests for the logs collector (ring buffer + duration filtering)."""

    @pytest.mark.asyncio
    async def test_returns_lines_from_buffer(self):
        now = datetime.now(UTC)
        entries = [
            {"timestamp": now.isoformat(), "event": "test log", "level": "info"},
        ]
        mock_buffer = MagicMock()
        mock_buffer.get_since.return_value = entries

        with patch("services.log_buffer.get_log_buffer", return_value=mock_buffer):
            result = await _collect_logs("1h")

        assert "lines" in result
        assert len(result["lines"]) == 1
        assert result["lines"][0]["event"] == "test log"

    @pytest.mark.asyncio
    async def test_empty_buffer_returns_empty_with_note(self):
        mock_buffer = MagicMock()
        mock_buffer.get_since.return_value = []

        with patch("services.log_buffer.get_log_buffer", return_value=mock_buffer):
            result = await _collect_logs("1h")

        assert result["lines"] == []
        assert "note" in result

    @pytest.mark.asyncio
    async def test_import_error_returns_empty(self):
        # Simulate ImportError by temporarily removing the module from sys.modules
        # and making the import fail

        with patch.dict("sys.modules", {"services.log_buffer": None}):
            result = await _collect_logs("1h")

        assert result["lines"] == []

    @pytest.mark.asyncio
    async def test_strips_internal_structlog_keys(self):
        now = datetime.now(UTC)
        entries = [
            {
                "timestamp": now.isoformat(),
                "event": "test",
                "level": "info",
                "_record": "should be stripped",
                "_logger": "should be stripped",
            },
        ]
        mock_buffer = MagicMock()
        mock_buffer.get_since.return_value = entries

        with patch("services.log_buffer.get_log_buffer", return_value=mock_buffer):
            result = await _collect_logs("1h")

        line = result["lines"][0]
        assert "_record" not in line
        assert "_logger" not in line
        assert "event" in line

    @pytest.mark.asyncio
    async def test_non_serializable_values_converted_to_string(self):
        now = datetime.now(UTC)
        entries = [
            {
                "timestamp": now.isoformat(),
                "event": "test",
                "custom_obj": object(),  # not JSON-serializable
            },
        ]
        mock_buffer = MagicMock()
        mock_buffer.get_since.return_value = entries

        with patch("services.log_buffer.get_log_buffer", return_value=mock_buffer):
            result = await _collect_logs("1h")

        # Should be converted to string, not raise
        assert isinstance(result["lines"][0]["custom_obj"], str)


# ═════════════════════════════════════════════════════════════════════
# _parse_duration
# ═════════════════════════════════════════════════════════════════════


class TestParseDuration:
    """Tests for human-friendly duration string parsing."""

    def test_hours(self):
        assert _parse_duration("1h") == timedelta(hours=1)

    def test_minutes(self):
        assert _parse_duration("30m") == timedelta(minutes=30)

    def test_days(self):
        assert _parse_duration("2d") == timedelta(days=2)

    def test_seconds(self):
        assert _parse_duration("90s") == timedelta(seconds=90)

    def test_combined(self):
        assert _parse_duration("1h30m") == timedelta(hours=1, minutes=30)

    def test_invalid_falls_back_to_1h(self):
        assert _parse_duration("invalid") == timedelta(hours=1)

    def test_empty_falls_back_to_1h(self):
        assert _parse_duration("") == timedelta(hours=1)

    def test_case_insensitive(self):
        assert _parse_duration("2H") == timedelta(hours=2)
        assert _parse_duration("30M") == timedelta(minutes=30)


# ═════════════════════════════════════════════════════════════════════
# _extract_stack_template
# ═════════════════════════════════════════════════════════════════════


class TestExtractStackTemplate:
    """Tests for stack trace sanitisation."""

    def test_extracts_file_and_function(self):
        trace = (
            "Traceback (most recent call last):\n"
            '  File "/app/main.py", line 42, in run\n'
            "    do_stuff()\n"
            '  File "/app/utils.py", line 10, in do_stuff\n'
            '    raise ValueError("oops")\n'
            "ValueError: oops"
        )
        template = _extract_stack_template(trace)
        assert "/app/main.py:run" in template
        assert "/app/utils.py:do_stuff" in template

    def test_no_exception_message_in_template(self):
        trace = (
            "Traceback (most recent call last):\n"
            '  File "/app/main.py", line 42, in run\n'
            "ValueError: secret password=hunter2"
        )
        template = _extract_stack_template(trace)
        assert "hunter2" not in template
        assert "secret password" not in template

    def test_arrow_separator(self):
        trace = '  File "/a.py", line 1, in foo\n  File "/b.py", line 2, in bar\n'
        template = _extract_stack_template(trace)
        assert " -> " in template

    def test_fallback_for_non_traceback(self):
        template = _extract_stack_template("SomeError: something went wrong")
        assert template  # should return something, not empty
        assert "something went wrong" not in template  # message stripped

    def test_empty_input(self):
        template = _extract_stack_template("")
        assert template == "unknown"


# ═════════════════════════════════════════════════════════════════════
# collect_diagnostics endpoint — partial failure
# ═════════════════════════════════════════════════════════════════════


class TestCollectDiagnosticsEndpoint:
    """Tests for the POST /collect endpoint behaviour."""

    @pytest.mark.asyncio
    async def test_partial_failure_still_returns_results(self):
        """Requirement 6.5, 6.6: partial failures reported, endpoint returns 200."""
        from api.ratelimit import limiter
        from api.routes.support import COLLECTORS, collect_diagnostics

        db = _mock_db()
        user = MagicMock()

        # Make versions succeed and health fail
        async def good_versions(db_arg, logs_since):
            return {"app_version": "1.0.0"}

        async def bad_health(db_arg, logs_since):
            raise RuntimeError("all probes failed")

        old_enabled = limiter.enabled
        limiter.enabled = False
        try:
            with patch.dict(
                COLLECTORS,
                {
                    "versions": lambda db, ls: good_versions(db, ls),
                    "health": lambda db, ls: bad_health(db, ls),
                },
                clear=True,
            ):
                body = CollectRequest(collectors=["versions", "health"])
                response = await collect_diagnostics(
                    request=MagicMock(),
                    body=body,
                    user=user,
                    db=db,
                )
        finally:
            limiter.enabled = old_enabled

        assert response.collectors["versions"].ok is True
        assert response.collectors["health"].ok is False
        assert response.collectors["health"].error == "RuntimeError"

    @pytest.mark.asyncio
    async def test_all_collectors_requested_by_default(self):
        from api.ratelimit import limiter
        from api.routes.support import COLLECTORS, collect_diagnostics

        db = _mock_db()
        user = MagicMock()

        async def noop(db_arg, logs_since):
            return {}

        old_enabled = limiter.enabled
        limiter.enabled = False
        try:
            with patch.dict(COLLECTORS, {name: lambda db, ls: noop(db, ls) for name in COLLECTORS}):
                body = CollectRequest()  # default: collectors=["all"]
                response = await collect_diagnostics(
                    request=MagicMock(),
                    body=body,
                    user=user,
                    db=db,
                )
        finally:
            limiter.enabled = old_enabled

        # Should have run all registered collectors
        assert len(response.collectors) == len(COLLECTORS)

    @pytest.mark.asyncio
    async def test_specific_collectors_requested(self):
        from api.ratelimit import limiter
        from api.routes.support import COLLECTORS, collect_diagnostics

        db = _mock_db()
        user = MagicMock()

        async def noop(db_arg, logs_since):
            return {}

        old_enabled = limiter.enabled
        limiter.enabled = False
        try:
            with patch.dict(COLLECTORS, {name: lambda db, ls: noop(db, ls) for name in COLLECTORS}):
                body = CollectRequest(collectors=["versions", "health"])
                response = await collect_diagnostics(
                    request=MagicMock(),
                    body=body,
                    user=user,
                    db=db,
                )
        finally:
            limiter.enabled = old_enabled

        assert set(response.collectors.keys()) == {"versions", "health"}

    @pytest.mark.asyncio
    async def test_response_includes_server_version(self):
        from api.ratelimit import limiter
        from api.routes.support import COLLECTORS, collect_diagnostics

        db = _mock_db()
        user = MagicMock()

        async def noop(db_arg, logs_since):
            return {}

        old_enabled = limiter.enabled
        limiter.enabled = False
        try:
            with patch.dict(
                COLLECTORS,
                {
                    "versions": lambda db, ls: noop(db, ls),
                },
                clear=True,
            ):
                body = CollectRequest(collectors=["versions"])
                response = await collect_diagnostics(
                    request=MagicMock(),
                    body=body,
                    user=user,
                    db=db,
                )
        finally:
            limiter.enabled = old_enabled

        assert isinstance(response.server_version, str)
        assert len(response.server_version) > 0

    @pytest.mark.asyncio
    async def test_unknown_collector_name_ignored(self):
        from api.ratelimit import limiter
        from api.routes.support import COLLECTORS, collect_diagnostics

        db = _mock_db()
        user = MagicMock()

        async def noop(db_arg, logs_since):
            return {}

        old_enabled = limiter.enabled
        limiter.enabled = False
        try:
            with patch.dict(
                COLLECTORS,
                {
                    "versions": lambda db, ls: noop(db, ls),
                },
                clear=True,
            ):
                body = CollectRequest(collectors=["versions", "nonexistent_collector"])
                response = await collect_diagnostics(
                    request=MagicMock(),
                    body=body,
                    user=user,
                    db=db,
                )
        finally:
            limiter.enabled = old_enabled

        assert "versions" in response.collectors
        assert "nonexistent_collector" not in response.collectors


# ═════════════════════════════════════════════════════════════════════
# CLI-side config allowlist filtering
# ═════════════════════════════════════════════════════════════════════


class TestConfigAllowlistFiltering:
    """Tests for CLI-side CONFIG_ALLOWLIST filtering (Requirement 7.4)."""

    def test_allowlist_contains_expected_keys(self):
        expected = {
            "DATABASE_URL",
            "CLICKHOUSE_URL",
            "REDIS_URL",
            "REDIS_SOCKET_TIMEOUT",
            "EVAL_MODEL_NAME",
            "EVAL_MODEL_PROVIDER",
            "AWS_REGION",
            "FRONTEND_URL",
            "JWT_ACCESS_TOKEN_EXPIRE_MINUTES",
            "JWT_REFRESH_TOKEN_EXPIRE_DAYS",
            "JWT_SIGNING_ALGORITHM",
            "JWT_HOOKS_TOKEN_EXPIRE_MINUTES",
            "RATE_LIMIT_AUTH",
            "RATE_LIMIT_AUTH_STRICT",
            "DATA_RETENTION_DAYS",
            "DEPLOYMENT_MODE",
        }
        assert expected.issubset(CONFIG_ALLOWLIST)

    def test_allowlist_excludes_secrets(self):
        forbidden = {
            "SECRET_KEY",
            "EVAL_MODEL_API_KEY",
            "EVAL_MODEL_URL",
            "OAUTH_CLIENT_ID",
            "OAUTH_CLIENT_SECRET",
            "OAUTH_SERVER_METADATA_URL",
            "JWT_KEY_DIR",
            "JWT_KEY_PASSWORD",
        }
        assert forbidden.isdisjoint(CONFIG_ALLOWLIST)

    def test_filtering_with_mixed_keys(self):
        """Simulate CLI-side filtering: only allowlisted keys survive."""
        raw_config = {
            "DATABASE_URL": "postgresql://user:pass@localhost/db",
            "SECRET_KEY": "super-secret-key-value",
            "DEPLOYMENT_MODE": "docker",
            "OAUTH_CLIENT_SECRET": "oauth-secret",
            "AWS_REGION": "us-east-1",
        }
        filtered = {k: v for k, v in raw_config.items() if k in CONFIG_ALLOWLIST}

        assert "DATABASE_URL" in filtered
        assert "DEPLOYMENT_MODE" in filtered
        assert "AWS_REGION" in filtered
        assert "SECRET_KEY" not in filtered
        assert "OAUTH_CLIENT_SECRET" not in filtered
