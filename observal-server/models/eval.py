# SPDX-FileCopyrightText: 2026 Subramania Raja <dhanpraja231@gmail.com>
# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-FileCopyrightText: 2026 Swathi Saravanan <ss4522@cornell.edu>
# SPDX-License-Identifier: AGPL-3.0-only

import enum
import uuid
from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, Enum, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.base import Base


class EvalRunStatus(str, enum.Enum):
    running = "running"
    completed = "completed"
    failed = "failed"


class EvalRun(Base):
    __tablename__ = "eval_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("agents.id"), nullable=False)
    triggered_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    status: Mapped[EvalRunStatus] = mapped_column(Enum(EvalRunStatus), default=EvalRunStatus.running)
    traces_evaluated: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    scorecards: Mapped[list["Scorecard"]] = relationship(
        back_populates="eval_run", lazy="raise", cascade="all, delete-orphan"
    )


class Scorecard(Base):
    __tablename__ = "scorecards"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("agents.id"), nullable=False)
    eval_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("eval_runs.id", ondelete="CASCADE"), nullable=False
    )
    trace_id: Mapped[str] = mapped_column(String(255), nullable=False)
    version: Mapped[str] = mapped_column(String(50), nullable=False)
    overall_score: Mapped[float] = mapped_column(Float, nullable=False)
    overall_grade: Mapped[str] = mapped_column(String(2), nullable=False)
    recommendations: Mapped[str | None] = mapped_column(Text, nullable=True)
    bottleneck: Mapped[str | None] = mapped_column(String(255), nullable=True)
    raw_output: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))

    # New 5-dimension scoring fields
    dimension_scores: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    composite_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    display_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    grade: Mapped[str | None] = mapped_column(String(2), nullable=True)
    scoring_recommendations: Mapped[list | None] = mapped_column(JSON, nullable=True)
    penalty_count: Mapped[int] = mapped_column(Integer, default=0)
    partial_evaluation: Mapped[bool] = mapped_column(Boolean, default=False)
    dimensions_skipped: Mapped[list | None] = mapped_column(JSON, nullable=True)
    warnings: Mapped[list | None] = mapped_column(JSON, nullable=True)

    eval_run: Mapped["EvalRun"] = relationship(back_populates="scorecards")
    dimensions: Mapped[list["ScorecardDimension"]] = relationship(
        back_populates="scorecard", lazy="selectin", cascade="all, delete-orphan"
    )
    penalties: Mapped[list["TracePenalty"]] = relationship(
        back_populates="scorecard", lazy="raise", cascade="all, delete-orphan"
    )


class ScorecardDimension(Base):
    __tablename__ = "scorecard_dimensions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    scorecard_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("scorecards.id", ondelete="CASCADE"), nullable=False
    )
    dimension: Mapped[str] = mapped_column(String(100), nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    grade: Mapped[str] = mapped_column(String(2), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    scorecard: Mapped["Scorecard"] = relationship(back_populates="dimensions")


# Import for relationship resolution
from models.scoring import TracePenalty  # noqa: E402, TC001
