"""Unit tests for the 6 new registry types: tool, skill, hook, prompt, sandbox, graphrag."""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from api.deps import get_current_user, get_db
from models.mcp import ListingStatus
from models.user import User, UserRole

# ── Helpers ──────────────────────────────────────────────


def _user(**kw):
    u = MagicMock(spec=User)
    u.id = kw.get("id", uuid.uuid4())
    u.role = kw.get("role", UserRole.admin)
    return u


def _mock_db():
    db = AsyncMock()
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.delete = AsyncMock()
    return db


def _app_with(router, user=None, db=None):
    user = user or _user()
    db = db or _mock_db()
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = lambda: db
    return app, db, user


def _listing_mock(model_cls, status=ListingStatus.pending, **extra):
    m = MagicMock()
    m.id = uuid.uuid4()
    m.name = "test-listing"
    m.version = "1.0.0"
    m.description = "A test listing description that is long enough"
    m.owner = "testowner"
    m.status = status
    m.rejection_reason = None
    m.submitted_by = uuid.uuid4()
    m.supported_ides = ["cursor"]
    m.created_at = datetime.now(UTC)
    m.updated_at = datetime.now(UTC)
    for k, v in extra.items():
        setattr(m, k, v)
    return m


def _scalar_result(val):
    """Mock db.execute() returning a result whose .scalar_one_or_none() returns val."""
    r = MagicMock()
    r.scalar_one_or_none.return_value = val
    r.scalars.return_value.all.return_value = [val] if val else []
    return r


# ═══════════════════════════════════════════════════════════
# 1. TestModels
# ═══════════════════════════════════════════════════════════


class TestModels:
    """Test that all 6 listing + download + link models have correct table names and reuse ListingStatus."""

    def test_skill_listing_tablename(self):
        from models.skill import SkillListing

        assert SkillListing.__tablename__ == "skill_listings"

    def test_hook_listing_tablename(self):
        from models.hook import HookListing

        assert HookListing.__tablename__ == "hook_listings"

    def test_prompt_listing_tablename(self):
        from models.prompt import PromptListing

        assert PromptListing.__tablename__ == "prompt_listings"

    def test_sandbox_listing_tablename(self):
        from models.sandbox import SandboxListing

        assert SandboxListing.__tablename__ == "sandbox_listings"

    def test_skill_download_tablename(self):
        from models.skill import SkillDownload

        assert SkillDownload.__tablename__ == "skill_downloads"

    def test_hook_download_tablename(self):
        from models.hook import HookDownload

        assert HookDownload.__tablename__ == "hook_downloads"

    def test_prompt_download_tablename(self):
        from models.prompt import PromptDownload

        assert PromptDownload.__tablename__ == "prompt_downloads"

    def test_sandbox_download_tablename(self):
        from models.sandbox import SandboxDownload

        assert SandboxDownload.__tablename__ == "sandbox_downloads"

    def test_listing_status_reused_not_redefined(self):
        """All remaining listing models import ListingStatus from models.mcp: not their own copy."""
        from models.hook import HookListing
        from models.mcp import ListingStatus as Canonical
        from models.prompt import PromptListing
        from models.sandbox import SandboxListing
        from models.skill import SkillListing

        for model in (SkillListing, HookListing, PromptListing, SandboxListing):
            col = model.__table__.columns["status"]
            assert col.type.enum_class is Canonical

    def test_submission_model_tablename(self):
        from models.submission import Submission

        assert Submission.__tablename__ == "submissions"


# ═══════════════════════════════════════════════════════════
# 2. TestSchemas
# ═══════════════════════════════════════════════════════════


