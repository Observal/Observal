# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

import uuid
from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class SamlConfig(Base):
    __tablename__ = "saml_configs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), unique=True, nullable=False
    )
    idp_entity_id: Mapped[str] = mapped_column(Text, nullable=False)
    idp_sso_url: Mapped[str] = mapped_column(Text, nullable=False)
    idp_slo_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    idp_x509_cert: Mapped[str] = mapped_column(Text, nullable=False)
    sp_entity_id: Mapped[str] = mapped_column(Text, nullable=False)
    sp_acs_url: Mapped[str] = mapped_column(Text, nullable=False)
    sp_private_key_enc: Mapped[str] = mapped_column(Text, nullable=False)
    sp_x509_cert: Mapped[str] = mapped_column(Text, nullable=False)
    jit_provisioning: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    default_role: Mapped[str] = mapped_column(String(50), default="user", server_default="user")
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )
