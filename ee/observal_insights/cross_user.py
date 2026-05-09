"""Cross-user pattern detection for Agent Insights (Phase 3 / V3).

All functions are deterministic — no LLM calls.
"""

from __future__ import annotations

from datetime import datetime

from .pricing import compute_session_cost

# ---------------------------------------------------------------------------
# Existing V2 functions (preserved)
# ---------------------------------------------------------------------------


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
            if isinstance(ts, str):
                dt = datetime.fromisoformat(ts)
            else:
                dt = ts
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
    outlier_sessions = [s for s, d in zip(sessions, durations) if p50 > 0 and d > 3 * p50]

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


# ---------------------------------------------------------------------------
# V3 additions
# ---------------------------------------------------------------------------


def detect_multi_session(sessions: list[dict]) -> dict:
    """Detect concurrent session usage patterns using sliding window.

    Algorithm: Group sessions by user, build time intervals from start_time/end_time,
    then detect overlapping intervals within each user to identify "multi-clauding".

    Returns:
        detected: bool
        concurrent_windows: int (number of overlap points detected)
        max_concurrent: int (maximum sessions active simultaneously)
        multi_session_users: list[str] (user_ids who multi-session)
    """
    if len(sessions) < 2:
        return {
            "detected": False,
            "concurrent_windows": 0,
            "max_concurrent": 1,
            "multi_session_users": [],
        }

    # Group sessions by user
    user_sessions: dict[str, list[dict]] = {}
    for s in sessions:
        uid = s.get("user_id") or "unknown"
        user_sessions.setdefault(uid, []).append(s)

    concurrent_windows = 0
    max_concurrent = 1
    multi_session_users: list[str] = []

    for uid, user_sess in user_sessions.items():
        if len(user_sess) < 2:
            continue

        # Build timeline: (start_time, end_time, session_id)
        intervals: list[tuple[datetime, datetime, str]] = []
        for s in user_sess:
            start = s.get("start_time", "")
            end = s.get("end_time", "")
            if start and end:
                try:
                    st = datetime.fromisoformat(str(start).replace("Z", "+00:00")) if isinstance(start, str) else start
                    et = datetime.fromisoformat(str(end).replace("Z", "+00:00")) if isinstance(end, str) else end
                    intervals.append((st, et, s.get("session_id", "")))
                except (ValueError, TypeError):
                    continue

        if len(intervals) < 2:
            continue

        # Sort by start time
        intervals.sort(key=lambda x: x[0])

        # Detect overlapping intervals
        user_concurrent = 0
        user_max = 1
        for i in range(len(intervals)):
            active = 1
            for j in range(i + 1, len(intervals)):
                # Check if session j overlaps with session i
                if intervals[j][0] < intervals[i][1]:  # j starts before i ends
                    active += 1
                else:
                    break
            user_max = max(user_max, active)
            if active > 1:
                user_concurrent += 1

        if user_concurrent > 0:
            concurrent_windows += user_concurrent
            multi_session_users.append(uid)
        max_concurrent = max(max_concurrent, user_max)

    return {
        "detected": concurrent_windows > 0,
        "concurrent_windows": concurrent_windows,
        "max_concurrent": max_concurrent,
        "multi_session_users": multi_session_users,
    }


def analyze_subagent_patterns(sessions: list[dict]) -> dict:
    """Analyze subagent usage patterns.

    Identifies sessions with a non-empty parent_session_id as subagent sessions
    and computes success rate, duration, delegation types, and cost.

    Returns:
        total_subagent_sessions: int
        subagent_success_rate: float (based on error/tool ratio heuristic)
        avg_subagent_duration: float (seconds)
        delegation_types: dict[str, int] (inferred from tool usage patterns)
        parent_sessions: int (distinct sessions that spawned subagents)
        avg_subagent_cost_usd: float
    """
    subagents = [s for s in sessions if s.get("parent_session_id")]
    parents = set(s.get("parent_session_id") for s in subagents if s.get("parent_session_id"))

    if not subagents:
        return {
            "total_subagent_sessions": 0,
            "subagent_success_rate": 0.0,
            "avg_subagent_duration": 0.0,
            "delegation_types": {},
            "parent_sessions": 0,
            "avg_subagent_cost_usd": 0.0,
        }

    durations = [int(s.get("duration_seconds") or 0) for s in subagents]
    avg_duration = sum(durations) / len(durations) if durations else 0

    # Estimate success rate: sessions with low error rate and reasonable duration
    successful = sum(
        1
        for s in subagents
        if int(s.get("error_count", 0)) == 0
        or (
            int(s.get("tool_call_count", 0)) > 0
            and int(s.get("error_count", 0)) / int(s.get("tool_call_count", 1)) < 0.3
        )
    )
    success_rate = successful / len(subagents) if subagents else 0.0

    # Infer delegation types from tool patterns
    delegation_types: dict[str, int] = {}
    for s in subagents:
        # Heuristic: classify by dominant tool count or duration
        tool_count = int(s.get("tool_call_count", 0))
        duration = int(s.get("duration_seconds", 0))
        if tool_count == 0 and duration < 30:
            delegation_types["quick_lookup"] = delegation_types.get("quick_lookup", 0) + 1
        elif tool_count > 10:
            delegation_types["complex_task"] = delegation_types.get("complex_task", 0) + 1
        elif duration > 120:
            delegation_types["long_running"] = delegation_types.get("long_running", 0) + 1
        else:
            delegation_types["standard_task"] = delegation_types.get("standard_task", 0) + 1

    # Cost estimate
    total_cost = 0.0
    for s in subagents:
        cost = compute_session_cost(
            input_tokens=int(s.get("input_tokens") or 0),
            output_tokens=int(s.get("output_tokens") or 0),
            cache_read=int(s.get("cache_read_tokens") or 0),
            cache_write=int(s.get("cache_write_tokens") or 0),
            model=s.get("model") or "",
        )
        total_cost += cost
    avg_cost = total_cost / len(subagents) if subagents else 0.0

    return {
        "total_subagent_sessions": len(subagents),
        "subagent_success_rate": round(success_rate, 3),
        "avg_subagent_duration": round(avg_duration, 1),
        "delegation_types": delegation_types,
        "parent_sessions": len(parents),
        "avg_subagent_cost_usd": round(avg_cost, 4),
    }


def detect_shared_friction(sessions: list[dict]) -> dict:
    """Detect friction patterns shared across multiple users.

    If 3+ users hit the same type of friction pattern, the confidence is "high",
    indicating a strong fix recommendation. 2 users = "medium" confidence.

    Returns:
        shared_patterns: list of {pattern, users_affected, confidence}
        adoption_gaps: list of tools/features underutilized
    """
    # Group errors by user
    user_errors: dict[str, dict[str, int]] = {}  # user_id -> {error_type: count}

    for s in sessions:
        uid = s.get("user_id") or "unknown"
        error_count = int(s.get("error_count") or 0)
        if error_count > 0:
            user_errors.setdefault(uid, {})
            # Detect patterns from tool_call_count vs error_count ratio
            tool_count = int(s.get("tool_call_count") or 0)
            if tool_count > 0 and error_count / tool_count > 0.2:
                user_errors[uid]["high_error_rate"] = user_errors[uid].get("high_error_rate", 0) + 1

    # Find patterns affecting 2+ users
    pattern_users: dict[str, set[str]] = {}
    for uid, errors in user_errors.items():
        for error_type in errors:
            pattern_users.setdefault(error_type, set()).add(uid)

    shared_patterns: list[dict] = []
    for pattern, users in pattern_users.items():
        if len(users) >= 2:
            shared_patterns.append(
                {
                    "pattern": pattern,
                    "users_affected": len(users),
                    "confidence": "high" if len(users) >= 3 else "medium",
                }
            )

    # Adoption gaps: tools with very low usage across users
    # (Will be enhanced when per-tool facet data is available)

    return {
        "shared_patterns": shared_patterns,
        "adoption_gaps": [],
    }


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------


async def compute_cross_user_patterns(session_metas: dict[str, dict]) -> dict:
    """Run all cross-user pattern detection and return combined results.

    Input: dict of session_id -> session metadata (from session_cache.get_or_compute_metas)
    Each session meta has fields: user_id, duration_seconds, error_count, tool_call_count,
    input_tokens, output_tokens, cache_read_tokens, cache_write_tokens, model, platform,
    first_event (timestamp string), start_time, end_time, parent_session_id, etc.
    """
    sessions = list(session_metas.values())

    return {
        "user_friction": detect_user_friction_clusters(sessions),
        "time_of_day": compute_time_of_day_distribution(sessions),
        "session_length": compute_session_length_trends(sessions),
        "cost_distribution": compute_cost_distribution(sessions),
        "ide_distribution": compute_ide_distribution(sessions),
        # V3 additions
        "multi_session": detect_multi_session(sessions),
        "subagents": analyze_subagent_patterns(sessions),
        "shared_friction": detect_shared_friction(sessions),
    }
