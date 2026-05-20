# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Per-IDE JSONL line classifiers for the ingest pipeline.

Each IDE has its own JSONL format.  This module provides:

  classify(ide, parsed)        -> event_type str | None (None = skip line)
  extract_preview(ide, parsed, event_type) -> str
  extract_tool_info(ide, parsed) -> (tool_name, tool_id)

Dispatch is **strict**: passing an unknown IDE raises ``KeyError`` so new
IDEs cannot silently fall through to a wrong classifier.  When adding
support for a new IDE:

  1. Add its entry to ``schemas/ide_registry.py`` with a ``"session_parser"``
     key referencing one of the parser IDs registered in ``_CLASSIFIERS`` below.
  2. If the IDE has a novel JSONL format, implement ``_classify_<name>``,
     ``_preview_<name>``, and ``_tool_info_<name>`` and register them.
  3. If the IDE uses an existing format (e.g. Claude Code), point its
     ``"session_parser"`` at the existing parser ID.
"""

from __future__ import annotations

from collections.abc import Callable

_PREVIEW_MAX = 500


# ---------------------------------------------------------------------------
# Claude Code classifier
# ---------------------------------------------------------------------------

_META_TYPES = frozenset({"summary", "completion_start", "tool_use_result", "tool_use_delta"})

_ATTACHMENT_TYPE_MAP: dict[str, str] = {
    "file": "attachment_file",
    "url": "attachment_url",
    "image": "attachment_image",
    "directory": "attachment_dir",
    "project_knowledge": "attachment_knowledge",
}


def _classify_claude_code(parsed: dict) -> str | None:
    """Classify one Claude Code JSONL line.

    Returns the event_type string, or None to skip the line entirely
    (empty continuation signals).
    """
    line_type = parsed.get("type", "")

    if line_type in _META_TYPES:
        return "meta"

    if line_type == "system":
        return "system"

    if line_type == "user":
        content = parsed.get("message", {}).get("content", [])
        if not content:
            return None  # empty continuation signal
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    return "tool_result"
            return "user_prompt"
        return "user_prompt"

    if line_type == "assistant":
        content = parsed.get("message", {}).get("content", [])
        if isinstance(content, list) and content:
            for block in content:
                if isinstance(block, dict):
                    btype = block.get("type", "")
                    if btype == "thinking":
                        return "thinking"
                    if btype == "tool_use":
                        return "tool_call"
                    if btype == "text":
                        return "assistant_text"
        return "assistant_text"

    if line_type == "attachment":
        attachment_type = parsed.get("attachment", {}).get("type", "")
        return _ATTACHMENT_TYPE_MAP.get(attachment_type, "system")

    # Unknown type -- store as system so nothing is silently dropped
    return "system"


def _preview_claude_code(parsed: dict, event_type: str) -> str:
    try:
        line_type = parsed.get("type", "")
        if line_type in ("user", "assistant"):
            content = parsed.get("message", {}).get("content", [])
            if isinstance(content, str):
                return content[:_PREVIEW_MAX]
            if isinstance(content, list):
                parts: list[str] = []
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    btype = block.get("type", "")
                    if btype == "text":
                        parts.append(block.get("text", "")[:_PREVIEW_MAX])
                    elif btype == "thinking":
                        parts.append(block.get("thinking", "")[:_PREVIEW_MAX])
                    elif btype == "tool_use":
                        parts.append(f"[tool_use: {block.get('name', '')}]")
                    elif btype == "tool_result":
                        inner = block.get("content", "")
                        if isinstance(inner, list):
                            for item in inner:
                                if isinstance(item, dict) and item.get("type") == "text":
                                    parts.append(item.get("text", "")[:_PREVIEW_MAX])
                        elif isinstance(inner, str):
                            parts.append(inner[:_PREVIEW_MAX])
                return " ".join(parts)[:_PREVIEW_MAX]
        if line_type == "attachment":
            attachment = parsed.get("attachment", {})
            name = attachment.get("name") or attachment.get("type", "")
            return f"[attachment: {name}]"[:_PREVIEW_MAX]
        if line_type == "system":
            return parsed.get("content", "")[:_PREVIEW_MAX]
    except Exception:
        pass
    return ""


def _tool_info_claude_code(parsed: dict) -> tuple[str | None, str | None]:
    content = parsed.get("message", {}).get("content", [])
    if not isinstance(content, list):
        return None, None
    for block in content:
        if isinstance(block, dict) and block.get("type") == "tool_use":
            return block.get("name"), block.get("id")
    return None, None


# ---------------------------------------------------------------------------
# Kiro classifier
# ---------------------------------------------------------------------------


def _classify_kiro(parsed: dict) -> str | None:
    """Classify one Kiro JSONL line.

    Kiro uses ``kind`` (not ``type``) with values:
      Prompt           -> user prompt
      AssistantMessage -> assistant text or tool call
      ToolResults      -> tool result
    """
    kind = parsed.get("kind", "")

    if kind == "Prompt":
        data = parsed.get("data", {})
        content = data.get("content", []) if isinstance(data, dict) else []
        # Skip empty prompts
        if not any(
            isinstance(item, dict) and item.get("kind") == "text" and item.get("data", "").strip() for item in content
        ):
            return None
        return "user_prompt"

    if kind == "AssistantMessage":
        data = parsed.get("data", {})
        content = data.get("content", []) if isinstance(data, dict) else []
        for item in content:
            if isinstance(item, dict) and item.get("kind") == "toolUse":
                return "tool_call"
        return "assistant_text"

    if kind == "ToolResults":
        return "tool_result"

    # Unknown Kiro kind -- store as system
    return "system"


def _preview_kiro(parsed: dict, event_type: str) -> str:
    try:
        kind = parsed.get("kind", "")
        data = parsed.get("data", {}) if isinstance(parsed.get("data"), dict) else {}
        content = data.get("content", [])

        if kind == "Prompt":
            parts = [
                item.get("data", "")
                for item in content
                if isinstance(item, dict) and item.get("kind") == "text" and isinstance(item.get("data"), str)
            ]
            return " ".join(parts)[:_PREVIEW_MAX]

        if kind == "AssistantMessage":
            parts = []
            for item in content:
                if not isinstance(item, dict):
                    continue
                if item.get("kind") == "text":
                    parts.append(str(item.get("data", ""))[:_PREVIEW_MAX])
                elif item.get("kind") == "toolUse":
                    name = item.get("data", {}).get("name", "") if isinstance(item.get("data"), dict) else ""
                    parts.append(f"[tool_use: {name}]")
            return " ".join(parts)[:_PREVIEW_MAX]

        if kind == "ToolResults":
            parts = []
            for item in content:
                if not isinstance(item, dict) or item.get("kind") != "toolResult":
                    continue
                item_data = item.get("data", {})
                if not isinstance(item_data, dict):
                    continue
                for rc in item_data.get("content", []):
                    if isinstance(rc, dict) and rc.get("kind") == "text":
                        parts.append(str(rc.get("data", ""))[:_PREVIEW_MAX])
            return " ".join(parts)[:_PREVIEW_MAX]
    except Exception:
        pass
    return ""


def _tool_info_kiro(parsed: dict) -> tuple[str | None, str | None]:
    kind = parsed.get("kind", "")
    data = parsed.get("data", {}) if isinstance(parsed.get("data"), dict) else {}
    content = data.get("content", [])
    if kind == "AssistantMessage":
        for item in content:
            if isinstance(item, dict) and item.get("kind") == "toolUse":
                item_data = item.get("data", {})
                if isinstance(item_data, dict):
                    return item_data.get("name"), item_data.get("toolUseId")
    return None, None


# ---------------------------------------------------------------------------
# Cursor classifier
# ---------------------------------------------------------------------------


def _classify_cursor(parsed: dict) -> str | None:
    """Classify one Cursor JSONL line.

    Cursor uses ``role`` (not ``type``) with values matching Claude Code's
    content block structure.  The ``message.content`` array contains blocks
    with ``type: text|tool_use|tool_result|thinking``.
    """
    role = parsed.get("role", "")

    if role == "user":
        content = parsed.get("message", {}).get("content", [])
        if not content:
            return None
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    return "tool_result"
            return "user_prompt"
        return "user_prompt"

    if role == "assistant":
        content = parsed.get("message", {}).get("content", [])
        if isinstance(content, list) and content:
            for block in content:
                if isinstance(block, dict):
                    btype = block.get("type", "")
                    if btype == "thinking":
                        return "thinking"
                    if btype == "tool_use":
                        return "tool_call"
                    if btype == "text":
                        return "assistant_text"
        return "assistant_text"

    if not role:
        return None

    return "system"


def _strip_cursor_xml_tags(text: str) -> str:
    """Strip Cursor's XML wrapper tags from user prompts.

    Cursor wraps user messages in <timestamp>...</timestamp> and
    <user_query>...</user_query> tags.  Strip them for clean display.
    """
    import re

    text = re.sub(r"<timestamp>.*?</timestamp>\s*", "", text, flags=re.DOTALL)
    text = re.sub(r"</?user_query>\s*", "", text)
    text = re.sub(r"</?system_reminder>\s*", "", text)
    text = re.sub(r"</?attached_files>\s*", "", text)
    return text.strip()


def _preview_cursor(parsed: dict, event_type: str) -> str:
    """Extract preview from Cursor JSONL (same content structure as Claude Code)."""
    try:
        content = parsed.get("message", {}).get("content", [])
        if isinstance(content, str):
            return _strip_cursor_xml_tags(content)[:_PREVIEW_MAX]
        if isinstance(content, list):
            parts: list[str] = []
            for block in content:
                if not isinstance(block, dict):
                    continue
                btype = block.get("type", "")
                if btype == "text":
                    text = block.get("text", "")
                    if event_type == "user_prompt":
                        text = _strip_cursor_xml_tags(text)
                    parts.append(text[:_PREVIEW_MAX])
                elif btype == "thinking":
                    parts.append(block.get("thinking", "")[:_PREVIEW_MAX])
                elif btype == "tool_use":
                    parts.append(f"[tool_use: {block.get('name', '')}]")
                elif btype == "tool_result":
                    inner = block.get("content", "")
                    if isinstance(inner, list):
                        for item in inner:
                            if isinstance(item, dict) and item.get("type") == "text":
                                parts.append(item.get("text", "")[:_PREVIEW_MAX])
                    elif isinstance(inner, str):
                        parts.append(inner[:_PREVIEW_MAX])
            return " ".join(parts)[:_PREVIEW_MAX]
    except Exception:
        pass
    return ""


def _tool_info_cursor(parsed: dict) -> tuple[str | None, str | None]:
    content = parsed.get("message", {}).get("content", [])
    if not isinstance(content, list):
        return None, None
    for block in content:
        if isinstance(block, dict) and block.get("type") == "tool_use":
            return block.get("name"), block.get("id")
    return None, None


# ---------------------------------------------------------------------------
# Registry  -- add new parsers here, update ide_registry.py session_parser key
# ---------------------------------------------------------------------------

_ClassifyFn = Callable[[dict], "str | None"]
_PreviewFn = Callable[[dict, str], str]
_ToolInfoFn = Callable[[dict], "tuple[str | None, str | None]"]
_Classifier = tuple[_ClassifyFn, _PreviewFn, _ToolInfoFn]

# Maps session_parser ID -> (classify_fn, preview_fn, tool_info_fn)
_CLASSIFIERS: dict[str, _Classifier] = {
    "claude-code": (_classify_claude_code, _preview_claude_code, _tool_info_claude_code),
    "kiro": (_classify_kiro, _preview_kiro, _tool_info_kiro),
    "cursor": (_classify_cursor, _preview_cursor, _tool_info_cursor),
}


def get_classifier(ide: str) -> tuple:
    """Return (classify_fn, preview_fn, tool_info_fn) for the given IDE.

    Looks up the ``session_parser`` key in ``ide_registry.IDE_REGISTRY`` and
    dispatches to the matching entry in ``_CLASSIFIERS``.

    Raises ``KeyError`` if the IDE is not registered or has no session_parser,
    so new IDEs cannot silently fall through to a wrong classifier.
    """
    from schemas.ide_registry import IDE_REGISTRY

    parser_id = IDE_REGISTRY[ide]["session_parser"]  # KeyError = unknown IDE
    return _CLASSIFIERS[parser_id]  # KeyError = unimplemented parser


def classify(ide: str, parsed: dict) -> str | None:
    """Classify a single parsed JSONL line for the given IDE."""
    classify_fn, _, _ = get_classifier(ide)
    return classify_fn(parsed)


def extract_preview(ide: str, parsed: dict, event_type: str) -> str:
    """Extract a short preview string for the given IDE."""
    _, preview_fn, _ = get_classifier(ide)
    return preview_fn(parsed, event_type)


def extract_tool_info(ide: str, parsed: dict) -> tuple[str | None, str | None]:
    """Extract (tool_name, tool_id) for the given IDE."""
    _, _, tool_info_fn = get_classifier(ide)
    return tool_info_fn(parsed)


# ---------------------------------------------------------------------------
# Timestamp extraction -- IDE-specific
# ---------------------------------------------------------------------------


def _ts_claude_code(parsed: dict) -> str | None:
    """Return ClickHouse timestamp string from a Claude Code JSONL line, or None."""
    raw = parsed.get("timestamp")
    if not raw:
        return None
    ts = str(raw).replace("T", " ").rstrip("Z")
    if "." not in ts:
        ts += ".000"
    return ts


def _ts_kiro(parsed: dict) -> str | None:
    """Return ClickHouse timestamp string from a Kiro JSONL line, or None.

    Kiro embeds unix epoch *seconds* at ``data.meta.timestamp``.  Only Prompt
    lines carry a timestamp; AssistantMessage and ToolResults inherit it.
    """
    data = parsed.get("data")
    if not isinstance(data, dict):
        return None
    meta = data.get("meta")
    if not isinstance(meta, dict):
        return None
    epoch_s = meta.get("timestamp")
    if not epoch_s:
        return None
    try:
        from datetime import UTC, datetime

        dt = datetime.fromtimestamp(float(epoch_s), tz=UTC)
        return dt.strftime("%Y-%m-%d %H:%M:%S.000")
    except Exception:
        return None


def _ts_cursor(parsed: dict) -> str | None:
    """Return ClickHouse timestamp string from a Cursor JSONL line, or None.

    Cursor does not embed timestamps in its JSONL transcript lines.
    Return None so the caller uses ingestion time (now) as fallback.
    """
    return None


_TS_EXTRACTORS: dict[str, object] = {
    "claude-code": _ts_claude_code,
    "kiro": _ts_kiro,
    "cursor": _ts_cursor,
}


def extract_timestamp(ide: str, parsed: dict) -> str | None:
    """Return a ClickHouse-formatted timestamp string for a JSONL line, or None.

    Returns None when the line has no timestamp -- callers should use a
    sentinel or inherit from a previous line rather than silently defaulting.
    Raises KeyError for unknown IDEs.
    """
    from schemas.ide_registry import IDE_REGISTRY

    parser_id = IDE_REGISTRY[ide]["session_parser"]  # KeyError = unknown IDE
    extractor = _TS_EXTRACTORS[parser_id]  # KeyError = unimplemented
    return extractor(parsed)  # type: ignore[call-arg,operator]


# ---------------------------------------------------------------------------
# Per-IDE extra rows (written after the main ingest loop)
# ---------------------------------------------------------------------------
# Each per-IDE module owns its own extra_ingest_rows() function.
# Register new IDEs here by importing and adding to _EXTRA_ROWS_HANDLERS.

from services.session_parsers.kiro import extra_ingest_rows as _kiro_extra_rows  # noqa: E402


def _no_extra_rows(*_args, **_kwargs) -> list[dict]:
    """Default: no extra rows for this IDE."""
    return []


_ExtraRowsFn = Callable[..., list[dict]]

_EXTRA_ROWS_HANDLERS: dict[str, _ExtraRowsFn] = {
    "kiro": _kiro_extra_rows,
    "claude-code": _no_extra_rows,
    "cursor": _no_extra_rows,
}


def get_extra_rows(
    ide: str,
    session_id: str,
    project_id: str,
    user_id: str,
    agent_id: str | None,
    agent_version: str | None,
    total_credits: float | None,
) -> list[dict]:
    """Return any extra ClickHouse rows to insert after the main ingest loop.

    Dispatches to per-IDE handlers via session_parser ID.
    Unknown IDEs fall back to _no_extra_rows (fail-open).
    """
    from schemas.ide_registry import IDE_REGISTRY

    parser_id = IDE_REGISTRY.get(ide, {}).get("session_parser", "claude-code")
    handler = _EXTRA_ROWS_HANDLERS.get(parser_id, _no_extra_rows)
    return handler(session_id, project_id, user_id, agent_id, agent_version, ide, total_credits)
