# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""MigrationJob model for tracking data migration operations."""

import enum
import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class MigrationOperation(str, enum.Enum):
    export = "export"
    import_ = "import"
    validate = "validate"


class MigrationScope(str, enum.Enum):
    postgres = "postgres"
    clickhouse = "clickhouse"
    both = "both"


class MigrationStatus(str, enum.Enum):
    queued = "queued"
    running = "running"
    completed = "completed"
    failed = "failed"


class MigrationJob(Base):
    __tablename__ = "migration_jobs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    operation_type: Mapped[MigrationOperation] = mapped_column(
        Enum(MigrationOperation, name="migration_operation"), nullable=False
    )
    data_scope: Mapped[MigrationScope] = mapped_column(Enum(MigrationScope, name="migration_scope"), nullable=False)
    status: Mapped[MigrationStatus] = mapped_column(
        Enum(MigrationStatus, name="migration_status"), default=MigrationStatus.queued, index=True
    )
    progress_phase: Mapped[str | None] = mapped_column(String(50), nullable=True, default="queued")
    progress_pct: Mapped[int] = mapped_column(Integer, default=0)
    progress_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    progress_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    artifacts_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    artifact_dir: Mapped[str | None] = mapped_column(Text, nullable=True)
    schema_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    org_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
