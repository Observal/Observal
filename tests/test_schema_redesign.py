"""Tests for the agent-centric schema redesign."""

import uuid

import pytest


class TestOrganizationModel:
    def test_organization_tablename(self):
        from models.organization import Organization

        assert Organization.__tablename__ == "organizations"

    def test_organization_has_required_columns(self):
        from models.organization import Organization

        cols = {c.name for c in Organization.__table__.columns}
        assert "id" in cols
        assert "name" in cols
        assert "slug" in cols
        assert "created_at" in cols
        assert "updated_at" in cols

    def test_organization_slug_is_unique(self):
        from models.organization import Organization

        slug_col = Organization.__table__.c.slug
        assert slug_col.unique or any(
            uc
            for uc in Organization.__table__.constraints
            if hasattr(uc, "columns") and "slug" in [c.name for c in uc.columns]
        )


class TestUserOrgField:
    def test_user_has_org_id(self):
        from models.user import User

        cols = {c.name for c in User.__table__.columns}
        assert "org_id" in cols

    def test_user_org_id_is_nullable(self):
        from models.user import User

        org_col = User.__table__.c.org_id
        assert org_col.nullable is True


class TestComponentSourceModel:
    def test_component_source_tablename(self):
        from models.component_source import ComponentSource

        assert ComponentSource.__tablename__ == "component_sources"

    def test_component_source_has_required_columns(self):
        from models.component_source import ComponentSource

        cols = {c.name for c in ComponentSource.__table__.columns}
        required = {
            "id",
            "url",
            "provider",
            "component_type",
            "is_public",
            "owner_org_id",
            "auto_sync_interval",
            "last_synced_at",
            "sync_status",
            "sync_error",
            "created_at",
            "updated_at",
        }
        assert required.issubset(cols)

    def test_component_source_url_type_unique(self):
        from models.component_source import ComponentSource

        table = ComponentSource.__table__
        unique_constraints = [uc for uc in table.constraints if hasattr(uc, "columns") and len(uc.columns) == 2]
        col_sets = [frozenset(c.name for c in uc.columns) for uc in unique_constraints]
        assert frozenset({"url", "component_type"}) in col_sets


class TestComponentTableUpdates:
    """All component tables must have: is_private, owner_org_id, download_count, unique_agents."""

    @pytest.mark.parametrize(
        "model_path,model_name",
        [
            ("models.mcp", "McpListing"),
            ("models.skill", "SkillListing"),
            ("models.hook", "HookListing"),
            ("models.prompt", "PromptListing"),
            ("models.sandbox", "SandboxListing"),
        ],
    )
    def test_component_has_org_fields(self, model_path, model_name):
        import importlib

        mod = importlib.import_module(model_path)
        cls = getattr(mod, model_name)
        cols = {c.name for c in cls.__table__.columns}
        assert "is_private" in cols, f"{model_name} missing is_private"
        assert "owner_org_id" in cols, f"{model_name} missing owner_org_id"

    @pytest.mark.parametrize(
        "model_path,model_name",
        [
            ("models.mcp", "McpListing"),
            ("models.skill", "SkillListing"),
            ("models.hook", "HookListing"),
            ("models.prompt", "PromptListing"),
            ("models.sandbox", "SandboxListing"),
        ],
    )
    def test_component_has_download_counts(self, model_path, model_name):
        import importlib

        mod = importlib.import_module(model_path)
        cls = getattr(mod, model_name)
        cols = {c.name for c in cls.__table__.columns}
        assert "download_count" in cols, f"{model_name} missing download_count"
        assert "unique_agents" in cols, f"{model_name} missing unique_agents"

    @pytest.mark.parametrize(
        "model_path,model_name",
        [
            ("models.mcp", "McpListing"),
            ("models.skill", "SkillListing"),
            ("models.hook", "HookListing"),
            ("models.prompt", "PromptListing"),
            ("models.sandbox", "SandboxListing"),
        ],
    )
    def test_component_has_git_url(self, model_path, model_name):
        import importlib

        mod = importlib.import_module(model_path)
        cls = getattr(mod, model_name)
        cols = {c.name for c in cls.__table__.columns}
        assert "git_url" in cols, f"{model_name} missing git_url"

    @pytest.mark.parametrize(
        "model_path,model_name",
        [
            ("models.mcp", "McpListing"),
            ("models.skill", "SkillListing"),
            ("models.hook", "HookListing"),
            ("models.prompt", "PromptListing"),
            ("models.sandbox", "SandboxListing"),
        ],
    )
    def test_component_has_git_ref(self, model_path, model_name):
        import importlib

        mod = importlib.import_module(model_path)
        cls = getattr(mod, model_name)
        cols = {c.name for c in cls.__table__.columns}
        assert "git_ref" in cols, f"{model_name} missing git_ref"

    def test_mcp_has_mcp_validated(self):
        from models.mcp import McpListing

        cols = {c.name for c in McpListing.__table__.columns}
        assert "mcp_validated" in cols

    def test_skill_link_table_removed(self):
        """AgentSkillLink should no longer exist — replaced by AgentComponent."""
        from models import skill

        assert not hasattr(skill, "AgentSkillLink")

    def test_hook_link_table_removed(self):
        """AgentHookLink should no longer exist — replaced by AgentComponent."""
        from models import hook

        assert not hasattr(hook, "AgentHookLink")


