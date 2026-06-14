# SPDX-FileCopyrightText: 2026 Swathi Saravanan <ss4522@cornell.edu>
# SPDX-License-Identifier: AGPL-3.0-only

"""Candidate artifact store for the self-learning loop.

A CandidateArtifact is a concrete, machine-applicable change (a Cursor rule, a
prompt edit, or a tool-config change) derived deterministically from an insight
report's suggestions. It is the unit that flows through verify -> promote.

Versioned store: never edited in place. Every change is a new row.
"""

import enum
import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base

# Fixed identity of the system user that OWNS auto-generated candidate versions
# (agent_versions.released_by). We never attribute auto-candidates to a real
# user. Kept in sync with the same literal in alembic 0008.
SYSTEM_AUTO_CANDIDATE_USER_ID = "0a0a0a0a-0000-4000-8000-00000000a0c1"


class CandidateArtifactType(str, enum.Enum):
    cursor_rule = "cursor_rule"
    prompt_edit = "prompt_edit"
    tool_config_change = "tool_config_change"


class CandidateArtifactStatus(str, enum.Enum):
    pending = "pending"  # written, not yet verified
    verification_failed = "verification_failed"  # a hard gate failed
    verification_inconclusive = "verification_inconclusive"  # replay deferred / no signal
    promoted = "promoted"  # written to agent_versions as pending_review


class CandidateArtifact(Base):
    __tablename__ = "candidate_artifacts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False
    )
    source_report_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("insight_reports.id", ondelete="SET NULL"), nullable=True
    )
    # cursor_rule | prompt_edit | tool_config_change (CandidateArtifactType value)
    artifact_type: Mapped[str] = mapped_column(String(32), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # synthetic stable ids of the suggestions that motivated this artifact
    source_suggestions: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    motivating_session_ids: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    # selection rule, fix_types, working dirs, etc. — the provenance block
    provenance: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # pending | verification_failed | verification_inconclusive | promoted
    status: Mapped[str] = mapped_column(String(32), default=CandidateArtifactStatus.pending.value, nullable=False)
    verification_result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    promoted_version_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )
