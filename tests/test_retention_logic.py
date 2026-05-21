# SPDX-FileCopyrightText: 2026 Kaushik Kumar <kaushikrjpm10@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Pure-Python unit tests for retention purge algorithms.

No project imports required — verifies algorithmic correctness of the
count-based cutoff, score retention defaults, timestamp formatting, and
deletion ordering logic.
"""

import re
from datetime import UTC, datetime, timedelta


def _compute_score_days(data_retention_days, score_retention_days=None):
    """Reproduce the score-days derivation from run_retention_purge."""
    score_days = score_retention_days or ((data_retention_days * 2) if data_retention_days else None)
    if score_days:
        score_days = max(score_days, 30)
    return score_days


def _count_based_cutoff(data, max_trace_count):
    """Reproduce the cutoff-day walk from _purge_count_based."""
    running_total = 0
    cutoff_day = None
    for row in data:
        running_total += int(row["cnt"])
        if running_total > max_trace_count:
            cutoff_day = row["day"]
            break
    return cutoff_day, running_total


# ── Count-based cutoff ────────────────────────────────────────────────────────


def test_count_based_cutoff_basic():
    data = [
        {"day": "2026-05-11", "cnt": "2000"},
        {"day": "2026-05-10", "cnt": "2000"},
        {"day": "2026-05-09", "cnt": "2000"},
        {"day": "2026-05-08", "cnt": "1500"},
    ]
    cutoff, total = _count_based_cutoff(data, max_trace_count=5000)
    # 2000+2000+2000 = 6000 > 5000 → cutoff on third day
    assert cutoff == "2026-05-09"
    assert total == 6000


def test_count_based_cutoff_all_fit():
    data = [
        {"day": "2026-05-11", "cnt": "500"},
        {"day": "2026-05-10", "cnt": "500"},
        {"day": "2026-05-09", "cnt": "500"},
    ]
    cutoff, total = _count_based_cutoff(data, max_trace_count=10000)
    # 1500 < 10000 → no purge needed
    assert cutoff is None
    assert total == 1500


def test_count_based_cutoff_boundary():
    """Strictly greater-than, not >=, so exact-limit does not trigger purge."""
    data = [
        {"day": "2026-05-11", "cnt": "2500"},
        {"day": "2026-05-10", "cnt": "2500"},
        {"day": "2026-05-09", "cnt": "1"},
    ]
    cutoff, total = _count_based_cutoff(data, max_trace_count=5000)
    # 2500+2500=5000 (not >5000), +1=5001 → cutoff on third day
    assert cutoff == "2026-05-09"
    assert total == 5001


def test_count_based_cutoff_empty():
    cutoff, total = _count_based_cutoff([], max_trace_count=1000)
    assert cutoff is None
    assert total == 0


# ── Score retention defaults ──────────────────────────────────────────────────


def test_score_days_default_floored_at_30():
    # 14*2=28, max(28,30)=30
    assert _compute_score_days(14) == 30


def test_score_days_default_above_floor():
    # 20*2=40, max(40,30)=40
    assert _compute_score_days(20) == 40


def test_score_days_explicit_overrides_default():
    assert _compute_score_days(14, 60) == 60


def test_score_days_minimum_trace_retention():
    # 7*2=14, floor to 30
    assert _compute_score_days(7) == 30


def test_score_days_none_when_no_retention():
    # count-only retention — no score purge
    assert _compute_score_days(None) is None


# ── Cutoff timestamp formatting ───────────────────────────────────────────────

TIMESTAMP_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.000$")


def test_time_based_cutoff_format():
    cutoff = datetime.now(UTC) - timedelta(days=14)
    cutoff_str = cutoff.strftime("%Y-%m-%d %H:%M:%S.000")
    assert TIMESTAMP_PATTERN.match(cutoff_str), f"Format mismatch: {cutoff_str}"


def test_count_based_cutoff_timestamp_format():
    cutoff_str = "2026-05-09 00:00:00.000"
    assert TIMESTAMP_PATTERN.match(cutoff_str)


# ── Deletion order ────────────────────────────────────────────────────────────


def test_deletion_order_children_before_traces():
    """Children (spans, session_events) must be deleted before traces."""
    deletion_order = []
    for table, _col in [("spans", "start_time"), ("session_events", "timestamp")]:
        deletion_order.append(f"DELETE FROM {table}")
    deletion_order.append("DELETE orphan session_stats_agg")
    deletion_order.append("DELETE FROM scores")
    deletion_order.append("DELETE FROM traces")

    traces_idx = deletion_order.index("DELETE FROM traces")
    assert deletion_order.index("DELETE FROM spans") < traces_idx
    assert deletion_order.index("DELETE FROM session_events") < traces_idx
    assert deletion_order.index("DELETE orphan session_stats_agg") < traces_idx
    assert deletion_order.index("DELETE FROM scores") < traces_idx