class TestAgentModelUpdate:
    def test_agent_has_org_fields(self):
        from models.agent import Agent

        cols = {c.name for c in Agent.__table__.columns}
        assert "is_private" in cols
        assert "owner_org_id" in cols

    def test_agent_has_git_url(self):
        from models.agent import Agent

        cols = {c.name for c in Agent.__table__.columns}
        assert "git_url" in cols

    def test_agent_has_download_metrics(self):
        from models.agent import Agent

        cols = {c.name for c in Agent.__table__.columns}
        assert "download_count" in cols
        assert "unique_users" in cols

    def test_agent_git_url_is_nullable(self):
        from models.agent import Agent

        git_col = Agent.__table__.c.git_url
        assert git_col.nullable is True

    def test_agent_mcp_link_removed(self):
        """AgentMcpLink should no longer exist — replaced by AgentComponent."""
        from models import agent

        assert not hasattr(agent, "AgentMcpLink")


class TestAgentComponentModel:
    def test_agent_component_tablename(self):
        from models.agent_component import AgentComponent

        assert AgentComponent.__tablename__ == "agent_components"

    def test_agent_component_has_required_columns(self):
        from models.agent_component import AgentComponent

        cols = {c.name for c in AgentComponent.__table__.columns}
        required = {
            "id",
            "agent_id",
            "component_type",
            "component_id",
            "version_ref",
            "order_index",
            "config_override",
            "created_at",
        }
        assert required.issubset(cols)

    def test_agent_component_has_unique_constraint(self):
        from models.agent_component import AgentComponent

        table = AgentComponent.__table__
        unique_constraints = [uc for uc in table.constraints if hasattr(uc, "columns") and len(uc.columns) == 3]
        col_sets = [frozenset(c.name for c in uc.columns) for uc in unique_constraints]
        assert frozenset({"agent_id", "component_type", "component_id"}) in col_sets

    def test_agent_component_no_fk_on_component_id(self):
        """component_id should NOT have a FK constraint (polymorphic, future flexibility)."""
        from models.agent_component import AgentComponent

        col = AgentComponent.__table__.c.component_id
        fks = col.foreign_keys
        assert len(fks) == 0, "component_id should have no FK constraints"


class TestDownloadModels:
    def test_agent_download_tablename(self):
        from models.download import AgentDownloadRecord

        assert AgentDownloadRecord.__tablename__ == "agent_download_records"

    def test_agent_download_has_required_columns(self):
        from models.download import AgentDownloadRecord

        cols = {c.name for c in AgentDownloadRecord.__table__.columns}
        required = {"id", "agent_id", "user_id", "fingerprint", "source", "ide", "installed_at"}
        assert required.issubset(cols)

    def test_agent_download_user_id_nullable(self):
        """user_id nullable for anonymous users (fingerprint used instead)."""
        from models.download import AgentDownloadRecord

        col = AgentDownloadRecord.__table__.c.user_id
        assert col.nullable is True

    def test_agent_download_has_unique_constraints(self):
        from models.download import AgentDownloadRecord

        table = AgentDownloadRecord.__table__
        unique_constraints = [uc for uc in table.constraints if hasattr(uc, "columns") and len(uc.columns) == 2]
        col_sets = [frozenset(c.name for c in uc.columns) for uc in unique_constraints]
        assert frozenset({"agent_id", "user_id"}) in col_sets
        assert frozenset({"agent_id", "fingerprint"}) in col_sets

    def test_component_download_tablename(self):
        from models.download import ComponentDownloadRecord

        assert ComponentDownloadRecord.__tablename__ == "component_download_records"

    def test_component_download_has_required_columns(self):
        from models.download import ComponentDownloadRecord

        cols = {c.name for c in ComponentDownloadRecord.__table__.columns}
        required = {"id", "component_type", "component_id", "version_ref", "agent_id", "source", "downloaded_at"}
        assert required.issubset(cols)

    def test_component_download_no_unique_constraint(self):
        """Component downloads are NOT deduplicated — count every agent pull."""
        from models.download import ComponentDownloadRecord

        table = ComponentDownloadRecord.__table__
        # Should only have PK constraint
        non_pk_unique = [uc for uc in table.constraints if hasattr(uc, "columns") and len(uc.columns) > 1]
        assert len(non_pk_unique) == 0, "component_download_records should have no multi-column unique constraints"

    def test_component_download_no_fk_on_component_id(self):
        """component_id should NOT have a FK constraint (polymorphic)."""
        from models.download import ComponentDownloadRecord

        col = ComponentDownloadRecord.__table__.c.component_id
        fks = col.foreign_keys
        assert len(fks) == 0


