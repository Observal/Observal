# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: LicenseRef-Observal-Enterprise

"""Deterministic per-session metadata extraction from raw JSONL transcripts.

Reads session_events.raw_line from ClickHouse and computes rich stats
per session: lines added/removed, git commits, languages, tool errors,
response times, interruptions, file modifications, subagent/MCP usage,
message timestamps, and more.

Modeled after the pi /insights extension's extractSessionStats and
buildSessionMeta functions, adapted for cross-user server-side execution.
"""

from __future__ import annotations

import json
import os
from datetime import datetime

import structlog

from ._deps import get_query

logger = structlog.get_logger(__name__)

# Language detection by file extension
EXTENSION_TO_LANGUAGE: dict[str, str] = {
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".py": "Python",
    ".rb": "Ruby",
    ".go": "Go",
    ".rs": "Rust",
    ".java": "Java",
    ".md": "Markdown",
    ".json": "JSON",
    ".yaml": "YAML",
    ".yml": "YAML",
    ".sh": "Shell",
    ".css": "CSS",
    ".html": "HTML",
    ".c": "C",
    ".cpp": "C++",
    ".cs": "C#",
    ".kt": "Kotlin",
    ".swift": "Swift",
}


def _ext(path: str) -> str:
    """Get file extension from path."""
    _, ext = os.path.splitext(path)
    return ext.lower()


def _count_newlines(s: str) -> int:
    return s.count("\n")


