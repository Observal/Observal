# SPDX-FileCopyrightText: 2026 Apoorv Garg <apoorvgarg.work@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Tests for the Google OAuth provider.

Covers route gating when not configured, email_verified enforcement, domain
allowlist enforcement, user provisioning with provider/subject metadata, and
the domain-allowlist parser.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.responses import RedirectResponse
from httpx import ASGITransport, AsyncClient

from api.ratelimit import limiter
from api.routes import auth as auth_module
from main import app
from services.crypto import init_key_manager


@pytest.fixture(autouse=True, scope="module")
def _init_key_manager(tmp_path_factory):
    key_dir = tmp_path_factory.mktemp("keys")
    init_key_manager(key_dir=str(key_dir), key_password=None)


def _mock_google_client(userinfo: dict | None = None):
    client = MagicMock()
    client.authorize_redirect = AsyncMock()
    client.authorize_access_token = AsyncMock(return_value={"userinfo": userinfo} if userinfo is not None else {})
    return client


@pytest.fixture
async def google_client(monkeypatch):
    """Yields (httpx client, set_google) — set_google swaps oauth.google for the test."""
    limiter.enabled = False

    def set_google(client):
        monkeypatch.setattr(auth_module.oauth, "google", client, raising=False)

    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    ) as http:
        yield http, set_google

    app.dependency_overrides.clear()


class TestGoogleOAuthNotConfigured:
    """Routes must 500 cleanly when Google OAuth env vars are unset."""

    @pytest.mark.asyncio
    async def test_login_returns_500_when_not_configured(self, google_client):
        http, set_google = google_client
        set_google(None)
        resp = await http.get("/api/v1/auth/oauth/google/login")
        assert resp.status_code == 500
        assert "not configured" in resp.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_callback_returns_500_when_not_configured(self, google_client):
        http, set_google = google_client
        set_google(None)
        resp = await http.get("/api/v1/auth/oauth/google/callback")
        assert resp.status_code == 500
        assert "not configured" in resp.json()["detail"].lower()


class TestGoogleCallback:
    """The /oauth/google/callback handler validates the ID-token claims."""

    @pytest.mark.asyncio
    async def test_rejects_missing_userinfo(self, google_client):
        http, set_google = google_client
        set_google(_mock_google_client())
        resp = await http.get("/api/v1/auth/oauth/google/callback")
        assert resp.status_code == 400
        assert "missing userinfo" in resp.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_rejects_missing_email_claim(self, google_client):
        http, set_google = google_client
        set_google(_mock_google_client({"sub": "g-123", "name": "Bob"}))
        resp = await http.get("/api/v1/auth/oauth/google/callback")
        assert resp.status_code == 400
        assert "email" in resp.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_rejects_unverified_email(self, google_client):
        http, set_google = google_client
        set_google(
            _mock_google_client(
                {
                    "sub": "g-123",
                    "email": "bob@acme.com",
                    "email_verified": False,
                    "name": "Bob",
                }
            )
        )
        resp = await http.get("/api/v1/auth/oauth/google/callback")
        assert resp.status_code == 400
        assert "not verified" in resp.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_rejects_disallowed_domain(self, google_client, monkeypatch):
        http, set_google = google_client
        monkeypatch.setattr(
            auth_module.ds,
            "get_sync",
            lambda key, default=None: "acme.com,acme.io" if key == "google.allowed_domains" else default,
        )
        set_google(
            _mock_google_client(
                {
                    "sub": "g-123",
                    "email": "bob@gmail.com",
                    "email_verified": True,
                    "name": "Bob",
                }
            )
        )
        resp = await http.get("/api/v1/auth/oauth/google/callback")
        assert resp.status_code == 403
        assert "domain" in resp.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_allowlisted_domain_reaches_provisioning(self, google_client, monkeypatch):
        """Happy path: claim validation passes, provisioner is called with provider='google'."""
        http, set_google = google_client
        monkeypatch.setattr(
            auth_module.ds,
            "get_sync",
            lambda key, default=None: "acme.com" if key == "google.allowed_domains" else default,
        )
        set_google(
            _mock_google_client(
                {
                    "sub": "g-123",
                    "email": "Alice@Acme.com",
                    "email_verified": True,
                    "name": "Alice",
                }
            )
        )

        fake_user = MagicMock()
        fake_user.id = "u-1"
        fake_user.email = "alice@acme.com"
        fake_user.role = MagicMock(value="user")

        provision_mock = AsyncMock(return_value=fake_user)
        complete_mock = AsyncMock(return_value=RedirectResponse(url="http://test/login?code=xxx", status_code=302))
        monkeypatch.setattr(auth_module, "_provision_sso_user", provision_mock)
        monkeypatch.setattr(auth_module, "_complete_sso_login", complete_mock)

        resp = await http.get("/api/v1/auth/oauth/google/callback", follow_redirects=False)

        assert resp.status_code in (302, 307)
        provision_mock.assert_awaited_once()
        kwargs = provision_mock.await_args.kwargs
        assert kwargs["provider"] == "google"
        assert kwargs["email"] == "alice@acme.com"
        assert kwargs["subject_id"] == "g-123"


class TestAllowedDomainsParser:
    """_parse_allowed_domains normalizes the env-supplied list."""

    def test_empty_input_returns_empty_set(self):
        assert auth_module._parse_allowed_domains(None) == set()
        assert auth_module._parse_allowed_domains("") == set()
        assert auth_module._parse_allowed_domains("   ,  ") == set()

    def test_comma_separated_input_is_lowercased_and_stripped(self):
        assert auth_module._parse_allowed_domains("Acme.com, ACME.io ,  ") == {"acme.com", "acme.io"}


class TestIsSafeNext:
    """`_is_safe_next` guards the post-OAuth redirect from open-redirect payloads."""

    @pytest.mark.parametrize(
        "value",
        [None, "", "no-leading-slash", "https://evil.com", "//evil.com/path", "/back\\slash"],
    )
    def test_rejects_unsafe_or_missing(self, value):
        assert auth_module._is_safe_next(value) is False

    @pytest.mark.parametrize("value", ["/", "/device", "/login?code=abc", "/admin/users/123"])
    def test_accepts_local_paths(self, value):
        assert auth_module._is_safe_next(value) is True


class TestGoogleLoginRedirect:
    """When Google is configured, /oauth/google/login delegates to Authlib's authorize_redirect."""

    @pytest.mark.asyncio
    async def test_redirect_uri_targets_google_callback_path(self, google_client):
        from starlette.responses import Response as StarletteResponse

        http, set_google = google_client
        client = MagicMock()
        client.authorize_redirect = AsyncMock(return_value=StarletteResponse("ok"))
        set_google(client)

        resp = await http.get("/api/v1/auth/oauth/google/login")

        assert resp.status_code == 200
        client.authorize_redirect.assert_awaited_once()
        # authorize_redirect(request, redirect_uri) — redirect_uri is positional arg 1.
        redirect_uri = client.authorize_redirect.await_args.args[1]
        assert redirect_uri.endswith("/api/v1/auth/oauth/google/callback")


class TestOidcCallback:
    """The generic OIDC callback keeps the diagnostics redirect behavior from main."""

    @pytest.mark.asyncio
    async def test_callback_redirects_with_diagnostics_when_not_configured(self, monkeypatch):
        from httpx import ASGITransport, AsyncClient

        monkeypatch.setattr(auth_module.oauth, "oidc", None, raising=False)
        async with AsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://test",
        ) as http:
            resp = await http.get("/api/v1/auth/oauth/callback", follow_redirects=False)
        assert resp.status_code in (302, 307)
        assert "sso_error=" in resp.headers["location"]


