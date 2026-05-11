# SPDX-FileCopyrightText: 2026 Vishnu Muthiah <vishnu.muthiah04@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Unit tests for webhook_delivery module."""

import uuid
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from services.webhook_delivery import (
    _buffer_delivery_record,
    _delivery_buffer,
    deliver_webhook,
    flush_delivery_records,
)


@pytest.fixture(autouse=True)
def clear_buffer():
    """Clear the delivery buffer before each test."""
    _delivery_buffer.clear()
    yield
    _delivery_buffer.clear()


ALERT_RULE_ID = uuid.uuid4()
TEST_SECRET = "a" * 64
TEST_URL = "https://example.com/webhook"
TEST_PAYLOAD = {"alert_name": "Test", "metric_value": 0.5}


class TestDeliverWebhook:
    @pytest.mark.asyncio
    async def test_successful_delivery(self):
        """Successful 200 response returns success=True."""
        mock_response = httpx.Response(200, request=httpx.Request("POST", TEST_URL))

        with patch("services.webhook_delivery.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await deliver_webhook(TEST_URL, TEST_SECRET, TEST_PAYLOAD, ALERT_RULE_ID)

        assert result.success is True
        assert result.status_code == 200
        assert result.attempts == 1
        assert result.error is None
        assert isinstance(result.event_id, uuid.UUID)

    @pytest.mark.asyncio
    async def test_4xx_not_retried(self):
        """4xx responses are NOT retried (client error)."""
        mock_response = httpx.Response(400, request=httpx.Request("POST", TEST_URL))

        with patch("services.webhook_delivery.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await deliver_webhook(TEST_URL, TEST_SECRET, TEST_PAYLOAD, ALERT_RULE_ID)

        assert result.success is False
        assert mock_client.post.call_count == 1  # No retry

    @pytest.mark.asyncio
    async def test_5xx_triggers_retry(self):
        """5xx responses trigger retry with eventual success."""
        fail_response = httpx.Response(500, request=httpx.Request("POST", TEST_URL))
        success_response = httpx.Response(200, request=httpx.Request("POST", TEST_URL))

        with patch("services.webhook_delivery.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post.side_effect = [fail_response, success_response]
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            with patch("services.webhook_delivery.asyncio.sleep", new_callable=AsyncMock):
                result = await deliver_webhook(TEST_URL, TEST_SECRET, TEST_PAYLOAD, ALERT_RULE_ID)

        assert result.success is True
        assert result.attempts == 2
        assert mock_client.post.call_count == 2

    @pytest.mark.asyncio
    async def test_all_retries_exhausted(self):
        """All retries fail returns success=False."""
        fail_response = httpx.Response(500, request=httpx.Request("POST", TEST_URL))

        with patch("services.webhook_delivery.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post.return_value = fail_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            with patch("services.webhook_delivery.asyncio.sleep", new_callable=AsyncMock):
                result = await deliver_webhook(TEST_URL, TEST_SECRET, TEST_PAYLOAD, ALERT_RULE_ID, max_retries=3)

        assert result.success is False
        assert result.attempts == 3
        assert mock_client.post.call_count == 3

    @pytest.mark.asyncio
    async def test_ssrf_rejection(self):
        """Private/internal URLs are rejected immediately."""
        result = await deliver_webhook("http://127.0.0.1/webhook", TEST_SECRET, TEST_PAYLOAD, ALERT_RULE_ID)
        assert result.success is False
        assert result.attempts == 0
        assert "SSRF" in result.error

    @pytest.mark.asyncio
    async def test_network_error_triggers_retry(self):
        """Network errors trigger retry."""
        with patch("services.webhook_delivery.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post.side_effect = httpx.ConnectError("Connection refused")
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            with patch("services.webhook_delivery.asyncio.sleep", new_callable=AsyncMock):
                result = await deliver_webhook(TEST_URL, TEST_SECRET, TEST_PAYLOAD, ALERT_RULE_ID, max_retries=2)

        assert result.success is False
        assert mock_client.post.call_count == 2

    @pytest.mark.asyncio
    async def test_same_event_id_across_retries(self):
        """Event ID is consistent across all retry attempts."""
        fail_response = httpx.Response(500, request=httpx.Request("POST", TEST_URL))
        success_response = httpx.Response(200, request=httpx.Request("POST", TEST_URL))

        with patch("services.webhook_delivery.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post.side_effect = [fail_response, success_response]
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            with patch("services.webhook_delivery.asyncio.sleep", new_callable=AsyncMock):
                result = await deliver_webhook(TEST_URL, TEST_SECRET, TEST_PAYLOAD, ALERT_RULE_ID)

        # All buffered records should have the same event_id
        event_ids = {r["event_id"] for r in _delivery_buffer}
        assert len(event_ids) == 1
        assert event_ids.pop() == str(result.event_id)

    @pytest.mark.asyncio
    async def test_payload_immutability(self):
        """Same bytes are sent on every attempt (payload immutability)."""
        fail_response = httpx.Response(500, request=httpx.Request("POST", TEST_URL))
        success_response = httpx.Response(200, request=httpx.Request("POST", TEST_URL))

        sent_bodies = []

        with patch("services.webhook_delivery.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()

            async def capture_post(url, content=None, headers=None):
                sent_bodies.append(content)
                if len(sent_bodies) == 1:
                    return fail_response
                return success_response

            mock_client.post.side_effect = capture_post
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            with patch("services.webhook_delivery.asyncio.sleep", new_callable=AsyncMock):
                await deliver_webhook(TEST_URL, TEST_SECRET, TEST_PAYLOAD, ALERT_RULE_ID)

        # All sent bodies must be identical bytes
        assert len(sent_bodies) == 2
        assert sent_bodies[0] == sent_bodies[1]

    @pytest.mark.asyncio
    async def test_empty_secret_delivers_without_signature(self):
        """Empty webhook_secret delivers without X-Observal-Signature header."""
        sent_headers = {}
        mock_response = httpx.Response(200, request=httpx.Request("POST", TEST_URL))

        with patch("services.webhook_delivery.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()

            async def capture_post(url, content=None, headers=None):
                sent_headers.update(headers or {})
                return mock_response

            mock_client.post.side_effect = capture_post
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await deliver_webhook(TEST_URL, "", TEST_PAYLOAD, ALERT_RULE_ID)

        assert result.success is True
        assert "X-Observal-Signature" not in sent_headers
        assert "X-Observal-Event-Id" in sent_headers


class TestBufferAndFlush:
    def test_buffer_delivery_record_adds_to_buffer(self):
        """Records are added to the in-memory buffer."""
        _buffer_delivery_record(ALERT_RULE_ID, uuid.uuid4(), 1, TEST_URL, 200, "delivered", None, 100.0, 256)
        assert len(_delivery_buffer) == 1
        assert _delivery_buffer[0]["delivery_status"] == "delivered"

    @pytest.mark.asyncio
    async def test_flush_clears_buffer(self):
        """Flush empties the buffer and returns count."""
        _buffer_delivery_record(ALERT_RULE_ID, uuid.uuid4(), 1, TEST_URL, 200, "delivered", None, 100.0, 256)
        _buffer_delivery_record(ALERT_RULE_ID, uuid.uuid4(), 1, TEST_URL, 500, "failed", None, 200.0, 256)

        with patch("services.clickhouse._insert_webhook_deliveries", new_callable=AsyncMock) as mock_insert:
            count = await flush_delivery_records()

        assert count == 2
        assert len(_delivery_buffer) == 0
        mock_insert.assert_called_once()

    @pytest.mark.asyncio
    async def test_flush_empty_buffer_returns_zero(self):
        """Flushing empty buffer returns 0 without calling ClickHouse."""
        count = await flush_delivery_records()
        assert count == 0
