"""Observal Insights — enterprise insight generation engine.

This module lives under ee/ and is covered by the Observal Enterprise License.
It is only available when DEPLOYMENT_MODE=enterprise.

Usage:
    from ee.observal_insights import configure, generate_report_content, render_report_html

    # 1. Configure at app startup
    configure(
        settings=settings,
        query_fn=clickhouse_query,
        call_model_fn=call_eval_model,
        db_session_factory=async_session,
        meta_model=InsightSessionMeta,
        facets_model=InsightSessionFacets,
    )

    # 2. Generate reports
    result = await generate_report_content(...)
"""

from __future__ import annotations

from . import _deps

INSIGHTS_AVAILABLE = True
__version__ = "0.1.0"


def configure(
    *,
    settings,
    query_fn,
    call_model_fn,
    db_session_factory,
    meta_model=None,
    facets_model=None,
):
    """Wire up dependencies from the host application.

    Must be called before any insight generation functions are used.
    """
    _deps.settings = settings
    _deps.query = query_fn
    _deps.call_model = call_model_fn
    _deps.db_session = db_session_factory
    _deps.InsightSessionMeta = meta_model
    _deps.InsightSessionFacets = facets_model


# Lazy imports for public API — avoids import-time dependency checks
def generate_report_content(*args, **kwargs):
    from .generator import generate_report_content as _impl

    return _impl(*args, **kwargs)


def render_report_html(*args, **kwargs):
    from .html_export import render_report_html as _impl

    return _impl(*args, **kwargs)
