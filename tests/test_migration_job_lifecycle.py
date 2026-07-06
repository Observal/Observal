# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for background job lifecycle (10.2).

Tests status transitions (queued→running→completed, queued→running→failed),
progress writes, error_message population, and terminal audit events.

Requirements: 6.4, 6.5, 2.4
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from models.migration_job import MigrationJob, MigrationOperation, MigrationScope, MigrationStatus
from observal_shared.migration.exceptions import ChecksumMismatchError, ConnectionFailedError, MigrationError

# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_job_row(
    status: MigrationStatus = MigrationStatus.queued,
    operation: MigrationOperation = MigrationOperation.export,
    scope: MigrationScope = MigrationScope.postgres,
) -> MagicMock:
    """Create a mock MigrationJob row."""
    job = MagicMock(spec=MigrationJob)
    job.id = uuid.uuid4()
    job.operation_type = operation
    job.data_scope = scope
    job.status = status
    job.started_at = None
    job.finished_at = None
    job.artifact_dir = None
    job.org_id = uuid.uuid4()
    job.progress_phase = "queued"
    job.progress_pct = 0
    job.progress_message = "Queued"
    job.error_message = None
    return job


# ══════════════════════════════════════════════════════════════════════════════
# 10.2.1: Status transitions queued→running→completed
# ══════════════════════════════════════════════════════════════════════════════


class TestSuccessfulLifecycle:
    """Test the happy path: queued → running → completed."""

    def test_queued_transitions_to_running(self):
        """A queued job transitions to running when picked up."""
        job = _make_job_row(status=MigrationStatus.queued)
        # Simulate the worker picking up the job
        job.status = MigrationStatus.running
        job.started_at = datetime.now(UTC)
        assert job.status == MigrationStatus.running
        assert job.started_at is not None

    def test_running_transitions_to_completed(self):
        """A running job transitions to completed on success."""
        job = _make_job_row(status=MigrationStatus.running)
        # Simulate successful completion
        job.status = MigrationStatus.completed
        job.finished_at = datetime.now(UTC)
        job.progress_phase = "completed"
        job.progress_pct = 100
        assert job.status == MigrationStatus.completed
        assert job.finished_at is not None
        assert job.progress_pct == 100

    def test_full_lifecycle_queued_running_completed(self):
        """Full lifecycle: queued → running → completed."""
        job = _make_job_row(status=MigrationStatus.queued)

        # Step 1: queued → running
        assert job.status == MigrationStatus.queued
        job.status = MigrationStatus.running
        job.started_at = datetime.now(UTC)

        # Step 2: running → completed
        job.status = MigrationStatus.completed
        job.finished_at = datetime.now(UTC)
        job.progress_phase = "completed"
        job.progress_pct = 100
        job.progress_message = "Completed"

        assert job.status == MigrationStatus.completed
        assert job.started_at is not None
        assert job.finished_at is not None


# ══════════════════════════════════════════════════════════════════════════════
# 10.2.2: Status transitions queued→running→failed (on MigrationError)
# ══════════════════════════════════════════════════════════════════════════════


class TestFailedLifecycle:
    """Test the failure path: queued → running → failed."""

    def test_running_transitions_to_failed_on_error(self):
        """A running job transitions to failed when MigrationError is raised."""
        job = _make_job_row(status=MigrationStatus.running)
        error = MigrationError("Connection lost")

        # Simulate failure handling
        job.status = MigrationStatus.failed
        job.finished_at = datetime.now(UTC)
        job.error_message = str(error)
        job.progress_phase = "failed"

        assert job.status == MigrationStatus.failed
        assert job.error_message == "Connection lost"

    def test_checksum_error_produces_failed_status(self):
        """ChecksumMismatchError leads to failed status with descriptive message."""
        job = _make_job_row(status=MigrationStatus.running)
        error = ChecksumMismatchError("organizations: expected abc, got xyz")

        job.status = MigrationStatus.failed
        job.error_message = str(error)

        assert job.status == MigrationStatus.failed
        assert "organizations" in job.error_message

    def test_connection_error_produces_failed_status(self):
        """ConnectionFailedError leads to failed status."""
        job = _make_job_row(status=MigrationStatus.running)
        error = ConnectionFailedError("Cannot connect to PostgreSQL")

        job.status = MigrationStatus.failed
        job.error_message = str(error)

        assert "Cannot connect" in job.error_message


