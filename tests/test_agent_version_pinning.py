# SPDX-FileCopyrightText: 2026 Princess0407 <princess0407@github.com>
# SPDX-License-Identifier: Apache-2.0

"""Unit and regression tests for GitHub issue #1705:
Component version pinning and lock file support for reproducible agent installs.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest
import yaml
from fastapi import HTTPException
from typer.testing import CliRunner

from models.agent import Agent, AgentStatus, AgentVersion
from models.mcp import ListingStatus, McpListing, McpVersion
from models.skill import SkillListing
from observal_cli.main import app as cli_app
from schemas.agent import ComponentRef
from services.agent_lock_file import compute_integrity_hash, generate_lock_file
from services.agent_resolver import (
    _VersionedListing,
    resolve_agent,
    resolve_component_versions,
    validate_component_ids,
)

# ---------------------------------------------------------------------------
# 1. Lock File Generation & Integrity
# ---------------------------------------------------------------------------


class TestAgentLockFileGeneration:
    def test_generate_lock_file_includes_agent_metadata(self):
        components = [
            {
                "type": "mcp",
                "name": "stripe-mcp",
                "resolved": "1.0.4",
                "id": str(uuid.uuid4()),
            },
            {
                "type": "prompt",
                "name": "system-prompt",
                "resolved": "1.0.0",
                "id": str(uuid.uuid4()),
                "content": "You are a secure code reviewer.",
            },
        ]
        result = generate_lock_file(components, agent="security-auditor", agent_version="1.2.3")
        assert result.startswith("# Auto-generated")

        parsed = yaml.safe_load(result)
        assert parsed["lock_version"] == 1
        assert parsed["agent"] == "security-auditor"
        assert parsed["agent_version"] == "1.2.3"
        assert "resolved_at" in parsed
        assert len(parsed["components"]) == 2

        comp0 = parsed["components"][0]
        assert comp0["name"] == "stripe-mcp"
        assert comp0["type"] == "mcp"
        assert comp0["resolved"] == "1.0.4"
        assert "integrity" not in comp0

        comp1 = parsed["components"][1]
        assert comp1["name"] == "system-prompt"
        assert comp1["type"] == "prompt"
        assert comp1["resolved"] == "1.0.0"
        assert comp1["integrity"].startswith("sha256-")
        assert comp1["integrity"] == compute_integrity_hash("You are a secure code reviewer.")

    def test_deterministic_lock_file_output(self):
        components = [
            {"type": "skill", "name": "test-skill", "resolved": "2.1.0", "id": "uuid-1"},
        ]
        r1 = generate_lock_file(components, agent="my-agent", agent_version="1.0.0")
        r2 = generate_lock_file(components, agent="my-agent", agent_version="1.0.0")
        # Strip resolved_at timestamps to compare structure
        p1 = yaml.safe_load(r1)
        p2 = yaml.safe_load(r2)
        p1.pop("resolved_at")
        p2.pop("resolved_at")
        assert p1 == p2


# ---------------------------------------------------------------------------
# 2. Pinned Version Resolution: Locked Version Wins
# ---------------------------------------------------------------------------


class TestAgentResolverVersionPinning:
    @pytest.mark.asyncio
    async def test_locked_version_wins_over_latest_listing_version(self):
        """When component has resolved_version='1.0.0' and latest listing is '2.0.0',
        resolve_agent MUST resolve to 1.0.0.
        """
        agent_id = uuid.uuid4()
        mcp_id = uuid.uuid4()

        agent = MagicMock()
        agent.id = agent_id
        agent.name = "auditor"
        agent.version = "1.0.0"
        agent.prompt = "prompt"
        agent.description = "desc"
        agent.model_name = "model"
        agent.models_by_harness = {}
        agent.team_id = None
        agent.is_private = False

        comp = MagicMock()
        comp.component_type = "mcp"
        comp.component_id = mcp_id
        comp.resolved_version = "1.0.0"  # Pinned to 1.0.0
        comp.order_index = 0
        comp.config_override = None
        agent.components = [comp]

        # Latest listing has version 2.0.0
        listing = MagicMock(spec=McpListing)
        listing.id = mcp_id
        listing.name = "stripe-mcp"
        listing.slug = "stripe-mcp"
        listing.version = "2.0.0"
        listing.status = ListingStatus.approved
        listing.description = "Version 2 description"
        listing.git_url = "git://example.com/mcp"
        listing.git_ref = "v2.0.0"
        listing.transport = "stdio"
        listing.tools_schema = None
        listing.mcp_validated = True
        listing.setup_instructions = None

        # Pinned version 1.0.0 in version table
        pinned_version = MagicMock(spec=McpVersion)
        pinned_version.version = "1.0.0"
        pinned_version.description = "Version 1 description"
        pinned_version.git_url = "git://example.com/mcp"
        pinned_version.git_ref = "v1.0.0"
        pinned_version.status = ListingStatus.approved
        pinned_version.transport = "stdio"
        pinned_version.tools_schema = None
        pinned_version.mcp_validated = True
        pinned_version.setup_instructions = None

        listing_scalars = MagicMock()
        listing_scalars.all.return_value = [listing]
        listing_result = MagicMock()
        listing_result.scalars.return_value = listing_scalars

        version_result = MagicMock()
        version_result.scalar_one_or_none.return_value = pinned_version

        db = AsyncMock()
        db.execute.side_effect = [listing_result, version_result]

        resolved = await resolve_agent(agent, db)
        assert resolved.ok is True
        assert len(resolved.components) == 1
        resolved_comp = resolved.components[0]
        # Must resolve to 1.0.0, NOT 2.0.0!
        assert resolved_comp.version == "1.0.0"
        assert resolved_comp.description == "Version 1 description"
        assert resolved_comp.git_ref == "v1.0.0"

    @pytest.mark.asyncio
    async def test_missing_locked_version_fails_closed(self):
        """When an agent pins a version that doesn't exist, resolution MUST fail closed
        and record an error (never silently fall back to latest).
        """
        agent = MagicMock()
        agent.id = uuid.uuid4()
        agent.name = "auditor"
        agent.version = "1.0.0"
        agent.prompt = ""
        agent.description = ""
        agent.model_name = ""
        agent.models_by_harness = {}
        agent.team_id = None
        agent.is_private = False

        mcp_id = uuid.uuid4()
        comp = MagicMock()
        comp.component_type = "mcp"
        comp.component_id = mcp_id
        comp.resolved_version = "9.9.9"  # Nonexistent
        comp.order_index = 0
        comp.config_override = None
        agent.components = [comp]

        listing = MagicMock(spec=McpListing)
        listing.id = mcp_id
        listing.name = "stripe-mcp"
        listing.version = "1.0.0"
        listing.status = ListingStatus.approved

        listing_scalars = MagicMock()
        listing_scalars.all.return_value = [listing]
        listing_result = MagicMock()
        listing_result.scalars.return_value = listing_scalars

        version_result = MagicMock()
        version_result.scalar_one_or_none.return_value = None  # Not found

        db = AsyncMock()
        db.execute.side_effect = [listing_result, version_result]

        resolved = await resolve_agent(agent, db)
        assert resolved.ok is False
        assert len(resolved.errors) == 1
        assert "version '9.9.9' not found" in resolved.errors[0].reason

    @pytest.mark.asyncio
    async def test_unversioned_or_latest_component_resolves_cleanly(self):
        """When resolved_version is 'latest', resolution resolves to listing's current version."""
        agent = MagicMock()
        agent.id = uuid.uuid4()
        agent.name = "auditor"
        agent.version = "1.0.0"
        agent.prompt = ""
        agent.description = ""
        agent.model_name = ""
        agent.models_by_harness = {}
        agent.team_id = None
        agent.is_private = False

        mcp_id = uuid.uuid4()
        comp = MagicMock()
        comp.component_type = "mcp"
        comp.component_id = mcp_id
        comp.resolved_version = "latest"
        comp.order_index = 0
        comp.config_override = None
        agent.components = [comp]

        listing = MagicMock(spec=McpListing)
        listing.id = mcp_id
        listing.name = "stripe-mcp"
        listing.slug = "stripe-mcp"
        listing.version = "2.0.0"
        listing.status = ListingStatus.approved
        listing.description = "Latest"
        listing.git_url = None
        listing.git_ref = None
        listing.transport = None
        listing.tools_schema = None
        listing.mcp_validated = False
        listing.setup_instructions = None

        listing_scalars = MagicMock()
        listing_scalars.all.return_value = [listing]
        listing_result = MagicMock()
        listing_result.scalars.return_value = listing_scalars

        db = AsyncMock()
        db.execute.return_value = listing_result

        resolved = await resolve_agent(agent, db)
        assert resolved.ok is True
        assert resolved.components[0].version == "2.0.0"


