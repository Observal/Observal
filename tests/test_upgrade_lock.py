# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Tests for observal_cli.upgrade_lock."""

from __future__ import annotations

import json
import os
import time

import pytest

from observal_cli import upgrade_lock
from observal_cli.upgrade_lock import (
    UpgradeLockError,
    acquire_lock,
    release_lock,
)


@pytest.fixture(autouse=True)
def isolated_lock_dir(tmp_path, monkeypatch):
    """Redirect lock files to tmp dir."""
    monkeypatch.setattr(upgrade_lock, "CONFIG_DIR", tmp_path)
    return tmp_path


class TestAcquireLock:
    def test_acquire_creates_lock_file(self, isolated_lock_dir):
        lock = acquire_lock("cli")
        assert lock.exists()
        data = json.loads(lock.read_text())
        assert data["pid"] == os.getpid()
        assert "timestamp" in data
        release_lock(lock)

    def test_release_removes_file(self, isolated_lock_dir):
        lock = acquire_lock("cli")
        assert lock.exists()
        release_lock(lock)
        assert not lock.exists()


class TestStaleLock:
    def test_stale_lock_auto_broken(self, isolated_lock_dir):
        """Lock older than STALE_THRESHOLD is automatically broken."""
        lock_path = isolated_lock_dir / ".cli-upgrade.lock"
        # Write a lock with old timestamp
        lock_path.write_text(
            json.dumps(
                {
                    "pid": 99999,
                    "timestamp": time.time() - 3600,  # 1 hour ago
                }
            )
        )

        # Should succeed (breaks stale lock)
        lock = acquire_lock("cli")
        assert lock.exists()
        data = json.loads(lock.read_text())
        assert data["pid"] == os.getpid()
        release_lock(lock)

    def test_orphaned_lock_from_dead_pid(self, isolated_lock_dir):
        """Lock from a dead PID (within threshold) is broken."""
        lock_path = isolated_lock_dir / ".cli-upgrade.lock"
        # PID 1 is always init — use a likely-dead PID
        lock_path.write_text(
            json.dumps(
                {
                    "pid": 2147483647,  # Max PID, almost certainly dead
                    "timestamp": time.time(),  # Recent
                }
            )
        )

        # Should succeed (dead PID)
        lock = acquire_lock("cli")
        assert lock.exists()
        release_lock(lock)


class TestConcurrentLock:
    def test_active_lock_blocks_second_acquire(self, isolated_lock_dir):
        """If another live process holds the lock, acquire fails."""
        lock_path = isolated_lock_dir / ".cli-upgrade.lock"
        # Write lock with current PID (simulates another thread/process)
        lock_path.write_text(
            json.dumps(
                {
                    "pid": os.getpid(),  # This PID IS alive
                    "timestamp": time.time(),
                }
            )
        )

        with pytest.raises(UpgradeLockError, match="Another upgrade is in progress"):
            acquire_lock("cli")
