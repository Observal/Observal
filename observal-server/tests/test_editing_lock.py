# SPDX-FileCopyrightText: 2026 Shanmukh Sharma <satejmore28@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""
observal-server/tests/test_editing_lock.py

Unit tests for services/editing_lock.py.
Verifies version row object locking without any external infrastructure.
"""

from __future__ import annotations

import uuid
import pytest
from datetime import datetime, timedelta, UTC
from fastapi import HTTPException

# 1. Clean Top-Level Imports (Addresses Moderator Feedback)
from services.editing_lock import acquire_edit_lock, release_edit_lock, is_actively_editing


# ---------------------------------------------------------------------------
# Fixtures & Helpers
# ---------------------------------------------------------------------------

class MockVersion:
    """A minimal mock object simulating an ORM or data model row state."""
    def __init__(self):
        self.is_editing = False
        self.editing_since = None
        self.editing_by = None


@pytest.fixture
def version() -> MockVersion:
    """Provides a fresh, unlocked MockVersion object instance for each test function."""
    return MockVersion()


@pytest.fixture
def user_id() -> uuid.UUID:
    """Provides a standard user UUID token string for tracking ownership."""
    return uuid.uuid4()


# ---------------------------------------------------------------------------
# acquire_edit_lock Tests
# ---------------------------------------------------------------------------

class TestAcquireEditLock:
    """Tests for services.editing_lock.acquire_edit_lock."""

    def test_successful_acquisition(self, version, user_id):
        """Should successfully lock an unedited version row structure."""
        acquire_edit_lock(version, user_id)
        
        assert version.is_editing is True
        assert version.editing_by == user_id
        assert isinstance(version.editing_since, datetime)

    def test_lock_contention_raises_409(self, version, user_id):
        """Should raise an HTTP 409 error code when another user holds an active lock."""
        other_user = uuid.uuid4()
        version.is_editing = True
        version.editing_by = other_user
        version.editing_since = datetime.now(UTC)

        with pytest.raises(HTTPException) as exc_info:
            acquire_edit_lock(version, user_id)
        
        assert exc_info.value.status_code == 409

    def test_overwrites_expired_lock(self, version, user_id):
        """Should allow another user to acquire the lock if the existing lock has expired."""
        other_user = uuid.uuid4()
        version.is_editing = True
        version.editing_by = other_user
        # Simulate an old lock created 31 minutes ago (exceeding TTL constraint)
        version.editing_since = datetime.now(UTC) - timedelta(minutes=31)

        acquire_edit_lock(version, user_id)

        assert version.is_editing is True
        assert version.editing_by == user_id


# ---------------------------------------------------------------------------
# release_edit_lock Tests
# ---------------------------------------------------------------------------

class TestReleaseEditLock:
    """Tests for services.editing_lock.release_edit_lock."""

    def test_clean_release_by_owner(self, version, user_id):
        """The active lock holder should be able to cleanly release their own lock."""
        version.is_editing = True
        version.editing_by = user_id
        version.editing_since = datetime.now(UTC)

        release_edit_lock(version, user_id)

        assert version.is_editing is False
        assert version.editing_since is None
        assert version.editing_by is None

    def test_non_owner_release_raises_403(self, version, user_id):
        """Releasing someone else's active lock without force flag must trigger an HTTP 403."""
        other_user = uuid.uuid4()
        version.is_editing = True
        version.editing_by = other_user
        version.editing_since = datetime.now(UTC)

        with pytest.raises(HTTPException) as exc_info:
            release_edit_lock(version, user_id)
        
        assert exc_info.value.status_code == 403

    def test_force_release_by_non_owner(self, version, user_id):
        """Should bypass authorization ownership limits when force flag is set explicitly."""
        other_user = uuid.uuid4()
        version.is_editing = True
        version.editing_by = other_user
        version.editing_since = datetime.now(UTC)

        release_edit_lock(version, user_id, force=True)

        assert version.is_editing is False
        assert version.editing_by is None


# ---------------------------------------------------------------------------
# is_actively_editing Tests
# ---------------------------------------------------------------------------

class TestIsActivelyEditing:
    """Tests for services.editing_lock.is_actively_editing."""

    def test_returns_false_when_not_locked(self, version):
        """Should evaluate to False if the schema flags describe an open version state."""
        assert is_actively_editing(version) == False

    def test_returns_true_on_valid_lock(self, version, user_id):
        """Should evaluate to True when an unexpired lease context exists on-chain."""
        version.is_editing = True
        version.editing_by = user_id
        version.editing_since = datetime.now(UTC)

        assert is_actively_editing(version) == True

    def test_returns_false_when_expired(self, version, user_id):
        """Should evaluate to False if the temporal metadata exceeds the timeout limits."""
        version.is_editing = True
        version.editing_by = user_id
        version.editing_since = datetime.now(UTC) - timedelta(minutes=35)

        assert is_actively_editing(version) == False