# ---------------------------------------------------------------------------
# 3. ComponentRef & Version Validation
# ---------------------------------------------------------------------------


class TestComponentRefVersionResolution:
    @pytest.mark.asyncio
    async def test_resolve_component_versions_pins_requested_version(self):
        comp_id = uuid.uuid4()
        comp_ref = ComponentRef(
            component_type="mcp",
            component_id=comp_id,
            version="1.0.4",
        )

        listing = MagicMock(spec=McpListing)
        listing.id = comp_id
        listing.version = "2.0.0"

        db = AsyncMock()
        db.execute.side_effect = [
            MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[listing])))),
            MagicMock(scalar_one_or_none=MagicMock(return_value="1.0.4")),
        ]

        versions = await resolve_component_versions([comp_ref], db)
        assert versions[("mcp", comp_id)] == "1.0.4"

    @pytest.mark.asyncio
    async def test_validate_component_ids_rejects_missing_version(self):
        comp_id = uuid.uuid4()
        ref = {"component_type": "skill", "component_id": comp_id, "version": "9.9.9"}

        listing = MagicMock(spec=SkillListing)
        listing.id = comp_id
        listing.name = "my-skill"
        listing.version = "1.0.0"
        listing.status = ListingStatus.approved

        db = AsyncMock()
        # First query: listing lookup. Second query: version lookup (returns None)
        db.execute.side_effect = [
            MagicMock(scalar_one_or_none=MagicMock(return_value=listing)),
            MagicMock(scalar_one_or_none=MagicMock(return_value=None)),
        ]

        errors = await validate_component_ids([ref], db)
        assert len(errors) == 1
        assert "version '9.9.9' not found" in errors[0].reason


