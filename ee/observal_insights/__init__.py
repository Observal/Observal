# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-License-Identifier: LicenseRef-Observal-Enterprise

"""Observal Insights — enterprise insight generation engine.

This module lives under ee/ and is covered by the Observal Enterprise License.
It requires a valid OBSERVAL_LICENSE_KEY to function.

Usage:
    from ee.observal_insights import configure, generate_report_content, render_report_html
"""

from __future__ import annotations

from . import _deps
from .generator import generate_report_content
from .html_export import render_report_html

INSIGHTS_AVAILABLE = True
__version__ = "0.2.0"


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
    """Wire up dependencies from the host application.

    Must be called before any insight generation functions are used.
    """
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
