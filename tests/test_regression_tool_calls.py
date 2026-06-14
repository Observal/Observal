# SPDX-License-Identifier: AGPL-3.0-only

"""Tests for the additive tool_calls_per_session signal in detect_regressions.

Falsifiable: remove the tool-call block and test_tool_calls_degraded /
test_tool_calls_improved fail (no such flag is produced). The existing-metric
tests guard that the addition did not change prior behavior.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ee"))

from observal_insights.regression import THRESHOLDS, detect_regressions


def _metrics(tool_calls: int, sessions: int, error_rate: float = 0.0, total_cost: float = 0.0) -> dict:
    return {
        "overview": {"total_sessions": sessions},
        "errors": {"total_tool_calls": tool_calls, "error_rate": error_rate},
        "cost": {"total_cost_usd": total_cost, "avg_cost_per_session": 0.0},
        "interruptions": {},
    }


def _flag(flags: list[dict], metric: str) -> dict | None:
    return next((f for f in flags if f["metric"] == metric), None)


def test_tool_calls_degraded():
    """30 -> 45 tool calls/session (+50%) is a degraded flag."""
    current = _metrics(tool_calls=450, sessions=10)   # 45/session
    previous = _metrics(tool_calls=300, sessions=10)  # 30/session
    flags = detect_regressions(current, previous)
    f = _flag(flags, "tool_calls_per_session")
    assert f is not None
    assert f["direction"] == "degraded"
    assert f["current_value"] == 45.0
    assert f["previous_value"] == 30.0
    assert f["severity"] == "high"  # 50% change


def test_tool_calls_improved():
    """40 -> 28 tool calls/session (-30%) is an improved flag."""
    current = _metrics(tool_calls=280, sessions=10)   # 28/session
    previous = _metrics(tool_calls=400, sessions=10)  # 40/session
    flags = detect_regressions(current, previous)
    f = _flag(flags, "tool_calls_per_session")
    assert f is not None
    assert f["direction"] == "improved"
    assert f["severity"] == "medium"  # 30% change < 50%


def test_tool_calls_below_threshold_no_flag():
    """A change under the 20% threshold produces no flag."""
    current = _metrics(tool_calls=210, sessions=10)   # 21/session = +5%
    previous = _metrics(tool_calls=200, sessions=10)  # 20/session
    assert _flag(detect_regressions(current, previous), "tool_calls_per_session") is None


def test_normalized_by_session_count():
    """Same per-session rate at different volumes => no flag (not confounded by volume)."""
    current = _metrics(tool_calls=600, sessions=20)   # 30/session
    previous = _metrics(tool_calls=300, sessions=10)  # 30/session
    assert _flag(detect_regressions(current, previous), "tool_calls_per_session") is None


def test_zero_previous_tool_calls_no_flag():
    """No baseline tool calls => cannot compute a relative change, no flag."""
    current = _metrics(tool_calls=100, sessions=10)
    previous = _metrics(tool_calls=0, sessions=10)
    assert _flag(detect_regressions(current, previous), "tool_calls_per_session") is None


def test_existing_error_rate_flag_unchanged():
    """Guard: the additive block did not disturb the existing error_rate metric."""
    current = _metrics(tool_calls=100, sessions=10, error_rate=0.35)
    previous = _metrics(tool_calls=100, sessions=10, error_rate=0.10)
    f = _flag(detect_regressions(current, previous), "error_rate")
    assert f is not None and f["direction"] == "degraded"


def test_threshold_registered():
    assert THRESHOLDS["tool_call_increase"] == 0.20