def _extract_text_from_content(content) -> str:
    """Extract plain text from message content (string or list of blocks)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
        return " ".join(parts)
    return str(content) if content else ""


def extract_session_meta(session_id: str, raw_lines: list[str]) -> dict:
    """Extract deterministic metadata from raw JSONL lines for one session.

    Returns a dict with all computable stats (no LLM needed).
    """
    tool_counts: dict[str, int] = {}
    languages: dict[str, int] = {}
    tool_error_categories: dict[str, int] = {}
    files_modified: set[str] = set()
    user_response_times: list[float] = []
    message_hours: list[int] = []
    user_message_timestamps: list[str] = []

    git_commits = 0
    git_pushes = 0
    input_tokens = 0
    output_tokens = 0
    cache_read_tokens = 0
    cache_write_tokens = 0
    total_cost = 0.0
    user_interruptions = 0
    tool_errors = 0
    uses_subagent = False
    uses_mcp = False
    lines_added = 0
    lines_removed = 0
    user_message_count = 0
    assistant_message_count = 0
    first_prompt = ""
    total_messages = 0

    last_assistant_ts: float | None = None
    start_time: str | None = None
    end_time: str | None = None
    project_path = ""
    seen_tool_ids: set[str] = set()

    for raw in raw_lines:
        if not raw.strip():
            continue
        try:
            entry = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            continue

        entry_type = entry.get("type", "")
        ts_str = entry.get("timestamp", "")

        # Track time range
        if ts_str:
            if start_time is None or ts_str < start_time:
                start_time = ts_str
            if end_time is None or ts_str > end_time:
                end_time = ts_str

        # Session header
        if entry_type == "session":
            project_path = entry.get("cwd", "")
            continue

        if entry_type != "message":
            continue

        msg = entry.get("message", {})
        if not isinstance(msg, dict):
            continue

        role = msg.get("role", "")
        total_messages += 1

        # Parse timestamp for response time tracking
        msg_ts: float | None = None
        if ts_str:
            try:
                dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                msg_ts = dt.timestamp()
            except (ValueError, TypeError):
                pass

        # ── Assistant message ──
        if role == "assistant":
            assistant_message_count += 1
            if msg_ts:
                last_assistant_ts = msg_ts

            # Token usage
            usage = msg.get("usage", {})
            if usage:
                input_tokens += int(usage.get("input", 0) or 0)
                output_tokens += int(usage.get("output", 0) or 0)
                cache_read_tokens += int(usage.get("cacheRead", 0) or 0)
                cache_write_tokens += int(usage.get("cacheWrite", 0) or 0)
                cost = usage.get("cost", {})
                if isinstance(cost, dict) and cost.get("total"):
                    total_cost += float(cost["total"])

            # Tool calls in content
            content = msg.get("content", [])
            if isinstance(content, list):
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    if block.get("type") != "toolCall":
                        continue

                    tool_name = block.get("name", "")
                    tool_id = block.get("id", "")

                    if tool_id and tool_id in seen_tool_ids:
                        continue
                    if tool_id:
                        seen_tool_ids.add(tool_id)

                    tool_counts[tool_name] = tool_counts.get(tool_name, 0) + 1

                    if tool_name == "subagent":
                        uses_subagent = True
                    if tool_name.startswith("mcp__") or tool_name == "mcp":
                        uses_mcp = True

                    args = block.get("arguments", {})
                    if not isinstance(args, dict):
                        try:
                            args = json.loads(args) if isinstance(args, str) else {}
                        except (json.JSONDecodeError, TypeError):
                            args = {}

                    file_path = args.get("path", "") or args.get("file_path", "")

                    if file_path:
                        ext = _ext(file_path)
                        lang = EXTENSION_TO_LANGUAGE.get(ext)
                        if lang:
                            languages[lang] = languages.get(lang, 0) + 1

                    if tool_name == "write" and file_path:
                        files_modified.add(file_path)
                        content_str = args.get("content", "")
                        if isinstance(content_str, str):
                            lines_added += _count_newlines(content_str) + 1

                    if tool_name == "edit" and file_path:
                        files_modified.add(file_path)
                        edits = args.get("edits", [])
                        if isinstance(edits, list):
                            for e in edits:
                                if isinstance(e, dict):
                                    old = e.get("oldText", "") or e.get("old_string", "")
                                    new = e.get("newText", "") or e.get("new_string", "")
                                    if isinstance(old, str):
                                        lines_removed += _count_newlines(old) + 1
                                    if isinstance(new, str):
                                        lines_added += _count_newlines(new) + 1

                    if tool_name == "bash":
                        cmd = args.get("command", "")
                        if isinstance(cmd, str):
                            if "git commit" in cmd:
                                git_commits += 1
                            if "git push" in cmd:
                                git_pushes += 1

        # ── User message ──
        elif role == "user":
            content = msg.get("content", [])
            text = _extract_text_from_content(content)

            if text.strip():
                user_message_count += 1
                if not first_prompt:
                    first_prompt = text.strip()[:300]

                if "[Request interrupted by user" in text:
                    user_interruptions += 1

                if msg_ts:
                    try:
                        dt = datetime.fromtimestamp(msg_ts)
                        message_hours.append(dt.hour)
                        user_message_timestamps.append(dt.isoformat())
                    except (ValueError, OSError):
                        pass

                    if last_assistant_ts is not None:
                        gap_sec = msg_ts - last_assistant_ts
                        if 2 < gap_sec < 3600:
                            user_response_times.append(gap_sec)

        # ── Tool result ──
        elif role == "toolResult":
            is_error = msg.get("isError", False)
            if is_error:
                tool_errors += 1
                tool_name = msg.get("toolName", "other")
                # Categorize errors
                content = msg.get("content", [])
                error_text = _extract_text_from_content(content).lower()
                if "not found" in error_text or "no such file" in error_text:
                    cat = "file_not_found"
                elif "permission" in error_text:
                    cat = "permission_denied"
                elif "command failed" in error_text or "exit code" in error_text:
                    cat = "command_failed"
                elif "edit" in tool_name.lower() or "failed to apply" in error_text:
                    cat = "edit_failed"
                elif "reject" in error_text or "user" in error_text:
                    cat = "user_rejected"
                elif "file changed" in error_text or "modified" in error_text:
                    cat = "file_changed"
                else:
                    cat = "other"
                tool_error_categories[cat] = tool_error_categories.get(cat, 0) + 1

    # Compute duration
    duration_seconds = 0.0
    if start_time and end_time:
        try:
            t_start = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
            t_end = datetime.fromisoformat(end_time.replace("Z", "+00:00"))
            duration_seconds = (t_end - t_start).total_seconds()
        except (ValueError, TypeError):
            pass

    return {
        "session_id": session_id,
        "project_path": project_path,
        "start_time": start_time or "",
        "end_time": end_time or "",
        "duration_seconds": duration_seconds,
        "user_message_count": user_message_count,
        "assistant_message_count": assistant_message_count,
        "total_messages": total_messages,
        "tool_counts": tool_counts,
        "languages": languages,
        "git_commits": git_commits,
        "git_pushes": git_pushes,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cache_read_tokens": cache_read_tokens,
        "cache_write_tokens": cache_write_tokens,
        "total_cost": total_cost,
        "first_prompt": first_prompt,
        "user_interruptions": user_interruptions,
        "tool_errors": tool_errors,
        "tool_error_categories": tool_error_categories,
        "uses_subagent": uses_subagent,
        "uses_mcp": uses_mcp,
        "lines_added": lines_added,
        "lines_removed": lines_removed,
        "files_modified": len(files_modified),
        "user_response_times": user_response_times,
        "message_hours": message_hours,
        "user_message_timestamps": user_message_timestamps,
    }


async def fetch_all_session_transcripts(
    agent_id: str,
    period_start: str,
    period_end: str,
    agent_name: str = "",
    batch_size: int = 50,
) -> dict[str, list[str]]:
    """Fetch raw JSONL lines for all sessions of an agent from ClickHouse.

    Batches by session_id to avoid loading 200MB+ into memory at once.
    For 20 users x 100 sessions, fetches ~50 sessions at a time.

    Returns {session_id: [raw_line, ...]} for all sessions in the period.
    """
    query = get_query()

    # First, get the list of session_ids from the lightweight session_stats_agg
    id_sql = """
        SELECT session_id
        FROM session_stats_agg
        WHERE (agent_id = {agent_id:String} OR agent_id = {agent_name:String})
          AND first_event_time >= {t_start:String}
          AND first_event_time <= {t_end:String}
        GROUP BY session_id
        ORDER BY min(first_event_time)
        FORMAT JSON
    """
    params = {
        "param_agent_id": agent_id,
        "param_agent_name": agent_name,
        "param_t_start": period_start,
        "param_t_end": period_end,
    }

    try:
        r = await query(id_sql, params)
        r.raise_for_status()
        session_ids = [row["session_id"] for row in r.json().get("data", [])]
    except Exception as e:
        logger.error("fetch_session_ids_failed", error=str(e))
        return {}

    if not session_ids:
        return {}

    logger.info("fetching_transcripts", total_sessions=len(session_ids), batch_size=batch_size)

    # Fetch raw lines in batches
    all_sessions: dict[str, list[str]] = {}

    for i in range(0, len(session_ids), batch_size):
        batch_ids = session_ids[i : i + batch_size]

        batch_sql = """
            SELECT session_id, raw_line
            FROM session_events FINAL
            WHERE session_id IN ({ids:Array(String)})
              AND raw_line != ''
            ORDER BY session_id, line_offset
            FORMAT JSON
        """
        params = {"param_ids": "[" + ",".join(f"'{sid.replace(chr(39), '')}" + "'" for sid in batch_ids) + "]"}

        try:
            r = await query(batch_sql, params)
            r.raise_for_status()
            rows = r.json().get("data", [])
            for row in rows:
                sid = row["session_id"]
                all_sessions.setdefault(sid, []).append(row["raw_line"])
        except Exception as e:
            logger.warning("fetch_batch_failed", batch_start=i, error=str(e))
            continue

    logger.info(
        "fetched_session_transcripts",
        agent_id=agent_id,
        sessions=len(all_sessions),
        total_lines=sum(len(v) for v in all_sessions.values()),
    )
    return all_sessions


async def extract_all_session_metas(
    agent_id: str,
    period_start: str,
    period_end: str,
    agent_name: str = "",
) -> list[dict]:
    """Fetch transcripts and extract deterministic metadata for all sessions.

    This is the main entry point: fetches raw lines from ClickHouse,
    then runs extract_session_meta on each session.
    """
    transcripts = await fetch_all_session_transcripts(agent_id, period_start, period_end, agent_name=agent_name)

    metas = []
    for session_id, lines in transcripts.items():
        meta = extract_session_meta(session_id, lines)
        # Filter: only substantive sessions (2+ user messages, 1+ min duration)
        if meta["user_message_count"] >= 2 and meta["duration_seconds"] >= 60:
            metas.append(meta)

    logger.info(
        "extracted_session_metas",
        total=len(transcripts),
        substantive=len(metas),
    )
    return metas


def aggregate_metas(metas: list[dict]) -> dict:
    """Aggregate per-session metadata into a summary (like pi's aggregateData).

    Returns a single dict with totals, distributions, and top-N lists.
    """
    agg: dict = {
        "total_sessions": len(metas),
        "total_messages": 0,
        "total_duration_hours": 0.0,
        "total_input_tokens": 0,
        "total_output_tokens": 0,
        "total_cache_read_tokens": 0,
        "total_cache_write_tokens": 0,
        "total_cost": 0.0,
        "total_lines_added": 0,
        "total_lines_removed": 0,
        "total_files_modified": 0,
        "git_commits": 0,
        "git_pushes": 0,
        "total_tool_errors": 0,
        "total_interruptions": 0,
        "sessions_using_subagent": 0,
        "sessions_using_mcp": 0,
        "tool_counts": {},
        "languages": {},
        "tool_error_categories": {},
        "projects": {},
        "user_response_times": [],
        "message_hours": [],
        "days_active": set(),
    }

    for meta in metas:
        agg["total_messages"] += meta["total_messages"]
        agg["total_duration_hours"] += meta["duration_seconds"] / 3600
        agg["total_input_tokens"] += meta["input_tokens"]
        agg["total_output_tokens"] += meta["output_tokens"]
        agg["total_cache_read_tokens"] += meta["cache_read_tokens"]
        agg["total_cache_write_tokens"] += meta["cache_write_tokens"]
        agg["total_cost"] += meta["total_cost"]
        agg["total_lines_added"] += meta["lines_added"]
        agg["total_lines_removed"] += meta["lines_removed"]
        agg["total_files_modified"] += meta["files_modified"]
        agg["git_commits"] += meta["git_commits"]
        agg["git_pushes"] += meta["git_pushes"]
        agg["total_tool_errors"] += meta["tool_errors"]
        agg["total_interruptions"] += meta["user_interruptions"]

        if meta["uses_subagent"]:
            agg["sessions_using_subagent"] += 1
        if meta["uses_mcp"]:
            agg["sessions_using_mcp"] += 1

        # Merge tool counts
        for tool, count in meta["tool_counts"].items():
            agg["tool_counts"][tool] = agg["tool_counts"].get(tool, 0) + count

        # Merge languages
        for lang, count in meta["languages"].items():
            agg["languages"][lang] = agg["languages"].get(lang, 0) + count

        # Merge tool error categories
        for cat, count in meta["tool_error_categories"].items():
            agg["tool_error_categories"][cat] = agg["tool_error_categories"].get(cat, 0) + count

        # Projects
        if meta["project_path"]:
            proj = meta["project_path"].rsplit("/", 1)[-1] or meta["project_path"]
            agg["projects"][proj] = agg["projects"].get(proj, 0) + 1

        # Response times
        agg["user_response_times"].extend(meta["user_response_times"])

        # Message hours
        agg["message_hours"].extend(meta["message_hours"])

        # Days active
        if meta["start_time"]:
            agg["days_active"].add(meta["start_time"][:10])

    # Finalize
    agg["days_active"] = len(agg["days_active"])

    # Sort tool counts by frequency
    agg["top_tools"] = sorted(agg["tool_counts"].items(), key=lambda x: -x[1])[:15]
    agg["top_languages"] = sorted(agg["languages"].items(), key=lambda x: -x[1])[:10]

    return agg
