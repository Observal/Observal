"""Cross-user pattern detection for Agent Insights (Phase 3).

All functions are deterministic — no LLM calls.
"""

from __future__ import annotations

from datetime import datetime


def detect_user_friction_clusters(sessions: list[dict]) -> dict:
    """Analyze per-user error rates to find friction concentration.

    Returns:
        total_users: int
        high_friction_users: int (users with >2x average error rate)
        friction_concentrated: bool (high friction in <=20% of users)
        overall_error_rate: float
        per_user_summary: list of {user_id, session_count, avg_error_rate}
    """
    if not sessions:
        return {
            "total_users": 0,
            "high_friction_users": 0,
            "friction_concentrated": False,
            "overall_error_rate": 0.0,
            "per_user_summary": [],
        }

    # Aggregate per user
    user_errors: dict[str, list[float]] = {}
    for s in sessions:
        uid = s.get("user_id") or "unknown"
        error_count = float(s.get("error_count") or 0)
        user_errors.setdefault(uid, []).append(error_count)

    total_errors = sum(e for errs in user_errors.values() for e in errs)
    overall_error_rate = total_errors / len(sessions)

    per_user_summary = []
    for uid, errs in user_errors.items():
        avg = sum(errs) / len(errs)
        per_user_summary.append(
            {
                "user_id": uid,
                "session_count": len(errs),
                "avg_error_rate": round(avg, 4),
            }
        )

    total_users = len(user_errors)
    avg_user_error_rate = overall_error_rate  # same as global avg by definition

    high_friction_users = sum(
        1
        for entry in per_user_summary
        if avg_user_error_rate > 0 and entry["avg_error_rate"] >= 2 * avg_user_error_rate
    )

    friction_concentrated = total_users > 0 and high_friction_users > 0 and (high_friction_users / total_users) <= 0.20

    return {
        "total_users": total_users,
        "high_friction_users": high_friction_users,
        "friction_concentrated": friction_concentrated,
        "overall_error_rate": round(overall_error_rate, 4),
        "per_user_summary": per_user_summary,
    }


def compute_time_of_day_distribution(sessions: list[dict]) -> dict:
    """Compute hourly usage distribution.

    Returns:
        hourly_counts: dict[int, int] (hour 0-23 -> session count)
        peak_hours: list[int] (top 3 hours)
        work_hours_pct: float (% sessions during 9-17)
        night_usage_pct: float (% sessions during 22-6)
    """
    hourly_counts: dict[int, int] = {}
    valid = 0

    for s in sessions:
        ts = s.get("first_event")
        if not ts:
            continue
        try:
            dt = datetime.fromisoformat(ts) if isinstance(ts, str) else ts
            hour = dt.hour
            hourly_counts[hour] = hourly_counts.get(hour, 0) + 1
            valid += 1
        except (ValueError, TypeError, AttributeError):
            continue

    if valid == 0:
        return {
            "hourly_counts": {},
            "peak_hours": [],
            "work_hours_pct": 0.0,
            "night_usage_pct": 0.0,
        }

    peak_hours = sorted(hourly_counts, key=lambda h: -hourly_counts[h])[:3]

    work_count = sum(hourly_counts.get(h, 0) for h in range(9, 17))
    # Night: 22-23 and 0-6
    night_count = sum(hourly_counts.get(h, 0) for h in list(range(22, 24)) + list(range(0, 7)))

    return {
        "hourly_counts": hourly_counts,
        "peak_hours": peak_hours,
        "work_hours_pct": round(work_count / valid * 100, 2),
        "night_usage_pct": round(night_count / valid * 100, 2),
    }


