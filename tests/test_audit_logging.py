# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Tests for enterprise audit logging (SOC 2 / ISO 27001 / HIPAA compliance)."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.events import (
    AgentLifecycleEvent,
    AlertRuleChanged,
    AuditableAction,
    LoginFailure,
    LoginSuccess,
    RoleChanged,
    SettingsChanged,
    UserCreated,
    UserDeleted,
    bus,
)


class TestRegisterAuditHandlers:
    """Verify register_audit_handlers() wires the correct event types."""

    def setup_method(self):
        bus.clear()

    def teardown_method(self):
        bus.clear()

    def test_registers_correct_number_of_handlers(self):
        from ee.observal_server.services.audit import register_audit_handlers

        assert bus.handler_count == 0
        register_audit_handlers()
        assert bus.handler_count == 9

    def test_registers_handlers_for_all_event_types(self):
        from ee.observal_server.services.audit import register_audit_handlers

        register_audit_handlers()
        expected_types = [
            AuditableAction,
            UserCreated,
            UserDeleted,
            LoginSuccess,
            LoginFailure,
            RoleChanged,
            SettingsChanged,
            AlertRuleChanged,
            AgentLifecycleEvent,
        ]
        for event_type in expected_types:
            assert len(bus._handlers[event_type]) == 1, f"No handler registered for {event_type.__name__}"


class TestBufferedAuditWrite:
    """Verify buffered audit rows are constructed correctly."""

    def setup_method(self):
        bus.clear()

    def teardown_method(self):
        bus.clear()

    @pytest.mark.asyncio
    async def test_user_created_buffers_row(self):
        from ee.observal_server.services.audit import _audit_buffer, register_audit_handlers

        mock_insert = AsyncMock()
        with patch("ee.observal_server.services.audit.insert_audit_log", mock_insert):
            register_audit_handlers()
            _audit_buffer.clear()
            event = UserCreated(user_id="u1", email="test@example.com", role="viewer", is_demo=True)
            await bus.emit(event)

        assert len(_audit_buffer) == 1
        row = _audit_buffer[0]
        assert row["action"] == "user.created"
        assert row["actor_id"] == "u1"
        assert row["actor_email"] == "test@example.com"
        assert row["actor_role"] == "viewer"
        detail = json.loads(row["detail"])
        assert detail["is_demo"] is True
        _audit_buffer.clear()

    @pytest.mark.asyncio
    async def test_login_failure_buffers_row(self):
        from ee.observal_server.services.audit import _audit_buffer, register_audit_handlers

        register_audit_handlers()
        _audit_buffer.clear()
        event = LoginFailure(email="hacker@bad.com", method="password", reason="invalid credentials")
        await bus.emit(event)

        assert len(_audit_buffer) == 1
        row = _audit_buffer[0]
        assert row["action"] == "auth.login_failure"
        assert row["actor_id"] == ""
        detail = json.loads(row["detail"])
        assert detail["reason"] == "invalid credentials"
        _audit_buffer.clear()

    @pytest.mark.asyncio
    async def test_alert_rule_changed_buffers_row(self):
        from ee.observal_server.services.audit import _audit_buffer, register_audit_handlers

        register_audit_handlers()
        _audit_buffer.clear()
        event = AlertRuleChanged(
            alert_id="alert-42",
            action="created",
            actor_id="u1",
            actor_email="admin@example.com",
        )
        await bus.emit(event)

        assert len(_audit_buffer) == 1
        row = _audit_buffer[0]
        assert row["action"] == "alert.created"
        assert row["resource_type"] == "alert_rule"
        assert row["resource_id"] == "alert-42"
        _audit_buffer.clear()

    @pytest.mark.asyncio
    async def test_agent_lifecycle_buffers_row(self):
        from ee.observal_server.services.audit import _audit_buffer, register_audit_handlers

        register_audit_handlers()
        _audit_buffer.clear()
        event = AgentLifecycleEvent(
            agent_id="agent-7",
            action="deleted",
            actor_id="u2",
            actor_email="ops@example.com",
        )
        await bus.emit(event)

        assert len(_audit_buffer) == 1
        row = _audit_buffer[0]
        assert row["action"] == "agent.deleted"
        assert row["resource_type"] == "agent"
        assert row["resource_id"] == "agent-7"
        _audit_buffer.clear()

    @pytest.mark.asyncio
    async def test_auditable_action_buffers_row(self):
        from ee.observal_server.services.audit import _audit_buffer, register_audit_handlers

        register_audit_handlers()
        _audit_buffer.clear()
        event = AuditableAction(
            actor_id="u1",
            actor_email="admin@example.com",
            actor_role="admin",
            action="trace.view",
            resource_type="trace",
            resource_id="tr-1",
            detail='{"session_id": "s1"}',
        )
        await bus.emit(event)

        assert len(_audit_buffer) == 1
        row = _audit_buffer[0]
        assert row["action"] == "trace.view"
        assert row["resource_type"] == "trace"
        assert row["resource_id"] == "tr-1"
        assert row["actor_role"] == "admin"
        _audit_buffer.clear()


