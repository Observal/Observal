# SPDX-FileCopyrightText: 2026 Aryan Iyappan <aryaniyappan2006@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Teammate invites.

An invite is a single-use, time-limited token that lets someone join the
inviting admin's organization with a preassigned role. The raw token is
shown exactly once at creation time; only its SHA-256 hash is stored.

Channels:
- ``email``: the invite is pinned to a specific email address - only that
  address can accept it.
- ``link``:  a shareable link; the acceptor supplies their own email.
"""

import enum
import uuid
from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base
from models.user import UserRole


class InviteChannel(str, enum.Enum):
    email = "email"
    link = "link"


class Invite(Base):
    __tablename__ = "invites"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    # Pinned recipient for channel=email; None for shareable links
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    role: Mapped[UserRole] = mapped_column(Enum(UserRole), default=UserRole.user, nullable=False)
    channel: Mapped[InviteChannel] = mapped_column(Enum(InviteChannel), default=InviteChannel.link, nullable=False)
    # SHA-256 hex of the raw token (raw token is never persisted)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    invited_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    accepted_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    revoked: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)

    @property
    def status(self) -> str:
        if self.revoked:
            return "revoked"
        if self.accepted_at is not None:
            return "accepted"
        expires = self.expires_at if self.expires_at.tzinfo else self.expires_at.replace(tzinfo=UTC)
        if expires < datetime.now(UTC):
            return "expired"
        return "pending"
