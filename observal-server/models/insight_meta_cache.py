# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class InsightMetaCache(Base):
    """Caches batch session metadata for a given agent + time period.

    This avoids re-querying ClickHouse for the same session data across
    report regenerations for the same period.
    """

    __tablename__ = "insight_meta_cache"
    __table_args__ = (UniqueConstraint("agent_id", "period_start", "period_end", name="uq_meta_cache_agent_period"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False
    )
    period_start: Mapped[str] = mapped_column(String(30), nullable=False)
    period_end: Mapped[str] = mapped_column(String(30), nullable=False)
    session_metas: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
