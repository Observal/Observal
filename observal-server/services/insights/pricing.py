"""Model pricing lookup and cost computation for Agent Insights."""

from __future__ import annotations

# Pricing per 1M tokens (USD)
# Keys: input, output, cache_read, cache_write
MODEL_PRICING: dict[str, dict[str, float]] = {
    # Claude 4.6 family
    "claude-opus-4-6-20250514": {"input": 15.00, "output": 75.00, "cache_read": 1.50, "cache_write": 18.75},
    "claude-sonnet-4-6-20250514": {"input": 3.00, "output": 15.00, "cache_read": 0.30, "cache_write": 3.75},
    # Claude 4.5 family
    "claude-sonnet-4-5-20250514": {"input": 3.00, "output": 15.00, "cache_read": 0.30, "cache_write": 3.75},
    "claude-haiku-4-5-20251001": {"input": 0.80, "output": 4.00, "cache_read": 0.08, "cache_write": 1.00},
    # Claude 3.5 family (legacy)
    "claude-3-5-sonnet-20241022": {"input": 3.00, "output": 15.00, "cache_read": 0.30, "cache_write": 3.75},
    "claude-3-5-haiku-20241022": {"input": 0.80, "output": 4.00, "cache_read": 0.08, "cache_write": 1.00},
    # GPT-4o family
    "gpt-4o": {"input": 2.50, "output": 10.00, "cache_read": 1.25, "cache_write": 2.50},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60, "cache_read": 0.075, "cache_write": 0.15},
    # Gemini
    "gemini-2.5-pro": {"input": 1.25, "output": 10.00, "cache_read": 0.315, "cache_write": 1.25},
    "gemini-2.5-flash": {"input": 0.15, "output": 0.60, "cache_read": 0.0375, "cache_write": 0.15},
    # Fallback (Sonnet pricing)
    "_default": {"input": 3.00, "output": 15.00, "cache_read": 0.30, "cache_write": 3.75},
}


def get_pricing(model_name: str) -> dict[str, float]:
    """Look up pricing for a model, with fuzzy matching.

    Strips common prefixes (us., eu., bedrock ARN suffixes) and tries
    progressively shorter matches before falling back to _default.
    """
    if not model_name:
        return MODEL_PRICING["_default"]

    # Direct match
    if model_name in MODEL_PRICING:
        return MODEL_PRICING[model_name]

    # Strip common cloud prefixes/suffixes
    normalized = model_name
    for prefix in ("us.", "eu.", "ap.", "us.anthropic.", "eu.anthropic.", "anthropic."):
        if normalized.startswith(prefix):
            normalized = normalized[len(prefix) :]
            break

    # Strip Bedrock version suffixes like ":0", "-v1:0"
    if ":" in normalized:
        normalized = normalized.split(":")[0]
    if normalized.endswith("-v1"):
        normalized = normalized[:-3]

    # Try normalized
    if normalized in MODEL_PRICING:
        return MODEL_PRICING[normalized]

    # Try substring match (model ID embedded in longer string)
    for key in MODEL_PRICING:
        if key == "_default":
            continue
        if key in normalized or normalized in key:
            return MODEL_PRICING[key]

    return MODEL_PRICING["_default"]


def compute_session_cost(
    input_tokens: int,
    output_tokens: int,
    cache_read: int,
    cache_write: int,
    model: str,
) -> float:
    """Compute cost in USD for a single session's token usage."""
    pricing = get_pricing(model)
    cost = (
        (input_tokens / 1_000_000) * pricing["input"]
        + (output_tokens / 1_000_000) * pricing["output"]
        + (cache_read / 1_000_000) * pricing["cache_read"]
        + (cache_write / 1_000_000) * pricing["cache_write"]
    )
    return round(cost, 6)


def compute_cost_summary(sessions: list[dict]) -> dict:
    """Compute aggregate cost metrics from per-session token data.

    Each session dict should have: input_tokens, output_tokens,
    cache_read, cache_write, model, session_id.
    """
    if not sessions:
        return {
            "total_cost_usd": 0.0,
            "avg_cost_per_session": 0.0,
            "p50_session_cost": 0.0,
            "p90_session_cost": 0.0,
            "p99_session_cost": 0.0,
            "cache_efficiency_ratio": 0.0,
            "cost_by_model": [],
        }

    session_costs: list[float] = []
    model_costs: dict[str, float] = {}
    total_input = 0
    total_cache_read = 0
    total_cache_write = 0

    for s in sessions:
        inp = int(s.get("input_tokens") or 0)
        out = int(s.get("output_tokens") or 0)
        cr = int(s.get("cache_read") or 0)
        cw = int(s.get("cache_write") or 0)
        model = s.get("model") or ""

        cost = compute_session_cost(inp, out, cr, cw, model)
        session_costs.append(cost)

        model_key = model or "unknown"
        model_costs[model_key] = model_costs.get(model_key, 0.0) + cost

        total_input += inp
        total_cache_read += cr
        total_cache_write += cw

    total_cost = sum(session_costs)
    sorted_costs = sorted(session_costs)
    n = len(sorted_costs)

    # Cache efficiency: how much of total "input" came from cache reads
    total_billable_input = total_input + total_cache_read + total_cache_write
    cache_efficiency = round(total_cache_read / total_billable_input, 4) if total_billable_input > 0 else 0.0

    # Percentiles
    p50 = sorted_costs[n // 2] if n > 0 else 0.0
    p90 = sorted_costs[int(n * 0.9)] if n > 1 else sorted_costs[-1] if n else 0.0
    p99 = sorted_costs[int(n * 0.99)] if n > 1 else sorted_costs[-1] if n else 0.0

    # Most expensive model
    most_expensive_model = max(model_costs, key=model_costs.get) if model_costs else "unknown"

    cost_by_model = [
        {"model": m, "total_cost_usd": round(c, 4)} for m, c in sorted(model_costs.items(), key=lambda x: -x[1])
    ]

    return {
        "total_cost_usd": round(total_cost, 4),
        "avg_cost_per_session": round(total_cost / n, 4) if n else 0.0,
        "p50_session_cost": round(p50, 4),
        "p90_session_cost": round(p90, 4),
        "p99_session_cost": round(p99, 4),
        "cache_efficiency_ratio": cache_efficiency,
        "most_expensive_model": most_expensive_model,
        "cost_by_model": cost_by_model,
    }
