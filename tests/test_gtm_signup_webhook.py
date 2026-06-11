# SPDX-FileCopyrightText: 2026 Aryan Iyappan <aryaniyappan2006@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Tests for the GTM signup webhook integration (issue #1421)."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

import services.gtm_signup_handlers as gtm_handlers
import services.gtm_signup_webhook as gtm_webhook
from config import settings
from services.events import UserCreated


@pytest.fixture(autouse=True)
def _public_gtm_url(monkeypatch):
    """Use a stable public URL so SSRF guard does not block tests."""
    monkeypatch.setattr(
        settings,
        "GTM_SIGNUP_WEBHOOK_URL",
        "https://gtm.useobserval.xyz/webhooks/signup",
    )


class TestGate:
    def test_default_settings_are_off(self):
        from config import Settings

        defaults = Settings.model_fields
        assert defaults["GTM_SIGNUP_WEBHOOK_ENABLED"].default is False
        assert defaults["GTM_SIGNUP_WEBHOOK_URL"].default == "https://gtm.useobserval.xyz/webhooks/signup"
        assert defaults["GTM_SIGNUP_WEBHOOK_SECRET"].default == ""
        assert defaults["GTM_SIGNUP_WEBHOOK_TIMEOUT_SEC"].default == 5.0

    def test_is_enabled_matrix(self, monkeypatch):
        monkeypatch.setattr(settings, "GTM_SIGNUP_WEBHOOK_ENABLED", False)
        assert gtm_webhook.is_enabled() is False
        monkeypatch.setattr(settings, "GTM_SIGNUP_WEBHOOK_ENABLED", True)
        assert gtm_webhook.is_enabled() is True


class TestPayload:
    def test_build_payload_lowercases_email_and_omits_empty_optionals(self):
        payload = gtm_webhook._build_payload(email="Founder@Acme.COM", name=None, company=None)
        assert payload == {"email": "founder@acme.com"}

    def test_build_payload_includes_name_and_company(self):
        payload = gtm_webhook._build_payload(email="a@b.com", name="Jane", company="Acme")
        assert payload == {"email": "a@b.com", "name": "Jane", "company": "Acme"}


