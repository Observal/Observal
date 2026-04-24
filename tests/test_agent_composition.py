"""Tests for agent composition and resolver (issue #80).

Tests the resolver service, builder service, schema updates,
and route endpoints for multi-component agent composition.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

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

        assert {"mcp", "skill", "hook", "prompt", "sandbox"} == VALID_COMPONENT_TYPES

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
        from schemas.agent import AgentCreateRequest, ComponentRef, GoalSectionRequest, GoalTemplateRequest

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
        from schemas.agent import AgentCreateRequest, GoalSectionRequest, GoalTemplateRequest

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
        from schemas.agent import AgentCreateRequest, ComponentRef, GoalSectionRequest, GoalTemplateRequest

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
        from services.agent_resolver import ResolutionError, ResolvedAgent

        ra = ResolvedAgent(
            agent_id=uuid.uuid4(),
            agent_name="test",
            agent_version="1.0",
            errors=[
                ResolutionError(
                    component_type="mcp",
                    component_id=uuid.uuid4(),
                    reason="not found",
                )
            ],
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
                    component_type="mcp",
                    component_id=cid1,
                    name="mcp1",
                    version="1.0",
                    git_url="url",
                    git_ref="abc",
                    description="",
                    order_index=0,
                ),
                ResolvedComponent(
                    component_type="skill",
                    component_id=cid2,
                    name="skill1",
                    version="1.0",
                    git_url="url",
                    git_ref="abc",
                    description="",
                    order_index=1,
                ),
                ResolvedComponent(
                    component_type="mcp",
                    component_id=cid3,
                    name="mcp2",
                    version="2.0",
                    git_url="url",
                    git_ref="def",
                    description="",
                    order_index=2,
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
        listing.mcp_validated = True
        listing.setup_instructions = "pip install"
        extra = _extract_extra(listing, "mcp")
        assert extra["transport"] == "stdio"
        assert extra["mcp_validated"] is True
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
        agent.prompt = "Test prompt"
        agent.description = "Test desc"
        agent.model_name = "test-model"
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
        agent.prompt = ""
        agent.description = ""
        agent.model_name = ""

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
        agent.prompt = ""
        agent.description = ""
        agent.model_name = ""

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
        agent.prompt = ""
        agent.description = ""
        agent.model_name = ""

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
        agent.prompt = "Agent prompt"
        agent.description = "Agent desc"
        agent.model_name = "test-model"

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
        listing.mcp_validated = True
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
        agent.prompt = ""
        agent.description = ""
        agent.model_name = ""

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
        agent.prompt = ""
        agent.description = ""
        agent.model_name = ""

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
        good_listing.mcp_validated = True
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
                    component_type="mcp",
                    component_id=uuid.uuid4(),
                    name="filesystem-mcp",
                    version="2.0.0",
                    git_url="https://github.com/org/repo.git",
                    git_ref="abc123",
                    description="FS ops",
                    order_index=0,
                    extra={
                        "transport": "stdio",
                        "tools_schema": None,
                        "mcp_validated": True,
                        "setup_instructions": None,
                    },
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
                component_type=ctype,
                component_id=uuid.uuid4(),
                name=name,
                version="1.0",
                git_url="url",
                git_ref="ref",
                description=f"{name} desc",
                order_index=order,
                extra=extra_kw,
            )

        resolved = ResolvedAgent(
            agent_id=uuid.uuid4(),
            agent_name="full-agent",
            agent_version="2.0.0",
            components=[
                _comp("mcp", "fs-mcp", 0, transport="stdio"),
                _comp("skill", "tdd", 1, task_type="dev", slash_command="/tdd"),
                _comp("hook", "pre-commit", 2, event="PreCommit", execution_mode="sync", priority=50),
                _comp("prompt", "review", 3, template="Review: {{code}}", variables=["code"]),
                _comp("sandbox", "python", 4, image="python:3.12", runtime_type="docker", resource_limits={"cpu": "1"}),
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
        from services.agent_resolver import ResolutionError, ResolvedAgent

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
                    component_type="hook",
                    component_id=uuid.uuid4(),
                    name="pre-commit-lint",
                    version="1.0",
                    git_url="url",
                    git_ref="ref",
                    description="Lint hook",
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
                    component_type="sandbox",
                    component_id=uuid.uuid4(),
                    name="python-sandbox",
                    version="1.0",
                    git_url="url",
                    git_ref="ref",
                    description="",
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
                    component_type="mcp",
                    component_id=uuid.uuid4(),
                    name="db-mcp",
                    version="1.0",
                    git_url="url",
                    git_ref="ref",
                    description="",
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
        from services.agent_resolver import ResolutionError, ResolvedAgent

        resolved = ResolvedAgent(
            agent_id=uuid.uuid4(),
            agent_name="bad-agent",
            agent_version="1.0",
            errors=[ResolutionError(component_type="mcp", component_id=uuid.uuid4(), reason="missing")],
        )
        summary = build_composition_summary(resolved)
        assert summary["resolved"] is False
        assert "errors" in summary

    def test_summary_component_counts(self):
        from services.agent_builder import build_composition_summary
        from services.agent_resolver import ResolvedAgent, ResolvedComponent

        def _comp(ctype, name, order):
            return ResolvedComponent(
                component_type=ctype,
                component_id=uuid.uuid4(),
                name=name,
                version="1.0",
                git_url="u",
                git_ref="r",
                description="",
                order_index=order,
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


class TestPydanticValidation:
    """Verify Pydantic validation on resolver/builder models."""

    def test_resolved_component_is_frozen(self):
        from services.agent_resolver import ResolvedComponent

        comp = ResolvedComponent(
            component_type="mcp",
            component_id=uuid.uuid4(),
            name="test",
            version="1.0",
            git_url="url",
        )
        with pytest.raises((TypeError, AttributeError, ValidationError)):
            comp.name = "changed"

    def test_resolution_error_is_frozen(self):
        from services.agent_resolver import ResolutionError

        err = ResolutionError(
            component_type="mcp",
            component_id=uuid.uuid4(),
            reason="test",
        )
        with pytest.raises((TypeError, AttributeError, ValidationError)):
            err.reason = "changed"

    def test_resolved_agent_serializes_to_dict(self):
        from services.agent_resolver import ResolvedAgent

        ra = ResolvedAgent(
            agent_id=uuid.uuid4(),
            agent_name="test",
            agent_version="1.0",
        )
        data = ra.model_dump()
        assert data["agent_name"] == "test"
        assert data["ok"] is True

    def test_resolved_component_rejects_invalid_type(self):
        from pydantic import ValidationError

        from services.agent_resolver import ResolvedComponent

        with pytest.raises(ValidationError):
            ResolvedComponent(
                component_type="invalid_type",
                component_id=uuid.uuid4(),
                name="bad",
                version="1.0",
                git_url="url",
            )

    def test_manifest_component_dump_compact(self):
        from services.agent_builder import ManifestComponent

        comp = ManifestComponent(
            name="test-mcp",
            version="1.0",
            git_url="url",
            description="desc",
            transport="stdio",
        )
        dumped = comp.model_dump_compact()
        assert "transport" in dumped
        assert "image" not in dumped  # None fields excluded
        assert "slash_command" not in dumped

    def test_agent_manifest_model_validates(self):
        from services.agent_builder import AgentManifest, ManifestComponent, ManifestComponents

        manifest = AgentManifest(
            name="my-agent",
            version="2.0",
            components=ManifestComponents(
                mcps=[ManifestComponent(name="a", version="1.0", git_url="url")],
            ),
        )
        assert manifest.name == "my-agent"
        assert len(manifest.components.mcps) == 1
        compact = manifest.model_dump_compact()
        assert compact["components"]["mcps"][0]["name"] == "a"
        assert "skills" not in compact["components"]

    def test_ide_agent_config_model(self):
        from services.agent_builder import AgentFile, IdeAgentConfig

        config = IdeAgentConfig(
            ide="claude-code",
            files=[
                AgentFile(path=".claude/rules/test.md", content="# Rules", format="markdown"),
                AgentFile(path=".mcp.json", content={"mcpServers": {}}, format="json"),
            ],
            env={"OTEL_ENDPOINT": "http://localhost:8000"},
        )
        assert len(config.files) == 2
        assert config.files[0].format == "markdown"
        assert config.files[1].format == "json"

    def test_composition_summary_model(self):
        from services.agent_builder import CompositionSummary

        summary = CompositionSummary(
            agent_id=str(uuid.uuid4()),
            agent_name="test",
            agent_version="1.0",
            resolved=True,
            component_counts={"mcp": 2, "skill": 1},
        )
        data = summary.model_dump()
        assert data["resolved"] is True
        assert data["component_counts"]["mcp"] == 2


class TestResolverAndBuilderModulesImportable:
    def test_resolver_module_importable(self):
        from services.agent_resolver import (
            _LISTING_MODELS,
            resolve_agent,
            validate_component_ids,
        )

        assert callable(resolve_agent)
        assert callable(validate_component_ids)
        assert len(_LISTING_MODELS) == 5

    def test_builder_module_importable(self):
        from services.agent_builder import (
            SUPPORTED_IDES,
            build_agent_manifest,
            build_composition_summary,
            generate_ide_agent_files,
        )

        assert callable(build_agent_manifest)
        assert callable(build_composition_summary)
        assert callable(generate_ide_agent_files)
        assert "claude-code" in SUPPORTED_IDES
        assert "copilot" in SUPPORTED_IDES


class TestGenerateIdeAgentFiles:
    """Tests for universal IDE agent file generation from AgentManifest."""

    def _make_manifest(self, **overrides):
        from services.agent_builder import (
            AgentManifest,
            ManifestComponent,
            ManifestComponents,
        )

        defaults = {
            "name": "test-agent",
            "version": "1.0",
            "prompt": "You are a helpful coding assistant.",
            "description": "A test agent for unit testing.",
            "model_name": "claude-sonnet-4-20250514",
            "components": ManifestComponents(
                mcps=[
                    ManifestComponent(
                        name="github-mcp",
                        version="2.0",
                        git_url="https://github.com/example/mcp",
                        description="GitHub integration MCP server",
                    ),
                    ManifestComponent(
                        name="postgres-mcp",
                        version="1.5",
                        git_url="https://github.com/example/pg",
                        description="PostgreSQL query MCP",
                    ),
                ],
                skills=[
                    ManifestComponent(
                        name="code-review",
                        version="1.0",
                        git_url="https://github.com/example/cr",
                        slash_command="review",
                    ),
                ],
            ),
        }
        defaults.update(overrides)
        return AgentManifest(**defaults)

    # ── Claude Code ────────────────────────────────────────────

    def test_claude_code_generates_rules_file(self):
        from services.agent_builder import generate_ide_agent_files

        manifest = self._make_manifest()
        config = generate_ide_agent_files(manifest, "claude-code")
        assert config.ide == "claude-code"
        agent_file = next(f for f in config.files if f.path == ".claude/agents/test-agent.md")
        assert agent_file.format == "markdown"
        assert "You are a helpful coding assistant." in agent_file.content

    def test_claude_code_mcp_setup_commands(self):
        from services.agent_builder import generate_ide_agent_files

        manifest = self._make_manifest()
        config = generate_ide_agent_files(manifest, "claude-code")
        assert len(config.setup_commands) == 2
        assert config.setup_commands[0][:3] == ["claude", "mcp", "add"]
        assert "github-mcp" in config.setup_commands[0]

    def test_claude_code_env_includes_telemetry(self):
        from services.agent_builder import generate_ide_agent_files

        manifest = self._make_manifest()
        config = generate_ide_agent_files(manifest, "claude-code")
        assert "CLAUDE_CODE_ENABLE_TELEMETRY" in config.env
        assert config.env["OTEL_EXPORTER_OTLP_PROTOCOL"] == "http/json"

    def test_claude_code_underscore_alias(self):
        from services.agent_builder import generate_ide_agent_files

        manifest = self._make_manifest()
        config = generate_ide_agent_files(manifest, "claude_code")
        assert config.ide == "claude-code"

    # ── Cursor ─────────────────────────────────────────────────

    def test_cursor_generates_rules_and_mcp_json(self):
        from services.agent_builder import generate_ide_agent_files

        manifest = self._make_manifest()
        config = generate_ide_agent_files(manifest, "cursor")
        assert config.ide == "cursor"
        rules = next(f for f in config.files if f.path == ".cursor/rules/test-agent.md")
        mcp_json = next(f for f in config.files if f.format == "json")
        assert rules.format == "markdown"
        assert mcp_json.path == ".cursor/mcp.json"
        assert "mcpServers" in mcp_json.content
        assert "github-mcp" in mcp_json.content["mcpServers"]

    # ── VS Code ────────────────────────────────────────────────

    def test_vscode_generates_rules_and_mcp_json(self):
        from services.agent_builder import generate_ide_agent_files

        manifest = self._make_manifest()
        config = generate_ide_agent_files(manifest, "vscode")
        assert config.ide == "vscode"
        rules = next(f for f in config.files if f.format == "markdown")
        mcp_json = next(f for f in config.files if f.format == "json")
        assert rules.path == ".vscode/rules/test-agent.md"
        assert mcp_json.path == ".vscode/mcp.json"

    # ── Gemini CLI ─────────────────────────────────────────────

    def test_gemini_cli_generates_gemini_md(self):
        from services.agent_builder import generate_ide_agent_files

        manifest = self._make_manifest()
        config = generate_ide_agent_files(manifest, "gemini-cli")
        assert config.ide == "gemini-cli"
        md_files = [f for f in config.files if f.format == "markdown"]
        assert len(md_files) == 1
        assert md_files[0].path == "GEMINI.md"
        assert "You are a helpful coding assistant." in md_files[0].content

    def test_gemini_cli_env_includes_otel(self):
        from services.agent_builder import generate_ide_agent_files

        manifest = self._make_manifest()
        config = generate_ide_agent_files(manifest, "gemini-cli")
        assert config.env["OTEL_EXPORTER_OTLP_PROTOCOL"] == "http/json"

    def test_gemini_cli_underscore_alias(self):
        from services.agent_builder import generate_ide_agent_files

        manifest = self._make_manifest()
        config = generate_ide_agent_files(manifest, "gemini_cli")
        assert config.ide == "gemini-cli"

    # ── Kiro ───────────────────────────────────────────────────

    def test_kiro_generates_agent_json(self):
        from services.agent_builder import generate_ide_agent_files

        manifest = self._make_manifest()
        config = generate_ide_agent_files(manifest, "kiro")
        assert config.ide == "kiro"
        agent_file = next(f for f in config.files if f.path == "~/.kiro/agents/test-agent.json")
        assert agent_file.format == "json"
        content = agent_file.content
        assert content["name"] == "test-agent"
        assert "You are a helpful coding assistant." in content["prompt"]
        assert "Agent Specialization" in content["prompt"]
        assert "mcpServers" in content
        assert "github-mcp" in content["mcpServers"]
        assert "*" in content["tools"]
        assert content["model"] is None  # Kiro uses auto model selection

    # ── Codex ──────────────────────────────────────────────────

    def test_codex_generates_agents_md(self):
        from services.agent_builder import generate_ide_agent_files

        manifest = self._make_manifest()
        config = generate_ide_agent_files(manifest, "codex")
        assert config.ide == "codex"
        assert len(config.files) >= 1
        md_file = next(f for f in config.files if f.format == "markdown")
        assert md_file.path == "AGENTS.md"

    # ── GitHub Copilot ─────────────────────────────────────────

    def test_copilot_generates_instructions_md(self):
        from services.agent_builder import generate_ide_agent_files

        manifest = self._make_manifest()
        config = generate_ide_agent_files(manifest, "copilot")
        assert config.ide == "copilot"
        paths = [f.path for f in config.files]
        assert ".github/copilot-instructions.md" in paths
        md = next(f for f in config.files if f.path == ".github/copilot-instructions.md")
        assert md.format == "markdown"
        assert "You are a helpful coding assistant." in md.content

    def test_copilot_generates_mcp_json(self):
        from services.agent_builder import generate_ide_agent_files

        manifest = self._make_manifest()
        config = generate_ide_agent_files(manifest, "copilot")
        paths = [f.path for f in config.files]
        assert ".vscode/mcp.json" in paths
        mcp_file = next(f for f in config.files if f.path == ".vscode/mcp.json")
        assert mcp_file.format == "json"
        assert "servers" in mcp_file.content

    # ── Rules markdown content ─────────────────────────────────

    def test_rules_markdown_includes_component_sections(self):
        from services.agent_builder import generate_ide_agent_files

        manifest = self._make_manifest()
        config = generate_ide_agent_files(manifest, "cursor")
        rules = next(f for f in config.files if f.format == "markdown")
        content = rules.content
        assert "## MCP Servers" in content
        assert "**github-mcp**" in content
        assert "**postgres-mcp**" in content
        assert "## Skills" in content
        assert "**code-review**" in content
        assert "`/review`" in content

    def test_rules_markdown_empty_prompt(self):
        from services.agent_builder import generate_ide_agent_files

        manifest = self._make_manifest(prompt="")
        config = generate_ide_agent_files(manifest, "copilot")
        content = config.files[0].content
        # Should still have component sections
        assert "## MCP Servers" in content

    def test_rules_markdown_no_components(self):
        from services.agent_builder import AgentManifest, ManifestComponents, generate_ide_agent_files

        manifest = AgentManifest(
            name="bare-agent",
            version="1.0",
            prompt="Just a prompt, no components.",
            components=ManifestComponents(),
        )
        config = generate_ide_agent_files(manifest, "copilot")
        content = config.files[0].content
        assert "Just a prompt, no components." in content
        assert "## MCP Servers" not in content

    # ── MCP entries ────────────────────────────────────────────

    def test_mcp_entries_use_observal_shim(self):
        from services.agent_builder import generate_ide_agent_files

        manifest = self._make_manifest()
        config = generate_ide_agent_files(manifest, "cursor")
        for name, entry in config.mcp_servers.items():
            assert entry["command"] == "observal-shim"
            assert "--mcp-id" in entry["args"]

    def test_no_mcps_produces_empty_servers(self):
        from services.agent_builder import (
            AgentManifest,
            ManifestComponent,
            ManifestComponents,
            generate_ide_agent_files,
        )

        manifest = AgentManifest(
            name="no-mcp-agent",
            version="1.0",
            prompt="Agent without MCPs.",
            components=ManifestComponents(
                skills=[ManifestComponent(name="s", version="1.0", git_url="url")],
            ),
        )
        config = generate_ide_agent_files(manifest, "claude-code")
        assert config.mcp_servers == {}
        assert config.setup_commands == []

    # ── Name sanitization ──────────────────────────────────────

    def test_name_with_spaces_gets_sanitized(self):
        from services.agent_builder import generate_ide_agent_files

        manifest = self._make_manifest(name="My Cool Agent!")
        config = generate_ide_agent_files(manifest, "claude-code")
        rules = config.files[0]
        assert "My Cool Agent!" not in rules.path
        assert "My-Cool-Agent-" in rules.path

    # ── Unsupported IDE ────────────────────────────────────────

    def test_unsupported_ide_raises_value_error(self):
        import pytest

        from services.agent_builder import generate_ide_agent_files

        manifest = self._make_manifest()
        with pytest.raises(ValueError, match="Unsupported IDE"):
            generate_ide_agent_files(manifest, "notepad")

    # ── Hooks in markdown ──────────────────────────────────────

    def test_hooks_appear_in_rules_markdown(self):
        from services.agent_builder import (
            AgentManifest,
            ManifestComponent,
            ManifestComponents,
            generate_ide_agent_files,
        )

        manifest = AgentManifest(
            name="hook-agent",
            version="1.0",
            prompt="Agent with hooks.",
            components=ManifestComponents(
                hooks=[
                    ManifestComponent(
                        name="lint-hook",
                        version="1.0",
                        git_url="url",
                        event="pre_commit",
                        execution_mode="sync",
                    ),
                ],
            ),
        )
        config = generate_ide_agent_files(manifest, "gemini-cli")
        content = config.files[0].content
        assert "## Hooks" in content
        assert "**lint-hook**" in content
        assert "`pre_commit`" in content

    # ── All supported IDEs produce valid output ────────────────

    def test_all_supported_ides_produce_output(self):
        from services.agent_builder import SUPPORTED_IDES, generate_ide_agent_files

        manifest = self._make_manifest()
        for ide in SUPPORTED_IDES:
            config = generate_ide_agent_files(manifest, ide)
            assert config.ide is not None
            assert len(config.files) > 0

    # ── Manifest with prompt/description round-trips ───────────

    def test_manifest_compact_includes_prompt_and_description(self):
        manifest = self._make_manifest()
        compact = manifest.model_dump_compact()
        assert compact["prompt"] == "You are a helpful coding assistant."
        assert compact["description"] == "A test agent for unit testing."
        assert compact["model_name"] == "claude-sonnet-4-20250514"

    def test_manifest_compact_omits_empty_prompt(self):
        manifest = self._make_manifest(prompt="", description="", model_name="")
        compact = manifest.model_dump_compact()
        assert "prompt" not in compact
        assert "description" not in compact
        assert "model_name" not in compact
