"""Session file reconciliation — parse Claude Code JSONL session files
and enrich ClickHouse telemetry with per-turn token counts, model info,
stop reasons, and conversation structure.

This module is invoked either via:
  1. POST /api/v1/telemetry/reconcile (server endpoint)
  2. `observal reconcile <session-id>` (CLI command, reads local file, POSTs enrichment)
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

import structlog

logger = structlog.get_logger(__name__)


@dataclass
class TurnMetrics:
    """Per-turn metrics extracted from a session JSONL."""

    turn_index: int
    role: str  # "assistant" or "user"
    model: str | None = None
    stop_reason: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    service_tier: str | None = None
    has_thinking: bool = False
    thinking_token_estimate: int = 0
    tool_uses: list[str] = field(default_factory=list)
    tool_results: list[str] = field(default_factory=list)


@dataclass
class SessionEnrichment:
    """Full enrichment data for a session, ready to merge into ClickHouse."""

    session_id: str
    turns: list[TurnMetrics] = field(default_factory=list)
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cache_read_tokens: int = 0
    total_cache_creation_tokens: int = 0
    models_used: list[str] = field(default_factory=list)
    primary_model: str | None = None
    total_cost_usd: float = 0.0
    service_tier: str | None = None
    conversation_turns: int = 0
    tool_use_count: int = 0
    thinking_turns: int = 0
    stop_reasons: dict[str, int] = field(default_factory=dict)
    completeness_score: float = 1.0


def parse_claude_code_jsonl(lines: list[str], session_id: str) -> SessionEnrichment:
    """Parse Claude Code session JSONL lines into enrichment data.

    Claude Code JSONL format:
    - Each line is a JSON object with a "type" field
    - Types: "assistant", "user", "system", "attachment", "last-prompt"
    - Assistant records have: message.content[], usage{}, model, stop_reason
    - User records have: message.content[] (tool_result blocks)
    """
    enrichment = SessionEnrichment(session_id=session_id)
    models_seen: set[str] = set()
    turn_index = 0

    for line in lines:
        line = line.strip()
        if not line:
            continue

        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue

        record_type = record.get("type")

        if record_type == "assistant":
            turn_index += 1
            turn = _parse_assistant_record(record, turn_index)
            enrichment.turns.append(turn)

            # Accumulate totals
            enrichment.total_input_tokens += turn.input_tokens
            enrichment.total_output_tokens += turn.output_tokens
            enrichment.total_cache_read_tokens += turn.cache_read_tokens
            enrichment.total_cache_creation_tokens += turn.cache_creation_tokens

            if turn.model:
                models_seen.add(turn.model)

            if turn.stop_reason:
                enrichment.stop_reasons[turn.stop_reason] = (
                    enrichment.stop_reasons.get(turn.stop_reason, 0) + 1
                )

            if turn.has_thinking:
                enrichment.thinking_turns += 1

            enrichment.tool_use_count += len(turn.tool_uses)

        elif record_type == "user":
            # Count tool results in user messages
            content = record.get("message", {}).get("content", [])
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "tool_result":
                        pass  # Already tracked via assistant tool_use

    enrichment.conversation_turns = turn_index
    enrichment.models_used = sorted(models_seen)
    enrichment.primary_model = enrichment.models_used[0] if enrichment.models_used else None
    enrichment.service_tier = enrichment.turns[-1].service_tier if enrichment.turns else None

    # Compute cost
    from services.insights.pricing import compute_session_cost

    enrichment.total_cost_usd = compute_session_cost(
        input_tokens=enrichment.total_input_tokens,
        output_tokens=enrichment.total_output_tokens,
        cache_read_tokens=enrichment.total_cache_read_tokens,
        cache_creation_tokens=enrichment.total_cache_creation_tokens,
        model=enrichment.primary_model or "claude-sonnet-4-6-20250514",
    )

    return enrichment


def _parse_assistant_record(record: dict, turn_index: int) -> TurnMetrics:
    """Extract metrics from a single assistant JSONL record."""
    usage = record.get("usage", {})
    message = record.get("message", {})
    content = message.get("content", [])

    # Extract tool uses and thinking blocks
    tool_uses: list[str] = []
    has_thinking = False
    thinking_estimate = 0

    if isinstance(content, list):
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use":
                tool_uses.append(block.get("name", "unknown"))
            elif block.get("type") == "thinking":
                has_thinking = True
                thinking_text = block.get("thinking", "")
                # Rough token estimate: 4 chars per token
                thinking_estimate += len(thinking_text) // 4

    return TurnMetrics(
        turn_index=turn_index,
        role="assistant",
        model=record.get("model") or message.get("model"),
        stop_reason=record.get("stop_reason") or message.get("stop_reason"),
        input_tokens=usage.get("input_tokens", 0),
        output_tokens=usage.get("output_tokens", 0),
        cache_read_tokens=usage.get("cache_read_input_tokens", 0),
        cache_creation_tokens=usage.get("cache_creation_input_tokens", 0),
        service_tier=usage.get("service_tier"),
        has_thinking=has_thinking,
        thinking_token_estimate=thinking_estimate,
        tool_uses=tool_uses,
        tool_results=[],
    )


def enrichment_to_dict(enrichment: SessionEnrichment) -> dict:
    """Convert enrichment to JSON-serializable dict for API transport."""
    return {
        "session_id": enrichment.session_id,
        "total_input_tokens": enrichment.total_input_tokens,
        "total_output_tokens": enrichment.total_output_tokens,
        "total_cache_read_tokens": enrichment.total_cache_read_tokens,
        "total_cache_creation_tokens": enrichment.total_cache_creation_tokens,
        "models_used": enrichment.models_used,
        "primary_model": enrichment.primary_model,
        "total_cost_usd": enrichment.total_cost_usd,
        "service_tier": enrichment.service_tier,
        "conversation_turns": enrichment.conversation_turns,
        "tool_use_count": enrichment.tool_use_count,
        "thinking_turns": enrichment.thinking_turns,
        "stop_reasons": enrichment.stop_reasons,
        "completeness_score": enrichment.completeness_score,
        "per_turn": [
            {
                "turn_index": t.turn_index,
                "model": t.model,
                "stop_reason": t.stop_reason,
                "input_tokens": t.input_tokens,
                "output_tokens": t.output_tokens,
                "cache_read_tokens": t.cache_read_tokens,
                "cache_creation_tokens": t.cache_creation_tokens,
                "has_thinking": t.has_thinking,
                "tool_uses": t.tool_uses,
            }
            for t in enrichment.turns
        ],
    }