# ---------------------------------------------------------------------------
# 4. _VersionedListing Proxy Identity Invariants
# ---------------------------------------------------------------------------


class TestVersionedListingProxy:
    def test_identity_attrs_preserved_from_listing(self):
        listing_id = uuid.uuid4()
        version_id = uuid.uuid4()

        listing = SimpleNamespace(
            id=listing_id,
            name="cool-mcp",
            namespace="acme",
            slug="cool-mcp",
            version="2.0.0",
            description="v2 description",
            status=ListingStatus.approved,
        )
        pinned = SimpleNamespace(
            id=version_id,
            version="1.0.0",
            description="v1 description",
            status=ListingStatus.approved,
            transport="stdio",
        )

        proxy = _VersionedListing(listing, pinned)
        # Identity stays tied to listing
        assert proxy.id == listing_id
        assert proxy.name == "cool-mcp"
        assert proxy.slug == "cool-mcp"
        assert proxy.namespace == "acme"
        # Version-dependent fields resolve to pinned version
        assert proxy.version == "1.0.0"
        assert proxy.description == "v1 description"
        assert proxy.transport == "stdio"
        assert proxy.latest_version == pinned


# ---------------------------------------------------------------------------
# 5. CLI Pull: Exact Version Requested & Locked
# ---------------------------------------------------------------------------


runner = CliRunner()
_FAKE_CONFIG = {"server_url": "http://localhost:8000", "api_key": "test-key"}


