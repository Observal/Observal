import enum
import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class InsightReportStatus(str, enum.Enum):
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"


class InsightReport(Base):
    __tablename__ = "insight_reports"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("agents.id"), nullable=False)
    triggered_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    status: Mapped[InsightReportStatus] = mapped_column(Enum(InsightReportStatus), default=InsightReportStatus.pending)
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # Deterministic metrics from ClickHouse
    metrics: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # LLM-generated narrative sections
    narrative: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    sessions_analyzed: Mapped[int] = mapped_column(Integer, default=0)
    llm_model_used: Mapped[str | None] = mapped_column(String(255), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))

    # V2 fields
    previous_report_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("insight_reports.id", ondelete="SET NULL"), nullable=True
    )
    aggregated_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    report_version: Mapped[int] = mapped_column(Integer, default=1)
