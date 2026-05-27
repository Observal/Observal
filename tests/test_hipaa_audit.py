# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-FileCopyrightText: 2026 Yash Gadgil <yashgadgil08@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Tests for the HIPAA audit logging system."""

from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestClassification:
    """Route sensitivity classification."""

    def test_health_is_skip(self):
        from services.audit.classification import classify_route

        assert classify_route("GET", "/health") == "skip"

    def test_livez_is_skip(self):
        from services.audit.classification import classify_route

        assert classify_route("GET", "/livez") == "skip"

    def test_metrics_is_skip(self):
        from services.audit.classification import classify_route

        assert classify_route("GET", "/metrics") == "skip"

    def test_openapi_is_skip(self):
        from services.audit.classification import classify_route

        assert classify_route("GET", "/openapi.json") == "skip"

    def test_sessions_is_phi_adjacent(self):
        from services.audit.classification import classify_route

        assert classify_route("GET", "/api/v1/sessions") == "phi_adjacent"
        assert classify_route("GET", "/api/v1/sessions/abc") == "phi_adjacent"

    def test_ingest_is_phi_adjacent(self):
        from services.audit.classification import classify_route

        assert classify_route("POST", "/api/v1/ingest/session") == "phi_adjacent"

    def test_reconcile_is_phi_adjacent(self):
        from services.audit.classification import classify_route

        assert classify_route("POST", "/api/v1/reconcile") == "phi_adjacent"

    def test_telemetry_is_phi_adjacent(self):
        from services.audit.classification import classify_route

        assert classify_route("POST", "/api/v1/telemetry/ingest") == "phi_adjacent"

    def test_admin_is_admin(self):
        from services.audit.classification import classify_route

        assert classify_route("GET", "/api/v1/admin/settings") == "admin"

    def test_agents_is_high(self):
        from services.audit.classification import classify_route

        assert classify_route("POST", "/api/v1/agents") == "high"

    def test_auth_is_high(self):
        from services.audit.classification import classify_route

        assert classify_route("POST", "/api/v1/auth/login") == "high"

    def test_feedback_is_standard(self):
        from services.audit.classification import classify_route

        assert classify_route("POST", "/api/v1/feedback") == "standard"

    def test_config_is_low(self):
        from services.audit.classification import classify_route

        assert classify_route("GET", "/api/v1/config/public") == "low"

    def test_unknown_api_defaults_to_standard(self):
        from services.audit.classification import classify_route

        assert classify_route("GET", "/api/v1/unknown") == "standard"

    def test_non_api_is_skip(self):
        from services.audit.classification import classify_route

        assert classify_route("GET", "/favicon.ico") == "skip"


class TestHelpers:
    """audit_detail() helper."""

    def test_sets_fields(self):
        from services.audit.helpers import audit_detail

        request = MagicMock()
        request.state = MagicMock()
        audit_detail(request, action="mcp.submit", resource_type="mcp", resource_id="abc")
        assert request.state.audit_action == "mcp.submit"
        assert request.state.audit_resource_type == "mcp"
        assert request.state.audit_resource_id == "abc"

    def test_skips_empty(self):
        from services.audit.helpers import audit_detail

        request = MagicMock()
        request.state = MagicMock(spec=[])
        audit_detail(request, action="test")
        assert request.state.audit_action == "test"


class TestSink:
    """Audit sink buffer and flush."""

    @pytest.mark.asyncio
    async def test_buffers_records(self):
        from services.audit.sink import _buffer, _buffer_lock, audit_sink

        async with _buffer_lock:
            _buffer.clear()

        record = {
            "record": {
                "time": {"timestamp": 1779600000.123},
                "extra": {
                    "audit": True,
                    "event_id": str(uuid.uuid4()),
                    "actor_id": "user-1",
                    "actor_email": "test@example.com",
                    "actor_role": "admin",
                    "action": "test.action",
                    "resource_type": "test",
                    "resource_id": "123",
                    "resource_name": "",
                    "http_method": "GET",
                    "http_path": "/api/v1/test",
                    "status_code": 200,
                    "ip_address": "127.0.0.1",
                    "user_agent": "test",
                    "detail": "",
                    "org_id": "",
                    "sensitivity": "standard",
                    "request_id": "req-1",
                    "outcome": "success",
                    "duration_ms": 5.0,
                    "_chain_hash": "abc123",
                    "source": "server",
                },
            }
        }

        await audit_sink(json.dumps(record))

        async with _buffer_lock:
            assert len(_buffer) == 1
            row = _buffer[0]
            assert row["actor_id"] == "user-1"
            assert row["action"] == "test.action"
            assert row["chain_hash"] == "abc123"
            assert "2026-" in row["timestamp"]
            _buffer.clear()

    @pytest.mark.asyncio
    async def test_ignores_non_audit(self):
        from services.audit.sink import _buffer, _buffer_lock, audit_sink

        async with _buffer_lock:
            _buffer.clear()

        record = {"record": {"time": {"timestamp": 0}, "extra": {"audit": False}}}
        await audit_sink(json.dumps(record))

        async with _buffer_lock:
            assert len(_buffer) == 0

    @pytest.mark.asyncio
    async def test_flush_calls_insert(self):
        from services.audit.sink import _buffer, _buffer_lock, _flush

        async with _buffer_lock:
            _buffer.clear()
            _buffer.append({"event_id": "test", "timestamp": "2026-01-01 00:00:00.000", "action": "t"})

        with patch("services.clickhouse.insert_audit_log", new_callable=AsyncMock) as mock_insert:
            async with _buffer_lock:
                await _flush()
            mock_insert.assert_called_once()
            assert len(mock_insert.call_args[0][0]) == 1

    @pytest.mark.asyncio
    async def test_flush_empty_noop(self):
        from services.audit.sink import _buffer, _buffer_lock, _flush

        async with _buffer_lock:
            _buffer.clear()

        with patch("services.clickhouse.insert_audit_log", new_callable=AsyncMock) as mock_insert:
            async with _buffer_lock:
                await _flush()
            mock_insert.assert_not_called()


class TestSetup:
    """Hash chain and setup."""

    def test_chain_hash_adds_hash(self):
        from services.audit.setup import _chain_hash_patcher

        record = {"extra": {"audit": True, "action": "test"}}
        _chain_hash_patcher(record)
        assert "_chain_hash" in record["extra"]
        assert len(record["extra"]["_chain_hash"]) == 64

    def test_chain_hash_skips_non_audit(self):
        from services.audit.setup import _chain_hash_patcher

        record = {"extra": {"audit": False}}
        _chain_hash_patcher(record)
        assert "_chain_hash" not in record["extra"]

    def test_chain_is_sequential(self):
        from services.audit import setup as setup_mod

        setup_mod._prev_hash = "0" * 64
        r1 = {"extra": {"audit": True, "action": "first"}}
        setup_mod._chain_hash_patcher(r1)
        r2 = {"extra": {"audit": True, "action": "second"}}
        setup_mod._chain_hash_patcher(r2)
        assert r1["extra"]["_chain_hash"] != r2["extra"]["_chain_hash"]


class TestMiddleware:
    """AuditMiddleware."""

    @pytest.mark.asyncio
    async def test_skips_health(self):
        from api.middleware.audit import AuditMiddleware

        middleware = AuditMiddleware(MagicMock())
        request = MagicMock()
        request.method = "GET"
        request.url.path = "/health"
        request.state = MagicMock()

        call_next = AsyncMock(return_value=MagicMock(status_code=200))
        response = await middleware.dispatch(request, call_next)
        call_next.assert_called_once()
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_emits_for_api(self):
        from api.middleware.audit import AuditMiddleware

        middleware = AuditMiddleware(MagicMock())
        request = MagicMock()
        request.method = "GET"
        request.url.path = "/api/v1/agents"
        request.state = MagicMock()
        request.state.request_id = "req-1"
        request.state.audit_user = None
        request.state.audit_action = ""
        request.state.audit_resource_type = ""
        request.state.audit_resource_id = ""
        request.state.audit_resource_name = ""
        request.state.audit_detail = ""
        request.headers = {"x-forwarded-for": "10.0.0.1", "user-agent": "test/1.0"}
        request.client = MagicMock()
        request.client.host = "127.0.0.1"

        call_next = AsyncMock(return_value=MagicMock(status_code=200))

        with patch("api.middleware.audit.logger") as mock_logger:
            mock_bound = MagicMock()
            mock_logger.bind.return_value = mock_bound
            await middleware.dispatch(request, call_next)
            mock_logger.bind.assert_called_once()
            kwargs = mock_logger.bind.call_args[1]
            assert kwargs["audit"] is True
            assert kwargs["outcome"] == "success"
            assert kwargs["sensitivity"] == "high"
            assert kwargs["ip_address"] == "127.0.0.1"
            mock_bound.info.assert_called_once_with("audit")

    @pytest.mark.asyncio
    async def test_denied_on_403(self):
        from api.middleware.audit import AuditMiddleware

        middleware = AuditMiddleware(MagicMock())
        request = MagicMock()
        request.method = "POST"
        request.url.path = "/api/v1/admin/settings"
        request.state = MagicMock()
        request.state.request_id = ""
        request.state.audit_user = None
        request.state.audit_action = ""
        request.state.audit_resource_type = ""
        request.state.audit_resource_id = ""
        request.state.audit_resource_name = ""
        request.state.audit_detail = ""
        request.headers = {"x-forwarded-for": "", "user-agent": ""}
        request.client = MagicMock()
        request.client.host = "192.168.1.1"

        call_next = AsyncMock(return_value=MagicMock(status_code=403))

        with patch("api.middleware.audit.logger") as mock_logger:
            mock_bound = MagicMock()
            mock_logger.bind.return_value = mock_bound
            await middleware.dispatch(request, call_next)
            kwargs = mock_logger.bind.call_args[1]
            assert kwargs["outcome"] == "denied"
            assert kwargs["actor_id"] == "anonymous"


