# SPDX-FileCopyrightText: 2026 Vishnu Muthiah <vishnu.muthiah04@gmail.com>
# SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

import uuid
from datetime import UTC, datetime

from sqlalchemy import DATE, DateTime, ForeignKey, Integer, Numeric, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class ExecDashboardConfig(Base):
    __tablename__ = "exec_dashboard_config"
    __table_args__ = (UniqueConstraint("org_id", name="uq_exec_dashboard_config_org"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    hourly_dev_cost: Mapped[float] = mapped_column(Numeric(10, 2), default=75.00)
    pre_ai_baselines: Mapped[dict] = mapped_column(JSON, default=dict)
    department_budgets: Mapped[dict] = mapped_column(JSON, default=dict)
    target_adoption_pct: Mapped[int] = mapped_column(Integer, default=100)
    target_adoption_date: Mapped[datetime | None] = mapped_column(DATE, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )
