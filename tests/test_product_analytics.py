# SPDX-FileCopyrightText: 2026 Aryan Iyappan <aryaniyappan2006@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Tests for the PostHog product analytics integration (issue #1418).

Covers:
- the enable gate matrix (flag x key x trace_privacy)
- bus-subscriber mapping to the exact GTM event contract
- fire-and-forget behaviour (client failures never propagate)
- settings-export / support-bundle allowlists (key redacted)
"""

from unittest.mock import MagicMock

import pytest

import services.product_analytics as pa
import services.product_analytics_handlers as handlers
from config import settings
from services.events import AgentCreated, UserCreated


@pytest.fixture(autouse=True)
def _reset_client():
    """Reset the lazily-initialized client between tests."""
    pa._client = None
    pa._init_attempted = False
    yield
    pa._client = None
    pa._init_attempted = False


def _fake_client():
    client = MagicMock()
    pa._client = client
    pa._init_attempted = True
    return client


# ── Gate matrix ──────────────────────────────────────────────────────


class TestGate:
    @pytest.mark.parametrize(
        ("enabled", "key", "expected"),
        [
            (False, "", False),
            (False, "phc_test", False),
            (True, "", False),
            (True, "phc_test", True),
        ],
    )
    def test_is_enabled_matrix(self, monkeypatch, enabled, key, expected):
        monkeypatch.setattr(settings, "PRODUCT_ANALYTICS_ENABLED", enabled)
        monkeypatch.setattr(settings, "POSTHOG_API_KEY", key)
        assert pa.is_enabled() is expected

    def test_default_settings_are_off(self):
        from config import Settings

        defaults = Settings.model_fields
        assert defaults["PRODUCT_ANALYTICS_ENABLED"].default is False
        assert defaults["POSTHOG_API_KEY"].default == ""
        assert defaults["POSTHOG_HOST"].default == "https://us.i.posthog.com"

    @pytest.mark.asyncio
    async def test_capture_is_noop_when_disabled(self, monkeypatch):
        monkeypatch.setattr(settings, "PRODUCT_ANALYTICS_ENABLED", False)
        monkeypatch.setattr(settings, "POSTHOG_API_KEY", "")
        # Must not raise and must not create a client
        await pa.capture("user-1", "user_signed_up", {"a": 1})
        assert pa._client is None

    @pytest.mark.asyncio
    async def test_handlers_short_circuit_when_disabled(self, monkeypatch):
        monkeypatch.setattr(handlers.product_analytics, "is_enabled", lambda: False)
        called = []

        async def fake_capture(*a, **kw):
            called.append(a)

        monkeypatch.setattr(handlers.product_analytics, "capture", fake_capture)
        await handlers._capture_user_signed_up(UserCreated(user_id="u1", email="a@b", role="user"))
        await handlers._capture_agent_registered(
            AgentCreated(agent_id="ag1", org_id="org1", category=None, created_by="u1")
        )
        assert called == []

    @pytest.mark.asyncio
    async def test_trace_private_org_drops_events(self, monkeypatch):
        monkeypatch.setattr(handlers.product_analytics, "is_enabled", lambda: True)

        async def private(_org_id):
            return True

        monkeypatch.setattr(handlers, "org_trace_private", private)
        called = []

        async def fake_capture(*a, **kw):
            called.append(a)

        monkeypatch.setattr(handlers.product_analytics, "capture", fake_capture)
        await handlers._capture_user_signed_up(UserCreated(user_id="u1", email="a@b", role="user", org_id="org1"))
        await handlers._capture_agent_registered(
            AgentCreated(agent_id="ag1", org_id="org1", category="coding", created_by="u1")
        )
        assert called == []


# ── Bus-subscriber mapping (exact GTM contract) ──────────────────────


@pytest.fixture
def captured(monkeypatch):
    events: list[tuple[str, str, dict]] = []

    async def fake_capture(distinct_id, event, properties=None):
        events.append((distinct_id, event, properties or {}))

    async def not_private(_org_id):
        return False

    monkeypatch.setattr(handlers.product_analytics, "is_enabled", lambda: True)
    monkeypatch.setattr(handlers.product_analytics, "capture", fake_capture)
    monkeypatch.setattr(handlers, "org_trace_private", not_private)
    return events


class TestSubscriberMapping:
    @pytest.mark.asyncio
    async def test_events_route_through_bus_to_capture(self, captured):
        """Bus dispatch routes UserCreated/AgentCreated to the PostHog handlers.

        Uses a fresh bus: other suites clear the global singleton's handlers.
        """
        from services.events import EventBus

        local_bus = EventBus()
        local_bus.register(UserCreated, handlers._capture_user_signed_up)
        local_bus.register(AgentCreated, handlers._capture_agent_registered)

        await local_bus.emit(UserCreated(user_id="u1", email="a@b", role="user", org_id="o1"))
        await local_bus.emit(AgentCreated(agent_id="ag1", org_id="o1", category=None, created_by="u1"))

        assert [(c[0], c[1]) for c in captured] == [("u1", "user_signed_up"), ("u1", "agent_registered")]

    @pytest.mark.asyncio
    async def test_user_signed_up_contract(self, captured):
        await handlers._capture_user_signed_up(
            UserCreated(
                user_id="user-uuid",
                email="a@b.com",
                role="user",
                org_id="org-uuid",
                auth_provider="oidc",
                utm_source="hn",
                utm_medium="social",
                utm_campaign="launch",
            )
        )
        assert captured == [
            (
                "user-uuid",
                "user_signed_up",
                {
                    "utm_source": "hn",
                    "utm_medium": "social",
                    "utm_campaign": "launch",
                    "auth_provider": "oidc",
                    "org_id": "org-uuid",
                },
            )
        ]

    @pytest.mark.asyncio
    async def test_user_signed_up_null_utms_for_provisioned_users(self, captured):
        await handlers._capture_user_signed_up(
            UserCreated(user_id="u1", email="a@b", role="user", org_id="org1", auth_provider="scim")
        )
        _, _, props = captured[0]
        assert props["utm_source"] is None
        assert props["utm_medium"] is None
        assert props["utm_campaign"] is None
        assert props["auth_provider"] == "scim"

    @pytest.mark.asyncio
    async def test_demo_accounts_emit_nothing(self, captured):
        await handlers._capture_user_signed_up(UserCreated(user_id="u1", email="demo@b", role="user", is_demo=True))
        assert captured == []

    @pytest.mark.asyncio
    async def test_agent_registered_contract(self, captured):
        await handlers._capture_agent_registered(
            AgentCreated(agent_id="agent-uuid", org_id="org-uuid", category="coding", created_by="user-uuid")
        )
        assert captured == [
            (
                "user-uuid",
                "agent_registered",
                {
                    "workspace_id": "org-uuid",
                    "agent_id": "agent-uuid",
                    "agent_type": "coding",
                },
            )
        ]

    @pytest.mark.asyncio
    async def test_no_pii_in_properties(self, captured):
        await handlers._capture_user_signed_up(
            UserCreated(user_id="u1", email="secret@example.com", role="user", org_id="org1")
        )
        _, _, props = captured[0]
        assert "email" not in props
        assert "name" not in props
        assert "secret@example.com" not in str(props.values())


# ── Capture behaviour ────────────────────────────────────────────────


class TestCapture:
    @pytest.mark.asyncio
    async def test_capture_nulls_ip(self):
        client = _fake_client()
        await pa.capture("u1", "user_signed_up", {"org_id": "o1"})
        client.capture.assert_called_once_with(
            event="user_signed_up",
            distinct_id="u1",
            properties={"org_id": "o1", "$ip": None},
        )

    @pytest.mark.asyncio
    async def test_capture_swallows_client_errors(self):
        client = _fake_client()
        client.capture.side_effect = RuntimeError("network down")
        # Must never raise into the request path
        await pa.capture("u1", "agent_registered", {})

    def test_shutdown_flushes_and_resets(self):
        client = _fake_client()
        pa.shutdown()
        client.shutdown.assert_called_once()
        assert pa._client is None
        assert pa._init_attempted is False

    def test_shutdown_swallows_errors(self):
        client = _fake_client()
        client.shutdown.side_effect = RuntimeError("boom")
        pa.shutdown()  # must not raise


# ── UTM threading through signup schemas ─────────────────────────────


class TestSchemas:
    def test_init_request_accepts_optional_utms(self):
        from schemas.auth import InitRequest

        req = InitRequest(email="a@b.com", name="A", utm_source="hn", utm_medium="social")
        assert req.utm_source == "hn"
        assert req.utm_medium == "social"
        assert req.utm_campaign is None

        # Omitted entirely -> all None (backward compatible)
        req2 = InitRequest(email="a@b.com", name="A")
        assert req2.utm_source is None

    def test_exchange_request_accepts_optional_utms(self):
        from schemas.auth import CodeExchangeRequest

        req = CodeExchangeRequest(code="x", utm_source="invite")
        assert req.utm_source == "invite"
        assert CodeExchangeRequest(code="x").utm_source is None

    def test_user_created_event_defaults(self):
        e = UserCreated(user_id="1", email="a@b", role="user")
        assert e.org_id is None
        assert e.auth_provider == "local"
        assert e.utm_source is None


# ── Settings export / support bundle ─────────────────────────────────


class TestSettingsExport:
    def test_server_support_allowlist_includes_analytics_keys(self):
        from api.routes.support import CONFIG_ALLOWLIST

        assert "PRODUCT_ANALYTICS_ENABLED" in CONFIG_ALLOWLIST
        assert "POSTHOG_API_KEY" in CONFIG_ALLOWLIST
        assert "POSTHOG_HOST" in CONFIG_ALLOWLIST

    def test_cli_support_allowlist_includes_analytics_keys(self):
        from observal_cli.cmd_support import CONFIG_ALLOWLIST

        assert "PRODUCT_ANALYTICS_ENABLED" in CONFIG_ALLOWLIST
        assert "POSTHOG_API_KEY" in CONFIG_ALLOWLIST
        assert "POSTHOG_HOST" in CONFIG_ALLOWLIST

    def test_posthog_api_key_value_is_redacted(self):
        from observal_cli.support.redaction import REDACTED, redact_value

        redacted, count = redact_value(
            {
                "PRODUCT_ANALYTICS_ENABLED": True,
                "POSTHOG_API_KEY": "phc_supersecretprojectkey",
                "POSTHOG_HOST": "https://us.i.posthog.com",
            }
        )
        assert redacted["POSTHOG_API_KEY"] == REDACTED
        assert count >= 1
        # Non-secret analytics settings remain readable for diagnostics
        assert redacted["PRODUCT_ANALYTICS_ENABLED"] is True
        assert redacted["POSTHOG_HOST"] == "https://us.i.posthog.com"