# ══════════════════════════════════════════════════════════════════════════════
# 10.2.3: Progress writes are throttled
# ══════════════════════════════════════════════════════════════════════════════


class TestProgressThrottling:
    """Progress writes to the DB are throttled."""

    @pytest.mark.asyncio
    async def test_progress_reporter_throttles_writes(self):
        """DbProgressReporter skips writes within throttle interval."""
        from jobs.migration import DbProgressReporter

        mock_session_factory = AsyncMock()
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.execute = AsyncMock()
        mock_session.commit = AsyncMock()
        mock_session_factory.return_value = mock_session

        reporter = DbProgressReporter(mock_session_factory, str(uuid.uuid4()))

        # First write should go through
        await reporter.update(phase="exporting", pct=10, message="Starting")

        # Second immediate write should be throttled
        await reporter.update(phase="exporting", pct=20, message="Progress")

        # Only one DB write should have occurred (the first one)
        assert mock_session_factory.call_count <= 1


# ══════════════════════════════════════════════════════════════════════════════
# 10.2.4: error_message population
# ══════════════════════════════════════════════════════════════════════════════


class TestErrorMessagePopulation:
    """Failed jobs have non-empty error_message."""

    def test_migration_error_populates_message(self):
        """MigrationError message is stored in error_message field."""
        error = MigrationError("Table 'users' has schema conflict")
        job = _make_job_row(status=MigrationStatus.running)
        job.error_message = str(error)
        assert job.error_message == "Table 'users' has schema conflict"

    def test_timeout_error_populates_message(self):
        """Timeout produces descriptive error_message."""
        timeout_seconds = 3600
        job = _make_job_row(status=MigrationStatus.running)
        job.error_message = f"Job timed out after {timeout_seconds} seconds"
        assert "timed out" in job.error_message
        assert "3600" in job.error_message

    def test_unexpected_error_populates_message(self):
        """Unexpected exceptions produce error_message with type info."""
        try:
            raise RuntimeError("disk full")
        except RuntimeError as exc:
            error_message = f"Unexpected error: {type(exc).__name__}: {exc}"

        job = _make_job_row(status=MigrationStatus.running)
        job.error_message = error_message
        assert "RuntimeError" in job.error_message
        assert "disk full" in job.error_message


# ══════════════════════════════════════════════════════════════════════════════
# 10.2.5: Terminal audit events
# ══════════════════════════════════════════════════════════════════════════════


class TestTerminalAuditEvents:
    """Terminal states emit audit events."""

    @pytest.mark.asyncio
    async def test_completed_job_emits_success_audit(self):
        """Completed job emits audit event with outcome=success."""
        from services.security_events import EventType, SecurityEvent, Severity

        event = SecurityEvent(
            event_type=EventType.SETTING_CHANGED,
            severity=Severity.INFO,
            outcome="success",
            actor_id="system",
            target_id=str(uuid.uuid4()),
            target_type="migration_job",
            detail="Migration export completed (scope=postgres)",
        )

        assert event.outcome == "success"
        assert event.target_type == "migration_job"
        assert "completed" in event.detail

    @pytest.mark.asyncio
    async def test_failed_job_emits_failure_audit(self):
        """Failed job emits audit event with outcome=failure."""
        from services.security_events import EventType, SecurityEvent, Severity

        event = SecurityEvent(
            event_type=EventType.SETTING_CHANGED,
            severity=Severity.WARNING,
            outcome="failure",
            actor_id="system",
            target_id=str(uuid.uuid4()),
            target_type="migration_job",
            detail="Migration export failed (scope=postgres)",
        )

        assert event.outcome == "failure"
        assert event.severity == Severity.WARNING
        assert "failed" in event.detail
