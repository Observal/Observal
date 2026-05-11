# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Session JSONL ingest service.

Receives raw JSONL transcript lines from IDE sessions, classifies each
line into an event type, and batch-inserts into the ``session_events`` table.

Classification dispatches strictly by IDE via
``services.session_parsers.ingest_classify.get_classifier`` -- there is no
default fallback.  Passing an unknown ``ide`` value raises ``KeyError``.
"""

import hashlib
import json
from dataclasses import dataclass

import structlog

from services.clickhouse import insert_session_events, query_existing_for_dedup, query_session_event_count
from services.secrets_redactor import redact_secrets
from services.session_parsers.ingest_classify import extract_timestamp, get_classifier, get_extra_rows

logger = structlog.get_logger(__name__)


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
    ide: str = "claude-code",
    lines: list[str] | None = None,
    start_offset: int = 0,
    total_credits: float | None = None,
    parent_session_id: str | None = None,
) -> IngestResult:
    """Parse, classify, and batch-insert JSONL transcript lines.

    Each string in *lines* is one raw JSONL line from an IDE session.
    Lines that fail to parse are counted as errors and skipped.
    ``continuation`` lines (empty API signals) are counted as skipped.

    Args:
        session_id:      Unique session identifier (UUID).
        project_id:      Project the session belongs to.
        user_id:         User who owns the session.
        agent_id:        Optional agent identifier.
        agent_version:   Optional agent version string.
        ide:             IDE name (e.g. ``"claude-code"``, ``"kiro"``).
        lines:           Raw JSONL strings to ingest.
        start_offset:    Line offset of the first item in *lines* within the
                         full session transcript.

    Returns:
        An :class:`IngestResult` with ``ingested``, ``skipped``, and
        ``errors`` counts.
    """
    ingested = 0
    skipped = 0
    errors = 0

    if not lines:
        # No JSONL lines -- still store any IDE-specific extra rows (e.g. Kiro credits).
        extra = get_extra_rows(ide, session_id, project_id, user_id, agent_id, agent_version, total_credits)
        if extra:
            await insert_session_events(extra)
        return IngestResult(ingested=0, skipped=0, errors=0)

    # Pre-check: fetch (existing_offsets, existing_hashes) for this batch range.
    max_batch_offset = start_offset + len(lines) - 1
    existing_offsets, existing_hashes = await query_existing_for_dedup(
        session_id, project_id, start_offset, max_batch_offset
    )

    rows: list[dict] = []
    classify_fn, preview_fn, tool_info_fn = get_classifier(ide)
    last_real_ts: str | None = None  # carry forward when a line has no timestamp

    for i, raw_line in enumerate(lines):
        line_offset = start_offset + i
        line_hash = hashlib.sha256(raw_line.encode("utf-8", errors="replace")).hexdigest()

        if line_offset in existing_offsets or line_hash in existing_hashes:
            skipped += 1
            continue

        try:
            parsed = json.loads(raw_line)
        except (json.JSONDecodeError, ValueError) as exc:
            logger.warning(
                "session_ingest_parse_error",
                session_id=session_id,
                line_offset=line_offset,
                error=str(exc),
            )
            errors += 1
            continue

        event_type = classify_fn(parsed)
        if event_type is None:
            skipped += 1
            continue

        redacted_line = redact_secrets(raw_line)
        preview = preview_fn(parsed, event_type)
        tool_name, tool_id = tool_info_fn(parsed)

        ts = extract_timestamp(ide, parsed)
        if ts is not None:
            last_real_ts = ts
        timestamp = ts if ts is not None else (last_real_ts if last_real_ts is not None else "2000-01-01 00:00:00.000")

        rows.append(
            {
                "session_id": session_id,
                "project_id": project_id,
                "user_id": user_id,
                "agent_id": agent_id,
                "agent_version": agent_version,
                "layer_hash": layer_hash,
                "ide": ide,
                "line_offset": line_offset,
                "line_hash": line_hash,
                "event_type": event_type,
                "timestamp": timestamp,
                "uuid": parsed.get("uuid"),
                "parent_uuid": parsed.get("parentUuid"),
                "tool_name": tool_name,
                "tool_id": tool_id,
                "content_preview": preview,
                "content_length": len(raw_line.encode()),
                "raw_line": redacted_line,
                "credits": 0.0,
                "parent_session_id": parent_session_id,
            }
        )
        ingested += 1

    if rows:
        await insert_session_events(rows)

    # Store any IDE-specific extra rows (e.g. Kiro credits summary row).
    extra = get_extra_rows(ide, session_id, project_id, user_id, agent_id, agent_version, total_credits)
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
    stored_count, stored_max_offset = await query_session_event_count(session_id, project_id)
    ok = stored_count == expected_line_count and stored_max_offset == expected_offset
    return IntegrityResult(
        ok=ok,
        stored_count=stored_count,
        stored_max_offset=stored_max_offset,
        expected_count=expected_line_count,
        expected_offset=expected_offset,
    )
