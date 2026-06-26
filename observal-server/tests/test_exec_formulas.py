# SPDX-FileCopyrightText: 2026 Vishnu Muthiah <vishnu.muthiah04@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only
"""Unit tests for exec dashboard computation functions.

These are pure math tests — no database, no network, no async.
Run with: pytest tests/test_exec_formulas.py -v
"""

from datetime import UTC, timedelta
from datetime import datetime as dt


# Inline the functions to avoid importing the full app module chain
def compute_trend_percent(current: int, previous: int) -> float:
    if previous == 0:
        return 100.0 if current > 0 else 0.0
    return round(((current - previous) / previous) * 100, 1)


_RANGE_MAP = {"24h": 1, "7d": 7, "30d": 30, "90d": 90}


def _range_days(range_: str | None) -> int:
    return _RANGE_MAP.get(range_ or "7d", 7)


def _period_bounds(range_: str | None) -> tuple[dt, dt, dt, dt]:
    days = _range_days(range_)
    now = dt.now(UTC)
    current_start = now - timedelta(days=days)
    current_end = now
    previous_start = current_start - timedelta(days=days)
    previous_end = current_start
    return current_start, current_end, previous_start, previous_end


class TestComputeTrendPercent:
    def test_positive_growth(self):
        assert compute_trend_percent(150, 100) == 50.0

    def test_negative_growth(self):
        assert compute_trend_percent(50, 100) == -50.0

    def test_zero_previous_with_current(self):
        assert compute_trend_percent(50, 0) == 100.0

    def test_zero_both(self):
        assert compute_trend_percent(0, 0) == 0.0

    def test_zero_current_nonzero_previous(self):
        assert compute_trend_percent(0, 100) == -100.0

    def test_same_values(self):
        assert compute_trend_percent(100, 100) == 0.0

    def test_doubles(self):
        assert compute_trend_percent(200, 100) == 100.0

    def test_small_numbers(self):
        result = compute_trend_percent(3, 2)
        assert result == 50.0

    def test_large_numbers(self):
        result = compute_trend_percent(1000000, 999000)
        assert 0 < result < 1  # ~0.1% growth


class TestRangeDays:
    def test_default_none(self):
        assert _range_days(None) == 7

    def test_24h(self):
        assert _range_days("24h") == 1

    def test_7d(self):
        assert _range_days("7d") == 7

    def test_30d(self):
        assert _range_days("30d") == 30

    def test_90d(self):
        assert _range_days("90d") == 90

    def test_invalid_defaults_to_7(self):
        assert _range_days("invalid") == 7

    def test_empty_string_defaults_to_7(self):
        assert _range_days("") == 7


class TestPeriodBounds:
    def test_returns_four_datetimes(self):
        cs, ce, ps, pe = _period_bounds("7d")
        assert cs < ce
        assert ps < pe
        assert pe == cs  # previous ends where current starts

    def test_periods_equal_length(self):
        cs, ce, ps, pe = _period_bounds("30d")
        current_len = (ce - cs).days
        previous_len = (pe - ps).days
        assert current_len == previous_len

    def test_contiguous(self):
        cs, ce, ps, pe = _period_bounds("7d")
        assert pe == cs  # no gap between periods

    def test_none_uses_7d(self):
        cs, ce, ps, pe = _period_bounds(None)
        assert (ce - cs).days == 7


class TestAIInsightsCacheResponse:
    def test_empty_response_is_not_generated(self):
        from ee.observal_server.routes.exec_dashboard import _empty_ai_insights_response

        response = _empty_ai_insights_response()

        assert response.generated is False
        assert response.generated_at is None
        assert response.platform_insight["title"] == "No cached report"

    def test_legacy_cached_payload_without_generated_at_validates(self):
        from ee.observal_server.routes.exec_dashboard import AIInsightsResponse

        response = AIInsightsResponse.model_validate(
            {
                "quick_wins": [],
                "adoption_gaps": [],
                "platform_insight": {},
                "model_insight": {},
                "automation_opportunity": {},
                "usage_pattern": {},
                "generated": True,
            }
        )

        assert response.generated is True
        assert response.generated_at is None