class TestFlushBuffer:
    """Verify the flush mechanism."""

    @pytest.mark.asyncio
    async def test_flush_sends_batch(self):
        from ee.observal_server.services.audit import _audit_buffer, _make_row, flush_audit_buffer

        mock_insert = AsyncMock()
        _audit_buffer.clear()
        _audit_buffer.append(
            _make_row(
                actor_id="u1",
                actor_email="a@b.com",
                action="test",
                resource_type="test",
            )
        )
        _audit_buffer.append(
            _make_row(
                actor_id="u2",
                actor_email="c@d.com",
                action="test2",
                resource_type="test2",
            )
        )
        with patch("ee.observal_server.services.audit.insert_audit_log", mock_insert):
            count = await flush_audit_buffer()

        assert count == 2
        mock_insert.assert_called_once()
        assert len(mock_insert.call_args[0][0]) == 2
        assert len(_audit_buffer) == 0


class TestAuditLogEndpoint:
    """Test the audit log list endpoint with mocked ClickHouse responses."""

    @pytest.mark.asyncio
    async def test_list_audit_logs_returns_entries(self):
        from ee.observal_server.routes.audit import list_audit_logs

        fake_row = {
            "event_id": "550e8400-e29b-41d4-a716-446655440000",
            "timestamp": "2026-04-14 12:00:00.000",
            "actor_id": "u1",
            "actor_email": "admin@example.com",
            "actor_role": "admin",
            "action": "user.created",
            "resource_type": "user",
            "resource_id": "u2",
            "resource_name": "new@example.com",
            "http_method": "",
            "http_path": "",
            "status_code": 0,
            "ip_address": "",
            "user_agent": "",
            "detail": "{}",
        }
        fake_resp = MagicMock()
        fake_resp.status_code = 200
        fake_resp.text = json.dumps(fake_row)

        mock_query = AsyncMock(return_value=fake_resp)
        mock_user = MagicMock()
        mock_user.org_id = None

        with patch("ee.observal_server.routes.audit._query", mock_query):
            result = await list_audit_logs(
                actor=None,
                action=None,
                resource_type=None,
                start_date=None,
                end_date=None,
                limit=50,
                offset=0,
                current_user=mock_user,
            )

        assert len(result) == 1
        assert result[0]["action"] == "user.created"
        assert result[0]["actor_email"] == "admin@example.com"

    @pytest.mark.asyncio
    async def test_list_endpoint_handles_empty_response(self):
        from ee.observal_server.routes.audit import list_audit_logs

        fake_resp = MagicMock()
        fake_resp.status_code = 500
        fake_resp.text = ""

        mock_query = AsyncMock(return_value=fake_resp)
        mock_user = MagicMock()
        mock_user.org_id = None

        with patch("ee.observal_server.routes.audit._query", mock_query):
            result = await list_audit_logs(
                actor=None,
                action=None,
                resource_type=None,
                start_date=None,
                end_date=None,
                limit=50,
                offset=0,
                current_user=mock_user,
            )

        assert result == []

    @pytest.mark.asyncio
    async def test_list_endpoint_with_filters(self):
        from ee.observal_server.routes.audit import list_audit_logs

        fake_row = {
            "event_id": "550e8400-e29b-41d4-a716-446655440000",
            "timestamp": "2026-04-14 12:00:00.000",
            "actor_id": "u1",
            "actor_email": "admin@example.com",
            "actor_role": "admin",
            "action": "user.created",
            "resource_type": "user",
            "resource_id": "u2",
            "resource_name": "new@example.com",
            "http_method": "",
            "http_path": "",
            "status_code": 0,
            "ip_address": "",
            "user_agent": "",
            "detail": "{}",
        }
        fake_resp = MagicMock()
        fake_resp.status_code = 200
        fake_resp.text = json.dumps(fake_row)

        mock_query = AsyncMock(return_value=fake_resp)
        mock_user = MagicMock()
        mock_user.org_id = None

        with patch("ee.observal_server.routes.audit._query", mock_query):
            result = await list_audit_logs(
                actor="admin@example.com",
                action="user.created",
                resource_type="user",
                start_date=None,
                end_date=None,
                limit=50,
                offset=0,
                current_user=mock_user,
            )

        assert len(result) == 1
        # Verify the SQL includes filter params
        sql_arg = mock_query.call_args[0][0]
        params_arg = mock_query.call_args[0][1]
        assert "actor_email = {actor:String}" in sql_arg
        assert "action = {action:String}" in sql_arg
        assert "resource_type = {rtype:String}" in sql_arg
        assert params_arg["param_actor"] == "admin@example.com"
        assert params_arg["param_action"] == "user.created"
        assert params_arg["param_rtype"] == "user"
