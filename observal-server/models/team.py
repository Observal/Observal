# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import enum
import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Index, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class TeamRole(str, enum.Enum):
    owner = "owner"
    reviewer = "reviewer"
    member = "member"


class Team(Base):
    __tablename__ = "teams"
    __table_args__ = (
        UniqueConstraint("handle", name="uq_teams_handle"),
        Index("ix_teams_created_by", "created_by"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    handle: Mapped[str] = mapped_column(String(32), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )


class TeamMembership(Base):
    __tablename__ = "team_memberships"
    __table_args__ = (
        UniqueConstraint("team_id", "user_id", name="uq_team_memberships_team_user"),
        Index("ix_team_memberships_user_id", "user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    team_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("teams.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[TeamRole] = mapped_column(Enum(TeamRole), nullable=False, default=TeamRole.member)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class TeamJoinRequestStatus(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"
    cancelled = "cancelled"  # requester withdrew before a decision


class TeamMembershipRequest(Base):
    """A user's explicit request to join a teamspace.

    The row is the audit record the approval flow needs — requester, reviewer,
    decision, reason, and timestamps all live here — so decisions stay
    reconstructable without a separate history table. A shared teamspace link
    only ever leads here: membership itself is granted exclusively by an owner
    (or admin) approving a pending row.

    The partial unique index allows one PENDING request per (team, user) while
    keeping decided rows as history: a user rejected once may ask again, and
    both rows remain.
    """

    __tablename__ = "team_membership_requests"
    __table_args__ = (
        Index(
            "uq_team_membership_requests_pending",
            "team_id",
            "user_id",
            unique=True,
            postgresql_where=text("status = 'pending'"),
            sqlite_where=text("status = 'pending'"),
        ),
        Index("ix_team_membership_requests_user_id", "user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    team_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("teams.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[TeamJoinRequestStatus] = mapped_column(
        Enum(TeamJoinRequestStatus, name="team_join_request_status"),
        nullable=False,
        default=TeamJoinRequestStatus.pending,
    )
    message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    decided_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decision_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
