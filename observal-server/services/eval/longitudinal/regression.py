# SPDX-FileCopyrightText: 2026 Swathi Saravanan <ss4522@cornell.edu>
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Cross-session regression detection over rolling 7d / 30d / 90d windows.

Pure functions. Inputs are time-stamped score samples; outputs are
DriftAlerts and CheckResults. Detects:

- rolling-mean shift > 1 std from baseline
- per-CheckType regression (failure rate of a CheckType up vs. baseline)
- seasonal patterns (weekday vs. weekend, working-hours vs. off-hours)

Same inputs → same outputs.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from statistics import StatisticsError, mean, stdev

from services.eval.check_result.models import (
    Category,
    CheckResult,
    CheckType,
    Status,
)


@dataclass(frozen=True)
class ScorePoint:
    timestamp: datetime
    score: float


@dataclass(frozen=True)
class CheckTypePoint:
    timestamp: datetime
    check_type: str
    failed: bool


@dataclass(frozen=True)
class DriftAlert:
    window_days: int
    baseline_mean: float
    baseline_std: float
    recent_mean: float
    z: float
    direction: str  # "up" | "down"


def _bisect_window(points: list[ScorePoint], end: datetime, days: int) -> list[ScorePoint]:
    start = end - timedelta(days=days)
    return [p for p in points if start <= p.timestamp <= end]


def detect_drift(
    points: list[ScorePoint],
    *,
    now: datetime | None = None,
    z_threshold: float = 1.0,
) -> list[DriftAlert]:
    """Detect rolling-mean shifts > z_threshold from baseline std.

    For each window in (7, 30, 90) days, compare the *recent half* of the
    window (anchored at `now`) against the *baseline half*. An alert
    fires when |z| > z_threshold AND baseline std is > 0.
    """
    if not points:
        return []
    cur = now or datetime.now(UTC)
    out: list[DriftAlert] = []
    for window in (7, 30, 90):
        full = _bisect_window(points, cur, window)
        if len(full) < 4:
            continue
        mid = cur - timedelta(days=window / 2)
        baseline = [p.score for p in full if p.timestamp < mid]
        recent = [p.score for p in full if p.timestamp >= mid]
        if len(baseline) < 2 or len(recent) < 2:
            continue
        b_mean = mean(baseline)
        try:
            b_std = stdev(baseline)
        except StatisticsError:
            continue
        if b_std == 0:
            continue
        r_mean = mean(recent)
        z = (r_mean - b_mean) / b_std
        if abs(z) > z_threshold:
            out.append(
                DriftAlert(
                    window_days=window,
                    baseline_mean=b_mean,
                    baseline_std=b_std,
                    recent_mean=r_mean,
                    z=z,
                    direction="up" if z > 0 else "down",
                )
            )
    return out


def per_check_type_drift(
    points: list[CheckTypePoint],
    *,
    now: datetime | None = None,
    window_days: int = 30,
) -> list[CheckResult]:
    """Per-CheckType failure-rate regression — emits REGRESSION_DETECTED.

    Compares the failure rate in the most recent half of the window
    against the baseline half. A relative increase >= 50% (and absolute
    increase >= 0.05) emits a CheckResult.
    """
    if not points:
        return []
    cur = now or datetime.now(UTC)
    start = cur - timedelta(days=window_days)
    mid = cur - timedelta(days=window_days / 2)

    by_type: dict[str, list[CheckTypePoint]] = defaultdict(list)
    for p in points:
        if start <= p.timestamp <= cur:
            by_type[p.check_type].append(p)

    out: list[CheckResult] = []
    for ctype, items in by_type.items():
        baseline = [p for p in items if p.timestamp < mid]
        recent = [p for p in items if p.timestamp >= mid]
        if len(baseline) < 5 or len(recent) < 5:
            continue
        b_rate = sum(1 for p in baseline if p.failed) / len(baseline)
        r_rate = sum(1 for p in recent if p.failed) / len(recent)
        if r_rate - b_rate < 0.05:
            continue
        if b_rate > 0 and (r_rate - b_rate) / max(b_rate, 1e-9) < 0.5:
            continue
        out.append(
            CheckResult(
                check_type=CheckType.REGRESSION_DETECTED,
                status=Status.WARN,
                weight=1.0,
                points_earned=0.0,
                points_possible=1.0,
                category=Category.EFFICIENCY,
                meta={
                    "regressed_check_type": ctype,
                    "window_days": window_days,
                    "baseline_failure_rate": b_rate,
                    "recent_failure_rate": r_rate,
                },
            )
        )
    return out


def seasonal_pattern(points: list[ScorePoint]) -> dict[str, float]:
    """Mean score by (weekday|weekend) and (working_hours|off_hours).

    Returns a dict with up to 4 keys: weekday_working, weekday_off,
    weekend_working, weekend_off. Missing categories are omitted.
    """
    buckets: dict[str, list[float]] = defaultdict(list)
    for p in points:
        ts = p.timestamp.astimezone(UTC)
        is_weekend = ts.weekday() >= 5
        working = 9 <= ts.hour < 17
        key = ("weekend" if is_weekend else "weekday") + ("_working" if working else "_off")
        buckets[key].append(p.score)
    return {k: mean(v) for k, v in buckets.items() if v}
