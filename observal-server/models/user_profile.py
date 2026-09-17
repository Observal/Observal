# SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Per-user work profiles and recommendation feedback.

A profile is a small, deterministic summary of what a user actually works on
(languages, tools, MCP servers, topic buckets), derived from their own
sessions. It exists so registry recommendations can be personal without
re-scanning DuckDB on every page load.

Profiles are private to their owner. Nothing here stores prompt text or any
other transcript content — only aggregate counts over metadata.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class UserWorkProfile(Base):
    """Cached summary of one user's recent work."""

    __tablename__ = "user_work_profiles"
    __table_args__ = (UniqueConstraint("user_id", name="uq_user_work_profiles_user"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    # Number of sessions the profile was derived from. Zero means the user has
    # no usable history yet and callers should fall back to popularity.
    session_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # {"languages": [...], "tools": [...], "mcp_servers": [...],
    #  "topics": [...], "harnesses": [...], "error_categories": [...]}
    profile: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)


class RecommendationFeedback(Base):
    """A user's explicit response to a recommendation.

    Dismissals are honoured on subsequent requests so a recommendation the
    user rejected does not keep reappearing.
    """

    __tablename__ = "recommendation_feedback"
    __table_args__ = (
        UniqueConstraint("user_id", "component_type", "component_id", name="uq_recommendation_feedback_user_component"),
        Index("ix_recommendation_feedback_user", "user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    component_type: Mapped[str] = mapped_column(String(50), nullable=False)
    component_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    # "dismissed" | "not_relevant" | "installed"
    action: Mapped[str] = mapped_column(String(30), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