class TestCliAudit:
    """CLI audit emission."""

    def test_no_config_is_noop(self):
        with patch("observal_cli.config.load", return_value={}):
            from observal_cli.audit import emit_cli_audit

            emit_cli_audit("test.action")  # should not raise

    def test_starts_thread(self):
        cfg = {"api_key": "test-key", "server_url": "http://localhost:8000"}
        with (
            patch("observal_cli.config.load", return_value=cfg),
            patch("threading.Thread") as mock_thread,
        ):
            from observal_cli.audit import emit_cli_audit

            emit_cli_audit("agent.pull", resource_type="agent", resource_id="abc")
            mock_thread.assert_called_once()
            assert mock_thread.call_args[1]["daemon"] is True


class TestSchemaExpansion:
    """ClickHouse schema includes new audit columns."""

    def test_new_columns_in_init_sql(self):
        from services.clickhouse.schema import INIT_SQL

        sql_blob = "\n".join(INIT_SQL)
        assert "ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS org_id" in sql_blob
        assert "ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS sensitivity" in sql_blob
        assert "ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS outcome" in sql_blob
        assert "ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS duration_ms" in sql_blob
        assert "ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS chain_hash" in sql_blob
        assert "ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS source" in sql_blob

    def test_new_indexes_in_init_sql(self):
        from services.clickhouse.schema import INIT_SQL

        sql_blob = "\n".join(INIT_SQL)
        assert "idx_outcome" in sql_blob
        assert "idx_sensitivity" in sql_blob
        assert "idx_source" in sql_blob


class TestInsertAuditLog:
    """insert_audit_log writes new fields."""

    @pytest.mark.asyncio
    async def test_includes_all_fields(self):
        with patch("services.clickhouse.client._query", new_callable=AsyncMock) as mock_query:
            mock_response = MagicMock()
            mock_response.raise_for_status = MagicMock()
            mock_query.return_value = mock_response

            with patch("services.clickhouse.client._invalidate_cache", new_callable=AsyncMock):
                from services.clickhouse.insert import insert_audit_log

                rows = [
                    {
                        "event_id": str(uuid.uuid4()),
                        "timestamp": "2026-01-01 00:00:00.000",
                        "actor_id": "user-1",
                        "actor_email": "t@t.com",
                        "actor_role": "admin",
                        "action": "test",
                        "resource_type": "",
                        "resource_id": "",
                        "resource_name": "",
                        "http_method": "POST",
                        "http_path": "/test",
                        "status_code": 200,
                        "ip_address": "10.0.0.1",
                        "user_agent": "cli",
                        "detail": "",
                        "org_id": "org-1",
                        "sensitivity": "high",
                        "request_id": "req-1",
                        "outcome": "success",
                        "duration_ms": 42.5,
                        "chain_hash": "a" * 64,
                        "source": "cli",
                    }
                ]

                await insert_audit_log(rows)
                mock_query.assert_called_once()
                data = mock_query.call_args.kwargs.get("data", "")
                parsed = json.loads(data)
                assert parsed["org_id"] == "org-1"
                assert parsed["sensitivity"] == "high"
                assert parsed["outcome"] == "success"
                assert parsed["source"] == "cli"
                assert parsed["chain_hash"] == "a" * 64