def compute_session_length_trends(sessions: list[dict]) -> dict:
    """Analyze session duration trends.

    Returns:
        p50_duration_seconds: int
        p90_duration_seconds: int
        p99_duration_seconds: int
        trend_direction: "increasing" | "decreasing" | "stable"
        trend_magnitude_pct: float (% change over the period)
        outlier_sessions: list (sessions >3x p50)
    """
    if not sessions:
        return {
            "p50_duration_seconds": 0,
            "p90_duration_seconds": 0,
            "p99_duration_seconds": 0,
            "trend_direction": "stable",
            "trend_magnitude_pct": 0.0,
            "outlier_sessions": [],
        }

    durations = [int(s.get("duration_seconds") or 0) for s in sessions]
    sorted_durations = sorted(durations)
    n = len(sorted_durations)

    p50 = sorted_durations[(n - 1) // 2]
    p90 = sorted_durations[int((n - 1) * 0.9)] if n > 1 else sorted_durations[-1]
    p99 = sorted_durations[int((n - 1) * 0.99)] if n > 1 else sorted_durations[-1]

    # Outliers: sessions with duration > 3x p50
    outlier_sessions = [s for s, d in zip(sessions, durations, strict=False) if p50 > 0 and d > 3 * p50]

    # Trend: compare first half avg vs second half avg (sorted by first_event if possible)
    try:
        ordered = sorted(
            sessions,
            key=lambda s: s.get("first_event") or "",
        )
    except TypeError:
        ordered = sessions

    trend_direction = "stable"
    trend_magnitude_pct = 0.0

    if n >= 4:
        mid = n // 2
        first_half_durations = [int(ordered[i].get("duration_seconds") or 0) for i in range(mid)]
        second_half_durations = [int(ordered[i].get("duration_seconds") or 0) for i in range(mid, n)]

        first_avg = sum(first_half_durations) / len(first_half_durations)
        second_avg = sum(second_half_durations) / len(second_half_durations)

        if first_avg > 0:
            change_pct = (second_avg - first_avg) / first_avg * 100
            trend_magnitude_pct = round(abs(change_pct), 2)
            if change_pct > 10:
                trend_direction = "increasing"
            elif change_pct < -10:
                trend_direction = "decreasing"

    return {
        "p50_duration_seconds": p50,
        "p90_duration_seconds": p90,
        "p99_duration_seconds": p99,
        "trend_direction": trend_direction,
        "trend_magnitude_pct": trend_magnitude_pct,
        "outlier_sessions": outlier_sessions,
    }


def compute_cost_distribution(sessions: list[dict]) -> dict:
    """Compute cost percentiles and outliers.

    Returns:
        p50_cost_usd: float
        p90_cost_usd: float
        p99_cost_usd: float
        outlier_sessions: list (sessions >3x p50 cost)
        total_cost_usd: float
    """
    from services.insights.pricing import compute_session_cost

    if not sessions:
        return {
            "p50_cost_usd": 0.0,
            "p90_cost_usd": 0.0,
            "p99_cost_usd": 0.0,
            "outlier_sessions": [],
            "total_cost_usd": 0.0,
        }

    session_costs: list[tuple[dict, float]] = []
    for s in sessions:
        cost = compute_session_cost(
            input_tokens=int(s.get("input_tokens") or 0),
            output_tokens=int(s.get("output_tokens") or 0),
            cache_read=int(s.get("cache_read_tokens") or 0),
            cache_write=int(s.get("cache_write_tokens") or 0),
            model=s.get("model") or "",
        )
        session_costs.append((s, cost))

    costs_sorted = sorted(session_costs, key=lambda x: x[1])
    n = len(costs_sorted)

    p50 = costs_sorted[n // 2][1]
    p90 = costs_sorted[int(n * 0.9)][1] if n > 1 else costs_sorted[-1][1]
    p99 = costs_sorted[int(n * 0.99)][1] if n > 1 else costs_sorted[-1][1]
    total = sum(c for _, c in session_costs)

    outlier_sessions = [s for s, c in session_costs if p50 > 0 and c > 3 * p50]

    return {
        "p50_cost_usd": round(p50, 6),
        "p90_cost_usd": round(p90, 6),
        "p99_cost_usd": round(p99, 6),
        "outlier_sessions": outlier_sessions,
        "total_cost_usd": round(total, 6),
    }


def compute_ide_distribution(sessions: list[dict]) -> dict:
    """Group sessions by IDE/platform.

    Returns:
        distribution: dict[str, int] (ide_name -> session count)
        primary_ide: str
        multi_ide: bool (>1 IDE used)
    """
    distribution: dict[str, int] = {}

    for s in sessions:
        platform = s.get("platform") or "unknown"
        distribution[platform] = distribution.get(platform, 0) + 1

    if not distribution:
        return {
            "distribution": {},
            "primary_ide": "",
            "multi_ide": False,
        }

    primary_ide = max(distribution, key=distribution.__getitem__)
    multi_ide = len(distribution) > 1

    return {
        "distribution": distribution,
        "primary_ide": primary_ide,
        "multi_ide": multi_ide,
    }


async def compute_cross_user_patterns(session_metas: dict[str, dict]) -> dict:
    """Run all cross-user pattern detection and return combined results.

    Input: dict of session_id -> session metadata (from session_cache.get_or_compute_metas)
    Each session meta has fields: user_id, duration_seconds, error_count, tool_call_count,
    input_tokens, output_tokens, model, platform, first_event (timestamp string), etc.
    """
    sessions = list(session_metas.values())

    return {
        "user_friction": detect_user_friction_clusters(sessions),
        "time_of_day": compute_time_of_day_distribution(sessions),
        "session_length": compute_session_length_trends(sessions),
        "cost_distribution": compute_cost_distribution(sessions),
        "ide_distribution": compute_ide_distribution(sessions),
    }
