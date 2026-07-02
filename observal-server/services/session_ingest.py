# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Session JSONL ingest service.

Receives raw JSONL transcript lines from harness sessions, classifies each
line into an event type, and batch-inserts into the ``session_events`` table.

Classification dispatches strictly by harness via
``services.session_parsers.ingest_classify.get_classifier`` -- there is no
default fallback.  Passing an unknown ``harness`` value raises ``KeyError``.
"""

import uuid as _uuid
from collections.abc import Callable
from dataclasses import dataclass

import orjson
import xxhash
from loguru import logger as optic

from services.clickhouse import insert_session_events, query_existing_for_dedup, query_session_event_count
from services.secrets_redactor import redact_secrets
from services.session_parsers.ingest_classify import extract_timestamp, get_classifier, get_extra_rows

# ---------------------------------------------------------------------------
# Per-harness token usage extraction (dispatch pattern)
# ---------------------------------------------------------------------------


def _usage_claude_code(parsed: dict) -> dict:
    """Claude Code / Cursor / Kiro: usage.input_tokens, usage.output_tokens, etc."""
    msg = parsed.get("message", {})
    usage = msg.get("usage") or {}
    return {
        "input_tokens": int(usage.get("input_tokens") or 0),
        "output_tokens": int(usage.get("output_tokens") or 0),
        "cache_read_tokens": int(usage.get("cache_read_input_tokens") or 0),
        "cache_write_tokens": int(usage.get("cache_creation_input_tokens") or 0),
        "model": str(msg.get("model") or parsed.get("model") or ""),
    }


def _usage_pi(parsed: dict) -> dict:
    """Pi: usage.input, usage.output, usage.cacheRead, usage.cacheWrite."""
    msg = parsed.get("message", {})
    usage = msg.get("usage") or {}
    return {
        "input_tokens": int(usage.get("input") or 0),
        "output_tokens": int(usage.get("output") or 0),
        "cache_read_tokens": int(usage.get("cacheRead") or 0),
        "cache_write_tokens": int(usage.get("cacheWrite") or 0),
        "model": str(msg.get("model") or ""),
    }


def _usage_antigravity(parsed: dict) -> dict:
    """Antigravity: no token counts in transcript format."""
    return {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
        "model": "",
    }


def _usage_codex(parsed: dict) -> dict:
    """Codex: event_msg/token_count has payload.info.total_token_usage."""
    payload = parsed.get("payload", {})
    if not isinstance(payload, dict):
        return {"input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0, "cache_write_tokens": 0, "model": ""}
    info = payload.get("info", {})
    if not isinstance(info, dict):
        info = {}
    usage = info.get("last_token_usage") or info.get("total_token_usage") or {}
    return {
        "input_tokens": int(usage.get("input_tokens") or 0),
        "output_tokens": int(usage.get("output_tokens") or 0),
        "cache_read_tokens": int(usage.get("cached_input_tokens") or 0),
        "cache_write_tokens": 0,
        "model": "",
    }


def _usage_copilot_cli(parsed: dict) -> dict:
    """Copilot CLI: tokens are in assistant.message data or assistant.usage events.

    Copilot CLI v1.0.59+ uses flat format:
      {"type": "assistant.message", "data": {"outputTokens": N, "model": "..."}, ...}
    Older/SDK format uses envelope:
      {"agentId": "...", "ts": "...", "event": {"type": "assistant.usage", "data": {...}}}
    """
    # Try flat format first (Copilot CLI v1.0.59+)
    data = parsed.get("data", {})
    if isinstance(data, dict) and (data.get("outputTokens") or data.get("inputTokens")):
        return {
            "input_tokens": int(data.get("inputTokens") or 0),
            "output_tokens": int(data.get("outputTokens") or 0),
            "cache_read_tokens": int(data.get("cacheReadTokens") or 0),
            "cache_write_tokens": int(data.get("cacheWriteTokens") or 0),
            "model": str(data.get("model") or ""),
        }

    # Try envelope format (older/SDK)
    event = parsed.get("event", {})
    if isinstance(event, dict):
        edata = event.get("data", {})
        if isinstance(edata, dict) and (edata.get("outputTokens") or edata.get("inputTokens")):
            return {
                "input_tokens": int(edata.get("inputTokens") or 0),
                "output_tokens": int(edata.get("outputTokens") or 0),
                "cache_read_tokens": int(edata.get("cacheReadTokens") or 0),
                "cache_write_tokens": int(edata.get("cacheWriteTokens") or 0),
                "model": str(edata.get("model") or ""),
            }

    return {"input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0, "cache_write_tokens": 0, "model": ""}


_UsageFn = Callable[[dict], dict]

_USAGE_EXTRACTORS: dict[str, _UsageFn] = {
    "claude-code": _usage_claude_code,
    "codex": _usage_codex,
    "kiro": _usage_claude_code,
    "cursor": _usage_claude_code,
    "pi": _usage_pi,
    "copilot-cli": _usage_copilot_cli,
    "copilot": _usage_copilot_cli,
    "opencode": _usage_claude_code,
    "antigravity": _usage_antigravity,
}


# ---------------------------------------------------------------------------
# Per-harness UUID extraction (dispatch pattern)
# ---------------------------------------------------------------------------


def _uuid_default(parsed: dict) -> tuple[str | None, str | None]:
    """Claude Code / Kiro / Cursor: uuid, parentUuid."""
    return parsed.get("uuid"), parsed.get("parentUuid")


def _uuid_pi(parsed: dict) -> tuple[str | None, str | None]:
    """Pi: id, parentId (at entry level)."""
    return parsed.get("id"), parsed.get("parentId")


def _uuid_antigravity(parsed: dict) -> tuple[str | None, str | None]:
    """Antigravity: use step_index as a pseudo-UUID (no native UUIDs)."""
    step = parsed.get("step_index")
    if step is not None:
        return str(step), None
    return None, None


_UuidFn = Callable[[dict], "tuple[str | None, str | None]"]

_UUID_EXTRACTORS: dict[str, _UuidFn] = {
    "claude-code": _uuid_default,
    "kiro": _uuid_default,
    "cursor": _uuid_default,
    "opencode": _uuid_default,
    "pi": _uuid_pi,
    "antigravity": _uuid_antigravity,
}


def _extract_usage_tokens(parsed: dict, harness: str = "claude-code") -> dict:
    """Extract input/output/cache token counts and model from a parsed JSONL line.

    Dispatches to per-harness extractor. Falls back to Claude Code format.
    """
    extractor = _USAGE_EXTRACTORS.get(harness, _usage_claude_code)
    return extractor(parsed)


def _extract_uuid(parsed: dict, harness: str = "claude-code") -> tuple[str | None, str | None]:
    """Extract (uuid, parent_uuid) from a parsed JSONL line.

    Dispatches to per-harness extractor. Falls back to Claude Code format.
    """
    extractor = _UUID_EXTRACTORS.get(harness, _uuid_default)
    return extractor(parsed)


# ---------------------------------------------------------------------------
# Agent attribution resolution
# ---------------------------------------------------------------------------


def _is_uuid(value: str) -> bool:
    """Return True if *value* is a valid UUID string."""
    try:
        _uuid.UUID(value)
        return True
    except (ValueError, AttributeError):
        return False


async def _resolve_agent_id(agent_id: str | None) -> str | None:
    """Resolve an agent name to its UUID if it isn't one already.

    Uses a Redis cache (5min TTL) to avoid hitting Postgres on every
    ingest push. At 500 active sessions with named agents, this saves
    ~500 Postgres queries/sec.

    Returns the original value unchanged if it is already a UUID, None,
    or if the name cannot be resolved.
    """
    if not agent_id:
        return agent_id
    if _is_uuid(agent_id):
        return agent_id

    # Check Redis cache first
    from services.redis import get_redis

    cache_key = f"agent_name_resolve:{agent_id}"
    redis = None
    try:
        redis = get_redis()
        cached = await redis.get(cache_key)
        if cached is not None:
            return cached if cached != "__none__" else agent_id
    except Exception as e:
        optic.trace("Redis cache read failed for agent resolution: {}", e)

    # Import lazily to avoid circular deps at module level
    from sqlalchemy import select

    from database import async_session
    from models.agent import Agent

    resolved = None
    try:
        async with async_session() as db:
            stmt = select(Agent.id).where(Agent.name == agent_id).limit(1)
            result = await db.execute(stmt)
            row = result.scalar_one_or_none()
            if row:
                resolved = str(row)
                optic.debug("resolved agent name '{}' to UUID {}", agent_id, resolved)
    except Exception as e:
        optic.warning("agent_id resolution failed: {}", e)

    # Cache result in Redis (5 min TTL)
    if redis:
        try:
            await redis.setex(cache_key, 300, resolved or "__none__")
        except Exception as e:
            optic.trace("Redis cache write failed for agent resolution: {}", e)

    return resolved if resolved else agent_id


async def _resolve_agent_version(agent_id: str | None, agent_version: str | None) -> str | None:
    """Resolve the mutable latest alias to the agent's current version."""
    if agent_version != "latest" or not agent_id or not _is_uuid(agent_id):
        return agent_version

    from services.redis import get_redis

    cache_key = f"agent_version_resolve:{agent_id}:latest"
    redis = None
    try:
        redis = get_redis()
        cached = await redis.get(cache_key)
        if cached is not None:
            return cached if cached != "__none__" else agent_version
    except Exception as e:
        optic.trace("Redis cache read failed for agent version resolution: {}", e)

    from sqlalchemy import select

    from database import async_session
    from models.agent import Agent, AgentVersion

    resolved = None
    try:
        async with async_session() as db:
            stmt = (
                select(AgentVersion.version)
                .join(Agent, Agent.latest_version_id == AgentVersion.id)
                .where(Agent.id == _uuid.UUID(agent_id))
                .limit(1)
            )
            result = await db.execute(stmt)
            resolved = result.scalar_one_or_none()
    except Exception as e:
        optic.warning("agent_version resolution failed: {}", e)

    if redis:
        try:
            await redis.setex(cache_key, 300, resolved or "__none__")
        except Exception as e:
            optic.trace("Redis cache write failed for agent version resolution: {}", e)

    return resolved if resolved else agent_version


