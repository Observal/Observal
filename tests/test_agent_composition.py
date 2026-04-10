"""Tests for agent composition and resolver (issue #80).

Tests the resolver service, builder service, schema updates,
and route endpoints for multi-component agent composition.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest


# ── Schema Tests ────────────────────────────────────────────────────


class TestComponentRefSchema:
    def test_component_ref_fields(self):
        from schemas.agent import ComponentRef
        ref = ComponentRef(component_type="mcp", component_id=uuid.uuid4())
        assert ref.component_type == "mcp"
        assert ref.config_override is None

    def test_component_ref_with_override(self):
        from schemas.agent import ComponentRef
        cid = uuid.uuid4()
        ref = ComponentRef(
            component_type="skill",
            component_id=cid,
            config_override={"key": "value"},
        )
        assert ref.component_type == "skill"
        assert ref.component_id == cid
        assert ref.config_override == {"key": "value"}

    def test_valid_component_types_constant(self):
        from schemas.agent import VALID_COMPONENT_TYPES
        assert VALID_COMPONENT_TYPES == {"mcp", "skill", "hook", "prompt", "sandbox"}

    def test_component_ref_rejects_invalid_type(self):
        from pydantic import ValidationError
        from schemas.agent import ComponentRef
        with pytest.raises(ValidationError):
            ComponentRef(component_type="invalid", component_id=uuid.uuid4())


class TestComponentLinkResponseSchema:
    def test_component_link_response_fields(self):
        from schemas.agent import ComponentLinkResponse
        resp = ComponentLinkResponse(
            component_type="hook",
            component_id=uuid.uuid4(),
            version_ref="1.0.0",
            order=0,
        )
        assert resp.component_type == "hook"
        assert resp.version_ref == "1.0.0"
        assert resp.config_override is None


class TestAgentCreateRequestWithComponents:
    def test_create_request_accepts_components(self):
        from schemas.agent import AgentCreateRequest, ComponentRef, GoalTemplateRequest, GoalSectionRequest
        cid = uuid.uuid4()
        req = AgentCreateRequest(
            name="test-agent",
            version="1.0.0",
            owner="test",
            model_name="claude-sonnet-4-6",
            components=[
                ComponentRef(component_type="mcp", component_id=cid),
                ComponentRef(component_type="skill", component_id=uuid.uuid4()),
            ],
            goal_template=GoalTemplateRequest(
                description="test",
                sections=[GoalSectionRequest(name="s1")],
            ),
        )
        assert len(req.components) == 2
        assert req.components[0].component_type == "mcp"

    def test_create_request_backwards_compat(self):
        """mcp_server_ids should still work."""
        from schemas.agent import AgentCreateRequest, GoalTemplateRequest, GoalSectionRequest
        req = AgentCreateRequest(
            name="legacy-agent",
            version="1.0.0",
            owner="test",
            model_name="claude-sonnet-4-6",
            mcp_server_ids=[uuid.uuid4()],
            goal_template=GoalTemplateRequest(
                description="test",
                sections=[GoalSectionRequest(name="s1")],
            ),
        )
        assert len(req.mcp_server_ids) == 1
        assert len(req.components) == 0

    def test_create_request_both_fields(self):
        """Both mcp_server_ids and components can coexist."""
        from schemas.agent import AgentCreateRequest, ComponentRef, GoalTemplateRequest, GoalSectionRequest
        req = AgentCreateRequest(
            name="dual-agent",
            version="1.0.0",
            owner="test",
            model_name="claude-sonnet-4-6",
            mcp_server_ids=[uuid.uuid4()],
            components=[
                ComponentRef(component_type="skill", component_id=uuid.uuid4()),
            ],
            goal_template=GoalTemplateRequest(
                description="test",
                sections=[GoalSectionRequest(name="s1")],
            ),
        )
        assert len(req.mcp_server_ids) == 1
        assert len(req.components) == 1


class TestAgentUpdateRequestWithComponents:
    def test_update_request_components_optional(self):
        from schemas.agent import AgentUpdateRequest
        req = AgentUpdateRequest()
        assert req.components is None

    def test_update_request_with_components(self):
        from schemas.agent import AgentUpdateRequest, ComponentRef
        req = AgentUpdateRequest(
            components=[
                ComponentRef(component_type="mcp", component_id=uuid.uuid4()),
                ComponentRef(component_type="hook", component_id=uuid.uuid4()),
            ],
        )
        assert len(req.components) == 2


class TestAgentResponseWithComponentLinks:
    def test_response_has_component_links(self):
        from schemas.agent import AgentResponse
        fields = AgentResponse.model_fields
        assert "component_links" in fields
        assert "mcp_links" in fields  # backwards compat


# ── Resolver Service Tests ──────────────────────────────────────────


class TestResolvedAgentDataclass:
    def test_ok_when_no_errors(self):
        from services.agent_resolver import ResolvedAgent
        ra = ResolvedAgent(
            agent_id=uuid.uuid4(),
            agent_name="test",
            agent_version="1.0",
        )
        assert ra.ok is True

    def test_not_ok_when_errors(self):
        from services.agent_resolver import ResolvedAgent, ResolutionError
        ra = ResolvedAgent(
            agent_id=uuid.uuid4(),
            agent_name="test",
            agent_version="1.0",
            errors=[ResolutionError(
                component_type="mcp",
                component_id=uuid.uuid4(),
                reason="not found",
            )],
        )
        assert ra.ok is False

    def test_components_by_type(self):
        from services.agent_resolver import ResolvedAgent, ResolvedComponent
        cid1 = uuid.uuid4()
        cid2 = uuid.uuid4()
        cid3 = uuid.uuid4()
        ra = ResolvedAgent(
            agent_id=uuid.uuid4(),
            agent_name="test",
            agent_version="1.0",
            components=[
                ResolvedComponent(
                    component_type="mcp", component_id=cid1, name="mcp1",
                    version="1.0", git_url="url", git_ref="abc",
                    description="", order_index=0,
                ),
                ResolvedComponent(
                    component_type="skill", component_id=cid2, name="skill1",
                    version="1.0", git_url="url", git_ref="abc",
                    description="", order_index=1,
                ),
                ResolvedComponent(
                    component_type="mcp", component_id=cid3, name="mcp2",
                    version="2.0", git_url="url", git_ref="def",
                    description="", order_index=2,
                ),
            ],
        )
        mcps = ra.components_by_type("mcp")
        assert len(mcps) == 2
        assert mcps[0].name == "mcp1"
        assert mcps[1].name == "mcp2"

        skills = ra.components_by_type("skill")
        assert len(skills) == 1
        assert skills[0].name == "skill1"

        hooks = ra.components_by_type("hook")
        assert len(hooks) == 0


class TestListingModelMap:
    def test_all_types_mapped(self):
        from services.agent_resolver import _LISTING_MODELS
        assert set(_LISTING_MODELS.keys()) == {"mcp", "skill", "hook", "prompt", "sandbox"}

    def test_mcp_maps_to_mcp_listing(self):
        from models.mcp import McpListing
        from services.agent_resolver import _LISTING_MODELS
        assert _LISTING_MODELS["mcp"] is McpListing

    def test_skill_maps_to_skill_listing(self):
        from models.skill import SkillListing
        from services.agent_resolver import _LISTING_MODELS
        assert _LISTING_MODELS["skill"] is SkillListing

    def test_hook_maps_to_hook_listing(self):
        from models.hook import HookListing
        from services.agent_resolver import _LISTING_MODELS
        assert _LISTING_MODELS["hook"] is HookListing

    def test_prompt_maps_to_prompt_listing(self):
        from models.prompt import PromptListing
        from services.agent_resolver import _LISTING_MODELS
        assert _LISTING_MODELS["prompt"] is PromptListing

    def test_sandbox_maps_to_sandbox_listing(self):
        from models.sandbox import SandboxListing
        from services.agent_resolver import _LISTING_MODELS
        assert _LISTING_MODELS["sandbox"] is SandboxListing


class TestExtractExtra:
    def test_mcp_extra(self):
        from services.agent_resolver import _extract_extra
        listing = MagicMock()
        listing.transport = "stdio"
        listing.tools_schema = {"tools": []}
        listing.fastmcp_validated = True
        listing.setup_instructions = "pip install"
        extra = _extract_extra(listing, "mcp")
        assert extra["transport"] == "stdio"
        assert extra["fastmcp_validated"] is True
        assert extra["tools_schema"] == {"tools": []}

    def test_skill_extra(self):
        from services.agent_resolver import _extract_extra
        listing = MagicMock()
        listing.skill_path = "/skills/tdd"
        listing.task_type = "development"
        listing.slash_command = "/tdd"
        listing.triggers = {"on": "test"}
        listing.has_scripts = True
        listing.is_power = False
        listing.mcp_server_config = None
        extra = _extract_extra(listing, "skill")
        assert extra["skill_path"] == "/skills/tdd"
        assert extra["slash_command"] == "/tdd"
        assert extra["has_scripts"] is True

    def test_hook_extra(self):
        from services.agent_resolver import _extract_extra
        listing = MagicMock()
        listing.event = "PreCommit"
        listing.execution_mode = "sync"
        listing.priority = 50
        listing.handler_type = "script"
        listing.handler_config = {"cmd": "lint"}
        listing.scope = "agent"
        extra = _extract_extra(listing, "hook")
        assert extra["event"] == "PreCommit"
        assert extra["priority"] == 50

    def test_prompt_extra(self):
        from services.agent_resolver import _extract_extra
        listing = MagicMock()
        listing.template = "Review this code: {{code}}"
        listing.variables = ["code"]
        listing.category = "review"
        extra = _extract_extra(listing, "prompt")
        assert extra["template"] == "Review this code: {{code}}"
        assert extra["variables"] == ["code"]

    def test_sandbox_extra(self):
        from services.agent_resolver import _extract_extra
        listing = MagicMock()
        listing.runtime_type = "docker"
        listing.image = "python:3.12"
        listing.resource_limits = {"cpu": "1", "memory": "512m"}
        listing.network_policy = "none"
        listing.entrypoint = "/bin/sh"
        extra = _extract_extra(listing, "sandbox")
        assert extra["image"] == "python:3.12"
        assert extra["runtime_type"] == "docker"

    def test_unknown_type_returns_empty(self):
        from services.agent_resolver import _extract_extra
        extra = _extract_extra(MagicMock(), "nonexistent")
        assert extra == {}


class TestResolveAgent:
    @pytest.mark.asyncio
    async def test_resolve_empty_agent(self):
        from services.agent_resolver import resolve_agent
        agent = MagicMock()
        agent.id = uuid.uuid4()
        agent.name = "empty-agent"
        agent.version = "1.0.0"
        agent.components = []
        db = AsyncMock()

        resolved = await resolve_agent(agent, db)
        assert resolved.ok is True
        assert resolved.components == []
        assert resolved.errors == []

    @pytest.mark.asyncio
    async def test_resolve_unknown_component_type(self):
        from services.agent_resolver import resolve_agent
        agent = MagicMock()
        agent.id = uuid.uuid4()
        agent.name = "bad-type-agent"
        agent.version = "1.0.0"

        comp = MagicMock()
        comp.component_type = "nonexistent_type"
        comp.component_id = uuid.uuid4()
        agent.components = [comp]

        db = AsyncMock()
        resolved = await resolve_agent(agent, db)
        assert resolved.ok is False
        assert len(resolved.errors) == 1
        assert "Unknown component type" in resolved.errors[0].reason

    @pytest.mark.asyncio
    async def test_resolve_missing_listing(self):
        from services.agent_resolver import resolve_agent
        agent = MagicMock()
        agent.id = uuid.uuid4()
        agent.name = "missing-listing-agent"
        agent.version = "1.0.0"

        comp = MagicMock()
        comp.component_type = "mcp"
        comp.component_id = uuid.uuid4()
        agent.components = [comp]

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        db = AsyncMock()
        db.execute.return_value = mock_result

        resolved = await resolve_agent(agent, db)
        assert resolved.ok is False
        assert "not found" in resolved.errors[0].reason

    @pytest.mark.asyncio
    async def test_resolve_unapproved_listing(self):
        from models.mcp import ListingStatus
        from services.agent_resolver import resolve_agent
        agent = MagicMock()
        agent.id = uuid.uuid4()
        agent.name = "unapproved-agent"
        agent.version = "1.0.0"

        comp = MagicMock()
        comp.component_type = "mcp"
        comp.component_id = uuid.uuid4()
        agent.components = [comp]

        listing = MagicMock()
        listing.status = ListingStatus.pending
        listing.name = "pending-mcp"

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = listing
        db = AsyncMock()
        db.execute.return_value = mock_result

        resolved = await resolve_agent(agent, db)
        assert resolved.ok is False
        assert "not approved" in resolved.errors[0].reason

    @pytest.mark.asyncio
    async def test_resolve_approved_listing(self):
        from models.mcp import ListingStatus
        from services.agent_resolver import resolve_agent
        agent = MagicMock()
        agent.id = uuid.uuid4()
        agent.name = "good-agent"
        agent.version = "1.0.0"

        comp = MagicMock()
        comp.component_type = "mcp"
        comp.component_id = uuid.uuid4()
        comp.order_index = 0
        comp.config_override = None
        agent.components = [comp]

        listing = MagicMock()
        listing.status = ListingStatus.approved
        listing.name = "good-mcp"
        listing.version = "2.0.0"
        listing.git_url = "https://github.com/org/repo.git"
        listing.git_ref = "abc123"
        listing.description = "A good MCP"
        listing.transport = "stdio"
        listing.tools_schema = None
        listing.fastmcp_validated = True
        listing.setup_instructions = None

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = listing
        db = AsyncMock()
        db.execute.return_value = mock_result

        resolved = await resolve_agent(agent, db)
        assert resolved.ok is True
        assert len(resolved.components) == 1
        assert resolved.components[0].name == "good-mcp"
        assert resolved.components[0].version == "2.0.0"
        assert resolved.components[0].git_ref == "abc123"

    @pytest.mark.asyncio
    async def test_resolve_skip_approval_check(self):
        """When require_approved=False, unapproved listings should resolve."""
        from models.mcp import ListingStatus
        from services.agent_resolver import resolve_agent
        agent = MagicMock()
        agent.id = uuid.uuid4()
        agent.name = "draft-agent"
        agent.version = "0.1.0"

        comp = MagicMock()
        comp.component_type = "skill"
        comp.component_id = uuid.uuid4()
        comp.order_index = 0
        comp.config_override = None
        agent.components = [comp]

        listing = MagicMock()
        listing.status = ListingStatus.pending
        listing.name = "pending-skill"
        listing.version = "1.0.0"
        listing.git_url = "https://github.com/org/skill.git"
        listing.git_ref = None
        listing.description = "A pending skill"
        listing.skill_path = "/"
        listing.task_type = "dev"
        listing.slash_command = None
        listing.triggers = None
        listing.has_scripts = False
        listing.is_power = False
        listing.mcp_server_config = None

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = listing
        db = AsyncMock()
        db.execute.return_value = mock_result

        resolved = await resolve_agent(agent, db, require_approved=False)
        assert resolved.ok is True
        assert len(resolved.components) == 1
        assert resolved.components[0].name == "pending-skill"

    @pytest.mark.asyncio
    async def test_resolve_mixed_success_and_failure(self):
        """An agent with both valid and invalid components."""
        from models.mcp import ListingStatus
        from services.agent_resolver import resolve_agent
        agent = MagicMock()
        agent.id = uuid.uuid4()
        agent.name = "mixed-agent"
        agent.version = "1.0.0"

        good_comp = MagicMock()
        good_comp.component_type = "mcp"
        good_comp.component_id = uuid.uuid4()
        good_comp.order_index = 0
        good_comp.config_override = None

        bad_comp = MagicMock()
        bad_comp.component_type = "mcp"
        bad_comp.component_id = uuid.uuid4()
        bad_comp.order_index = 1

        agent.components = [good_comp, bad_comp]

        good_listing = MagicMock()
        good_listing.status = ListingStatus.approved
        good_listing.name = "good-mcp"
        good_listing.version = "1.0"
        good_listing.git_url = "url"
        good_listing.git_ref = "abc"
        good_listing.description = ""
        good_listing.transport = None
        good_listing.tools_schema = None
        good_listing.fastmcp_validated = True
        good_listing.setup_instructions = None

        # Return good listing for first call, None for second
        mock_result_good = MagicMock()
        mock_result_good.scalar_one_or_none.return_value = good_listing
        mock_result_bad = MagicMock()
        mock_result_bad.scalar_one_or_none.return_value = None

        db = AsyncMock()
        db.execute.side_effect = [mock_result_good, mock_result_bad]

        resolved = await resolve_agent(agent, db)
        assert resolved.ok is False
        assert len(resolved.components) == 1
        assert len(resolved.errors) == 1


class TestValidateComponentIds:
    @pytest.mark.asyncio
    async def test_validate_empty_list(self):
        from services.agent_resolver import validate_component_ids
        db = AsyncMock()
        errors = await validate_component_ids([], db)
        assert errors == []

    @pytest.mark.asyncio
    async def test_validate_unknown_type(self):
        from services.agent_resolver import validate_component_ids
        db = AsyncMock()
        errors = await validate_component_ids(
            [{"component_type": "unknown", "component_id": uuid.uuid4()}],
            db,
        )
        assert len(errors) == 1
        assert "Unknown component type" in errors[0].reason

    @pytest.mark.asyncio
    async def test_validate_missing_component(self):
        from services.agent_resolver import validate_component_ids
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        db = AsyncMock()
        db.execute.return_value = mock_result

        errors = await validate_component_ids(
            [{"component_type": "mcp", "component_id": uuid.uuid4()}],
            db,
        )
        assert len(errors) == 1
        assert "not found" in errors[0].reason

    @pytest.mark.asyncio
    async def test_validate_unapproved_component(self):
        from models.mcp import ListingStatus
        from services.agent_resolver import validate_component_ids
        listing = MagicMock()
        listing.status = ListingStatus.pending
        listing.name = "pending-mcp"

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = listing
        db = AsyncMock()
        db.execute.return_value = mock_result

        errors = await validate_component_ids(
            [{"component_type": "mcp", "component_id": uuid.uuid4()}],
            db,
        )
        assert len(errors) == 1
        assert "not approved" in errors[0].reason

    @pytest.mark.asyncio
    async def test_validate_approved_component(self):
        from models.mcp import ListingStatus
        from services.agent_resolver import validate_component_ids
        listing = MagicMock()
        listing.status = ListingStatus.approved

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = listing
        db = AsyncMock()
        db.execute.return_value = mock_result

        errors = await validate_component_ids(
            [{"component_type": "mcp", "component_id": uuid.uuid4()}],
            db,
        )
        assert errors == []


# ── Builder Service Tests ───────────────────────────────────────────


class TestBuildAgentManifest:
    def test_empty_agent_manifest(self):
        from services.agent_builder import build_agent_manifest
        from services.agent_resolver import ResolvedAgent
        resolved = ResolvedAgent(
            agent_id=uuid.uuid4(),
            agent_name="empty",
            agent_version="1.0.0",
        )
        manifest = build_agent_manifest(resolved)
        assert manifest["name"] == "empty"
        assert manifest["version"] == "1.0.0"
        assert manifest["components"] == {}
        assert "errors" not in manifest

    def test_manifest_with_mcps(self):
        from services.agent_builder import build_agent_manifest
        from services.agent_resolver import ResolvedAgent, ResolvedComponent
        resolved = ResolvedAgent(
            agent_id=uuid.uuid4(),
            agent_name="mcp-agent",
            agent_version="1.0.0",
            components=[
                ResolvedComponent(
                    component_type="mcp", component_id=uuid.uuid4(),
                    name="filesystem-mcp", version="2.0.0",
                    git_url="https://github.com/org/repo.git", git_ref="abc123",
                    description="FS ops", order_index=0,
                    extra={"transport": "stdio", "tools_schema": None,
                           "fastmcp_validated": True, "setup_instructions": None},
                ),
            ],
        )
        manifest = build_agent_manifest(resolved)
        assert "mcps" in manifest["components"]
        assert len(manifest["components"]["mcps"]) == 1
        mcp = manifest["components"]["mcps"][0]
        assert mcp["name"] == "filesystem-mcp"
        assert mcp["version"] == "2.0.0"
        assert mcp["git_ref"] == "abc123"
        assert mcp["transport"] == "stdio"

    def test_manifest_with_all_types(self):
        from services.agent_builder import build_agent_manifest
        from services.agent_resolver import ResolvedAgent, ResolvedComponent

        def _comp(ctype, name, order, **extra_kw):
            return ResolvedComponent(
                component_type=ctype, component_id=uuid.uuid4(),
                name=name, version="1.0", git_url="url", git_ref="ref",
                description=f"{name} desc", order_index=order,
                extra=extra_kw,
            )

        resolved = ResolvedAgent(
            agent_id=uuid.uuid4(),
            agent_name="full-agent",
            agent_version="2.0.0",
            components=[
                _comp("mcp", "fs-mcp", 0, transport="stdio"),
                _comp("skill", "tdd", 1, task_type="dev", slash_command="/tdd"),
                _comp("hook", "pre-commit", 2, event="PreCommit",
                      execution_mode="sync", priority=50),
                _comp("prompt", "review", 3, template="Review: {{code}}",
                      variables=["code"]),
                _comp("sandbox", "python", 4, image="python:3.12",
                      runtime_type="docker", resource_limits={"cpu": "1"}),
            ],
        )
        manifest = build_agent_manifest(resolved)
        assert set(manifest["components"].keys()) == {"mcps", "skills", "hooks", "prompts", "sandboxes"}
        assert len(manifest["components"]["mcps"]) == 1
        assert len(manifest["components"]["skills"]) == 1
        assert len(manifest["components"]["hooks"]) == 1
        assert len(manifest["components"]["prompts"]) == 1
        assert len(manifest["components"]["sandboxes"]) == 1

    def test_manifest_includes_errors(self):
        from services.agent_builder import build_agent_manifest
        from services.agent_resolver import ResolvedAgent, ResolutionError
        resolved = ResolvedAgent(
            agent_id=uuid.uuid4(),
            agent_name="error-agent",
            agent_version="1.0.0",
            errors=[
                ResolutionError(
                    component_type="mcp",
                    component_id=uuid.uuid4(),
                    reason="not found",
                ),
            ],
        )
        manifest = build_agent_manifest(resolved)
        assert "errors" in manifest
        assert len(manifest["errors"]) == 1
        assert manifest["errors"][0]["reason"] == "not found"

    def test_manifest_hook_fields(self):
        from services.agent_builder import build_agent_manifest
        from services.agent_resolver import ResolvedAgent, ResolvedComponent
        resolved = ResolvedAgent(
            agent_id=uuid.uuid4(),
            agent_name="hook-agent",
            agent_version="1.0.0",
            components=[
                ResolvedComponent(
                    component_type="hook", component_id=uuid.uuid4(),
                    name="pre-commit-lint", version="1.0",
                    git_url="url", git_ref="ref", description="Lint hook",
                    order_index=0,
                    extra={"event": "PreCommit", "execution_mode": "sync", "priority": 10},
                ),
            ],
        )
        manifest = build_agent_manifest(resolved)
        hook = manifest["components"]["hooks"][0]
        assert hook["event"] == "PreCommit"
        assert hook["execution_mode"] == "sync"
        assert hook["priority"] == 10

    def test_manifest_sandbox_fields(self):
        from services.agent_builder import build_agent_manifest
        from services.agent_resolver import ResolvedAgent, ResolvedComponent
        resolved = ResolvedAgent(
            agent_id=uuid.uuid4(),
            agent_name="sandbox-agent",
            agent_version="1.0.0",
            components=[
                ResolvedComponent(
                    component_type="sandbox", component_id=uuid.uuid4(),
                    name="python-sandbox", version="1.0",
                    git_url="url", git_ref="ref", description="",
                    order_index=0,
                    extra={
                        "image": "python:3.12",
                        "runtime_type": "docker",
                        "resource_limits": {"cpu": "1", "memory": "512m"},
                    },
                ),
            ],
        )
        manifest = build_agent_manifest(resolved)
        sandbox = manifest["components"]["sandboxes"][0]
        assert sandbox["image"] == "python:3.12"
        assert sandbox["runtime_type"] == "docker"
        assert sandbox["resource_limits"]["memory"] == "512m"

    def test_manifest_with_config_override(self):
        from services.agent_builder import build_agent_manifest
        from services.agent_resolver import ResolvedAgent, ResolvedComponent
        resolved = ResolvedAgent(
            agent_id=uuid.uuid4(),
            agent_name="override-agent",
            agent_version="1.0.0",
            components=[
                ResolvedComponent(
                    component_type="mcp", component_id=uuid.uuid4(),
                    name="db-mcp", version="1.0",
                    git_url="url", git_ref="ref", description="",
                    order_index=0,
                    config_override={"env": {"DB_URL": "postgres://..."}},
                    extra={},
                ),
            ],
        )
        manifest = build_agent_manifest(resolved)
        mcp = manifest["components"]["mcps"][0]
        assert mcp["config_override"] == {"env": {"DB_URL": "postgres://..."}}


class TestBuildCompositionSummary:
    def test_summary_resolved_flag(self):
        from services.agent_builder import build_composition_summary
        from services.agent_resolver import ResolvedAgent
        resolved = ResolvedAgent(
            agent_id=uuid.uuid4(),
            agent_name="ok-agent",
            agent_version="1.0",
        )
        summary = build_composition_summary(resolved)
        assert summary["resolved"] is True

    def test_summary_not_resolved_with_errors(self):
        from services.agent_builder import build_composition_summary
        from services.agent_resolver import ResolvedAgent, ResolutionError
        resolved = ResolvedAgent(
            agent_id=uuid.uuid4(),
            agent_name="bad-agent",
            agent_version="1.0",
            errors=[ResolutionError("mcp", uuid.uuid4(), "missing")],
        )
        summary = build_composition_summary(resolved)
        assert summary["resolved"] is False
        assert "errors" in summary

    def test_summary_component_counts(self):
        from services.agent_builder import build_composition_summary
        from services.agent_resolver import ResolvedAgent, ResolvedComponent

        def _comp(ctype, name, order):
            return ResolvedComponent(
                component_type=ctype, component_id=uuid.uuid4(),
                name=name, version="1.0", git_url="u", git_ref="r",
                description="", order_index=order,
            )

        resolved = ResolvedAgent(
            agent_id=uuid.uuid4(),
            agent_name="counted-agent",
            agent_version="1.0",
            components=[
                _comp("mcp", "a", 0),
                _comp("mcp", "b", 1),
                _comp("skill", "c", 2),
            ],
        )
        summary = build_composition_summary(resolved)
        assert summary["component_counts"]["mcp"] == 2
        assert summary["component_counts"]["skill"] == 1
        assert "hook" not in summary["component_counts"]


# ── Route Schema Integration Tests ──────────────────────────────────


class TestComponentLinkResponseInAgentResponse:
    def test_agent_response_has_component_links_field(self):
        """AgentResponse schema must include component_links."""
        from schemas.agent import AgentResponse
        assert "component_links" in AgentResponse.model_fields
        assert "mcp_links" in AgentResponse.model_fields  # backwards compat

    def test_component_link_response_serializes(self):
        from schemas.agent import ComponentLinkResponse
        cid = uuid.uuid4()
        link = ComponentLinkResponse(
            component_type="skill",
            component_id=cid,
            version_ref="2.0",
            order=1,
            config_override={"key": "val"},
        )
        data = link.model_dump()
        assert data["component_type"] == "skill"
        assert data["component_id"] == cid
        assert data["config_override"] == {"key": "val"}

    def test_component_link_response_no_override(self):
        from schemas.agent import ComponentLinkResponse
        link = ComponentLinkResponse(
            component_type="mcp",
            component_id=uuid.uuid4(),
            version_ref="1.0",
            order=0,
        )
        assert link.config_override is None


class TestResolverAndBuilderModulesImportable:
    def test_resolver_module_importable(self):
        from services.agent_resolver import (
            ResolvedAgent, ResolvedComponent, ResolutionError,
            resolve_agent, validate_component_ids, _LISTING_MODELS,
        )
        assert callable(resolve_agent)
        assert callable(validate_component_ids)
        assert len(_LISTING_MODELS) == 5

    def test_builder_module_importable(self):
        from services.agent_builder import (
            build_agent_manifest, build_composition_summary,
        )
        assert callable(build_agent_manifest)
        assert callable(build_composition_summary)