class TestCliPullVersionBehavior:
    @patch("observal_cli.cmd_pull.get_adapter")
    @patch("observal_cli.cmd_pull.ensure_loaded")
    @patch("observal_cli.client.resolve_registry_reference", return_value="uuid-agent-1")
    @patch("observal_cli.client.get")
    @patch("observal_cli.client.post_public")
    @patch("observal_cli.lockfile.upsert_agent")
    @patch("observal_cli.cmd_pull._write_file_checked", return_value="written")
    @patch("observal_cli.config.get_or_exit", return_value=_FAKE_CONFIG)
    def test_pull_with_explicit_version_requests_version_and_locks_it(
        self,
        mock_cfg,
        mock_write,
        mock_upsert,
        mock_post_public,
        mock_client_get,
        mock_resolve,
        mock_loaded,
        mock_adapter,
        tmp_path,
    ):
        mock_client_get.return_value = {
            "id": "uuid-agent-1",
            "name": "test-agent",
            "namespace": "alice",
            "slug": "test-agent",
            "version": "1.0.0",
            "latest_version": "2.0.0",
            "component_links": [
                {
                    "component_type": "mcp",
                    "component_id": str(uuid.uuid4()),
                    "component_name": "stripe-mcp",
                    "version_ref": "1.0.4",
                }
            ],
        }

        mock_post_public.return_value = {
            "config_snippet": {
                "mcp_config": {
                    "path": str(tmp_path / "mcp.json"),
                    "content": "{}",
                }
            },
            "warnings": [],
        }

        adapter_instance = MagicMock()
        adapter_instance.persist_active_agent = MagicMock()
        mock_adapter.return_value = adapter_instance

        with patch("observal_cli.lockfile.read_registry_lockfile", return_value=({}, {})):
            res = runner.invoke(
                cli_app,
                [
                    "agent",
                    "pull",
                    "alice/test-agent",
                    "--version",
                    "1.0.0",
                    "--harness",
                    "cursor",
                    "--dir",
                    str(tmp_path),
                    "--no-prompt",
                    "-o",
                    "json",
                ],
            )
            assert res.exit_code == 0

        # 1. Verification that GET request queried with ?version=1.0.0
        assert mock_client_get.call_args_list[0] == call("/api/v1/agents/uuid-agent-1?version=1.0.0")

        # 2. Verification that install payload included version="1.0.0"
        install_body = mock_post_public.call_args[0][1]
        assert install_body["version"] == "1.0.0"

        # 3. Verification that upsert_agent recorded version="1.0.0" and pinned component 1.0.4
        mock_upsert.assert_called_once()
        upsert_kwargs = mock_upsert.call_args[1]
        assert upsert_kwargs["version"] == "1.0.0"
        assert upsert_kwargs["components"] == [
            {
                "type": "mcp",
                "name": "stripe-mcp",
                "id": mock_client_get.return_value["component_links"][0]["component_id"],
                "version": "1.0.4",
            }
        ]


# ---------------------------------------------------------------------------
# 6. Install Route Pinned Components Verification
# ---------------------------------------------------------------------------


class TestInstallAgentComponentVersionPinning:
    @pytest.mark.asyncio
    async def test_install_agent_missing_pinned_version_raises_404(self):
        """When an agent contains a component pinned to a non-existent version,
        install_agent MUST raise HTTP 404 (failing closed).
        """
        from api.routes.agent import install as install_routes
        from schemas.agent import AgentInstallRequest

        agent_id = uuid.uuid4()
        mcp_id = uuid.uuid4()

        agent = MagicMock(spec=Agent)
        agent.id = agent_id
        agent.status = AgentStatus.approved
        agent.name = "my-agent"
        agent.is_private = False
        agent.team_id = None
        agent.created_by = uuid.uuid4()

        comp = MagicMock()
        comp.component_type = "mcp"
        comp.component_id = mcp_id
        comp.resolved_version = "9.9.9"  # Nonexistent version
        comp.order_index = 0

        ver = MagicMock(spec=AgentVersion)
        ver.version = "1.0.0"
        ver.status = AgentStatus.approved
        ver.components = [comp]
        agent.latest_version = ver

        listing = MagicMock(spec=McpListing)
        listing.id = mcp_id
        listing.name = "test-mcp"
        listing.version = "1.0.0"
        listing.status = ListingStatus.approved

        # db returns agent on _load_agent, listing on listing query, None on pinned version query
        db = AsyncMock()
        # Mocking the select for McpListing (scalars.all returns [listing])
        # then select for McpVersion (scalar_one_or_none returns None)
        mcp_res = MagicMock()
        mcp_res.scalars.return_value.all.return_value = [listing]
        ver_res = MagicMock()
        ver_res.scalar_one_or_none.return_value = None

        db.execute.side_effect = [mcp_res, ver_res]

        with (
            patch("api.routes.agent.install._load_agent", AsyncMock(return_value=agent)),
            patch("api.routes.agent.install.get_effective_agent_permission", return_value="read"),
        ):
            req = AgentInstallRequest(harness="cursor")
            with pytest.raises(HTTPException) as exc_info:
                await install_routes.install_agent(str(agent_id), req, request=MagicMock(), db=db, current_user=None)
            assert exc_info.value.status_code == 404
            assert "MCP test-mcp version '9.9.9' not found" in exc_info.value.detail