class TestExporterConfigModel:
    def test_exporter_config_tablename(self):
        from models.exporter_config import ExporterConfig

        assert ExporterConfig.__tablename__ == "exporter_configs"

    def test_exporter_config_has_required_columns(self):
        from models.exporter_config import ExporterConfig

        cols = {c.name for c in ExporterConfig.__table__.columns}
        required = {"id", "org_id", "exporter_type", "enabled", "config", "created_at", "updated_at"}
        assert required.issubset(cols)

    def test_exporter_config_unique_per_org(self):
        from models.exporter_config import ExporterConfig

        table = ExporterConfig.__table__
        unique_constraints = [uc for uc in table.constraints if hasattr(uc, "columns") and len(uc.columns) == 2]
        col_sets = [frozenset(c.name for c in uc.columns) for uc in unique_constraints]
        assert frozenset({"org_id", "exporter_type"}) in col_sets


class TestRemovedTypes:
    def test_tool_listing_not_importable(self):
        """ToolListing should no longer exist in models.__init__."""
        import models

        assert not hasattr(models, "ToolListing")
        assert not hasattr(models, "ToolDownload")

    def test_graphrag_listing_not_importable(self):
        """GraphRagListing should no longer exist in models.__init__."""
        import models

        assert not hasattr(models, "GraphRagListing")
        assert not hasattr(models, "GraphRagDownload")

    def test_new_models_importable(self):
        """All new models should be importable from models package."""
        from models import (
            AgentComponent,
            AgentDownloadRecord,
            ComponentDownloadRecord,
            ComponentSource,
            ExporterConfig,
            Organization,
        )

        assert Organization.__tablename__ == "organizations"
        assert ComponentSource.__tablename__ == "component_sources"
        assert AgentComponent.__tablename__ == "agent_components"
        assert AgentDownloadRecord.__tablename__ == "agent_download_records"
        assert ComponentDownloadRecord.__tablename__ == "component_download_records"
        assert ExporterConfig.__tablename__ == "exporter_configs"


class TestFeedbackSubmissionUpdates:
    def test_feedback_listing_type_wider(self):
        from models.feedback import Feedback

        col = Feedback.__table__.c.listing_type
        assert col.type.length >= 50

    def test_submission_listing_type_wider(self):
        from models.submission import Submission

        col = Submission.__table__.c.listing_type
        assert col.type.length >= 50


class TestDownloadTracking:
    """Tests for download tracking with bot prevention (#93)."""

    def test_anonymous_fingerprint_deterministic(self):
        from unittest.mock import MagicMock

        from services.download_tracker import _anonymous_fingerprint

        request = MagicMock()
        request.client.host = "192.168.1.1"
        request.headers.get.return_value = "Mozilla/5.0"

        fp1 = _anonymous_fingerprint(request)
        fp2 = _anonymous_fingerprint(request)
        assert fp1 == fp2
        assert len(fp1) == 64  # SHA-256 hex digest

    def test_anonymous_fingerprint_varies_by_ip(self):
        from unittest.mock import MagicMock

        from services.download_tracker import _anonymous_fingerprint

        req1 = MagicMock()
        req1.client.host = "192.168.1.1"
        req1.headers.get.return_value = "Mozilla/5.0"

        req2 = MagicMock()
        req2.client.host = "10.0.0.1"
        req2.headers.get.return_value = "Mozilla/5.0"

        assert _anonymous_fingerprint(req1) != _anonymous_fingerprint(req2)

    def test_anonymous_fingerprint_varies_by_ua(self):
        from unittest.mock import MagicMock

        from services.download_tracker import _anonymous_fingerprint

        req1 = MagicMock()
        req1.client.host = "192.168.1.1"
        req1.headers.get.return_value = "Mozilla/5.0"

        req2 = MagicMock()
        req2.client.host = "192.168.1.1"
        req2.headers.get.return_value = "curl/7.88"

        assert _anonymous_fingerprint(req1) != _anonymous_fingerprint(req2)

    def test_download_record_model_constraints(self):
        from models.download import AgentDownloadRecord

        constraints = {c.name for c in AgentDownloadRecord.__table__.constraints if hasattr(c, "name") and c.name}
        assert "uq_agent_downloads_agent_user" in constraints
        assert "uq_agent_downloads_agent_fingerprint" in constraints

    def test_component_download_not_deduplicated(self):
        """ComponentDownloadRecord should have no multi-column unique constraints."""
        from models.download import ComponentDownloadRecord

        unique_constraints = [
            c for c in ComponentDownloadRecord.__table__.constraints if hasattr(c, "columns") and len(c.columns) > 1
        ]
        # Only the PK constraint, no multi-column uniques
        assert len(unique_constraints) == 0

    def test_agent_has_download_count_fields(self):
        from models.agent import Agent

        assert hasattr(Agent, "download_count")
        assert hasattr(Agent, "unique_users")
        col_dl = Agent.__table__.columns["download_count"]
        col_uu = Agent.__table__.columns["unique_users"]
        assert col_dl.default.arg == 0
        assert col_uu.default.arg == 0

    def test_download_tracker_module_exists(self):
        from services.download_tracker import (
            _anonymous_fingerprint,
            get_download_stats,
            record_agent_download,
            record_component_download,
        )

        assert callable(record_agent_download)
        assert callable(record_component_download)
        assert callable(get_download_stats)
        assert callable(_anonymous_fingerprint)

    def test_install_agent_route_accepts_request(self):
        """The install_agent endpoint should accept a Request parameter for fingerprinting."""
        import inspect

        from api.routes.agent import install_agent

        sig = inspect.signature(install_agent)
        param_names = list(sig.parameters.keys())
        assert "request" in param_names


