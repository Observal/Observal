# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Every listing model must survive a flush that touches its version too.

Each listing pairs a one-to-many ``versions`` with a many-to-one ``latest_version``
pointing back into the same table. Without ``post_update=True`` on that
many-to-one, SQLAlchemy cannot order a unit of work containing both a dirty
listing and a dirty version, and raises CircularDependencyError.

Two real endpoints hit this:

* ``POST /api/v1/{type}/submit`` deletes a non-approved listing of the same
  identity before recreating it, which deletes the listing and its versions in
  one flush. That returned a 500 on any resubmit of a pending or rejected name.
* ``PATCH /api/v1/registry/{type}/{id}/visibility`` writes ``is_private`` on the
  listing and, when a team-private listing goes public, ``status`` on its version.

Agent already declared post_update=True. These tests pin the five component
listing models to the same behaviour so the two shapes cannot regress.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from models.base import Base
from models.hook import HookListing, HookVersion
from models.mcp import ListingStatus, McpListing, McpVersion
from models.prompt import PromptListing, PromptVersion
from models.sandbox import SandboxListing, SandboxVersion
from models.skill import SkillListing, SkillVersion

# (listing model, version model, non-null listing columns, non-null version columns)
LISTING_MODELS = [
    (McpListing, McpVersion, {"category": "general"}, {}),
    (SkillListing, SkillVersion, {}, {"task_type": "testing"}),
    (HookListing, HookVersion, {}, {"event": "PreToolUse", "handler_type": "command"}),
    (PromptListing, PromptVersion, {}, {"category": "testing", "template": "hi"}),
    (SandboxListing, SandboxVersion, {}, {"runtime_type": "docker", "image": "python:3.11"}),
]
IDS = [m.__name__ for m, _, _, _ in LISTING_MODELS]


@asynccontextmanager
async def _sessions(listing_model, version_model):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as conn:
            # Create every table: the listings cascade into download and
            # validation tables that a delete has to reach.
            await conn.run_sync(Base.metadata.create_all)
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()


async def _seed(sessions, listing_model, version_model, extra, version_extra, status=ListingStatus.pending):
    owner_id = uuid.uuid4()
    listing = listing_model(
        id=uuid.uuid4(),
        name="thing",
        namespace="alice",
        slug="thing",
        owner="alice",
        submitted_by=owner_id,
        is_private=True,
        co_authors=[],
        **extra,
    )
    version = version_model(
        id=uuid.uuid4(),
        listing_id=listing.id,
        version="1.0.0",
        description="seed",
        released_by=owner_id,
        released_at=datetime(2026, 1, 1, tzinfo=UTC),
        status=status,
        **version_extra,
    )
    async with sessions() as session:
        session.add(listing)
        await session.flush()
        session.add(version)
        await session.flush()
        listing.latest_version_id = version.id
        await session.commit()
    return listing.id


@pytest.mark.asyncio
@pytest.mark.parametrize(("listing_model", "version_model", "extra", "version_extra"), LISTING_MODELS, ids=IDS)
async def test_deleting_a_listing_and_its_version_flushes(listing_model, version_model, extra, version_extra):
    """The resubmit path: submit deletes a non-approved listing of the same name."""
    async with _sessions(listing_model, version_model) as sessions:
        listing_id = await _seed(sessions, listing_model, version_model, extra, version_extra)
        async with sessions() as session:
            listing = await session.get(listing_model, listing_id)
            await session.delete(listing)
            await session.flush()
            await session.commit()
        async with sessions() as session:
            assert await session.get(listing_model, listing_id) is None


@pytest.mark.asyncio
@pytest.mark.parametrize(("listing_model", "version_model", "extra", "version_extra"), LISTING_MODELS, ids=IDS)
async def test_listing_and_version_fields_change_in_one_flush(listing_model, version_model, extra, version_extra):
    """The visibility path: is_private on the listing, status on its version."""
    async with _sessions(listing_model, version_model) as sessions:
        listing_id = await _seed(
            sessions, listing_model, version_model, extra, version_extra, status=ListingStatus.approved
        )
        async with sessions() as session:
            listing = await session.get(listing_model, listing_id)
            listing.is_private = False
            listing.status = ListingStatus.pending
            await session.commit()
        async with sessions() as session:
            listing = await session.get(listing_model, listing_id)
            assert listing.is_private is False
            assert listing.status == ListingStatus.pending


@pytest.mark.asyncio
@pytest.mark.parametrize(("listing_model", "version_model", "extra", "version_extra"), LISTING_MODELS, ids=IDS)
async def test_latest_version_relationship_uses_post_update(listing_model, version_model, extra, version_extra):
    """Pin the mapper setting, so the fix cannot be removed without a failure."""
    relationship = listing_model.__mapper__.relationships["latest_version"]
    assert relationship.post_update is True