@dataclass
class IngestResult:
    ingested: int
    skipped: int
    errors: int


@dataclass
class IntegrityResult:
    ok: bool
    stored_count: int
    stored_max_offset: int
    expected_count: int
    expected_offset: int


async def ingest_session_lines(
    session_id: str,
    project_id: str,
    user_id: str,
    agent_id: str | None,
    agent_version: str | None,
    layer_hash: str | None = None,
    harness: str = "claude-code",
    lines: list[str] | None = None,
    start_offset: int = 0,
    total_credits: float | None = None,
    parent_session_id: str | None = None,
) -> IngestResult:
    """Parse, classify, and batch-insert JSONL transcript lines.

    Each string in *lines* is one raw JSONL line from an harness session.
    Lines that fail to parse are counted as errors and skipped.
    ``continuation`` lines (empty API signals) are counted as skipped.

    Args:
        session_id:      Unique session identifier (UUID).
        project_id:      Project the session belongs to.
        user_id:         User who owns the session.
        agent_id:        Optional agent identifier.
        agent_version:   Optional agent version string.
        harness:             harness name (e.g. ``"claude-code"``, ``"kiro"``).
        lines:           Raw JSONL strings to ingest.
        start_offset:    Line offset of the first item in *lines* within the
                         full session transcript.

    Returns:
        An :class:`IngestResult` with ``ingested``, ``skipped``, and
        ``errors`` counts.
    """
    optic.trace("ingesting session lines for session {}", session_id)

    # Normalize agent_id and agent_version so downstream queries match canonical versions.
    agent_id = await _resolve_agent_id(agent_id)
    agent_version = await _resolve_agent_version(agent_id, agent_version)

    ingested = 0
    skipped = 0
    errors = 0

    if not lines:
        # No JSONL lines -- still store any harness-specific extra rows (e.g. Kiro credits).
        extra = get_extra_rows(harness, session_id, project_id, user_id, agent_id, agent_version, total_credits)
        if extra:
            await insert_session_events(extra)
        optic.debug("no lines to ingest for session {}", session_id)
        return IngestResult(ingested=0, skipped=0, errors=0)

    # Pre-check: fetch (existing_offsets, existing_hashes) for this batch range.
    # Skip the expensive ClickHouse FINAL query on first push (start_offset=0)
    # when we haven't seen this session before. Use a Redis flag to detect retries.
    max_batch_offset = start_offset + len(lines) - 1
    if start_offset == 0:
        from services.redis import get_redis

        _flag_key = f"session_ingested:{session_id}"
        try:
            _redis = get_redis()
            _already_seen = await _redis.exists(_flag_key)
        except Exception as e:
            optic.trace("Redis flag check failed, falling back to dedup query: {}", e)
            _already_seen = True  # Fail safe: do the dedup check
        if not _already_seen:
            existing_offsets, existing_hashes = frozenset(), frozenset()
            try:
                await _redis.setex(_flag_key, 3600, "1")
            except Exception as e:
                optic.trace("Redis flag write failed: {}", e)
        else:
            existing_offsets, existing_hashes = await query_existing_for_dedup(
                session_id, project_id, start_offset, max_batch_offset
            )
    else:
        existing_offsets, existing_hashes = await query_existing_for_dedup(
            session_id, project_id, start_offset, max_batch_offset
        )

    rows: list[dict] = []
    classify_fn, preview_fn, tool_info_fn = get_classifier(harness)
    last_real_ts: str | None = None  # carry forward when a line has no timestamp

    for i, raw_line in enumerate(lines):
        line_offset = start_offset + i
        line_hash = xxhash.xxh128(raw_line.encode("utf-8", errors="replace")).hexdigest()

        if line_offset in existing_offsets or line_hash in existing_hashes:
            skipped += 1
            continue

        try:
            parsed = orjson.loads(raw_line)
        except (orjson.JSONDecodeError, ValueError) as exc:
            optic.warning(
                "session_ingest_parse_error: session={}, offset={}, error={}, line_preview={}",
                session_id,
                line_offset,
                str(exc),
                repr(raw_line[:200]),
            )
            errors += 1
            continue

        event_type = classify_fn(parsed)
        if event_type is None:
            skipped += 1
            continue

        redacted_line = redact_secrets(raw_line)
        preview = redact_secrets(preview_fn(parsed, event_type))
        tool_name, tool_id = tool_info_fn(parsed)
        uuid, parent_uuid = _extract_uuid(parsed, harness)

        ts = extract_timestamp(harness, parsed)
        if ts is not None:
            last_real_ts = ts
        if ts is not None:
            timestamp = ts
        elif last_real_ts is not None:
            timestamp = last_real_ts
        else:
            from datetime import UTC, datetime

            timestamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

        rows.append(
            {
                "session_id": session_id,
                "project_id": project_id,
                "user_id": user_id,
                "agent_id": agent_id,
                "agent_version": agent_version,
                "layer_hash": layer_hash,
                "harness": harness,
                "line_offset": line_offset,
                "line_hash": line_hash,
                "event_type": event_type,
                "timestamp": timestamp,
                "uuid": uuid,
                "parent_uuid": parent_uuid,
                "tool_name": tool_name,
                "tool_id": tool_id,
                "content_preview": preview,
                "content_length": len(raw_line.encode()),
                "raw_line": redacted_line,
                "credits": 0.0,
                "parent_session_id": parent_session_id,
                # Token counts from the JSONL line (harness-specific field names).
                **_extract_usage_tokens(parsed, harness),
            }
        )
        ingested += 1

    if rows:
        await insert_session_events(rows)
        optic.debug(
            "inserted {} rows into session_events for session={}",
            len(rows),
            session_id,
        )

    # Store any harness-specific extra rows (e.g. Kiro credits summary row).
    extra = get_extra_rows(harness, session_id, project_id, user_id, agent_id, agent_version, total_credits)
    if extra:
        await insert_session_events(extra)

    return IngestResult(ingested=ingested, skipped=skipped, errors=errors)


async def check_session_integrity(
    session_id: str,
    project_id: str,
    expected_line_count: int,
    expected_offset: int,
) -> IntegrityResult:
    """Verify that stored event counts match what the client sent.

    Queries ``SELECT count(), max(line_offset)`` for the session and
    compares against the expected values.
    """
    optic.trace("ingesting session lines for session {}", session_id)
    stored_count, stored_max_offset = await query_session_event_count(session_id, project_id)
    ok = stored_count == expected_line_count and stored_max_offset == expected_offset
    return IntegrityResult(
        ok=ok,
        stored_count=stored_count,
        stored_max_offset=stored_max_offset,
        expected_count=expected_line_count,
        expected_offset=expected_offset,
    )
