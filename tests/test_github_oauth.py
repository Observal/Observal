# SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Tests for the GitHub OAuth provider.

Covers route gating when not configured, verified-email enforcement (the
profile 'email' field is never trusted), org-allowlist enforcement, user
provisioning with provider/subject metadata, and the allowed-orgs parser.
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


def _resp(status_code: int, json_data):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json = MagicMock(return_value=json_data)
    return resp


def _mock_github_client(
    profile: dict | None = None,
    emails: list | None = None,
    memberships: dict[str, tuple[int, dict]] | None = None,
    profile_status: int = 200,
    emails_status: int = 200,
):
    """memberships maps org slug -> (status_code, body) for user/memberships/orgs/{org}."""
    client = MagicMock()
    client.authorize_redirect = AsyncMock()
    client.authorize_access_token = AsyncMock(return_value={"access_token": "gho_test", "token_type": "bearer"})

    async def _get(path, token=None, headers=None):
        if path == "user":
            return _resp(profile_status, profile if profile is not None else {})
        if path == "user/emails":
            return _resp(emails_status, emails if emails is not None else [])
        if path.startswith("user/memberships/orgs/"):
            org = path.rsplit("/", 1)[-1]
            status, body = (memberships or {}).get(org, (404, {"message": "Not Found"}))
            return _resp(status, body)
        return _resp(404, {"message": "Not Found"})

    client.get = AsyncMock(side_effect=_get)
    return client


_PROFILE = {"id": 12345, "login": "alice-gh", "name": "Alice"}
_VERIFIED_PRIMARY = [{"email": "Alice@Acme.com", "primary": True, "verified": True}]


@pytest.fixture
async def github_client(monkeypatch):
    """Yields (httpx client, set_github) — set_github swaps oauth.github for the test."""
    limiter.enabled = False

    def set_github(client):
        monkeypatch.setattr(auth_module.oauth, "github", client, raising=False)

    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    ) as http:
        yield http, set_github

    app.dependency_overrides.clear()


def _patch_allowed_orgs(monkeypatch, value: str):
    monkeypatch.setattr(
        auth_module.ds,
        "get_sync",
        lambda key, default=None: value if key == "github.allowed_orgs" else default,
    )


class TestGithubOAuthNotConfigured:
    """Routes must 500 cleanly when GitHub OAuth is not configured."""

    @pytest.mark.asyncio
    async def test_login_returns_500_when_not_configured(self, github_client):
        http, set_github = github_client
        set_github(None)
        resp = await http.get("/api/v1/auth/oauth/github/login")
        assert resp.status_code == 500
        assert "not configured" in resp.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_callback_returns_500_when_not_configured(self, github_client):
        http, set_github = github_client
        set_github(None)
        resp = await http.get("/api/v1/auth/oauth/github/callback")
        assert resp.status_code == 500
        assert "not configured" in resp.json()["detail"].lower()


class TestGithubCallback:
    """The /oauth/github/callback handler validates profile and email data."""

    @pytest.mark.asyncio
    async def test_rejects_failed_profile_fetch(self, github_client):
        http, set_github = github_client
        set_github(_mock_github_client(profile_status=401))
        resp = await http.get("/api/v1/auth/oauth/github/callback")
        assert resp.status_code == 400
        assert "profile" in resp.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_rejects_profile_without_id(self, github_client):
        http, set_github = github_client
        set_github(_mock_github_client(profile={"login": "alice-gh"}, emails=_VERIFIED_PRIMARY))
        resp = await http.get("/api/v1/auth/oauth/github/callback")
        assert resp.status_code == 400
        assert "user id" in resp.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_rejects_when_no_verified_email(self, github_client):
        """A profile-level email must not rescue an account with zero verified addresses."""
        http, set_github = github_client
        set_github(
            _mock_github_client(
                profile={**_PROFILE, "email": "spoofed@acme.com"},
                emails=[{"email": "spoofed@acme.com", "primary": True, "verified": False}],
            )
        )
        resp = await http.get("/api/v1/auth/oauth/github/callback")
        assert resp.status_code == 400
        assert "verified" in resp.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_rejects_failed_emails_fetch(self, github_client):
        http, set_github = github_client
        set_github(_mock_github_client(profile=_PROFILE, emails_status=403))
        resp = await http.get("/api/v1/auth/oauth/github/callback")
        assert resp.status_code == 400
        assert "email" in resp.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_happy_path_provisions_with_github_provider(self, github_client, monkeypatch):
        http, set_github = github_client
        set_github(_mock_github_client(profile=_PROFILE, emails=_VERIFIED_PRIMARY))

        fake_user = MagicMock()
        fake_user.id = "u-1"
        fake_user.email = "alice@acme.com"
        fake_user.role = MagicMock(value="user")

        provision_mock = AsyncMock(return_value=fake_user)
        complete_mock = AsyncMock(return_value=RedirectResponse(url="http://test/login?code=xxx", status_code=302))
        monkeypatch.setattr(auth_module, "_provision_sso_user", provision_mock)
        monkeypatch.setattr(auth_module, "_complete_sso_login", complete_mock)

        resp = await http.get("/api/v1/auth/oauth/github/callback", follow_redirects=False)

        assert resp.status_code in (302, 307)
        provision_mock.assert_awaited_once()
        kwargs = provision_mock.await_args.kwargs
        assert kwargs["provider"] == "github"
        assert kwargs["email"] == "alice@acme.com"
        # Numeric GitHub id (stable), never the login handle (renamable).
        assert kwargs["subject_id"] == "12345"

    @pytest.mark.asyncio
    async def test_falls_back_to_any_verified_email(self, github_client, monkeypatch):
        http, set_github = github_client
        set_github(
            _mock_github_client(
                profile=_PROFILE,
                emails=[
                    {"email": "unverified@acme.com", "primary": True, "verified": False},
                    {"email": "backup@acme.com", "primary": False, "verified": True},
                ],
            )
        )

        fake_user = MagicMock()
        fake_user.id = "u-1"
        fake_user.email = "backup@acme.com"
        fake_user.role = MagicMock(value="user")
        provision_mock = AsyncMock(return_value=fake_user)
        monkeypatch.setattr(auth_module, "_provision_sso_user", provision_mock)
        monkeypatch.setattr(
            auth_module,
            "_complete_sso_login",
            AsyncMock(return_value=RedirectResponse(url="http://test/login?code=xxx", status_code=302)),
        )

        resp = await http.get("/api/v1/auth/oauth/github/callback", follow_redirects=False)

        assert resp.status_code in (302, 307)
        assert provision_mock.await_args.kwargs["email"] == "backup@acme.com"


