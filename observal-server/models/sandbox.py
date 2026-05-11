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


class SandboxListing(Base):
    __tablename__ = "sandbox_listings"
    __table_args__ = (Index("ix_sandbox_listings_submitted_by", "submitted_by"),)

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
    unique_agents: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )
    latest_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sandbox_versions.id", use_alter=True, ondelete="SET NULL"),
        nullable=True,
    )

    versions: Mapped[list[SandboxVersion]] = relationship(
        back_populates="listing",
        lazy="selectin",
        cascade="all, delete-orphan",
        foreign_keys="SandboxVersion.listing_id",
    )
    latest_version: Mapped[SandboxVersion | None] = relationship(
        foreign_keys=[latest_version_id], lazy="selectin", uselist=False
    )

    # ------------------------------------------------------------------
    # Deprecated compatibility properties — delegate to latest_version.
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
    def git_url(self) -> str | None:
        return self.latest_version.source_url if self.latest_version else None

    @git_url.setter
    def git_url(self, value: str | None) -> None:
        if not self.latest_version:
            raise RuntimeError(f"{type(self).__name__} has no latest_version; cannot set git_url")
        self.latest_version.source_url = value

    @property
    def git_ref(self) -> str | None:
        return self.latest_version.source_ref if self.latest_version else None

    @git_ref.setter
    def git_ref(self, value: str | None) -> None:
        if not self.latest_version:
            raise RuntimeError(f"{type(self).__name__} has no latest_version; cannot set git_ref")
        self.latest_version.source_ref = value

    @property
    def runtime_type(self) -> str:
        return self.latest_version.runtime_type if self.latest_version else ""

    @runtime_type.setter
    def runtime_type(self, value: str) -> None:
        if not self.latest_version:
            raise RuntimeError(f"{type(self).__name__} has no latest_version; cannot set runtime_type")
        self.latest_version.runtime_type = value

    @property
    def image(self) -> str:
        return self.latest_version.image if self.latest_version else ""

    @image.setter
    def image(self, value: str) -> None:
        if not self.latest_version:
            raise RuntimeError(f"{type(self).__name__} has no latest_version; cannot set image")
        self.latest_version.image = value

    @property
    def dockerfile_url(self) -> str | None:
        return self.latest_version.dockerfile_url if self.latest_version else None

    @dockerfile_url.setter
    def dockerfile_url(self, value: str | None) -> None:
        if not self.latest_version:
            raise RuntimeError(f"{type(self).__name__} has no latest_version; cannot set dockerfile_url")
        self.latest_version.dockerfile_url = value

    @property
    def resource_limits(self) -> dict:
        return self.latest_version.resource_limits if self.latest_version else {}

    @resource_limits.setter
    def resource_limits(self, value: dict) -> None:
        if not self.latest_version:
            raise RuntimeError(f"{type(self).__name__} has no latest_version; cannot set resource_limits")
        self.latest_version.resource_limits = value

    @property
    def network_policy(self) -> str:
        return self.latest_version.network_policy if self.latest_version else "none"

    @network_policy.setter
    def network_policy(self, value: str) -> None:
        if not self.latest_version:
            raise RuntimeError(f"{type(self).__name__} has no latest_version; cannot set network_policy")
        self.latest_version.network_policy = value

    @property
    def allowed_mounts(self) -> list:
        return self.latest_version.allowed_mounts if self.latest_version else []

    @allowed_mounts.setter
    def allowed_mounts(self, value: list) -> None:
        if not self.latest_version:
            raise RuntimeError(f"{type(self).__name__} has no latest_version; cannot set allowed_mounts")
        self.latest_version.allowed_mounts = value

    @property
    def env_vars(self) -> dict:
        return self.latest_version.env_vars if self.latest_version else {}

    @env_vars.setter
    def env_vars(self, value: dict) -> None:
        if not self.latest_version:
            raise RuntimeError(f"{type(self).__name__} has no latest_version; cannot set env_vars")
        self.latest_version.env_vars = value

    @property
    def entrypoint(self) -> str | None:
        return self.latest_version.entrypoint if self.latest_version else None

    @entrypoint.setter
    def entrypoint(self, value: str | None) -> None:
        if not self.latest_version:
            raise RuntimeError(f"{type(self).__name__} has no latest_version; cannot set entrypoint")
        self.latest_version.entrypoint = value


class SandboxDownload(Base):
    __tablename__ = "sandbox_downloads"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    listing_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("sandbox_listings.id"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    ide: Mapped[str] = mapped_column(String(50), nullable=False)
    downloaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class SandboxVersion(Base):
    __tablename__ = "sandbox_versions"
    __table_args__ = (
        UniqueConstraint("listing_id", "version"),
        Index("ix_sandbox_versions_listing_id", "listing_id"),
        Index("ix_sandbox_versions_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    listing_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sandbox_listings.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[str] = mapped_column(String(50), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    changelog: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    source_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    resolved_sha: Mapped[str | None] = mapped_column(String(40), nullable=True)
    status: Mapped[ListingStatus] = mapped_column(Enum(ListingStatus), default=ListingStatus.pending)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    download_count: Mapped[int] = mapped_column(Integer, default=0)
    released_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    released_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    supported_ides: Mapped[list] = mapped_column(JSON, default=list)
    runtime_type: Mapped[str] = mapped_column(String(20), nullable=False)
    image: Mapped[str] = mapped_column(String(500), nullable=False)
    dockerfile_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    resource_limits: Mapped[dict] = mapped_column(JSON, default=dict)
    network_policy: Mapped[str] = mapped_column(String(20), default="none")
    allowed_mounts: Mapped[list] = mapped_column(JSON, default=list)
    env_vars: Mapped[dict] = mapped_column(JSON, default=dict)
    entrypoint: Mapped[str | None] = mapped_column(String(500), nullable=True)
    is_editing: Mapped[bool] = mapped_column(Boolean, default=False)
    editing_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    editing_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)

    listing: Mapped[SandboxListing] = relationship(back_populates="versions", foreign_keys=[listing_id])
