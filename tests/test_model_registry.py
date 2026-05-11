# SPDX-FileCopyrightText: 2026 Aryan Iyappan <aryaniyappan2006@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Tests for the live model catalog + resolver.

Covers:

* ``services.model_catalog.format_for_ide`` — per-IDE formatting rules.
* ``services.model_catalog._normalize_models_dev`` — payload normalization.
* ``services.model_resolver.resolve_saved_value`` — sync, used by the offline
  manifest builder.
* ``services.model_resolver.resolve_model_for_ide`` — async, used by online
  installs (covers fallback matrix: unknown id, wrong-provider, deprecated,
  Claude Code aliases, "ignored override" for IDEs that don't accept models).
* The CLI helper ``observal_cli.cmd_pull._parse_model_overrides``.
* GET ``/api/v1/models`` ETag round-trip + admin refresh role check.

We avoid hitting Redis or the real upstream by patching ``get_catalog`` /
``get_redis``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

# ──────────────────────── Helpers ────────────────────────────


def _build_catalog(*, degraded: bool = False, source: str = "live"):
    from schemas.models import Catalog, CatalogModel

    models = [
        CatalogModel(
            model_id="claude-sonnet-4-5",
            display_name="Claude Sonnet 4.5",
            provider="anthropic",
            family="claude-sonnet",
            release_date=date(2025, 9, 29),
            supported_ides=["claude-code", "kiro", "opencode"],
        ),
        CatalogModel(
            model_id="gpt-5",
            display_name="GPT-5",
            provider="openai",
            family="gpt",
            release_date=date(2025, 8, 1),
            supported_ides=["codex", "opencode"],
        ),
        CatalogModel(
            model_id="gemini-2.5-pro",
            display_name="Gemini 2.5 Pro",
            provider="google",
            family="gemini",
            supported_ides=["gemini-cli", "opencode"],
        ),
        CatalogModel(
            model_id="claude-opus-3-deprecated",
            display_name="Claude Opus 3 (deprecated)",
            provider="anthropic",
            family="claude-opus",
            supported_ides=["claude-code", "kiro", "opencode"],
            deprecated=True,
        ),
    ]
    return Catalog(
        models=models,
        fetched_at=datetime.now(UTC),
        source=source,  # type: ignore[arg-type]
        degraded=degraded,
        etag='W/"abc"',
        upstream_etag='W/"upstream"',
        model_count=len(models),
    )


# ──────────────────────── format_for_ide ────────────────────


class TestFormatForIde:
    def test_claude_code_short_alias(self):
        from services.model_catalog import format_for_ide

        assert format_for_ide("claude-sonnet-4-5", "anthropic", "claude-code") == "sonnet"
        assert format_for_ide("claude-opus-3", "anthropic", "claude-code") == "opus"
        assert format_for_ide("claude-haiku-3", "anthropic", "claude-code") == "haiku"

    def test_claude_code_passthrough_when_unknown(self):
        from services.model_catalog import format_for_ide

        assert format_for_ide("custom-model", "anthropic", "claude-code") == "custom-model"

    def test_opencode_uses_provider_prefix(self):
        from services.model_catalog import format_for_ide

        assert format_for_ide("claude-sonnet-4-5", "anthropic", "opencode") == "anthropic/claude-sonnet-4-5"
        assert format_for_ide("gpt-5", "openai", "opencode") == "openai/gpt-5"

    def test_other_ides_pass_id_verbatim(self):
        from services.model_catalog import format_for_ide

        assert format_for_ide("claude-sonnet-4-5", "anthropic", "kiro") == "claude-sonnet-4-5"
        assert format_for_ide("gpt-5", "openai", "codex") == "gpt-5"
        assert format_for_ide("gemini-2.5-pro", "google", "gemini-cli") == "gemini-2.5-pro"


# ──────────────────────── _normalize_models_dev ─────────────


class TestNormalizeModelsDev:
    def test_emits_only_mapped_providers(self):
        from services.model_catalog import _normalize_models_dev

        payload = {
            "anthropic": {
                "models": {
                    "claude-sonnet-4-5": {
                        "id": "claude-sonnet-4-5",
                        "name": "Claude Sonnet 4.5",
                        "family": "claude-sonnet",
                        "tool_call": True,
                        "modalities": {"input": ["text", "image"]},
                        "limit": {"context": 200000, "output": 8192},
                        "cost": {"input": 3.0, "output": 15.0},
                    }
                }
            },
            "unmapped-provider": {"models": {"foo": {"id": "foo", "name": "Foo"}}},
        }
        rows = _normalize_models_dev(payload)
        assert len(rows) == 1
        row = rows[0]
        assert row.model_id == "claude-sonnet-4-5"
        assert row.provider == "anthropic"
        assert "tool_call" in row.capabilities
        assert "vision" in row.capabilities
        assert row.context_window == 200000
        assert row.cost_input == 3.0
        assert "claude-code" in row.supported_ides

    def test_skips_non_dict_models(self):
        from services.model_catalog import _normalize_models_dev

        payload = {"anthropic": {"models": {"weird": "string", "ok": {"id": "ok", "name": "OK"}}}}
        rows = _normalize_models_dev(payload)
        assert [r.model_id for r in rows] == ["ok"]


# ──────────────────────── resolve_saved_value ───────────────


class TestResolveSavedValue:
    def test_returns_none_for_ides_that_dont_accept_choice(self):
        from services.model_resolver import resolve_saved_value

        assert resolve_saved_value("cursor", "claude-sonnet-4-5", None) is None
        assert resolve_saved_value("vscode", "claude-sonnet-4-5", None) is None
        assert resolve_saved_value("copilot", "claude-sonnet-4-5", None) is None

    def test_per_ide_override_wins(self):
        from services.model_resolver import resolve_saved_value

        result = resolve_saved_value(
            "kiro",
            "claude-sonnet-4-5",
            {"kiro": "claude-opus-4-5"},
        )
        assert result == "claude-opus-4-5"

    def test_claude_code_uses_legacy_model_name(self):
        from services.model_resolver import resolve_saved_value

        # Unknown id stays verbatim through format_for_ide(...)
        assert resolve_saved_value("claude-code", "custom-model", None) == "custom-model"

    def test_other_ides_emit_none_without_override(self):
        from services.model_resolver import resolve_saved_value

        # Kiro / Codex / Gemini default to the auto sentinel when no override exists
        assert resolve_saved_value("kiro", "claude-sonnet-4-5", None) is None
        assert resolve_saved_value("codex", "claude-sonnet-4-5", None) is None
        assert resolve_saved_value("gemini-cli", "claude-sonnet-4-5", None) is None
        assert resolve_saved_value("opencode", "claude-sonnet-4-5", None) is None


# ──────────────────────── resolve_model_for_ide ─────────────


class TestResolveModelForIde:
    @pytest.mark.asyncio
    async def test_ide_without_model_choice_warns_on_override(self):
        from services.model_resolver import resolve_model_for_ide

        emitted, warnings = await resolve_model_for_ide(
            "cursor",
            model_name="",
            override="gpt-5",
        )
        assert emitted is None
        assert any("does not accept" in w for w in warnings)

    @pytest.mark.asyncio
    async def test_claude_code_short_alias_passthrough(self):
        from services.model_resolver import resolve_model_for_ide

        emitted, warnings = await resolve_model_for_ide(
            "claude-code",
            model_name="sonnet",
        )
        assert emitted == "sonnet"
        assert warnings == []

    @pytest.mark.asyncio
    async def test_claude_code_inherit_resolves_to_none(self):
        from services.model_resolver import resolve_model_for_ide

        emitted, warnings = await resolve_model_for_ide("claude-code", model_name="inherit")
        assert emitted is None
        assert warnings == []

    @pytest.mark.asyncio
    async def test_unknown_model_falls_back_to_auto_with_warning(self):
        from services import model_resolver

        catalog = _build_catalog()
        with patch.object(model_resolver, "get_catalog", AsyncMock(return_value=catalog)):
            emitted, warnings = await model_resolver.resolve_model_for_ide(
                "kiro",
                model_name="",
                models_by_ide={"kiro": "totally-fake-model"},
            )
        assert emitted is None
        assert any("not in the catalog" in w for w in warnings)

    @pytest.mark.asyncio
    async def test_wrong_provider_falls_back_to_auto(self):
        from services import model_resolver

        catalog = _build_catalog()
        with patch.object(model_resolver, "get_catalog", AsyncMock(return_value=catalog)):
            # gpt-5 is openai provider; Kiro only accepts anthropic
            emitted, warnings = await model_resolver.resolve_model_for_ide(
                "kiro",
                model_name="",
                models_by_ide={"kiro": "gpt-5"},
            )
        assert emitted is None
        assert any("not supported by kiro" in w for w in warnings)

    @pytest.mark.asyncio
    async def test_deprecated_model_resolves_with_soft_warning(self):
        from services import model_resolver

        catalog = _build_catalog()
        with patch.object(model_resolver, "get_catalog", AsyncMock(return_value=catalog)):
            emitted, warnings = await model_resolver.resolve_model_for_ide(
                "kiro",
                model_name="",
                models_by_ide={"kiro": "claude-opus-3-deprecated"},
            )
        assert emitted == "claude-opus-3-deprecated"
        assert any("deprecated" in w for w in warnings)

    @pytest.mark.asyncio
    async def test_degraded_catalog_trusts_saved_value_with_soft_warning(self):
        from services import model_resolver

        catalog = _build_catalog(degraded=True, source="snapshot")
        with patch.object(model_resolver, "get_catalog", AsyncMock(return_value=catalog)):
            emitted, warnings = await model_resolver.resolve_model_for_ide(
                "kiro",
                model_name="",
                models_by_ide={"kiro": "anything-goes"},
            )
        assert emitted == "anything-goes"
        assert any("catalog is unavailable" in w.lower() for w in warnings)

    @pytest.mark.asyncio
    async def test_supported_model_emits_ide_format(self):
        from services import model_resolver

        catalog = _build_catalog()
        with patch.object(model_resolver, "get_catalog", AsyncMock(return_value=catalog)):
            # OpenCode prepends provider/
            emitted, warnings = await model_resolver.resolve_model_for_ide(
                "opencode",
                model_name="",
                models_by_ide={"opencode": "claude-sonnet-4-5"},
            )
        assert emitted == "anthropic/claude-sonnet-4-5"
        assert warnings == []


# ──────────────────────── CLI _parse_model_overrides ─────────


class TestParseModelOverrides:
    def test_default_value(self):
        from observal_cli.cmd_pull import _parse_model_overrides

        default, overrides = _parse_model_overrides(["claude-sonnet-4-5"])
        assert default == "claude-sonnet-4-5"
        assert overrides == {}

    def test_per_ide_override(self):
        from observal_cli.cmd_pull import _parse_model_overrides

        default, overrides = _parse_model_overrides(["kiro=claude-opus", "codex=gpt-5"])
        assert default is None
        assert overrides == {"kiro": "claude-opus", "codex": "gpt-5"}

    def test_mixed(self):
        from observal_cli.cmd_pull import _parse_model_overrides

        default, overrides = _parse_model_overrides(["sonnet", "kiro=claude-opus"])
        assert default == "sonnet"
        assert overrides == {"kiro": "claude-opus"}

    def test_skips_blank_and_malformed(self):
        from observal_cli.cmd_pull import _parse_model_overrides

        default, overrides = _parse_model_overrides(["", "  ", "kiro=", "=claude"])
        assert default is None
        assert overrides == {}


# ──────────────────────── /api/v1/models endpoint ─────────────


class TestModelsEndpoint:
    def _make_user(self):
        from models.user import User, UserRole

        user = MagicMock(spec=User)
        user.id = uuid.uuid4()
        user.role = UserRole.user
        user.org_id = None
        return user

    def _make_admin(self):
        from models.user import User, UserRole

        user = MagicMock(spec=User)
        user.id = uuid.uuid4()
        user.role = UserRole.admin
        user.org_id = None
        return user

    @pytest.mark.asyncio
    async def test_returns_catalog_with_cache_headers(self):
        from api.deps import get_current_user
        from main import app

        catalog = _build_catalog()
        user = self._make_user()

        async def _mock_user():
            return user

        app.dependency_overrides[get_current_user] = _mock_user
        try:
            with patch("api.routes.registry_models.get_catalog", AsyncMock(return_value=catalog)):
                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                    r = await ac.get("/api/v1/models")
            assert r.status_code == 200
            data = r.json()
            assert data["model_count"] == 4
            assert data["source"] == "live"
            # Cache headers are present
            assert "Cache-Control" in r.headers
            assert "ETag" in r.headers
            assert r.headers["X-Catalog-Source"] == "live"
            assert r.headers["X-Catalog-Degraded"] == "0"
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_conditional_get_returns_304(self):
        from api.deps import get_current_user
        from main import app

        catalog = _build_catalog()
        user = self._make_user()

        async def _mock_user():
            return user

        app.dependency_overrides[get_current_user] = _mock_user
        try:
            with patch("api.routes.registry_models.get_catalog", AsyncMock(return_value=catalog)):
                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                    r = await ac.get(
                        "/api/v1/models",
                        headers={"If-None-Match": catalog.etag},
                    )
            assert r.status_code == 304
            assert r.headers.get("ETag") == catalog.etag
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_admin_refresh_requires_admin(self):
        from api.deps import get_current_user
        from main import app

        user = self._make_user()

        async def _mock_user():
            return user

        app.dependency_overrides[get_current_user] = _mock_user
        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                r = await ac.post("/api/v1/admin/models/refresh")
            assert r.status_code == 403
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_admin_refresh_returns_diff(self):
        from api.deps import get_current_user
        from main import app

        catalog = _build_catalog()
        admin = self._make_admin()

        async def _mock_admin():
            return admin

        app.dependency_overrides[get_current_user] = _mock_admin
        try:
            with (
                patch("api.routes.registry_models.get_catalog", AsyncMock(return_value=catalog)),
                patch(
                    "api.routes.registry_models.diff_against_current",
                    AsyncMock(return_value={"added": [], "removed": [], "updated": [], "total": catalog.model_count}),
                ),
            ):
                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                    r = await ac.post("/api/v1/admin/models/refresh")
            assert r.status_code == 200
            data = r.json()
            assert data["ok"] is True
            assert data["model_count"] == catalog.model_count
            assert data["source"] == "live"
            assert "diff" in data
        finally:
            app.dependency_overrides.clear()


# ──────────────────────── Builder round-trip ───────────────────


def _empty_manifest(model_name: str = "", models_by_ide: dict | None = None):
    """Construct a minimal AgentManifest for codegen tests."""
    from services.agent_builder import AgentManifest, ManifestComponents

    return AgentManifest(
        name="test-agent",
        version="1.0.0",
        prompt="Be helpful.",
        description="Test agent",
        model_name=model_name,
        models_by_ide=models_by_ide or {},
        components=ManifestComponents(),
    )


class TestBuilderModelEmission:
    def test_manifest_carries_models_by_ide_from_resolved(self):
        from services.agent_builder import build_agent_manifest
        from services.agent_resolver import ResolvedAgent

        resolved = ResolvedAgent(
            agent_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
            agent_name="alpha",
            agent_version="1.0.0",
            agent_prompt="hi",
            agent_description="d",
            model_name="claude-sonnet-4-5",
            models_by_ide={"kiro": "claude-opus-4-5", "codex": "gpt-5"},
            components=[],
            errors=[],
        )
        manifest_dict = build_agent_manifest(resolved)
        assert manifest_dict["model_name"] == "claude-sonnet-4-5"
        assert manifest_dict["models_by_ide"] == {
            "kiro": "claude-opus-4-5",
            "codex": "gpt-5",
        }

    def test_claude_code_emits_alias_in_frontmatter(self):
        from services.agent_builder import _generate_claude_code

        manifest = _empty_manifest(model_name="claude-sonnet-4-5")
        cfg = _generate_claude_code(manifest)
        agent_md = cfg.files[0].content
        assert isinstance(agent_md, str)
        assert "model: sonnet" in agent_md  # short alias from format_for_ide

    def test_claude_code_omits_model_when_no_choice(self):
        from services.agent_builder import _generate_claude_code

        manifest = _empty_manifest()  # no model name
        cfg = _generate_claude_code(manifest)
        agent_md = cfg.files[0].content
        assert "model:" not in agent_md

    def test_kiro_uses_per_ide_override(self):
        from services.agent_builder import _generate_kiro

        manifest = _empty_manifest(
            model_name="claude-sonnet-4-5",
            models_by_ide={"kiro": "claude-opus-4-5"},
        )
        cfg = _generate_kiro(manifest)
        kiro_json = cfg.files[0].content
        assert isinstance(kiro_json, dict)
        assert kiro_json["model"] == "claude-opus-4-5"

    def test_kiro_emits_null_without_override(self):
        from services.agent_builder import _generate_kiro

        # model_name is set but no per-IDE override → Kiro auto sentinel (null)
        manifest = _empty_manifest(model_name="claude-sonnet-4-5")
        cfg = _generate_kiro(manifest)
        kiro_json = cfg.files[0].content
        assert kiro_json["model"] is None

    def test_gemini_cli_settings_carries_model(self):
        from services.agent_builder import _generate_gemini_cli

        manifest = _empty_manifest(models_by_ide={"gemini-cli": "gemini-2.5-pro"})
        cfg = _generate_gemini_cli(manifest)
        settings_file = next(f for f in cfg.files if f.path == ".gemini/settings.json")
        assert isinstance(settings_file.content, dict)
        assert settings_file.content["model"] == "gemini-2.5-pro"

    def test_gemini_cli_omits_model_setting_without_override(self):
        from services.agent_builder import _generate_gemini_cli

        manifest = _empty_manifest()
        cfg = _generate_gemini_cli(manifest)
        settings_file = next(f for f in cfg.files if f.path == ".gemini/settings.json")
        assert "model" not in settings_file.content

    def test_codex_toml_carries_model(self):
        from services.agent_builder import _generate_codex

        manifest = _empty_manifest(models_by_ide={"codex": "gpt-5"})
        cfg = _generate_codex(manifest)
        toml = next(f for f in cfg.files if f.path == "~/.codex/config.toml").content
        assert isinstance(toml, str)
        assert 'model = "gpt-5"' in toml

    def test_opencode_uses_provider_prefix(self):
        from services.agent_builder import _generate_opencode

        manifest = _empty_manifest(
            models_by_ide={"opencode": "claude-sonnet-4-5"},
        )
        cfg = _generate_opencode(manifest)
        oc_file = next(f for f in cfg.files if f.path == "opencode.json")
        # _saved_model_for is sync and doesn't know providers, so it falls back
        # to the legacy "anthropic" default. Either way we must format the value.
        assert isinstance(oc_file.content, dict)
        assert oc_file.content["model"].endswith("/claude-sonnet-4-5")
        assert oc_file.content["model"].split("/")[0] in {"anthropic", "openai", "google"}