class TestGithubOrgAllowlist:
    """github.allowed_orgs restricts logins to active members of listed orgs."""

    @pytest.mark.asyncio
    async def test_rejects_non_member(self, github_client, monkeypatch):
        http, set_github = github_client
        _patch_allowed_orgs(monkeypatch, "acme-inc")
        set_github(_mock_github_client(profile=_PROFILE, emails=_VERIFIED_PRIMARY, memberships={}))

        resp = await http.get("/api/v1/auth/oauth/github/callback")
        assert resp.status_code == 403
        assert "organization" in resp.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_rejects_pending_membership(self, github_client, monkeypatch):
        http, set_github = github_client
        _patch_allowed_orgs(monkeypatch, "acme-inc")
        set_github(
            _mock_github_client(
                profile=_PROFILE,
                emails=_VERIFIED_PRIMARY,
                memberships={"acme-inc": (200, {"state": "pending", "role": "member"})},
            )
        )

        resp = await http.get("/api/v1/auth/oauth/github/callback")
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_active_member_reaches_provisioning(self, github_client, monkeypatch):
        http, set_github = github_client
        _patch_allowed_orgs(monkeypatch, "acme-inc,other-org")
        set_github(
            _mock_github_client(
                profile=_PROFILE,
                emails=_VERIFIED_PRIMARY,
                memberships={"acme-inc": (200, {"state": "active", "role": "member"})},
            )
        )

        fake_user = MagicMock()
        fake_user.id = "u-1"
        fake_user.email = "alice@acme.com"
        fake_user.role = MagicMock(value="user")
        provision_mock = AsyncMock(return_value=fake_user)
        monkeypatch.setattr(auth_module, "_provision_sso_user", provision_mock)
        monkeypatch.setattr(
            auth_module,
            "_complete_sso_login",
            AsyncMock(return_value=RedirectResponse(url="http://test/login?code=xxx", status_code=302)),
        )

        resp = await http.get("/api/v1/auth/oauth/github/callback", follow_redirects=False)

        assert resp.status_code in (302, 307)
        provision_mock.assert_awaited_once()


class TestAllowedOrgsParser:
    """_github_allowed_orgs normalizes and validates the configured list."""

    def test_empty_input_returns_empty_set(self, monkeypatch):
        _patch_allowed_orgs(monkeypatch, "")
        assert auth_module._github_allowed_orgs() == set()

    def test_normalizes_case_whitespace_and_at_prefix(self, monkeypatch):
        _patch_allowed_orgs(monkeypatch, " @Acme-Inc , other-org ,")
        assert auth_module._github_allowed_orgs() == {"acme-inc", "other-org"}

    def test_drops_slugs_that_could_break_out_of_the_api_path(self, monkeypatch):
        _patch_allowed_orgs(monkeypatch, "good-org,bad/org,../evil,-leading,trailing-,a b")
        assert auth_module._github_allowed_orgs() == {"good-org"}


class TestGithubLoginRedirect:
    """When GitHub is configured, /oauth/github/login delegates to Authlib's authorize_redirect."""

    @pytest.mark.asyncio
    async def test_redirect_uri_targets_github_callback_path(self, github_client):
        from starlette.responses import Response as StarletteResponse

        http, set_github = github_client
        client = MagicMock()
        client.authorize_redirect = AsyncMock(return_value=StarletteResponse("ok"))
        set_github(client)

        resp = await http.get("/api/v1/auth/oauth/github/login")

        assert resp.status_code == 200
        client.authorize_redirect.assert_awaited_once()
        redirect_uri = client.authorize_redirect.await_args.args[1]
        assert redirect_uri.endswith("/api/v1/auth/oauth/github/callback")


class TestPublicConfigGithubFlag:
    """/config/public exposes github_sso_enabled."""

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
            monkeypatch.setattr(auth_module, "is_github_oauth_configured", lambda: True)
            async with AsyncClient(
                transport=ASGITransport(app=app, raise_app_exceptions=False),
                base_url="http://test",
            ) as http:
                resp = await http.get("/api/v1/config/public")

            assert resp.status_code == 200
            assert resp.json()["github_sso_enabled"] is True

            monkeypatch.setattr(auth_module, "is_github_oauth_configured", lambda: False)
            async with AsyncClient(
                transport=ASGITransport(app=app, raise_app_exceptions=False),
                base_url="http://test",
            ) as http:
                resp = await http.get("/api/v1/config/public")

            assert resp.json()["github_sso_enabled"] is False
        finally:
            app.dependency_overrides.clear()
