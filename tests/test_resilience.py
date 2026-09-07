# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Tests for resilience patterns: retries, health checks, and timeouts."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

# ---------------------------------------------------------------------------
# ClickHouse _query retries on ConnectError
# ---------------------------------------------------------------------------


class TestDuckDBHealth:
    """DuckDB health checks against a real (tmp_path) database file."""

    @pytest.fixture()
    def duckdb_path(self, tmp_path, monkeypatch):
        from config import settings
        from services.duckdb import close_con

        close_con()
        monkeypatch.setattr(settings, "DUCKDB_PATH", str(tmp_path / "health.duckdb"))
        monkeypatch.setattr(settings, "DUCKDB_READ_ONLY", False)
        yield
        close_con()

    @pytest.mark.asyncio
    async def test_health_returns_true_on_live_db(self, duckdb_path):
        from services.duckdb import duckdb_health

        assert await duckdb_health() is True

    @pytest.mark.asyncio
    async def test_health_returns_false_when_open_fails(self, tmp_path, monkeypatch):
        """A path that cannot be opened (a directory) must yield False, not raise."""
        from config import settings
        from services.duckdb import close_con, duckdb_health

        close_con()
        monkeypatch.setattr(settings, "DUCKDB_PATH", str(tmp_path))  # a directory
        monkeypatch.setattr(settings, "DUCKDB_READ_ONLY", False)
        try:
            assert await duckdb_health() is False
        finally:
            close_con()

    @pytest.mark.asyncio
    async def test_query_errors_return_error_result_not_raise(self, duckdb_path):
        """Embedded engine: SQL errors surface as status>=500 results, matching
        the legacy contract where callers check status_code / raise_for_status."""
        from services.duckdb import AnalyticsQueryError, _query

        resp = await _query("SELECT * FROM definitely_missing_table")
        assert resp.status_code >= 400
        with pytest.raises(AnalyticsQueryError):
            resp.raise_for_status()


# ---------------------------------------------------------------------------
# Redis publish() retries on ConnectionError
# ---------------------------------------------------------------------------


class TestRedisPublishRetry:
    """Verify publish retries on ConnectionError."""

    @pytest.mark.asyncio
    async def test_publish_retries_on_connection_error(self):
        from services.redis import publish

        mock_redis = MagicMock()
        mock_redis.publish = AsyncMock(side_effect=[ConnectionError("reset"), None])

        with (
            patch("services.redis.get_redis", return_value=mock_redis),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            await publish("test-channel", {"msg": "hello"})
            assert mock_redis.publish.call_count == 2

    @pytest.mark.asyncio
    async def test_publish_gives_up_after_max_attempts(self):
        from services.redis import publish

        mock_redis = MagicMock()
        mock_redis.publish = AsyncMock(side_effect=ConnectionError("persistent failure"))

        with (
            patch("services.redis.get_redis", return_value=mock_redis),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            await publish("test-channel", {"msg": "hello"})
            assert mock_redis.publish.call_count == 3

    @pytest.mark.asyncio
    async def test_publish_retries_on_os_error(self):
        from services.redis import publish

        mock_redis = MagicMock()
        mock_redis.publish = AsyncMock(side_effect=[OSError("network down"), None])

        with (
            patch("services.redis.get_redis", return_value=mock_redis),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            await publish("test-channel", {"msg": "hello"})
            assert mock_redis.publish.call_count == 2


# ---------------------------------------------------------------------------
# CLI _request_with_retry()
# ---------------------------------------------------------------------------


class TestCliRetry:
    """Verify CLI _request_with_retry retries on 429/503/504."""

    def test_retries_on_429(self):
        from observal_cli.client import _request_with_retry

        mock_resp_429 = MagicMock(spec=httpx.Response)
        mock_resp_429.status_code = 429
        mock_resp_429.headers = {}

        mock_resp_200 = MagicMock(spec=httpx.Response)
        mock_resp_200.status_code = 200
        mock_resp_200.headers = {}
        mock_resp_200.raise_for_status = MagicMock()

        with patch("httpx.get", side_effect=[mock_resp_429, mock_resp_200]), patch("time.sleep"):
            r = _request_with_retry("get", "http://test/api", {"Authorization": "Bearer test-token"})
            assert r.status_code == 200

    def test_retries_on_503(self):
        from observal_cli.client import _request_with_retry

        mock_resp_503 = MagicMock(spec=httpx.Response)
        mock_resp_503.status_code = 503
        mock_resp_503.headers = {}

        mock_resp_200 = MagicMock(spec=httpx.Response)
        mock_resp_200.status_code = 200
        mock_resp_200.headers = {}
        mock_resp_200.raise_for_status = MagicMock()

        with patch("httpx.get", side_effect=[mock_resp_503, mock_resp_200]), patch("time.sleep"):
            r = _request_with_retry("get", "http://test/api", {"Authorization": "Bearer test-token"})
            assert r.status_code == 200

    def test_honors_retry_after_header(self):
        from observal_cli.client import _request_with_retry

        mock_resp_429 = MagicMock(spec=httpx.Response)
        mock_resp_429.status_code = 429
        mock_resp_429.headers = {"Retry-After": "3"}

        mock_resp_200 = MagicMock(spec=httpx.Response)
        mock_resp_200.status_code = 200
        mock_resp_200.headers = {}
        mock_resp_200.raise_for_status = MagicMock()

        with (
            patch("httpx.get", side_effect=[mock_resp_429, mock_resp_200]),
            patch("time.sleep") as mock_sleep,
        ):
            r = _request_with_retry("get", "http://test/api", {"Authorization": "Bearer test-token"})
            assert r.status_code == 200
            mock_sleep.assert_called_once_with(3.0)

    def test_does_not_retry_on_400(self):
        """Non-retryable status codes should raise immediately."""
        from observal_cli.client import _request_with_retry

        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.status_code = 400
        mock_resp.headers = {"content-type": "application/json"}
        mock_resp.json.return_value = {"detail": "bad request"}
        mock_resp.text = "bad request"
        mock_resp.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError("bad", request=MagicMock(), response=mock_resp)
        )

        with patch("httpx.get", return_value=mock_resp), pytest.raises(httpx.HTTPStatusError):
            _request_with_retry("get", "http://test/api", {"Authorization": "Bearer test-token"})
