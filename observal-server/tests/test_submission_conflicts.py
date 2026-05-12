# SPDX-License-Identifier: AGPL-3.0-only

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError


def _duplicate_name_error() -> IntegrityError:
    return IntegrityError(
        "INSERT",
        {},
        Exception('duplicate key value violates unique constraint "mcp_listings_name_key"'),
    )


@pytest.mark.asyncio
async def test_listing_integrity_error_returns_conflict_for_unique_violation():
    from api.routes.submission_conflicts import raise_listing_integrity_error

    db = MagicMock()
    db.rollback = AsyncMock()

    with pytest.raises(HTTPException) as exc:
        await raise_listing_integrity_error(db, "MCP", "duplicate-test", _duplicate_name_error())

    assert exc.value.status_code == 409
    assert exc.value.detail == "A MCP listing named 'duplicate-test' already exists"
    db.rollback.assert_awaited_once()


@pytest.mark.asyncio
async def test_submit_mcp_returns_conflict_when_duplicate_name_hits_flush():
    from api.routes.mcp import submit_mcp
    from schemas.mcp import McpSubmitRequest

    no_existing = MagicMock()
    no_existing.scalars.return_value.first.return_value = None

    db = MagicMock()
    db.execute = AsyncMock(return_value=no_existing)
    db.flush = AsyncMock(side_effect=_duplicate_name_error())
    db.rollback = AsyncMock()

    current_user = MagicMock()
    current_user.id = uuid.uuid4()
    current_user.org_id = None

    req = McpSubmitRequest(
        name="duplicate-test",
        version="1.0.0",
        description="Test duplicate handling",
        category="developer-tools",
        owner="admin",
        command="node",
        args=["index.js"],
    )

    with pytest.raises(HTTPException) as exc:
        await submit_mcp(req, MagicMock(), db, current_user)

    assert exc.value.status_code == 409
    assert exc.value.detail == "A MCP listing named 'duplicate-test' already exists"
    db.rollback.assert_awaited_once()