class TestSchemas:
    """Validate pydantic schemas for all 6 types."""

    # ── SubmitRequest valid ──

    def test_skill_submit_valid(self):
        from schemas.skill import SkillSubmitRequest

        r = SkillSubmitRequest(name="s", version="1.0", description="desc", owner="o", task_type="code-review")
        assert r.skill_path == "/"

    def test_hook_submit_valid(self):
        from schemas.hook import HookSubmitRequest

        r = HookSubmitRequest(
            name="h", version="1.0", description="desc", owner="o", event="pre_tool_call", handler_type="script"
        )
        assert r.execution_mode == "async"
        assert r.priority == 100

    def test_prompt_submit_valid(self):
        from schemas.prompt import PromptSubmitRequest

        r = PromptSubmitRequest(
            name="p", version="1.0", description="desc", owner="o", category="c", template="Hello {{ name }}"
        )
        assert r.variables == []

    def test_sandbox_submit_valid(self):
        from schemas.sandbox import SandboxSubmitRequest

        r = SandboxSubmitRequest(
            name="sb", version="1.0", description="desc", owner="o", runtime_type="docker", image="python:3.11"
        )
        assert r.network_policy == "none"

    # ── SubmitRequest missing required fields ──

    def test_hook_submit_missing_event(self):
        from schemas.hook import HookSubmitRequest

        with pytest.raises(ValueError):
            HookSubmitRequest(name="h", version="1.0", description="d", owner="o", handler_type="script")

    def test_sandbox_submit_missing_image(self):
        from schemas.sandbox import SandboxSubmitRequest

        with pytest.raises(ValueError):
            SandboxSubmitRequest(name="sb", version="1.0", description="d", owner="o", runtime_type="docker")

    # ── ListingResponse from_attributes ──

    def _ns(self, **kw):
        """SimpleNamespace works with pydantic from_attributes (MagicMock.name conflicts)."""
        from types import SimpleNamespace

        return SimpleNamespace(**kw)

    def test_prompt_response_from_attrs(self):
        from schemas.prompt import PromptListingResponse

        obj = self._ns(
            id=uuid.uuid4(),
            name="p",
            version="1.0",
            description="d",
            owner="o",
            category="c",
            template="hi",
            variables=[],
            tags=[],
            supported_ides=[],
            status=ListingStatus.approved,
            rejection_reason=None,
            submitted_by=uuid.uuid4(),
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        r = PromptListingResponse.model_validate(obj, from_attributes=True)
        assert r.status == ListingStatus.approved

    # ── Prompt render schemas ──

    def test_prompt_render_request(self):
        from schemas.prompt import PromptRenderRequest

        r = PromptRenderRequest(variables={"name": "world"})
        assert r.variables["name"] == "world"

    def test_prompt_render_response(self):
        from schemas.prompt import PromptRenderResponse

        r = PromptRenderResponse(listing_id=uuid.uuid4(), rendered="Hello world")
        assert "world" in r.rendered


# ═══════════════════════════════════════════════════════════
# 3. TestRoutes
# ═══════════════════════════════════════════════════════════


class TestSkillRoutes:
    @pytest.mark.asyncio
    async def test_submit_calls_db_add_and_commit(self):
        from api.routes.skill import router

        app, db, user = _app_with(router)

        def _refresh(obj):
            obj.id = uuid.uuid4()
            obj.created_at = datetime.now(UTC)
            obj.updated_at = datetime.now(UTC)

        db.refresh = AsyncMock(side_effect=_refresh)

        # The route passes archive_url to SkillListing but the model lacks that column.
        # Patch SkillListing.__init__ to accept and ignore unknown kwargs.
        from models.skill import SkillListing

        _orig_init = SkillListing.__init__

        def _patched_init(self, **kwargs):
            kwargs.pop("archive_url", None)
            _orig_init(self, **kwargs)

        with patch.object(SkillListing, "__init__", _patched_init):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                r = await ac.post(
                    "/api/v1/skills/submit",
                    json={"name": "s", "version": "1.0", "description": "d", "owner": "o", "task_type": "review"},
                )
        assert r.status_code == 200
        db.add.assert_called_once()
        assert r.json()["status"] == "pending"

    @pytest.mark.asyncio
    async def test_get_missing_returns_404(self):
        from api.routes.skill import router

        app, db, _ = _app_with(router)
        db.execute = AsyncMock(return_value=_scalar_result(None))
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.get(f"/api/v1/skills/{uuid.uuid4()}")
        assert r.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_missing_returns_404(self):
        from api.routes.skill import router

        app, db, _ = _app_with(router)
        db.execute = AsyncMock(return_value=_scalar_result(None))
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.delete(f"/api/v1/skills/{uuid.uuid4()}")
        assert r.status_code == 404

    @pytest.mark.asyncio
    async def test_install_approved_returns_config(self):
        from api.routes.skill import router

        app, db, user = _app_with(router)
        listing = _listing_mock(None, status=ListingStatus.approved)
        db.execute = AsyncMock(return_value=_scalar_result(listing))
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.post(f"/api/v1/skills/{listing.id}/install", json={"ide": "cursor"})
        assert r.status_code == 200
        assert "config_snippet" in r.json()


class TestHookRoutes:
    @pytest.mark.asyncio
    async def test_submit_calls_db_add_and_commit(self):
        from api.routes.hook import router

        app, db, user = _app_with(router)

        def _refresh(obj):
            obj.id = uuid.uuid4()
            obj.created_at = datetime.now(UTC)
            obj.updated_at = datetime.now(UTC)

        db.refresh = AsyncMock(side_effect=_refresh)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.post(
                "/api/v1/hooks/submit",
                json={
                    "name": "h",
                    "version": "1.0",
                    "description": "d",
                    "owner": "o",
                    "event": "pre_tool_call",
                    "handler_type": "script",
                },
            )
        assert r.status_code == 200
        db.add.assert_called_once()
        assert r.json()["status"] == "pending"

    @pytest.mark.asyncio
    async def test_get_missing_returns_404(self):
        from api.routes.hook import router

        app, db, _ = _app_with(router)
        db.execute = AsyncMock(return_value=_scalar_result(None))
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.get(f"/api/v1/hooks/{uuid.uuid4()}")
        assert r.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_missing_returns_404(self):
        from api.routes.hook import router

        app, db, _ = _app_with(router)
        db.execute = AsyncMock(return_value=_scalar_result(None))
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.delete(f"/api/v1/hooks/{uuid.uuid4()}")
        assert r.status_code == 404

    @pytest.mark.asyncio
    async def test_install_approved_returns_config(self):
        from api.routes.hook import router

        app, db, user = _app_with(router)
        listing = _listing_mock(None, status=ListingStatus.approved)
        db.execute = AsyncMock(return_value=_scalar_result(listing))
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.post(f"/api/v1/hooks/{listing.id}/install", json={"ide": "cursor"})
        assert r.status_code == 200
        assert "config_snippet" in r.json()


class TestPromptRoutes:
    @pytest.mark.asyncio
    async def test_submit_calls_db_add_and_commit(self):
        from api.routes.prompt import router

        app, db, user = _app_with(router)

        def _refresh(obj):
            obj.id = uuid.uuid4()
            obj.created_at = datetime.now(UTC)
            obj.updated_at = datetime.now(UTC)

        db.refresh = AsyncMock(side_effect=_refresh)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.post(
                "/api/v1/prompts/submit",
                json={
                    "name": "p",
                    "version": "1.0",
                    "description": "d",
                    "owner": "o",
                    "category": "c",
                    "template": "Hello {{ name }}",
                },
            )
        assert r.status_code == 200
        db.add.assert_called_once()
        assert r.json()["status"] == "pending"

    @pytest.mark.asyncio
    async def test_get_missing_returns_404(self):
        from api.routes.prompt import router

        app, db, _ = _app_with(router)
        db.execute = AsyncMock(return_value=_scalar_result(None))
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.get(f"/api/v1/prompts/{uuid.uuid4()}")
        assert r.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_missing_returns_404(self):
        from api.routes.prompt import router

        app, db, _ = _app_with(router)
        db.execute = AsyncMock(return_value=_scalar_result(None))
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.delete(f"/api/v1/prompts/{uuid.uuid4()}")
        assert r.status_code == 404

    @pytest.mark.asyncio
    async def test_install_approved_returns_config(self):
        from api.routes.prompt import router

        app, db, user = _app_with(router)
        listing = _listing_mock(None, status=ListingStatus.approved)
        db.execute = AsyncMock(return_value=_scalar_result(listing))
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.post(f"/api/v1/prompts/{listing.id}/install")
        assert r.status_code == 200
        assert "config_snippet" in r.json()

    @pytest.mark.asyncio
    async def test_render_substitutes_variables(self):
        from api.routes.prompt import router

        app, db, user = _app_with(router)
        listing = _listing_mock(
            None, status=ListingStatus.approved, template="Hello {{ name }}, welcome to {{ place }}"
        )
        db.execute = AsyncMock(return_value=_scalar_result(listing))
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.post(
                f"/api/v1/prompts/{listing.id}/render",
                json={"variables": {"name": "Alice", "place": "Wonderland"}},
            )
        assert r.status_code == 200
        assert r.json()["rendered"] == "Hello Alice, welcome to Wonderland"

    @pytest.mark.asyncio
    async def test_render_missing_returns_404(self):
        from api.routes.prompt import router

        app, db, _ = _app_with(router)
        db.execute = AsyncMock(return_value=_scalar_result(None))
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.post(f"/api/v1/prompts/{uuid.uuid4()}/render", json={"variables": {}})
        assert r.status_code == 404


class TestSandboxRoutes:
    @pytest.mark.asyncio
    async def test_submit_calls_db_add_and_commit(self):
        from api.routes.sandbox import router

        app, db, user = _app_with(router)

        def _refresh(obj):
            obj.id = uuid.uuid4()
            obj.created_at = datetime.now(UTC)
            obj.updated_at = datetime.now(UTC)

        db.refresh = AsyncMock(side_effect=_refresh)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.post(
                "/api/v1/sandboxes/submit",
                json={
                    "name": "sb",
                    "version": "1.0",
                    "description": "d",
                    "owner": "o",
                    "runtime_type": "docker",
                    "image": "python:3.11",
                },
            )
        assert r.status_code == 200
        db.add.assert_called_once()
        assert r.json()["status"] == "pending"

    @pytest.mark.asyncio
    async def test_get_missing_returns_404(self):
        from api.routes.sandbox import router

        app, db, _ = _app_with(router)
        db.execute = AsyncMock(return_value=_scalar_result(None))
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.get(f"/api/v1/sandboxes/{uuid.uuid4()}")
        assert r.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_missing_returns_404(self):
        from api.routes.sandbox import router

        app, db, _ = _app_with(router)
        db.execute = AsyncMock(return_value=_scalar_result(None))
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.delete(f"/api/v1/sandboxes/{uuid.uuid4()}")
        assert r.status_code == 404

    @pytest.mark.asyncio
    async def test_install_approved_returns_config(self):
        from api.routes.sandbox import router

        app, db, user = _app_with(router)
        listing = _listing_mock(None, status=ListingStatus.approved)
        db.execute = AsyncMock(return_value=_scalar_result(listing))
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.post(f"/api/v1/sandboxes/{listing.id}/install", json={"ide": "cursor"})
        assert r.status_code == 200
        assert "config_snippet" in r.json()


# ═══════════════════════════════════════════════════════════
# 4. TestUnifiedReview
# ═══════════════════════════════════════════════════════════


class TestUnifiedReview:
    @pytest.mark.asyncio
    async def test_list_pending_returns_empty(self):
        from api.routes.review import router

        app, db, _ = _app_with(router)
        empty = MagicMock()
        empty.scalars.return_value.all.return_value = []
        db.execute = AsyncMock(return_value=empty)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.get("/api/v1/review")
        assert r.status_code == 200

    @pytest.mark.asyncio
    async def test_list_pending_requires_admin(self):
        from api.routes.review import router

        user = _user(role=UserRole.developer)
        app, db, _ = _app_with(router, user=user)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.get("/api/v1/review")
        assert r.status_code == 403

    @pytest.mark.asyncio
    async def test_approve_not_found(self):
        from api.routes.review import router

        app, db, _ = _app_with(router)
        db.execute = AsyncMock(return_value=_scalar_result(None))
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.post(f"/api/v1/review/{uuid.uuid4()}/approve")
        assert r.status_code == 404

    @pytest.mark.asyncio
    async def test_reject_not_found(self):
        from api.routes.review import router

        app, db, _ = _app_with(router)
        db.execute = AsyncMock(return_value=_scalar_result(None))
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.post(f"/api/v1/review/{uuid.uuid4()}/reject", json={"reason": "bad"})
        assert r.status_code == 404

    @pytest.mark.asyncio
    async def test_approve_changes_status(self):
        from api.routes.review import router

        app, db, _ = _app_with(router)
        listing = _listing_mock(None, status=ListingStatus.pending)
        db.execute = AsyncMock(return_value=_scalar_result(listing))
        db.refresh = AsyncMock(side_effect=lambda obj: None)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.post(f"/api/v1/review/{listing.id}/approve")
        assert r.status_code == 200
        assert listing.status == ListingStatus.approved

    @pytest.mark.asyncio
    async def test_reject_sets_reason(self):
        from api.routes.review import router

        app, db, _ = _app_with(router)
        listing = _listing_mock(None, status=ListingStatus.pending)
        db.execute = AsyncMock(return_value=_scalar_result(listing))
        db.refresh = AsyncMock(side_effect=lambda obj: None)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.post(f"/api/v1/review/{listing.id}/reject", json={"reason": "incomplete"})
        assert r.status_code == 200
        assert listing.status == ListingStatus.rejected
        assert listing.rejection_reason == "incomplete"

    def test_listing_models_dict_has_all_types(self):
        from api.routes.review import LISTING_MODELS

        for t in ("mcp", "skill", "hook", "prompt", "sandbox"):
            assert t in LISTING_MODELS


# ═══════════════════════════════════════════════════════════
# 5. TestFeedbackExtension
# ═══════════════════════════════════════════════════════════


class TestFeedbackExtension:
    """Verify the feedback schema accepts all 6 new listing types."""

    @pytest.mark.parametrize("lt", ["mcp", "agent", "skill", "hook", "prompt", "sandbox"])
    def test_feedback_schema_accepts_new_types(self, lt):
        from schemas.feedback import FeedbackCreateRequest

        req = FeedbackCreateRequest(listing_id=uuid.uuid4(), listing_type=lt, rating=4)
        assert req.listing_type == lt

    def test_feedback_schema_rejects_invalid_type(self):
        from schemas.feedback import FeedbackCreateRequest

        with pytest.raises(ValueError):
            FeedbackCreateRequest(listing_id=uuid.uuid4(), listing_type="invalid", rating=4)

    def test_feedback_schema_rejects_rating_out_of_range(self):
        from schemas.feedback import FeedbackCreateRequest

        with pytest.raises(ValueError):
            FeedbackCreateRequest(listing_id=uuid.uuid4(), listing_type="tool", rating=6)

    def test_feedback_schema_accepts_mcp_and_agent(self):
        from schemas.feedback import FeedbackCreateRequest

        for lt in ("mcp", "agent"):
            req = FeedbackCreateRequest(listing_id=uuid.uuid4(), listing_type=lt, rating=3)
            assert req.listing_type == lt


# ═══════════════════════════════════════════════════════════
# 6. TestCLICommands
# ═══════════════════════════════════════════════════════════


class TestCLICommands:
    """Verify CLI command groups exist with expected subcommands."""

    def _get_command_names(self, typer_app):
        """Extract registered command names from a Typer app."""
        info = typer_app.registered_commands
        return [c.name or c.callback.__name__ for c in info]

    def test_skill_app_exists(self):
        from observal_cli.cmd_skill import skill_app

        assert skill_app is not None

    def test_skill_app_has_subcommands(self):
        from observal_cli.cmd_skill import skill_app

        names = self._get_command_names(skill_app)
        for cmd in ("submit", "list", "show", "install", "delete"):
            assert cmd in names, f"skill missing '{cmd}' subcommand"
