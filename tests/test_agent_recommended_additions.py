# SPDX-FileCopyrightText: 2026 The Observal Authors
# SPDX-License-Identifier: Apache-2.0

"""Tests for the public agent recommended-additions endpoint.

This is the first consumer of the persisted ``registry_offer`` analysis. The
endpoint exposes only public component references — never session telemetry —
and degrades to an empty list when no report exists, the offer is empty, or
the feature was disabled at generation time.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException


def _make_offer(entries_by_type: dict | None = None, enabled: bool = True) -> dict:
    return {
        "enabled": enabled,
        "registry_has_components": True,
        "item_count": sum(len(v) for v in (entries_by_type or {}).values()),
        "offered_ids": [],
        "entries_by_type": entries_by_type or {},
    }


def _entry(cid: str, ctype: str = "skill", name: str = "foo-bar") -> dict:
    return {
        "type": ctype,
        "id": cid,
        "qualified_name": f"ns/{name}",
        "name": name,
        "description": "a useful skill",
        "category": "general",
    }


@pytest.mark.asyncio
async def test_recommended_additions_returns_offer_entries():
    from api.routes.agent.insights import agent_recommended_additions

    agent_id = uuid.uuid4()
    report_id = uuid.uuid4()
    completed = datetime.now(UTC)
    cid = str(uuid.uuid4())

    agent = SimpleNamespace(id=agent_id)
    report = SimpleNamespace(
        id=report_id,
        agent_id=agent_id,
        completed_at=completed,
        registry_offer=_make_offer({"skills": [_entry(cid)]}),
    )

    db = MagicMock()
    db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=report)))

    with (
        patch("api.routes.agent.helpers._load_agent", new=AsyncMock(return_value=agent)),
        patch("api.routes.agent.insights.check_listing_visibility_async", new=AsyncMock(return_value=True)),
    ):
        result = await agent_recommended_additions(str(agent_id), db, current_user=None)

    assert result.agent_id == agent_id
    assert result.source_report_id == report_id
    assert result.generated_at == completed
    assert len(result.items) == 1
    item = result.items[0]
    assert item.type == "skill"
    assert item.id == cid
    assert item.qualified_name == "ns/foo-bar"
    assert item.name == "foo-bar"


@pytest.mark.asyncio
async def test_recommended_additions_empty_when_no_report():
    from api.routes.agent.insights import agent_recommended_additions

    agent_id = uuid.uuid4()
    agent = SimpleNamespace(id=agent_id)

    db = MagicMock()
    db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None)))

    with (
        patch("api.routes.agent.helpers._load_agent", new=AsyncMock(return_value=agent)),
        patch("api.routes.agent.insights.check_listing_visibility_async", new=AsyncMock(return_value=True)),
    ):
        result = await agent_recommended_additions(str(agent_id), db, current_user=None)

    assert result.items == []
    assert result.source_report_id is None
    assert result.generated_at is None


@pytest.mark.asyncio
async def test_recommended_additions_empty_when_offer_null_on_old_report():
    """Old reports predate the registry_offer column (PR #1 backfill left null)."""
    from api.routes.agent.insights import agent_recommended_additions

    agent_id = uuid.uuid4()
    agent = SimpleNamespace(id=agent_id)
    report = SimpleNamespace(
        id=uuid.uuid4(),
        agent_id=agent_id,
        completed_at=datetime.now(UTC),
        registry_offer=None,
    )

    db = MagicMock()
    db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=report)))

    with (
        patch("api.routes.agent.helpers._load_agent", new=AsyncMock(return_value=agent)),
        patch("api.routes.agent.insights.check_listing_visibility_async", new=AsyncMock(return_value=True)),
    ):
        result = await agent_recommended_additions(str(agent_id), db, current_user=None)

    assert result.items == []


@pytest.mark.asyncio
async def test_recommended_additions_empty_when_feature_disabled():
    """An offer with enabled=False means the feature was off at generation time."""
    from api.routes.agent.insights import agent_recommended_additions

    agent_id = uuid.uuid4()
    agent = SimpleNamespace(id=agent_id)
    report = SimpleNamespace(
        id=uuid.uuid4(),
        agent_id=agent_id,
        completed_at=datetime.now(UTC),
        registry_offer=_make_offer({"skills": [_entry(str(uuid.uuid4()))]}, enabled=False),
    )

    db = MagicMock()
    db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=report)))

    with (
        patch("api.routes.agent.helpers._load_agent", new=AsyncMock(return_value=agent)),
        patch("api.routes.agent.insights.check_listing_visibility_async", new=AsyncMock(return_value=True)),
    ):
        result = await agent_recommended_additions(str(agent_id), db, current_user=None)

    assert result.items == []


@pytest.mark.asyncio
async def test_recommended_additions_404_when_agent_not_visible():
    from api.routes.agent.insights import agent_recommended_additions

    agent_id = uuid.uuid4()
    agent = SimpleNamespace(id=agent_id)

    db = MagicMock()

    with (
        patch("api.routes.agent.helpers._load_agent", new=AsyncMock(return_value=agent)),
        patch("api.routes.agent.insights.check_listing_visibility_async", new=AsyncMock(return_value=False)),
        pytest.raises(HTTPException) as exc,
    ):
        await agent_recommended_additions(str(agent_id), db, current_user=None)

    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_recommended_additions_skips_malformed_entries():
    """Malformed entries in the persisted offer are skipped, not fatal."""
    from api.routes.agent.insights import agent_recommended_additions

    agent_id = uuid.uuid4()
    agent = SimpleNamespace(id=agent_id)
    good_cid = str(uuid.uuid4())
    report = SimpleNamespace(
        id=uuid.uuid4(),
        agent_id=agent_id,
        completed_at=datetime.now(UTC),
        registry_offer=_make_offer(
            {
                "skills": [
                    _entry(good_cid),
                    {"missing": "type and id"},  # skipped
                    "not-a-dict",  # skipped
                ],
                "hooks": "not-a-list",  # skipped entirely
            }
        ),
    )

    db = MagicMock()
    db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=report)))

    with (
        patch("api.routes.agent.helpers._load_agent", new=AsyncMock(return_value=agent)),
        patch("api.routes.agent.insights.check_listing_visibility_async", new=AsyncMock(return_value=True)),
    ):
        result = await agent_recommended_additions(str(agent_id), db, current_user=None)

    assert len(result.items) == 1
    assert result.items[0].id == good_cid
