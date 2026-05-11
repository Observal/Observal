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


class SkillListing(Base):
    __tablename__ = "skill_listings"
    __table_args__ = (Index("ix_skill_listings_submitted_by", "submitted_by"),)

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
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )
    latest_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("skill_versions.id", use_alter=True, ondelete="SET NULL"),
        nullable=True,
    )

    versions: Mapped[list[SkillVersion]] = relationship(
        back_populates="listing",
        lazy="selectin",
        cascade="all, delete-orphan",
        foreign_keys="SkillVersion.listing_id",
    )
    latest_version: Mapped[SkillVersion | None] = relationship(
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
    def skill_path(self) -> str:
        return self.latest_version.skill_path if self.latest_version else "/"

    @skill_path.setter
    def skill_path(self, value: str) -> None:
        if not self.latest_version:
            raise RuntimeError(f"{type(self).__name__} has no latest_version; cannot set skill_path")
        self.latest_version.skill_path = value

    @property
    def target_agents(self) -> list:
        return self.latest_version.target_agents if self.latest_version else []

    @target_agents.setter
    def target_agents(self, value: list) -> None:
        if not self.latest_version:
            raise RuntimeError(f"{type(self).__name__} has no latest_version; cannot set target_agents")
        self.latest_version.target_agents = value

    @property
    def task_type(self) -> str:
        return self.latest_version.task_type if self.latest_version else ""

    @task_type.setter
    def task_type(self, value: str) -> None:
        if not self.latest_version:
            raise RuntimeError(f"{type(self).__name__} has no latest_version; cannot set task_type")
        self.latest_version.task_type = value

    @property
    def triggers(self) -> dict | None:
        return self.latest_version.triggers if self.latest_version else None

    @triggers.setter
    def triggers(self, value: dict | None) -> None:
        if not self.latest_version:
            raise RuntimeError(f"{type(self).__name__} has no latest_version; cannot set triggers")
        self.latest_version.triggers = value

    @property
    def slash_command(self) -> str | None:
        return self.latest_version.slash_command if self.latest_version else None

    @slash_command.setter
    def slash_command(self, value: str | None) -> None:
        if not self.latest_version:
            raise RuntimeError(f"{type(self).__name__} has no latest_version; cannot set slash_command")
        self.latest_version.slash_command = value

    @property
    def has_scripts(self) -> bool:
        return self.latest_version.has_scripts if self.latest_version else False

    @has_scripts.setter
    def has_scripts(self, value: bool) -> None:
        if not self.latest_version:
            raise RuntimeError(f"{type(self).__name__} has no latest_version; cannot set has_scripts")
        self.latest_version.has_scripts = value

    @property
    def has_templates(self) -> bool:
        return self.latest_version.has_templates if self.latest_version else False

    @has_templates.setter
    def has_templates(self, value: bool) -> None:
        if not self.latest_version:
            raise RuntimeError(f"{type(self).__name__} has no latest_version; cannot set has_templates")
        self.latest_version.has_templates = value

    @property
    def is_power(self) -> bool:
        return self.latest_version.is_power if self.latest_version else False

    @is_power.setter
    def is_power(self, value: bool) -> None:
        if not self.latest_version:
            raise RuntimeError(f"{type(self).__name__} has no latest_version; cannot set is_power")
        self.latest_version.is_power = value

    @property
    def power_md(self) -> str | None:
        return self.latest_version.power_md if self.latest_version else None

    @power_md.setter
    def power_md(self, value: str | None) -> None:
        if not self.latest_version:
            raise RuntimeError(f"{type(self).__name__} has no latest_version; cannot set power_md")
        self.latest_version.power_md = value

    @property
    def mcp_server_config(self) -> dict | None:
        return self.latest_version.mcp_server_config if self.latest_version else None

    @mcp_server_config.setter
    def mcp_server_config(self, value: dict | None) -> None:
        if not self.latest_version:
            raise RuntimeError(f"{type(self).__name__} has no latest_version; cannot set mcp_server_config")
        self.latest_version.mcp_server_config = value

    @property
    def activation_keywords(self) -> list | None:
        return self.latest_version.activation_keywords if self.latest_version else None

    @activation_keywords.setter
    def activation_keywords(self, value: list | None) -> None:
        if not self.latest_version:
            raise RuntimeError(f"{type(self).__name__} has no latest_version; cannot set activation_keywords")
        self.latest_version.activation_keywords = value


class SkillDownload(Base):
    __tablename__ = "skill_downloads"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    listing_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("skill_listings.id"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    ide: Mapped[str] = mapped_column(String(50), nullable=False)
    downloaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class SkillVersion(Base):
    __tablename__ = "skill_versions"
    __table_args__ = (
        UniqueConstraint("listing_id", "version"),
        Index("ix_skill_versions_listing_id", "listing_id"),
        Index("ix_skill_versions_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    listing_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("skill_listings.id", ondelete="CASCADE"), nullable=False
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
    skill_path: Mapped[str] = mapped_column(String(500), default="/")
    target_agents: Mapped[list] = mapped_column(JSON, default=list)
    task_type: Mapped[str] = mapped_column(String(100), nullable=False)
    triggers: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    slash_command: Mapped[str | None] = mapped_column(String(100), nullable=True)
    has_scripts: Mapped[bool] = mapped_column(Boolean, default=False)
    has_templates: Mapped[bool] = mapped_column(Boolean, default=False)
    is_power: Mapped[bool] = mapped_column(Boolean, default=False)
    power_md: Mapped[str | None] = mapped_column(Text, nullable=True)
    mcp_server_config: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    activation_keywords: Mapped[list | None] = mapped_column(JSON, nullable=True)
    is_editing: Mapped[bool] = mapped_column(Boolean, default=False)
    editing_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    editing_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)

    listing: Mapped[SkillListing] = relationship(back_populates="versions", foreign_keys=[listing_id])
