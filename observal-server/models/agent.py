import enum
import uuid
from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.base import Base


class AgentStatus(str, enum.Enum):
    draft = "draft"
    pending = "pending"
    approved = "approved"
    rejected = "rejected"
    archived = "archived"


class AgentVisibility(str, enum.Enum):
    public = "public"
    private = "private"


class AgentTeamAccess(Base):
    __tablename__ = "agent_team_access"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False
    )
    group_name: Mapped[str] = mapped_column(String(255), nullable=False)
    permission: Mapped[str] = mapped_column(String(50), nullable=False)  # 'view', 'edit'

    agent: Mapped["Agent"] = relationship(back_populates="team_accesses")


class AgentVersion(Base):
    __tablename__ = "agent_versions"
    __table_args__ = (
        UniqueConstraint("agent_id", "version", name="uq_agent_versions_agent_version"),
        Index("ix_agent_versions_agent_id", "agent_id"),
        Index("ix_agent_versions_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[str] = mapped_column(String(50), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    prompt: Mapped[str] = mapped_column(Text, nullable=False, default="")
    model_name: Mapped[str] = mapped_column(String(100), nullable=False)
    model_config_json: Mapped[dict] = mapped_column(JSON, default=dict)
    external_mcps: Mapped[list] = mapped_column(JSON, default=list)
    supported_ides: Mapped[list] = mapped_column(JSON, default=list)
    required_ide_features: Mapped[list] = mapped_column(JSON, default=list)
    inferred_supported_ides: Mapped[list] = mapped_column(JSON, default=list)
    yaml_snapshot: Mapped[str | None] = mapped_column(Text, nullable=True)
    ide_configs: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    lock_snapshot: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[AgentStatus] = mapped_column(Enum(AgentStatus), default=AgentStatus.pending)
    is_prerelease: Mapped[bool] = mapped_column(Boolean, default=False)
    promoted_from: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    download_count: Mapped[int] = mapped_column(Integer, default=0)
    released_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    released_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))

    agent: Mapped["Agent"] = relationship(back_populates="versions", foreign_keys=[agent_id])
    components: Mapped[list["AgentComponent"]] = relationship(
        back_populates="agent_version",
        lazy="selectin",
        order_by="AgentComponent.order_index",
        cascade="all, delete-orphan",
    )
    goal_template: Mapped["AgentGoalTemplate | None"] = relationship(
        back_populates="agent_version", lazy="selectin", uselist=False, cascade="all, delete-orphan"
    )


class Agent(Base):
    __tablename__ = "agents"
    __table_args__ = (UniqueConstraint("name", "created_by", name="uq_agents_name_created_by"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    owner: Mapped[str] = mapped_column(String(255), nullable=False)
    visibility: Mapped[AgentVisibility] = mapped_column(Enum(AgentVisibility), default=AgentVisibility.private)
    owner_org_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=True
    )
    co_maintainers: Mapped[list] = mapped_column(JSON, default=list)
    latest_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_versions.id", use_alter=True, ondelete="SET NULL"),
        nullable=True,
    )
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    versions: Mapped[list["AgentVersion"]] = relationship(
        back_populates="agent",
        lazy="selectin",
        cascade="all, delete-orphan",
        foreign_keys="AgentVersion.agent_id",
    )
    latest_version: Mapped["AgentVersion | None"] = relationship(
        foreign_keys=[latest_version_id], lazy="selectin", uselist=False
    )
    team_accesses: Mapped[list["AgentTeamAccess"]] = relationship(
        back_populates="agent", lazy="selectin", cascade="all, delete-orphan"
    )

    # ------------------------------------------------------------------
    # Deprecated compatibility properties — delegate to latest_version.
    # These allow existing route/service code to keep working until the
    # version-aware API endpoints (issues #620/#621) replace them.
    # ------------------------------------------------------------------
    @property
    def version(self) -> str:
        return self.latest_version.version if self.latest_version else "0.0.0"

    @version.setter
    def version(self, value: str) -> None:
        if self.latest_version:
            self.latest_version.version = value

    @property
    def description(self) -> str:
        return self.latest_version.description if self.latest_version else ""

    @description.setter
    def description(self, value: str) -> None:
        if self.latest_version:
            self.latest_version.description = value

    @property
    def prompt(self) -> str:
        return self.latest_version.prompt if self.latest_version else ""

    @prompt.setter
    def prompt(self, value: str) -> None:
        if self.latest_version:
            self.latest_version.prompt = value

    @property
    def model_name(self) -> str:
        return self.latest_version.model_name if self.latest_version else ""

    @model_name.setter
    def model_name(self, value: str) -> None:
        if self.latest_version:
            self.latest_version.model_name = value

    @property
    def model_config_json(self) -> dict:
        return self.latest_version.model_config_json if self.latest_version else {}

    @model_config_json.setter
    def model_config_json(self, value: dict) -> None:
        if self.latest_version:
            self.latest_version.model_config_json = value

    @property
    def external_mcps(self) -> list:
        return self.latest_version.external_mcps if self.latest_version else []

    @external_mcps.setter
    def external_mcps(self, value: list) -> None:
        if self.latest_version:
            self.latest_version.external_mcps = value

    @property
    def supported_ides(self) -> list:
        return self.latest_version.supported_ides if self.latest_version else []

    @supported_ides.setter
    def supported_ides(self, value: list) -> None:
        if self.latest_version:
            self.latest_version.supported_ides = value

    @property
    def required_ide_features(self) -> list:
        return self.latest_version.required_ide_features if self.latest_version else []

    @required_ide_features.setter
    def required_ide_features(self, value: list) -> None:
        if self.latest_version:
            self.latest_version.required_ide_features = value

    @property
    def inferred_supported_ides(self) -> list:
        return self.latest_version.inferred_supported_ides if self.latest_version else []

    @inferred_supported_ides.setter
    def inferred_supported_ides(self, value: list) -> None:
        if self.latest_version:
            self.latest_version.inferred_supported_ides = value

    @property
    def status(self) -> "AgentStatus":
        return self.latest_version.status if self.latest_version else AgentStatus.draft

    @status.setter
    def status(self, value: "AgentStatus") -> None:
        if self.latest_version:
            self.latest_version.status = value

    @property
    def rejection_reason(self) -> str | None:
        return self.latest_version.rejection_reason if self.latest_version else None

    @rejection_reason.setter
    def rejection_reason(self, value: str | None) -> None:
        if self.latest_version:
            self.latest_version.rejection_reason = value

    @property
    def download_count(self) -> int:
        return self.latest_version.download_count if self.latest_version else 0

    @property
    def unique_users(self) -> int:
        return 0

    @property
    def git_url(self) -> str | None:
        return None

    @property
    def components(self) -> list:
        return self.latest_version.components if self.latest_version else []

    @property
    def goal_template(self):
        return self.latest_version.goal_template if self.latest_version else None


class AgentGoalTemplate(Base):
    __tablename__ = "agent_goal_templates"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_versions.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    description: Mapped[str] = mapped_column(Text, nullable=False)

    agent_version: Mapped["AgentVersion"] = relationship(back_populates="goal_template")
    sections: Mapped[list["AgentGoalSection"]] = relationship(
        back_populates="goal_template", lazy="selectin", order_by="AgentGoalSection.order", cascade="all, delete-orphan"
    )


class AgentGoalSection(Base):
    __tablename__ = "agent_goal_sections"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    goal_template_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_goal_templates.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    grounding_required: Mapped[bool] = mapped_column(Boolean, default=False)
    order: Mapped[int] = mapped_column(Integer, default=0)

    goal_template: Mapped["AgentGoalTemplate"] = relationship(back_populates="sections")


from models.agent_component import AgentComponent  # noqa: E402

AgentComponent.agent_version = relationship("AgentVersion", back_populates="components")
