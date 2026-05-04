"""Regression detection between insight report periods."""

from __future__ import annotations

THRESHOLDS = {
    "error_rate_increase": 0.10,  # >10% absolute increase
    "cost_increase": 0.20,  # >20% relative increase
    "satisfaction_drop": 0.15,  # >15% drop in positive satisfaction
    "friction_spike": 0.25,  # >25% increase in any friction category
    "interruption_increase": 0.15,  # >15% increase in user interruptions
}


def detect_regressions(current: dict, previous: dict) -> list[dict]:
    """Compare metrics between current and previous periods.

    Returns a list of regression/improvement flags, each with:
    - metric: what changed
    - direction: "improved" or "degraded"
    - magnitude: percentage change
    - current_value: current period value
    - previous_value: previous period value
    - severity: "low", "medium", "high"
    """
    if not current or not previous:
        return []

    regressions: list[dict] = []

    # Error rate comparison
    current_errors = current.get("errors", {})
    previous_errors = previous.get("errors", {})
    curr_error_rate = float(current_errors.get("error_rate", 0))
    prev_error_rate = float(previous_errors.get("error_rate", 0))

    if prev_error_rate > 0:
        error_change = curr_error_rate - prev_error_rate
        if abs(error_change) > THRESHOLDS["error_rate_increase"]:
            regressions.append(
                {
                    "metric": "error_rate",
                    "direction": "degraded" if error_change > 0 else "improved",
                    "magnitude": round(error_change * 100, 1),
                    "current_value": round(curr_error_rate * 100, 1),
                    "previous_value": round(prev_error_rate * 100, 1),
                    "severity": "high" if abs(error_change) > 0.2 else "medium",
                }
            )

    # Cost comparison
    current_cost = current.get("cost", {})
    previous_cost = previous.get("cost", {})
    curr_total_cost = float(current_cost.get("total_cost_usd", 0))
    prev_total_cost = float(previous_cost.get("total_cost_usd", 0))

    if prev_total_cost > 0:
        cost_change_pct = (curr_total_cost - prev_total_cost) / prev_total_cost
        if abs(cost_change_pct) > THRESHOLDS["cost_increase"]:
            regressions.append(
                {
                    "metric": "total_cost",
                    "direction": "degraded" if cost_change_pct > 0 else "improved",
                    "magnitude": round(cost_change_pct * 100, 1),
                    "current_value": round(curr_total_cost, 4),
                    "previous_value": round(prev_total_cost, 4),
                    "severity": "medium" if abs(cost_change_pct) < 0.5 else "high",
                }
            )

    # Cost per session comparison
    curr_avg_cost = float(current_cost.get("avg_cost_per_session", 0))
    prev_avg_cost = float(previous_cost.get("avg_cost_per_session", 0))

    if prev_avg_cost > 0:
        avg_cost_change = (curr_avg_cost - prev_avg_cost) / prev_avg_cost
        if abs(avg_cost_change) > THRESHOLDS["cost_increase"]:
            regressions.append(
                {
                    "metric": "avg_cost_per_session",
                    "direction": "degraded" if avg_cost_change > 0 else "improved",
                    "magnitude": round(avg_cost_change * 100, 1),
                    "current_value": round(curr_avg_cost, 4),
                    "previous_value": round(prev_avg_cost, 4),
                    "severity": "low",
                }
            )

    # Cache efficiency comparison
    curr_cache = float(current_cost.get("cache_efficiency_ratio", 0))
    prev_cache = float(previous_cost.get("cache_efficiency_ratio", 0))

    if prev_cache > 0:
        cache_change = curr_cache - prev_cache
        if abs(cache_change) > 0.10:  # >10% absolute change in cache efficiency
            regressions.append(
                {
                    "metric": "cache_efficiency",
                    "direction": "improved" if cache_change > 0 else "degraded",
                    "magnitude": round(cache_change * 100, 1),
                    "current_value": round(curr_cache * 100, 1),
                    "previous_value": round(prev_cache * 100, 1),
                    "severity": "low",
                }
            )

    # Interruption rate comparison
    current_interruptions = current.get("interruptions", {})
    previous_interruptions = previous.get("interruptions", {})
    curr_interrupts = int(current_interruptions.get("user_interruptions", 0))
    prev_interrupts = int(previous_interruptions.get("user_interruptions", 0))
    curr_total_stops = int(current_interruptions.get("total_stops", 0))
    prev_total_stops = int(previous_interruptions.get("total_stops", 0))

    if prev_total_stops > 0 and curr_total_stops > 0:
        curr_interrupt_rate = curr_interrupts / curr_total_stops
        prev_interrupt_rate = prev_interrupts / prev_total_stops
        interrupt_change = curr_interrupt_rate - prev_interrupt_rate
        if abs(interrupt_change) > THRESHOLDS["interruption_increase"]:
            regressions.append(
                {
                    "metric": "user_interruption_rate",
                    "direction": "degraded" if interrupt_change > 0 else "improved",
                    "magnitude": round(interrupt_change * 100, 1),
                    "current_value": round(curr_interrupt_rate * 100, 1),
                    "previous_value": round(prev_interrupt_rate * 100, 1),
                    "severity": "medium",
                }
            )

    # Session count change (informational, not a regression)
    curr_sessions = int(current.get("overview", {}).get("total_sessions", 0))
    prev_sessions = int(previous.get("overview", {}).get("total_sessions", 0))
    if prev_sessions > 0:
        session_change = (curr_sessions - prev_sessions) / prev_sessions
        if abs(session_change) > 0.3:  # >30% change in usage
            regressions.append(
                {
                    "metric": "session_count",
                    "direction": "improved" if session_change > 0 else "degraded",
                    "magnitude": round(session_change * 100, 1),
                    "current_value": curr_sessions,
                    "previous_value": prev_sessions,
                    "severity": "low",
                }
            )

    return regressions
