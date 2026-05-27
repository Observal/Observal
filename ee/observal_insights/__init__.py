# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: LicenseRef-Observal-Enterprise

"""Observal Insights, enterprise insight generation engine.

V5 ground-up rewrite modeled after pi /insights. Reads raw session JSONL
from ClickHouse, extracts deterministic stats + LLM facets, generates
personal narrative sections, and renders HTML reports.
"""

from __future__ import annotations

from . import _deps
from .generator import generate_report_content
from .html_export import render_report_html

INSIGHTS_AVAILABLE = True
__version__ = "5.0.0"


def configure(
    *,
    settings,
    query_fn,
    call_model_fn,
    db_session_factory,
    meta_model=None,
    facets_model=None,
    meta_cache_model=None,
):
    """Wire up dependencies from the host application."""
    _deps.settings = settings
    _deps.query = query_fn
    _deps.call_model = call_model_fn
    _deps.db_session = db_session_factory
    if meta_model:
        _deps.InsightSessionMeta = meta_model
    if facets_model:
        _deps.InsightSessionFacets = facets_model
    if meta_cache_model:
        _deps.InsightMetaCache = meta_cache_model


__all__ = [
    "INSIGHTS_AVAILABLE",
    "configure",
    "generate_report_content",
    "render_report_html",
]