class TestNotify:
    @pytest.mark.asyncio
    async def test_notify_posts_json_payload(self, monkeypatch):
        monkeypatch.setattr(settings, "GTM_SIGNUP_WEBHOOK_ENABLED", True)
        monkeypatch.setattr(settings, "GTM_SIGNUP_WEBHOOK_SECRET", "")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("services.gtm_signup_webhook.httpx.AsyncClient", return_value=mock_client):
            await gtm_webhook.notify_gtm_signup(email="Jane@acme.com", name="Jane", company="Acme")

        mock_client.post.assert_awaited_once()
        call_kwargs = mock_client.post.await_args.kwargs
        body = call_kwargs["content"]
        assert json.loads(body) == {"email": "jane@acme.com", "name": "Jane", "company": "Acme"}
        assert call_kwargs["headers"]["Content-Type"] == "application/json"
        assert "X-GTM-Signature" not in call_kwargs["headers"]

    @pytest.mark.asyncio
    async def test_notify_adds_hmac_signature_when_secret_set(self, monkeypatch):
        monkeypatch.setattr(settings, "GTM_SIGNUP_WEBHOOK_ENABLED", True)
        monkeypatch.setattr(settings, "GTM_SIGNUP_WEBHOOK_SECRET", "test-secret")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("services.gtm_signup_webhook.httpx.AsyncClient", return_value=mock_client):
            await gtm_webhook.notify_gtm_signup(email="a@b.com", name=None, company=None)

        headers = mock_client.post.await_args.kwargs["headers"]
        assert headers["X-GTM-Signature"].startswith("sha256=")

    @pytest.mark.asyncio
    async def test_notify_swallows_http_errors(self, monkeypatch):
        monkeypatch.setattr(settings, "GTM_SIGNUP_WEBHOOK_ENABLED", True)

        mock_response = MagicMock()
        mock_response.status_code = 503
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("services.gtm_signup_webhook.httpx.AsyncClient", return_value=mock_client):
            await gtm_webhook.notify_gtm_signup(email="a@b.com", name=None, company=None)

    @pytest.mark.asyncio
    async def test_notify_swallows_timeouts(self, monkeypatch):
        monkeypatch.setattr(settings, "GTM_SIGNUP_WEBHOOK_ENABLED", True)

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=httpx.ReadTimeout("slow"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("services.gtm_signup_webhook.httpx.AsyncClient", return_value=mock_client):
            await gtm_webhook.notify_gtm_signup(email="a@b.com", name=None, company=None)

    @pytest.mark.asyncio
    async def test_notify_blocks_private_urls(self, monkeypatch):
        monkeypatch.setattr(settings, "GTM_SIGNUP_WEBHOOK_ENABLED", True)
        monkeypatch.setattr(settings, "GTM_SIGNUP_WEBHOOK_URL", "http://127.0.0.1/webhooks/signup")

        with patch("services.gtm_signup_webhook.httpx.AsyncClient") as mock_cls:
            await gtm_webhook.notify_gtm_signup(email="a@b.com", name=None, company=None)
            mock_cls.assert_not_called()


class TestHandlers:
    @pytest.mark.asyncio
    async def test_handler_schedules_notify_when_enabled(self, monkeypatch):
        monkeypatch.setattr(gtm_webhook, "is_enabled", lambda: True)

        async def not_private(_org_id):
            return False

        async def org_name(_org_id):
            return "Acme Corp"

        monkeypatch.setattr(gtm_handlers, "org_trace_private", not_private)
        monkeypatch.setattr(gtm_handlers, "resolve_org_name", org_name)
        scheduled: list[dict] = []
        monkeypatch.setattr(
            gtm_webhook,
            "schedule_gtm_signup_notify",
            lambda **kwargs: scheduled.append(kwargs),
        )

        await gtm_handlers.on_user_created_gtm(
            UserCreated(
                user_id="u1",
                email="founder@acme.com",
                role="user",
                name="Jane Doe",
                org_id="org1",
                auth_provider="oidc",
            )
        )
        assert scheduled == [
            {
                "email": "founder@acme.com",
                "name": "Jane Doe",
                "company": "Acme Corp",
            }
        ]

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "event",
        [
            UserCreated(user_id="u1", email="a@b.com", role="user", is_demo=True),
            UserCreated(user_id="u1", email="a@b.com", role="user", auth_provider="scim"),
            UserCreated(user_id="u1", email="admin@localhost", role="user"),
        ],
    )
    async def test_handler_skips_ineligible_signups(self, monkeypatch, event):
        monkeypatch.setattr(gtm_webhook, "is_enabled", lambda: True)
        monkeypatch.setattr(gtm_handlers, "org_trace_private", AsyncMock(return_value=False))
        scheduled: list[dict] = []
        monkeypatch.setattr(
            gtm_webhook,
            "schedule_gtm_signup_notify",
            lambda **kwargs: scheduled.append(kwargs),
        )

        await gtm_handlers.on_user_created_gtm(event)
        assert scheduled == []

    @pytest.mark.asyncio
    async def test_handler_skips_trace_private_orgs(self, monkeypatch):
        monkeypatch.setattr(gtm_webhook, "is_enabled", lambda: True)
        monkeypatch.setattr(gtm_handlers, "org_trace_private", AsyncMock(return_value=True))
        scheduled: list[dict] = []
        monkeypatch.setattr(
            gtm_webhook,
            "schedule_gtm_signup_notify",
            lambda **kwargs: scheduled.append(kwargs),
        )

        await gtm_handlers.on_user_created_gtm(
            UserCreated(user_id="u1", email="a@b.com", role="user", org_id="org1")
        )
        assert scheduled == []

    @pytest.mark.asyncio
    async def test_handler_short_circuits_when_disabled(self, monkeypatch):
        monkeypatch.setattr(gtm_webhook, "is_enabled", lambda: False)
        scheduled: list[dict] = []
        monkeypatch.setattr(
            gtm_webhook,
            "schedule_gtm_signup_notify",
            lambda **kwargs: scheduled.append(kwargs),
        )

        await gtm_handlers.on_user_created_gtm(
            UserCreated(user_id="u1", email="a@b.com", role="user", name="A")
        )
        assert scheduled == []

    def test_schedule_uses_create_task(self, monkeypatch):
        monkeypatch.setattr(gtm_webhook, "is_enabled", lambda: True)
        created: list = []

        def fake_create_task(coro, *, name=None):
            created.append(name)
            coro.close()
            return MagicMock()

        monkeypatch.setattr(gtm_webhook.asyncio, "create_task", fake_create_task)
        gtm_webhook.schedule_gtm_signup_notify(email="a@b.com", name="A", company=None)
        assert created == ["gtm-signup-webhook"]
