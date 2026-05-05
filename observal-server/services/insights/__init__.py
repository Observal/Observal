"""Insights plugin loader.

If the observal-insights private package is installed, this module re-exports
its public API. Otherwise, all functions raise HTTP 402 and INSIGHTS_AVAILABLE
is False — the frontend hides the feature entirely.
"""

try:
    import observal_insights

    INSIGHTS_AVAILABLE = True
except ImportError:
    observal_insights = None  # type: ignore[assignment]
    INSIGHTS_AVAILABLE = False


def _not_available():
    raise RuntimeError("Insights package is not installed. Install observal-insights to enable this feature.")


async def generate_report_content(*args, **kwargs):
    if not INSIGHTS_AVAILABLE:
        _not_available()
    return await observal_insights.generate_report_content(*args, **kwargs)


def render_report_html(*args, **kwargs):
    if not INSIGHTS_AVAILABLE:
        _not_available()
    return observal_insights.render_report_html(*args, **kwargs)


def configure_insights():
    """Wire up dependencies from the host app into the insights package.

    Called once at server startup. No-op if the package isn't installed.
    """
    if not INSIGHTS_AVAILABLE:
        return

    from config import settings
    from database import async_session
    from models.insight_session_facets import InsightSessionFacets
    from models.insight_session_meta import InsightSessionMeta
    from services.clickhouse import _query
    from services.eval.eval_service import call_eval_model

    observal_insights.configure(
        settings=settings,
        query_fn=_query,
        call_model_fn=call_eval_model,
        db_session_factory=async_session,
        meta_model=InsightSessionMeta,
        facets_model=InsightSessionFacets,
    )
