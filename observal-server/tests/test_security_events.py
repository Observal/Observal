# SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Tests for the security events module.

Validates SecurityEvent model, emit_security_event logging, and event types.
"""

import json
import logging

import pytest

from services.security_events import (
    EventType,
    SecurityEvent,
    Severity,
    _extract_request_info,
    emit_security_event,
)


class TestSecurityEventModel:
    def test_event_has_required_fields(self):
        event = SecurityEvent(
            event_type=EventType.LOGIN_SUCCESS,
            severity=Severity.INFO,
            outcome="success",
            actor_id="user-123",
            actor_email="test@example.com",
        )
        assert event.event_type == EventType.LOGIN_SUCCESS
        assert event.severity == Severity.INFO
        assert event.outcome == "success"
        assert event.actor_id == "user-123"
        assert event.event_id  # auto-generated UUID
        assert event.timestamp  # auto-generated

    def test_to_log_dict_serializes_enums(self):
        event = SecurityEvent(
            event_type=EventType.PERMISSION_DENIED,
            severity=Severity.WARNING,
            outcome="failure",
        )
        d = event.to_log_dict()
        assert d["event_type"] == "authz.permission_denied"
        assert d["severity"] == "warning"
        assert d["outcome"] == "failure"

    def test_to_clickhouse_row(self):
        event = SecurityEvent(
            event_type=EventType.LOGIN_FAILURE,
            severity=Severity.WARNING,
            outcome="failure",
            actor_email="attacker@example.com",
            source_ip="1.2.3.4",
            detail="Invalid email or password",
        )
        row = event.to_clickhouse_row()
        assert row["event_type"] == "auth.login.failure"
        assert row["severity"] == "warning"
        assert row["source_ip"] == "1.2.3.4"
        assert row["actor_email"] == "attacker@example.com"
        assert "event_id" in row
        assert "timestamp" in row

    def test_all_event_types_have_values(self):
        for et in EventType:
            assert "." in et.value

    def test_all_severities(self):
        assert set(s.value for s in Severity) == {"info", "warning", "critical"}


class TestEmitSecurityEvent:
    @pytest.mark.asyncio
    async def test_emit_logs_to_security_logger(self, caplog):
        event = SecurityEvent(
            event_type=EventType.LOGIN_SUCCESS,
            severity=Severity.INFO,
            outcome="success",
            actor_email="user@test.com",
        )
        with caplog.at_level(logging.INFO, logger="observal.security"):
            await emit_security_event(event)

        assert len(caplog.records) == 1
        record = caplog.records[0]
        assert "security_event" in record.message
        parsed = json.loads(record.message.split("security_event: ")[1])
        assert parsed["event_type"] == "auth.login.success"
        assert parsed["actor_email"] == "user@test.com"

    @pytest.mark.asyncio
    async def test_emit_warning_severity(self, caplog):
        event = SecurityEvent(
            event_type=EventType.LOGIN_FAILURE,
            severity=Severity.WARNING,
            outcome="failure",
        )
        with caplog.at_level(logging.WARNING, logger="observal.security"):
            await emit_security_event(event)

        assert caplog.records[0].levelno == logging.WARNING

    @pytest.mark.asyncio
    async def test_emit_critical_severity(self, caplog):
        event = SecurityEvent(
            event_type=EventType.INJECTION_DETECTED,
            severity=Severity.CRITICAL,
            outcome="detected",
            detail="html_comment_injection",
        )
        with caplog.at_level(logging.CRITICAL, logger="observal.security"):
            await emit_security_event(event)

        assert caplog.records[0].levelno == logging.CRITICAL

    @pytest.mark.asyncio
    async def test_emit_does_not_raise_on_clickhouse_failure(self, caplog):
        event = SecurityEvent(
            event_type=EventType.REGISTRATION,
            severity=Severity.INFO,
            outcome="success",
        )
        with caplog.at_level(logging.DEBUG, logger="observal.security"):
            await emit_security_event(event)
        # Should not raise even though ClickHouse is unavailable


class TestExtractRequestInfo:
    def test_extracts_from_mock_request(self):

        class MockClient:
            host = "192.168.1.100"

        class MockRequest:
            client = MockClient()
            headers = {"user-agent": "Mozilla/5.0"}

        ip, ua = _extract_request_info(MockRequest())
        assert ip == "192.168.1.100"
        assert ua == "Mozilla/5.0"

    def test_handles_none_request(self):
        ip, ua = _extract_request_info(None)
        assert ip == ""
        assert ua == ""

    def test_handles_missing_client(self):

        class MockRequest:
            client = None
            headers = {"user-agent": "curl/7.0"}

        ip, ua = _extract_request_info(MockRequest())
        assert ip == ""
        assert ua == "curl/7.0"
