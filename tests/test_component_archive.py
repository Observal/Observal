# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from api.routes._component_archive import archive_listing, unarchive_listing
from models.mcp import ListingStatus
from models.user import UserRole


class _Listing:
    def __init__(self, status=ListingStatus.approved):
        self.id = uuid.uuid4()
        self.name = "archivable"
        self.status = status
        self.submitted_by = uuid.uuid4()
        self.co_authors = []
        self.is_private = False


def _user(listing):
    user = MagicMock()
    user.id = listing.submitted_by
    user.role = UserRole.user
    user.org_id = None
    return user


@pytest.mark.asyncio
async def test_archive_listing_marks_component_archived(monkeypatch):
    listing = _Listing()
    db = AsyncMock()
    monkeypatch.setattr("api.routes._component_archive.resolve_listing", AsyncMock(return_value=listing))

    result = await archive_listing(MagicMock(), str(listing.id), db, _user(listing), "skill")

    assert listing.status == ListingStatus.archived
    assert result == {"id": str(listing.id), "name": "archivable", "status": "archived"}
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_unarchive_listing_restores_component(monkeypatch):
    listing = _Listing(status=ListingStatus.archived)
    db = AsyncMock()
    monkeypatch.setattr("api.routes._component_archive.resolve_listing", AsyncMock(return_value=listing))

    result = await unarchive_listing(MagicMock(), str(listing.id), db, _user(listing), "skill")

    assert listing.status == ListingStatus.approved
    assert result == {"id": str(listing.id), "name": "archivable", "status": "approved"}
    db.commit.assert_awaited_once()
