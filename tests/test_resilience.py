"""Tests for resilience patterns: retries, health checks, and timeouts."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

# ---------------------------------------------------------------------------
# ClickHouse _query retries on ConnectError
# ---------------------------------------------------------------------------


class TestClickHouseRetry:
    """Verify _query retries on transient connection errors."""

    @pytest.mark.asyncio
    async def test_query_retries_on_connect_error(self):
        """_query should retry up to 3 times on ConnectError."""
        from services.clickhouse import _query

        mock_client = AsyncMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_client.post = AsyncMock(
            side_effect=[
                httpx.ConnectError("conn refused"),
                httpx.ConnectError("conn refused"),
                mock_resp,
            ]
        )

        with patch("services.clickhouse._get_client", return_value=mock_client):
            resp = await _query("SELECT 1")
            assert resp.status_code == 200
            assert mock_client.post.call_count == 3

    @pytest.mark.asyncio
    async def test_query_raises_after_max_retries(self):
        """_query should reraise ConnectError after exhausting retries."""
        from services.clickhouse import _query

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=httpx.ConnectError("conn refused"))

        with patch("services.clickhouse._get_client", return_value=mock_client):
            with pytest.raises(httpx.ConnectError):
                await _query("SELECT 1")
            assert mock_client.post.call_count == 3

    @pytest.mark.asyncio
    async def test_query_retries_on_connect_timeout(self):
        """_query should retry on ConnectTimeout."""
        from services.clickhouse import _query

        mock_client = AsyncMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_client.post = AsyncMock(side_effect=[httpx.ConnectTimeout("timeout"), mock_resp])

        with patch("services.clickhouse._get_client", return_value=mock_client):
            resp = await _query("SELECT 1")
            assert resp.status_code == 200
            assert mock_client.post.call_count == 2

    @pytest.mark.asyncio
    async def test_query_does_not_retry_on_other_errors(self):
        """_query should NOT retry on non-transient errors like ReadError."""
        from services.clickhouse import _query

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=httpx.ReadError("broken pipe"))

        with patch("services.clickhouse._get_client", return_value=mock_client):
            with pytest.raises(httpx.ReadError):
                await _query("SELECT 1")
            assert mock_client.post.call_count == 1


# ---------------------------------------------------------------------------
# ClickHouse clickhouse_health()
# ---------------------------------------------------------------------------


class TestClickHouseHealth:
    """Verify clickhouse_health returns True/False."""

    @pytest.mark.asyncio
    async def test_health_returns_true_on_success(self):
        from services.clickhouse import clickhouse_health

        mock_resp = MagicMock()
        mock_resp.status_code = 200

        with patch("services.clickhouse._query", new_callable=AsyncMock, return_value=mock_resp):
            assert await clickhouse_health() is True

    @pytest.mark.asyncio
    async def test_health_returns_false_on_error(self):
        from services.clickhouse import clickhouse_health

        with patch(
            "services.clickhouse._query",
            new_callable=AsyncMock,
            side_effect=httpx.ConnectError("unreachable"),
        ):
            assert await clickhouse_health() is False

    @pytest.mark.asyncio
    async def test_health_returns_false_on_non_200(self):
        from services.clickhouse import clickhouse_health

        mock_resp = MagicMock()
        mock_resp.status_code = 500

        with patch("services.clickhouse._query", new_callable=AsyncMock, return_value=mock_resp):
            assert await clickhouse_health() is False


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


# ---------------------------------------------------------------------------
# Shim explicit timeout
# ---------------------------------------------------------------------------


class TestShimTimeout:
    """Verify the shim uses an explicit timeout on httpx calls."""

    def test_shim_send_has_explicit_timeout(self):
        """ShimState._send should use httpx.AsyncClient with a timeout."""
        import inspect

        from observal_cli.shim import ShimState

        source = inspect.getsource(ShimState._send)
        assert "timeout=" in source, "ShimState._send must specify an explicit timeout on httpx calls"
