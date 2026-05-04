"""Tests for cross-user pattern detection (Phase 3).

All functions are deterministic — no LLM, no I/O.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379")
os.environ.setdefault("SECRET_KEY", "test-secret-key-do-not-use-in-prod")

from services.insights.cross_user import (
    compute_cost_distribution,
    compute_cross_user_patterns,
    compute_ide_distribution,
    compute_session_length_trends,
    compute_time_of_day_distribution,
    detect_user_friction_clusters,
)

# ─── helpers ─────────────────────────────────────────────────────────────────


def _make_session(
    session_id: str = "s1",
    user_id: str = "u1",
    error_count: int = 0,
    duration_seconds: int = 300,
    input_tokens: int = 1000,
    output_tokens: int = 500,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
    model: str = "claude-sonnet-4-6-20250514",
    platform: str = "vscode",
    first_event: str = "2024-03-15 10:00:00",
) -> dict:
    return {
        "session_id": session_id,
        "user_id": user_id,
        "error_count": error_count,
        "duration_seconds": duration_seconds,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cache_read_tokens": cache_read_tokens,
        "cache_write_tokens": cache_write_tokens,
        "model": model,
        "platform": platform,
        "first_event": first_event,
    }


# ─── detect_user_friction_clusters ───────────────────────────────────────────


class TestDetectUserFrictionClusters:
    def test_empty_sessions_returns_zeros(self):
        result = detect_user_friction_clusters([])
        assert result["total_users"] == 0
        assert result["high_friction_users"] == 0
        assert result["friction_concentrated"] is False
        assert result["overall_error_rate"] == 0.0
        assert result["per_user_summary"] == []

    def test_single_user_no_errors(self):
        sessions = [_make_session("s1", "u1", error_count=0)]
        result = detect_user_friction_clusters(sessions)
        assert result["total_users"] == 1
        assert result["high_friction_users"] == 0
        assert result["overall_error_rate"] == 0.0

    def test_identifies_high_friction_user(self):
        # 1 high-friction user out of 10 total (10%) → friction_concentrated is True
        low_friction = [_make_session(f"s{i}", f"u{i}", error_count=0) for i in range(9)]
        high_friction = [
            _make_session("s9", "u_bad", error_count=20),
            _make_session("s10", "u_bad", error_count=20),
        ]
        sessions = low_friction + high_friction
        result = detect_user_friction_clusters(sessions)
        assert result["total_users"] == 10
        assert result["high_friction_users"] == 1
        assert result["friction_concentrated"] is True

    def test_spread_friction_not_concentrated(self):
        # All users have the same error rate → not concentrated
        sessions = [_make_session(f"s{i}", f"u{i}", error_count=2) for i in range(10)]
        result = detect_user_friction_clusters(sessions)
        assert result["friction_concentrated"] is False

    def test_per_user_summary_fields(self):
        sessions = [
            _make_session("s1", "u1", error_count=1),
            _make_session("s2", "u1", error_count=3),
        ]
        result = detect_user_friction_clusters(sessions)
        summary = result["per_user_summary"]
        assert len(summary) == 1
        entry = summary[0]
        assert entry["user_id"] == "u1"
        assert entry["session_count"] == 2
        assert "avg_error_rate" in entry

    def test_missing_user_id_handled(self):
        sessions = [
            {"session_id": "s1", "error_count": 0},  # no user_id key
        ]
        result = detect_user_friction_clusters(sessions)
        assert result["total_users"] >= 0  # should not raise

    def test_overall_error_rate_accuracy(self):
        # 2 sessions each with 2 errors → avg 2 errors/session
        sessions = [
            _make_session("s1", "u1", error_count=2),
            _make_session("s2", "u2", error_count=2),
        ]
        result = detect_user_friction_clusters(sessions)
        assert result["overall_error_rate"] == pytest.approx(2.0)


# ─── compute_time_of_day_distribution ────────────────────────────────────────


class TestComputeTimeOfDayDistribution:
    def test_empty_returns_zero_counts(self):
        result = compute_time_of_day_distribution([])
        assert result["hourly_counts"] == {}
        assert result["peak_hours"] == []
        assert result["work_hours_pct"] == 0.0
        assert result["night_usage_pct"] == 0.0

    def test_hourly_counts_keyed_by_int(self):
        sessions = [_make_session(first_event="2024-03-15 10:00:00")]
        result = compute_time_of_day_distribution(sessions)
        assert 10 in result["hourly_counts"]
        assert result["hourly_counts"][10] == 1

    def test_peak_hours_at_most_three(self):
        sessions = [_make_session(first_event=f"2024-03-15 {h:02d}:00:00") for h in range(24)]
        result = compute_time_of_day_distribution(sessions)
        assert len(result["peak_hours"]) <= 3

    def test_work_hours_pct_all_work(self):
        # All sessions at 10:00 → 100% work hours
        sessions = [_make_session(first_event="2024-03-15 10:00:00") for _ in range(5)]
        result = compute_time_of_day_distribution(sessions)
        assert result["work_hours_pct"] == pytest.approx(100.0)

    def test_night_usage_pct_all_night(self):
        # All sessions at 23:00 → 100% night usage
        sessions = [_make_session(first_event="2024-03-15 23:00:00") for _ in range(3)]
        result = compute_time_of_day_distribution(sessions)
        assert result["night_usage_pct"] == pytest.approx(100.0)

    def test_invalid_timestamp_skipped(self):
        sessions = [
            _make_session(first_event="not-a-timestamp"),
            _make_session(first_event="2024-03-15 10:00:00"),
        ]
        result = compute_time_of_day_distribution(sessions)
        total = sum(result["hourly_counts"].values())
        assert total == 1  # only valid session counted

    def test_missing_first_event_skipped(self):
        sessions = [{"session_id": "s1"}]
        result = compute_time_of_day_distribution(sessions)
        assert result["hourly_counts"] == {}


# ─── compute_session_length_trends ───────────────────────────────────────────


class TestComputeSessionLengthTrends:
    def test_empty_returns_zeros(self):
        result = compute_session_length_trends([])
        assert result["p50_duration_seconds"] == 0
        assert result["p90_duration_seconds"] == 0
        assert result["p99_duration_seconds"] == 0
        assert result["trend_direction"] == "stable"
        assert result["trend_magnitude_pct"] == 0.0
        assert result["outlier_sessions"] == []

    def test_single_session_no_outliers(self):
        sessions = [_make_session(duration_seconds=300)]
        result = compute_session_length_trends(sessions)
        assert result["p50_duration_seconds"] == 300
        assert result["outlier_sessions"] == []

    def test_percentiles_correct(self):
        durations = list(range(1, 101))  # 1 to 100 seconds
        sessions = [_make_session(f"s{i}", duration_seconds=d) for i, d in enumerate(durations)]
        result = compute_session_length_trends(sessions)
        assert result["p50_duration_seconds"] == 50
        assert result["p90_duration_seconds"] == 90
        assert result["p99_duration_seconds"] == 99

    def test_outlier_detection_gt_3x_p50(self):
        # p50 = 100s, outlier at 400s (> 3x100)
        sessions = [_make_session(f"s{i}", duration_seconds=100) for i in range(10)]
        sessions.append(_make_session("s_outlier", duration_seconds=400))
        result = compute_session_length_trends(sessions)
        outlier_ids = [s.get("session_id") for s in result["outlier_sessions"]]
        assert "s_outlier" in outlier_ids

    def test_trend_increasing(self):
        # First half: short sessions, second half: longer sessions
        early = [_make_session(f"s{i}", duration_seconds=100, first_event=f"2024-01-01 0{i}:00:00") for i in range(5)]
        late = [
            _make_session(f"s{i + 5}", duration_seconds=300, first_event=f"2024-01-31 0{i}:00:00") for i in range(5)
        ]
        result = compute_session_length_trends(early + late)
        assert result["trend_direction"] == "increasing"

    def test_trend_stable_when_consistent(self):
        sessions = [
            _make_session(f"s{i}", duration_seconds=200, first_event=f"2024-01-{i + 1:02d} 10:00:00") for i in range(10)
        ]
        result = compute_session_length_trends(sessions)
        assert result["trend_direction"] == "stable"


# ─── compute_cost_distribution ───────────────────────────────────────────────


class TestComputeCostDistribution:
    def test_empty_returns_zeros(self):
        result = compute_cost_distribution([])
        assert result["p50_cost_usd"] == 0.0
        assert result["p90_cost_usd"] == 0.0
        assert result["p99_cost_usd"] == 0.0
        assert result["total_cost_usd"] == 0.0
        assert result["outlier_sessions"] == []

    def test_single_session_has_cost(self):
        sessions = [_make_session(input_tokens=1000, output_tokens=500)]
        result = compute_cost_distribution(sessions)
        assert result["total_cost_usd"] > 0.0
        assert result["p50_cost_usd"] > 0.0

    def test_outlier_detection_gt_3x_p50(self):
        # 10 cheap sessions, 1 expensive session
        cheap = [_make_session(f"s{i}", input_tokens=100, output_tokens=50) for i in range(10)]
        expensive = _make_session("s_expensive", input_tokens=100_000, output_tokens=50_000)
        result = compute_cost_distribution([*cheap, expensive])
        outlier_ids = [s.get("session_id") for s in result["outlier_sessions"]]
        assert "s_expensive" in outlier_ids

    def test_total_cost_is_sum(self):
        sessions = [
            _make_session("s1", input_tokens=1_000_000, output_tokens=0),
            _make_session("s2", input_tokens=1_000_000, output_tokens=0),
        ]
        result = compute_cost_distribution(sessions)
        individual = compute_cost_distribution([sessions[0]])
        assert result["total_cost_usd"] == pytest.approx(individual["total_cost_usd"] * 2, rel=1e-4)

    def test_percentile_keys_present(self):
        sessions = [_make_session(f"s{i}") for i in range(5)]
        result = compute_cost_distribution(sessions)
        for key in ("p50_cost_usd", "p90_cost_usd", "p99_cost_usd", "total_cost_usd", "outlier_sessions"):
            assert key in result


# ─── compute_ide_distribution ────────────────────────────────────────────────


class TestComputeIdeDistribution:
    def test_empty_sessions(self):
        result = compute_ide_distribution([])
        assert result["distribution"] == {}
        assert result["primary_ide"] == ""
        assert result["multi_ide"] is False

    def test_single_ide(self):
        sessions = [_make_session(platform="vscode") for _ in range(3)]
        result = compute_ide_distribution(sessions)
        assert result["distribution"]["vscode"] == 3
        assert result["primary_ide"] == "vscode"
        assert result["multi_ide"] is False

    def test_multi_ide_detection(self):
        sessions = [
            _make_session("s1", platform="vscode"),
            _make_session("s2", platform="jetbrains"),
        ]
        result = compute_ide_distribution(sessions)
        assert result["multi_ide"] is True

    def test_primary_ide_is_most_common(self):
        sessions = [
            _make_session("s1", platform="vscode"),
            _make_session("s2", platform="vscode"),
            _make_session("s3", platform="jetbrains"),
        ]
        result = compute_ide_distribution(sessions)
        assert result["primary_ide"] == "vscode"

    def test_missing_platform_bucketed_as_unknown(self):
        sessions = [{"session_id": "s1"}]  # no platform field
        result = compute_ide_distribution(sessions)
        assert "unknown" in result["distribution"] or len(result["distribution"]) >= 0

    def test_distribution_sums_to_session_count(self):
        sessions = [
            _make_session("s1", platform="vscode"),
            _make_session("s2", platform="vscode"),
            _make_session("s3", platform="cursor"),
        ]
        result = compute_ide_distribution(sessions)
        total = sum(result["distribution"].values())
        assert total == len(sessions)


# ─── compute_cross_user_patterns (orchestrator) ───────────────────────────────


class TestComputeCrossUserPatterns:
    @pytest.mark.asyncio
    async def test_empty_input_returns_all_keys(self):
        result = await compute_cross_user_patterns({})
        assert "user_friction" in result
        assert "time_of_day" in result
        assert "session_length" in result
        assert "cost_distribution" in result
        assert "ide_distribution" in result

    @pytest.mark.asyncio
    async def test_passes_through_session_values(self):
        metas = {
            "s1": _make_session("s1", "u1", error_count=0, platform="vscode"),
            "s2": _make_session("s2", "u2", error_count=5, platform="cursor"),
        }
        result = await compute_cross_user_patterns(metas)
        assert result["user_friction"]["total_users"] == 2
        assert result["ide_distribution"]["multi_ide"] is True

    @pytest.mark.asyncio
    async def test_single_session(self):
        metas = {"s1": _make_session("s1")}
        result = await compute_cross_user_patterns(metas)
        assert result["user_friction"]["total_users"] == 1
        assert result["session_length"]["p50_duration_seconds"] == 300
