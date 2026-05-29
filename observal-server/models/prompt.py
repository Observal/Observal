# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-FileCopyrightText: 2026 Kaushik Kumar <kaushikrjpm10@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.base import Base
from models.mcp import ListingStatus


class PromptListing(Base):
    __tablename__ = "prompt_listings"
    __table_args__ = (Index("ix_prompt_listings_submitted_by", "submitted_by"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    owner: Mapped[str] = mapped_column(String(255), nullable=False)
    is_private: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    owner_org_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=True
    )
    bundle_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("component_bundles.id"), nullable=True
    )
    submitted_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    co_authors: Mapped[list] = mapped_column(JSON, default=list)
    unique_agents: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )
    latest_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("prompt_versions.id", use_alter=True, ondelete="SET NULL"),
        nullable=True,
    )

    versions: Mapped[list[PromptVersion]] = relationship(
        back_populates="listing",
        lazy="selectin",
        cascade="all, delete-orphan",
        foreign_keys="PromptVersion.listing_id",
    )
    latest_version: Mapped[PromptVersion | None] = relationship(
        foreign_keys=[latest_version_id], lazy="selectin", uselist=False
    )

    # ------------------------------------------------------------------
    # Deprecated compatibility properties - delegate to latest_version.
    # ------------------------------------------------------------------
    @property
    def version(self) -> str:
        return self.latest_version.version if self.latest_version else "0.0.0"

    @version.setter
    def version(self, value: str) -> None:
        if not self.latest_version:
            raise RuntimeError(f"{type(self).__name__} has no latest_version; cannot set version")
        self.latest_version.version = value

    @property
    def description(self) -> str:
        return self.latest_version.description if self.latest_version else ""

    @description.setter
    def description(self, value: str) -> None:
        if not self.latest_version:
            raise RuntimeError(f"{type(self).__name__} has no latest_version; cannot set description")
        self.latest_version.description = value

    @property
    def status(self) -> ListingStatus:
        return self.latest_version.status if self.latest_version else ListingStatus.draft

    @status.setter
    def status(self, value: ListingStatus) -> None:
        if not self.latest_version:
            raise RuntimeError(f"{type(self).__name__} has no latest_version; cannot set status")
        self.latest_version.status = value

    @property
    def rejection_reason(self) -> str | None:
        return self.latest_version.rejection_reason if self.latest_version else None

    @rejection_reason.setter
    def rejection_reason(self, value: str | None) -> None:
        if not self.latest_version:
            raise RuntimeError(f"{type(self).__name__} has no latest_version; cannot set rejection_reason")
        self.latest_version.rejection_reason = value

    @property
    def download_count(self) -> int:
        return self.latest_version.download_count if self.latest_version else 0

    @property
    def supported_ides(self) -> list:
        return self.latest_version.supported_ides if self.latest_version else []

    @supported_ides.setter
    def supported_ides(self, value: list) -> None:
        if not self.latest_version:
            raise RuntimeError(f"{type(self).__name__} has no latest_version; cannot set supported_ides")
        self.latest_version.supported_ides = value

    @property
    def category(self) -> str:
        return self.latest_version.category if self.latest_version else ""

    @category.setter
    def category(self, value: str) -> None:
        if not self.latest_version:
            raise RuntimeError(f"{type(self).__name__} has no latest_version; cannot set category")
        self.latest_version.category = value

    @property
    def template(self) -> str:
        return self.latest_version.template if self.latest_version else ""

    @template.setter
    def template(self, value: str) -> None:
        if not self.latest_version:
            raise RuntimeError(f"{type(self).__name__} has no latest_version; cannot set template")
        self.latest_version.template = value

    @property
    def variables(self) -> list:
        return self.latest_version.variables if self.latest_version else []

    @variables.setter
    def variables(self, value: list) -> None:
        if not self.latest_version:
            raise RuntimeError(f"{type(self).__name__} has no latest_version; cannot set variables")
        self.latest_version.variables = value

    @property
    def model_hints(self) -> dict | None:
        return self.latest_version.model_hints if self.latest_version else None

    @model_hints.setter
    def model_hints(self, value: dict | None) -> None:
        if not self.latest_version:
            raise RuntimeError(f"{type(self).__name__} has no latest_version; cannot set model_hints")
        self.latest_version.model_hints = value

    @property
    def tags(self) -> list:
        return self.latest_version.tags if self.latest_version else []

    @tags.setter
    def tags(self, value: list) -> None:
        if not self.latest_version:
            raise RuntimeError(f"{type(self).__name__} has no latest_version; cannot set tags")
        self.latest_version.tags = value


class PromptDownload(Base):
    __tablename__ = "prompt_downloads"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    listing_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("prompt_listings.id"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    ide: Mapped[str] = mapped_column(String(50), nullable=False)
    downloaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class PromptVersion(Base):
    __tablename__ = "prompt_versions"
    __table_args__ = (
        UniqueConstraint("listing_id", "version"),
        Index("ix_prompt_versions_listing_id", "listing_id"),
        Index("ix_prompt_versions_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    listing_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("prompt_listings.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[str] = mapped_column(String(50), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    changelog: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[ListingStatus] = mapped_column(Enum(ListingStatus), default=ListingStatus.pending)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    download_count: Mapped[int] = mapped_column(Integer, default=0)
    released_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    released_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    supported_ides: Mapped[list] = mapped_column(JSON, default=list)
    category: Mapped[str] = mapped_column(String(100), nullable=False)
    template: Mapped[str] = mapped_column(Text, nullable=False)
    variables: Mapped[list] = mapped_column(JSON, default=list)
    model_hints: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    tags: Mapped[list] = mapped_column(JSON, default=list)
    is_editing: Mapped[bool] = mapped_column(Boolean, default=False)
    editing_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    editing_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)

    listing: Mapped[PromptListing] = relationship(back_populates="versions", foreign_keys=[listing_id])
