# SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Tests for the SSO settings robustness fixes (issues #1563-#1567).

- #1567: admin settings PUT trims wrapping whitespace before store.
- #1565: import_sso_env_once overwrites empty-string DB rows from env vars.
- #1566: POST /admin/restart is super-admin gated and schedules a SIGTERM.
- #1563: the SAML validate button runs the same enterprise-gate validator
  the login-time middleware runs.
"""

import signal
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

import services.dynamic_settings as dsm
from api.deps import require_super_admin
from api.ratelimit import limiter
from api.routes.admin import enterprise_settings as es
from api.routes.admin import system as system_module
from main import app
from models.enterprise_config import EnterpriseConfig
from schemas.admin import EnterpriseConfigUpdate
from services.crypto import init_key_manager


@pytest.fixture(autouse=True, scope="module")
def _init_key_manager(tmp_path_factory):
    key_dir = tmp_path_factory.mktemp("keys")
    init_key_manager(key_dir=str(key_dir), key_password=None)


# ── #1567: upsert_setting trims whitespace ───────────────────────────────


def _mock_db(existing=None):
    result = MagicMock()
    result.scalar_one_or_none.return_value = existing
    db = MagicMock()
    db.execute = AsyncMock(return_value=result)
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    return db


def _admin_user():
    user = MagicMock()
    user.id = "u-1"
    user.email = "admin@acme.com"
    user.role = MagicMock(value="admin")
    return user


class TestUpsertSettingTrimsWhitespace:
    @pytest.mark.asyncio
    async def test_plain_value_is_stripped_before_store(self, monkeypatch):
        db = _mock_db()
        monkeypatch.setattr(es.ds, "invalidate", AsyncMock())
        monkeypatch.setattr(es.ds, "refresh_sync_cache", AsyncMock())
        monkeypatch.setattr(es, "emit_security_event", AsyncMock())

        url = "https://idp.example.com/.well-known/openid-configuration"
        resp = await es.upsert_setting(
            "oauth.server_metadata_url",
            EnterpriseConfigUpdate(value=f"  {url} \n"),
            db=db,
            current_user=_admin_user(),
        )

        stored = db.add.call_args.args[0]
        assert stored.value == url
        assert resp.value == url

    @pytest.mark.asyncio
    async def test_sensitive_value_is_stripped_before_encryption(self, monkeypatch):
        db = _mock_db()
        monkeypatch.setattr(es.ds, "invalidate", AsyncMock())
        monkeypatch.setattr(es.ds, "refresh_sync_cache", AsyncMock())
        monkeypatch.setattr(es, "emit_security_event", AsyncMock())
        seen = []

        def fake_encrypt(value):
            seen.append(value)
            return f"enc:{value}"

        monkeypatch.setattr(es.ds, "encrypt_value", fake_encrypt)

        await es.upsert_setting(
            "oauth.client_secret",
            EnterpriseConfigUpdate(value=" super-secret "),
            db=db,
            current_user=_admin_user(),
        )

        assert seen == ["super-secret"]
        assert db.add.call_args.args[0].value == "enc:super-secret"

    @pytest.mark.asyncio
    async def test_multiline_cert_keeps_interior_newlines(self, monkeypatch):
        db = _mock_db()
        monkeypatch.setattr(es.ds, "invalidate", AsyncMock())
        monkeypatch.setattr(es.ds, "refresh_sync_cache", AsyncMock())
        monkeypatch.setattr(es, "emit_security_event", AsyncMock())
        seen = []
        monkeypatch.setattr(es.ds, "encrypt_value", lambda v: seen.append(v) or v)

        pem = "-----BEGIN CERTIFICATE-----\nMIIB...\n-----END CERTIFICATE-----"
        await es.upsert_setting(
            "saml.idp_x509_cert",
            EnterpriseConfigUpdate(value=f"\n{pem}\n\n"),
            db=db,
            current_user=_admin_user(),
        )

        assert seen == [pem]


# ── #1565: import_sso_env_once and empty rows ────────────────────────────


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        scalars = MagicMock()
        scalars.all.return_value = self._rows
        return scalars


class _FakeSession:
    def __init__(self, rows):
        self._rows = rows
        self.added = []
        self.commits = 0

    async def execute(self, stmt):
        return _FakeResult(self._rows)

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        self.commits += 1


class _FakeSessionCtx:
    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, *exc):
        return False


def _patch_env_import(monkeypatch, session):
    import database

    monkeypatch.setattr(database, "async_session", lambda: _FakeSessionCtx(session))
    monkeypatch.setattr(dsm, "invalidate_all", AsyncMock())
    monkeypatch.setattr(dsm, "refresh_sync_cache", AsyncMock())
    for env_key in dsm.SSO_ENV_IMPORTS:
        monkeypatch.delenv(env_key, raising=False)


class TestImportSsoEnvOnce:
    @pytest.mark.asyncio
    async def test_env_var_overwrites_empty_row(self, monkeypatch):
        empty_row = EnterpriseConfig(key="oauth.server_metadata_url", value="")
        session = _FakeSession([empty_row])
        _patch_env_import(monkeypatch, session)
        monkeypatch.setenv(
            "OAUTH_SERVER_METADATA_URL",
            " https://idp.example.com/.well-known/openid-configuration ",
        )

        imported = await dsm.import_sso_env_once()

        assert imported == 1
        # Row updated in place (no duplicate insert) and value stripped.
        assert empty_row.value == "https://idp.example.com/.well-known/openid-configuration"
        assert session.added == []
        assert session.commits == 1

    @pytest.mark.asyncio
    async def test_non_empty_db_value_wins_over_env(self, monkeypatch):
        filled_row = EnterpriseConfig(key="oauth.client_id", value="db-client-id")
        session = _FakeSession([filled_row])
        _patch_env_import(monkeypatch, session)
        monkeypatch.setenv("OAUTH_CLIENT_ID", "env-client-id")

        imported = await dsm.import_sso_env_once()

        assert imported == 0
        assert filled_row.value == "db-client-id"
        assert session.commits == 0

    @pytest.mark.asyncio
    async def test_missing_row_is_created_from_env(self, monkeypatch):
        session = _FakeSession([])
        _patch_env_import(monkeypatch, session)
        monkeypatch.setenv("GITHUB_OAUTH_CLIENT_ID", "Iv1.test123")

        imported = await dsm.import_sso_env_once()

        assert imported == 1
        assert len(session.added) == 1
        assert session.added[0].key == "github.client_id"
        assert session.added[0].value == "Iv1.test123"

    @pytest.mark.asyncio
    async def test_whitespace_only_env_var_is_ignored(self, monkeypatch):
        session = _FakeSession([])
        _patch_env_import(monkeypatch, session)
        monkeypatch.setenv("OAUTH_CLIENT_ID", "   ")

        imported = await dsm.import_sso_env_once()

        assert imported == 0
        assert session.added == []


# ── #1566: POST /admin/restart ───────────────────────────────────────────


class TestRestartEndpoint:
    @pytest.mark.asyncio
    async def test_requires_authentication(self):
        limiter.enabled = False
        async with AsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://test",
        ) as http:
            resp = await http.post("/api/v1/admin/restart")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_super_admin_gets_202_and_sigterm_is_scheduled(self, monkeypatch):
        limiter.enabled = False
        user = MagicMock()
        user.id = "u-root"
        user.email = "root@acme.com"
        user.role = MagicMock(value="super_admin")

        scheduled = []
        fake_loop = MagicMock()
        fake_loop.call_later = lambda delay, fn, *args: scheduled.append((delay, fn))
        fake_asyncio = MagicMock()
        fake_asyncio.get_running_loop = lambda: fake_loop
        monkeypatch.setattr(system_module, "asyncio", fake_asyncio)
        monkeypatch.setattr(system_module, "emit_security_event", AsyncMock())

        app.dependency_overrides[require_super_admin] = lambda: user
        try:
            async with AsyncClient(
                transport=ASGITransport(app=app, raise_app_exceptions=False),
                base_url="http://test",
            ) as http:
                resp = await http.post("/api/v1/admin/restart")
        finally:
            app.dependency_overrides.clear()

        assert resp.status_code == 202
        assert resp.json()["detail"] == "API restart scheduled"
        assert scheduled == [(system_module._RESTART_DELAY_SECONDS, system_module._terminate_api_process)]


class TestTerminateApiProcess:
    """Target selection: container tree root vs dev process."""

    def _run(self, monkeypatch, pid, ppid):
        killed = []
        monkeypatch.setattr(system_module.os, "getpid", lambda: pid)
        monkeypatch.setattr(system_module.os, "getppid", lambda: ppid)
        monkeypatch.setattr(system_module.os, "kill", lambda p, sig: killed.append((p, sig)))
        system_module._terminate_api_process()
        return killed

    def test_dev_mode_only_kills_own_process(self, monkeypatch):
        assert self._run(monkeypatch, pid=500, ppid=400) == [(500, signal.SIGTERM)]

    def test_worker_under_pid1_master_kills_master(self, monkeypatch):
        assert self._run(monkeypatch, pid=7, ppid=1) == [(1, signal.SIGTERM)]

    def test_single_process_container_kills_pid1_self(self, monkeypatch):
        assert self._run(monkeypatch, pid=1, ppid=0) == [(1, signal.SIGTERM)]


# ── #1563: SAML validation runs the enterprise-gate validator ────────────


class TestEnterpriseGateCheck:
    @pytest.mark.asyncio
    async def test_passes_when_validator_finds_no_issues(self, monkeypatch):
        import ee.observal_server.services.config_validator as cv
        from ee.observal_server.routes import admin_sso

        monkeypatch.setattr(cv, "validate_enterprise_config_async", AsyncMock(return_value=[]))
        check = await admin_sso._enterprise_gate_check()
        assert check["status"] == "pass"

    @pytest.mark.asyncio
    async def test_fails_with_joined_issues_when_gate_would_503(self, monkeypatch):
        import ee.observal_server.services.config_validator as cv
        from ee.observal_server.routes import admin_sso

        issues = [
            "saml.sp_key_encryption_password is not set (required when SAML IdP is configured)",
            "deployment.frontend_url is localhost or empty",
        ]
        monkeypatch.setattr(cv, "validate_enterprise_config_async", AsyncMock(return_value=issues))
        check = await admin_sso._enterprise_gate_check()
        assert check["status"] == "fail"
        assert "sp_key_encryption_password" in check["message"]
        assert "frontend_url" in check["message"]
        assert "503" in check["hint"]
