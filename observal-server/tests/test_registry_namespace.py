# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0

import importlib.util
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from api.deps import resolve_listing
from models.agent import Agent
from models.hook import HookListing
from models.mcp import McpListing
from models.prompt import PromptListing
from models.sandbox import SandboxListing
from models.skill import SkillListing
from services.ownership import transfer_entity_owner
from services.registry_namespace import (
    _namespace_slug_parts,
    identity_for_user,
    slugify,
    validate_namespace,
)


def test_identity_validation_and_formatting():
    user = SimpleNamespace(username="alice")
    assert identity_for_user(user, "Code Reviewer") == ("alice", "code-reviewer")
    assert _namespace_slug_parts("alice/code-reviewer") == ("alice", "code-reviewer")
    assert _namespace_slug_parts("alice/code/reviewer") is None
    with pytest.raises(ValueError, match="reserved"):
        validate_namespace("admin")
    with pytest.raises(ValueError, match="reserved"):
        slugify("install")


def test_migration_numbers_colliding_slugs_per_namespace():
    migration_path = Path(__file__).parents[1] / "alembic/versions/016_registry_publish_loop.py"
    spec = importlib.util.spec_from_file_location("registry_publish_loop_migration", migration_path)
    assert spec and spec.loader
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    rows = [
        {"id": 1, "name": "Search", "username": "alice"},
        {"id": 2, "name": "Search!", "username": "alice"},
        {"id": 3, "name": "Search?", "username": "alice"},
        {"id": 4, "name": "Search", "username": "bob"},
        {"id": 5, "name": "Install", "username": "alice"},
    ]
    assert list(migration._listing_identities("agents", rows)) == [
        (1, "alice", "search"),
        (2, "alice", "search-1"),
        (3, "alice", "search-2"),
        (4, "bob", "search"),
        (5, "alice", "install-1"),
    ]
    long_slug = "x" * 64
    used: set[str] = set()
    assert migration._next_slug(long_slug, used) == long_slug
    assert migration._next_slug(long_slug, used) == f"{'x' * 62}-1"
    with pytest.raises(RuntimeError, match="orphaned listing 6"):
        list(migration._listing_identities("agents", [{"id": 6, "name": "Lost", "username": None}]))


def test_models_enforce_qualified_uniqueness():
    agent_index = next(index for index in Agent.__table__.indexes if index.name == "uq_agents_active_namespace_slug")
    assert [column.name for column in agent_index.columns] == ["namespace", "slug"]
    for model in (McpListing, SkillListing, HookListing, PromptListing, SandboxListing):
        constraint = next(
            constraint
            for constraint in model.__table__.constraints
            if constraint.name == f"uq_{model.__tablename__}_namespace_slug"
        )
        assert [column.name for column in constraint.columns] == ["namespace", "slug"]


class _Scalars:
    def __init__(self, rows):
        self.rows = rows

    def unique(self):
        return self

    def all(self):
        return self.rows


class _Result:
    def __init__(self, rows):
        self.rows = rows

    def scalars(self):
        return _Scalars(self.rows)


@pytest.mark.asyncio
async def test_resolver_accepts_qualified_and_rejects_ambiguous_bare_names():
    alice = SimpleNamespace(id=uuid.uuid4(), namespace="alice", slug="tool", qualified_name="alice/tool")
    bob = SimpleNamespace(id=uuid.uuid4(), namespace="bob", slug="tool", qualified_name="bob/tool")
    db = SimpleNamespace(execute=AsyncMock(side_effect=[_Result([alice]), _Result([alice, bob])]))

    assert await resolve_listing(McpListing, "alice/tool", db) is alice
    with pytest.raises(HTTPException) as exc:
        await resolve_listing(McpListing, "tool", db)
    assert exc.value.status_code == 409
    assert "alice/tool" in exc.value.detail


def test_harness_names_only_qualify_real_slug_collisions():
    from services.harness.helpers import _local_registry_names

    listings = {
        1: SimpleNamespace(name="Search", namespace="alice", slug="search"),
        2: SimpleNamespace(name="Search", namespace="bob", slug="search"),
        3: SimpleNamespace(name="Other", namespace="bob", slug="other"),
    }
    assert _local_registry_names(listings) == {
        1: "alice-search",
        2: "bob-search",
        3: "other",
    }


@pytest.mark.asyncio
async def test_username_change_is_blocked_after_publish():
    from api.routes.auth import set_username
    from schemas.auth import UsernameUpdateRequest

    user = SimpleNamespace(id=uuid.uuid4(), username="alice")
    result = SimpleNamespace(scalar_one_or_none=lambda: None)
    db = SimpleNamespace(execute=AsyncMock(return_value=result))
    with (
        patch("api.routes.auth.user_has_listings", new=AsyncMock(return_value=True)),
        pytest.raises(HTTPException) as exc,
    ):
        await set_username(UsernameUpdateRequest(username="alice-new"), db, user)
    assert exc.value.status_code == 409
    assert user.username == "alice"


def test_transfer_moves_namespace_and_keeps_slug():
    current = SimpleNamespace(id=uuid.uuid4())
    target = SimpleNamespace(id=uuid.uuid4(), username="bob", email="bob@example.com", org_id=None)
    entity = SimpleNamespace(
        owner="alice",
        namespace="alice",
        slug="tool",
        created_by=current.id,
        co_authors=[],
        owner_org_id=None,
    )
    transfer_entity_owner(entity, "agents", current, target)
    assert entity.namespace == "bob"
    assert entity.slug == "tool"
    assert entity.created_by == target.id
