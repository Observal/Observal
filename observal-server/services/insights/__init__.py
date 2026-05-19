# SPDX-FileCopyrightText: 2026 Subramania Raja <dhanpraja231@gmail.com>
# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Insights plugin loader.

Delegates to the enterprise insights engine (ee/observal_insights/) when:
1. INSIGHTS_AVAILABLE=true in config
2. A valid OBSERVAL_LICENSE_KEY is present

If either condition is unmet, all insight operations raise RuntimeError
or return 403 via the API layer.
"""

from config import settings

INSIGHTS_AVAILABLE: bool = settings.INSIGHTS_AVAILABLE

_generate = None
_render = None

_run_single_report = None
_discover_and_queue = None

if INSIGHTS_AVAILABLE:
    try:
        from ee.license import require_license

        require_license("insights")
        from ee.observal_insights import generate_report_content as _generate  # type: ignore[assignment]
        from ee.observal_insights import render_report_html as _render  # type: ignore[assignment]
        from ee.observal_insights.batch import (
            discover_and_queue_reports as _discover_and_queue,  # type: ignore[assignment]  # noqa: F401
        )
        from ee.observal_insights.batch import (
            run_single_report as _run_single_report,  # type: ignore[assignment]  # noqa: F401
        )
    except (ImportError, RuntimeError):
        # ee/ not present or license invalid — degrade gracefully
        INSIGHTS_AVAILABLE = False


def _not_available():
    raise RuntimeError(
        "Insights requires a valid Observal Enterprise license. Set OBSERVAL_LICENSE_KEY or contact team@observal.dev."
    )


async def generate_report_content(*args, **kwargs):
    if not INSIGHTS_AVAILABLE or _generate is None:
        _not_available()
    return await _generate(*args, **kwargs)


def render_report_html(*args, **kwargs):
    if not INSIGHTS_AVAILABLE or _render is None:
        _not_available()
    return _render(*args, **kwargs)


def configure_insights():
    """Wire up dependencies from the host app into the insights package.

    Called once at server startup. No-op if not licensed/available.
    """
    if not INSIGHTS_AVAILABLE:
        return

    from database import async_session
    from ee.observal_insights import configure
    from models.insight_meta_cache import InsightMetaCache
    from models.insight_session_facets import InsightSessionFacets
    from models.insight_session_meta import InsightSessionMeta
    from services.clickhouse import _query
    from services.eval.eval_service import call_eval_model

    configure(
        settings=settings,
        query_fn=_query,
        call_model_fn=call_eval_model,
        db_session_factory=async_session,
        meta_model=InsightSessionMeta,
        facets_model=InsightSessionFacets,
        meta_cache_model=InsightMetaCache,
    )


def licensed_features() -> list[str]:
    """Return licensed feature list via the gate — never import ee/ directly."""
    if not INSIGHTS_AVAILABLE:
        return []
    try:
        from ee.license import licensed_features as _lf

        return _lf()
    except (ImportError, RuntimeError):
        return []