class TestMcpValidationField:
    """Tests for MCP validation field (#92)."""

    def test_mcp_has_mcp_validated_field(self):
        from models.mcp import McpListing

        assert hasattr(McpListing, "mcp_validated")

    def test_mcp_validated_defaults_false(self):
        from models.mcp import McpListing

        col = McpListing.__table__.columns["mcp_validated"]
        # default is False
        assert col.default.arg is False

    @pytest.mark.asyncio
    async def test_approve_allows_non_validated_mcp(self):
        """Review approve should allow MCPs regardless of validation status."""
        from unittest.mock import AsyncMock, MagicMock

        from api.routes.review import approve
        from models.mcp import ListingStatus
        from models.user import UserRole

        # Create a mock MCP listing with mcp_validated=False
        listing = MagicMock()
        listing.id = uuid.uuid4()
        listing.name = "test-mcp"
        listing.status = ListingStatus.pending
        listing.mcp_validated = False

        mock_db = AsyncMock()
        mock_user = MagicMock()
        mock_user.role = UserRole.admin

        # Patch _find_listing to return our mock
        import api.routes.review as review_mod

        original_find = review_mod._find_listing
        review_mod._find_listing = AsyncMock(return_value=("mcp", listing))

        try:
            result = await approve(str(listing.id), mock_db, mock_user)
            assert result["status"] == "approved"
        finally:
            review_mod._find_listing = original_find

    @pytest.mark.asyncio
    async def test_approve_allows_validated_mcp(self):
        """Review approve should allow MCPs that passed validation."""
        from unittest.mock import AsyncMock, MagicMock

        from api.routes.review import approve
        from models.mcp import ListingStatus
        from models.user import UserRole

        listing = MagicMock()
        listing.id = uuid.uuid4()
        listing.name = "validated-mcp"
        listing.status = ListingStatus.pending
        listing.mcp_validated = True

        mock_db = AsyncMock()
        mock_user = MagicMock()
        mock_user.role = UserRole.admin

        import api.routes.review as review_mod

        original_find = review_mod._find_listing
        review_mod._find_listing = AsyncMock(return_value=("mcp", listing))

        try:
            result = await approve(str(listing.id), mock_db, mock_user)
            assert result["status"] == "approved"
        finally:
            review_mod._find_listing = original_find

    @pytest.mark.asyncio
    async def test_approve_non_mcp_not_affected(self):
        """Non-MCP listings should not be affected by validation check."""
        from unittest.mock import AsyncMock, MagicMock

        from api.routes.review import approve
        from models.mcp import ListingStatus
        from models.user import UserRole

        listing = MagicMock()
        listing.id = uuid.uuid4()
        listing.name = "test-skill"
        listing.status = ListingStatus.pending

        mock_db = AsyncMock()
        mock_user = MagicMock()
        mock_user.role = UserRole.admin

        import api.routes.review as review_mod

        original_find = review_mod._find_listing
        review_mod._find_listing = AsyncMock(return_value=("skill", listing))

        try:
            result = await approve(str(listing.id), mock_db, mock_user)
            assert result["status"] == "approved"
        finally:
            review_mod._find_listing = original_find
