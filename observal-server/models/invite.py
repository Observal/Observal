# SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Admin-minted invite links.

An invite authorizes exactly one thing: creating a standard user account while
self-registration is off. It never grants membership, content access, or an
elevated role — the roadmap's "the link never grants access" boundary applies
to accounts the same way it applies to teamspaces, so there is deliberately no
role column. Tokens are stored as SHA-256 hashes and the plaintext is shown
exactly once at mint time.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class Invite(Base):
    __tablename__ = "invites"
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_invites_token_hash"),
        Index("ix_invites_invited_by", "invited_by"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    invited_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # NULL means unlimited redemptions until expiry or revocation.
    max_uses: Mapped[int | None] = mapped_column(Integer, nullable=True)
    use_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Optional in-app destination appended to the invite URL as `next`, e.g.
    # /teamspaces/acme — validated against the same relative-only rule as every
    # other `next` value before it is ever emitted.
    next_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class InviteRedemption(Base):
    """Audit row linking each created account to the invite that allowed it."""

    __tablename__ = "invite_redemptions"
    __table_args__ = (Index("ix_invite_redemptions_invite_id", "invite_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    invite_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("invites.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
