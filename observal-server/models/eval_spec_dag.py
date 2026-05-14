# SPDX-FileCopyrightText: 2026 Swathi Saravanan <ss4522@cornell.edu>
#
# SPDX-License-Identifier: AGPL-3.0-only

"""SQLAlchemy model for the eval_spec_dags table."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class EvalSpecDAG(Base):
    __tablename__ = "eval_spec_dags"
    __table_args__ = (UniqueConstraint("task_type", "version", name="ux_eval_spec_dags_task_type_version"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_type: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    version: Mapped[str] = mapped_column(String(50), nullable=False)
    dag_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="hand_authored")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    created_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
