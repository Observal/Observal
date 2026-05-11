# SPDX-FileCopyrightText: 2026 Subramania Raja <dhanpraja231@gmail.com>
# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Insights plugin loader.

The insights engine lives under ee/observal_insights/ and is only available
when DEPLOYMENT_MODE=enterprise. If not in enterprise mode, all functions
raise RuntimeError and INSIGHTS_AVAILABLE is False — the frontend hides the
feature entirely.
"""

from config import settings

# Insights is only available in enterprise mode
if settings.DEPLOYMENT_MODE == "enterprise":
    try:
        from ee.observal_insights import (
            generate_report_content as _generate,
        )
        from ee.observal_insights import (
            render_report_html as _render,
        )

        INSIGHTS_AVAILABLE = True
    except ImportError:
        INSIGHTS_AVAILABLE = False
else:
    INSIGHTS_AVAILABLE = False


def _not_available():
    raise RuntimeError("Insights is an enterprise feature. Set DEPLOYMENT_MODE=enterprise to enable.")


async def generate_report_content(*args, **kwargs):
    if not INSIGHTS_AVAILABLE:
        _not_available()
    return await _generate(*args, **kwargs)


def render_report_html(*args, **kwargs):
    if not INSIGHTS_AVAILABLE:
        _not_available()
    return _render(*args, **kwargs)


def configure_insights():
    """Wire up dependencies from the host app into the insights package.

    Called once at server startup. No-op if not in enterprise mode.
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
