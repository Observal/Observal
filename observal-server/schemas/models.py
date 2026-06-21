# SPDX-FileCopyrightText: 2026 Aryan Iyappan <aryaniyappan2006@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Pydantic schemas for the live model catalog (sourced from legacy provider catalog).

The catalog is read-only. Our database stores only the user's choice
(``agent_versions.model_name`` + ``agent_versions.models_by_harness``), never the
catalog itself.
"""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field


class ModelDisplay(BaseModel):
    """Pre-computed display fields shipped to clients so they don't reparse names."""

    primary: str
    secondary: str | None = None
    is_rolling: bool = False
    is_deprecated: bool = False


class CatalogModel(BaseModel):
    """A single model entry, normalized from legacy provider catalog shape."""

    model_id: str = Field(description="Canonical model id, e.g. 'claude-sonnet-4-5'.")
    display_name: str = Field(description="Curated name from legacy provider catalog (raw, unstripped).")
    provider: str = Field(description="legacy provider catalog provider id, e.g. 'anthropic'.")
    family: str = Field(description="legacy provider catalog family, e.g. 'claude-sonnet'.")
    release_date: date | None = None
    last_updated: date | None = None
    context_window: int | None = None
    output_tokens: int | None = None
    cost_input: float | None = None
    cost_output: float | None = None
    capabilities: list[str] = Field(
        default_factory=list,
        description="Subset of ['tool_call', 'reasoning', 'attachment'] flags carried by the upstream entry.",
    )
    supported_harnesses: list[str] = Field(
        default_factory=list,
        description="harnesses that can install this model - derived from provider via the static mapping.",
    )
    deprecated: bool = False
    display: ModelDisplay | None = None


class Catalog(BaseModel):
    """Normalized model catalog plus provenance metadata."""

    models: list[CatalogModel] = Field(default_factory=list)
    fetched_at: datetime
    source: Literal["live", "redis", "snapshot", "empty"]
    degraded: bool = False
    etag: str | None = None
    upstream_etag: str | None = None
    model_count: int = 0