class TestProvisionSsoUser:
    """The shared SSO provisioning helper — covers create/lookup/upgrade branches."""

    def _mock_db_with_existing(self, existing_user):
        result = MagicMock()
        result.scalar_one_or_none.return_value = existing_user
        db = MagicMock()
        db.execute = AsyncMock(return_value=result)
        db.flush = AsyncMock()
        db.rollback = AsyncMock()
        return db

    @pytest.mark.asyncio
    async def test_creates_new_user_with_provider_and_subject(self, monkeypatch):
        db = self._mock_db_with_existing(None)
        default_org = MagicMock(id="org-1")
        monkeypatch.setattr(auth_module, "get_or_create_default_org", AsyncMock(return_value=default_org))
        monkeypatch.setattr(auth_module, "generate_unique_username", AsyncMock(return_value="alice"))

        user = await auth_module._provision_sso_user(
            db,
            email="alice@acme.com",
            name="Alice",
            groups=None,
            provider="google",
            subject_id="g-sub-1",
        )

        db.add.assert_called_once()
        added = db.add.call_args.args[0]
        assert added.email == "alice@acme.com"
        assert added.auth_provider == "google"
        assert added.sso_subject_id == "g-sub-1"
        assert added.org_id == "org-1"
        assert user is added

    @pytest.mark.asyncio
    async def test_returns_existing_user_unchanged_when_already_provisioned(self):
        existing = MagicMock()
        existing.auth_provider = "google"
        existing.sso_subject_id = "g-sub-old"
        db = self._mock_db_with_existing(existing)

        user = await auth_module._provision_sso_user(
            db,
            email="alice@acme.com",
            name="Alice",
            groups=None,
            provider="google",
            subject_id="g-sub-new",
        )

        assert user is existing
        assert existing.sso_subject_id == "g-sub-old"
        db.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_upgrades_local_user_on_first_sso_signin(self):
        existing = MagicMock()
        existing.auth_provider = "local"
        existing.sso_subject_id = None
        db = self._mock_db_with_existing(existing)

        await auth_module._provision_sso_user(
            db,
            email="alice@acme.com",
            name="Alice",
            groups=None,
            provider="google",
            subject_id="g-sub-fresh",
        )

        assert existing.auth_provider == "google"
        assert existing.sso_subject_id == "g-sub-fresh"


class TestCompleteSsoLogin:
    """Happy path for _complete_sso_login — verifies commit-then-emit ordering and the redirect."""

    @pytest.mark.asyncio
    async def test_emits_success_after_commit_and_redirects_with_code(self, monkeypatch):
        request = MagicMock()
        request.session = {}
        user = MagicMock()
        user.id = "u-1"
        user.email = "alice@acme.com"
        user.role = MagicMock(value="user")

        order: list[str] = []

        async def fake_commit():
            order.append("commit")

        db = MagicMock()
        db.commit = fake_commit

        fake_redis = MagicMock()

        async def fake_setex(*args, **kwargs):
            order.append("setex")

        fake_redis.setex = fake_setex

        async def fake_emit(_event):
            order.append("emit")

        monkeypatch.setattr(auth_module, "_issue_tokens", AsyncMock(return_value=("access", "refresh", 3600)))
        monkeypatch.setattr(auth_module, "get_redis", lambda: fake_redis)
        monkeypatch.setattr(auth_module, "_extract_request_info", lambda _r: ("1.2.3.4", "ua-test"))
        monkeypatch.setattr(auth_module, "emit_security_event", fake_emit)
        monkeypatch.setattr(auth_module.ds, "get_sync", lambda _k, default: "http://localhost:3000")

        resp = await auth_module._complete_sso_login(request, db, user, None)

        assert order == ["commit", "setex", "emit"]
        assert resp.status_code == 307
        assert "/login?code=" in resp.headers["location"]


class TestPublicConfigGoogleFlag:
    """/config/public exposes google_sso_enabled."""

    @pytest.mark.asyncio
    async def test_flag_reflects_oauth_client_state(self, monkeypatch):
        from api.deps import get_db

        result = MagicMock()
        result.scalars.return_value = MagicMock(all=lambda: [])
        result.scalar_one_or_none.return_value = None
        db = AsyncMock()
        db.execute = AsyncMock(return_value=result)

        async def _mock_get_db():
            yield db

        app.dependency_overrides[get_db] = _mock_get_db

        try:
            monkeypatch.setattr(auth_module, "is_google_oauth_configured", lambda: True)
            async with AsyncClient(
                transport=ASGITransport(app=app, raise_app_exceptions=False),
                base_url="http://test",
            ) as http:
                resp = await http.get("/api/v1/config/public")

            assert resp.status_code == 200
            assert resp.json()["google_sso_enabled"] is True

            monkeypatch.setattr(auth_module, "is_google_oauth_configured", lambda: False)
            async with AsyncClient(
                transport=ASGITransport(app=app, raise_app_exceptions=False),
                base_url="http://test",
            ) as http:
                resp = await http.get("/api/v1/config/public")

            assert resp.json()["google_sso_enabled"] is False
        finally:
            app.dependency_overrides.clear()
