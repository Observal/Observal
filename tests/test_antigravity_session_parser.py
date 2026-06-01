# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Tests for Antigravity session parser, classifiers, and ingest helpers."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "observal-server"))

from services.session_ingest import _usage_antigravity, _uuid_antigravity
from services.session_parsers.antigravity import parse_rows
from services.session_parsers.ingest_classify import (
    _classify_antigravity,
    _preview_antigravity,
    _tool_info_antigravity,
    _ts_antigravity,
)

# ── Sample Antigravity transcript lines ───────────────────────────────────────

USER_PROMPT = json.dumps(
    {
        "step_index": 0,
        "source": "USER_EXPLICIT",
        "type": "USER_INPUT",
        "status": "DONE",
        "created_at": "2026-06-01T14:30:00Z",
        "content": "<USER_REQUEST>\nwhat files are in this directory\n</USER_REQUEST>",
    }
)

USER_PROMPT_PLAIN = json.dumps(
    {
        "step_index": 0,
        "source": "USER_EXPLICIT",
        "type": "USER_INPUT",
        "status": "DONE",
        "created_at": "2026-06-01T14:30:00Z",
        "content": "list all python files",
    }
)

ASSISTANT_TEXT = json.dumps(
    {
        "step_index": 1,
        "source": "MODEL",
        "type": "PLANNER_RESPONSE",
        "status": "DONE",
        "created_at": "2026-06-01T14:30:05Z",
        "content": "I'll list the files in this directory for you.",
    }
)

ASSISTANT_WITH_TOOLS = json.dumps(
    {
        "step_index": 2,
        "source": "MODEL",
        "type": "PLANNER_RESPONSE",
        "status": "DONE",
        "created_at": "2026-06-01T14:30:10Z",
        "content": "Let me check the directory contents.",
        "tool_calls": [
            {"name": "list_dir", "args": {"path": "/workspace"}},
            {"name": "read_file", "args": {"path": "/workspace/main.py"}},
        ],
    }
)

TOOL_RESULT = json.dumps(
    {
        "step_index": 3,
        "source": "MODEL",
        "type": "LIST_DIRECTORY",
        "status": "DONE",
        "created_at": "2026-06-01T14:30:12Z",
        "content": "main.py\nutils.py\ntest.py",
    }
)

TOOL_RESULT_ERROR = json.dumps(
    {
        "step_index": 4,
        "source": "MODEL",
        "type": "READ_FILE",
        "status": "ERROR",
        "created_at": "2026-06-01T14:30:15Z",
        "content": "Permission denied: /workspace/secret.txt",
    }
)

SYSTEM_HISTORY = json.dumps(
    {
        "step_index": 5,
        "source": "SYSTEM",
        "type": "CONVERSATION_HISTORY",
        "status": "DONE",
        "created_at": "2026-06-01T14:30:00Z",
        "content": "Previous conversation context...",
    }
)

SYSTEM_PROMPT = json.dumps(
    {
        "step_index": 6,
        "source": "SYSTEM",
        "type": "SYSTEM_PROMPT",
        "status": "DONE",
        "created_at": "2026-06-01T14:30:00Z",
        "content": "You are a helpful assistant.",
    }
)


# ── Classify tests ────────────────────────────────────────────────────────────


class TestClassifyAntigravity:
    def test_user_prompt(self):
        assert _classify_antigravity(json.loads(USER_PROMPT)) == "user_prompt"

    def test_user_prompt_plain(self):
        assert _classify_antigravity(json.loads(USER_PROMPT_PLAIN)) == "user_prompt"

    def test_assistant_text(self):
        assert _classify_antigravity(json.loads(ASSISTANT_TEXT)) == "assistant_text"

    def test_assistant_with_tool_calls(self):
        assert _classify_antigravity(json.loads(ASSISTANT_WITH_TOOLS)) == "tool_call"

    def test_tool_result(self):
        assert _classify_antigravity(json.loads(TOOL_RESULT)) == "tool_result"

    def test_tool_result_error(self):
        assert _classify_antigravity(json.loads(TOOL_RESULT_ERROR)) == "tool_result"

    def test_system_history_skipped(self):
        assert _classify_antigravity(json.loads(SYSTEM_HISTORY)) is None

    def test_system_prompt_skipped(self):
        assert _classify_antigravity(json.loads(SYSTEM_PROMPT)) is None

    def test_system_source_is_system(self):
        parsed = {"source": "SYSTEM", "type": "UNKNOWN_TYPE", "content": "something"}
        assert _classify_antigravity(parsed) == "system"

    def test_unknown_source_returns_none(self):
        parsed = {"source": "UNKNOWN", "type": "UNKNOWN_TYPE", "content": "something"}
        assert _classify_antigravity(parsed) is None


# ── Preview tests ─────────────────────────────────────────────────────────────


class TestPreviewAntigravity:
    def test_user_prompt_strips_xml(self):
        parsed = json.loads(USER_PROMPT)
        preview = _preview_antigravity(parsed, "user_prompt")
        assert "what files are in this directory" in preview
        assert "<USER_REQUEST>" not in preview

    def test_user_prompt_plain_no_xml(self):
        parsed = json.loads(USER_PROMPT_PLAIN)
        preview = _preview_antigravity(parsed, "user_prompt")
        assert preview == "list all python files"

    def test_assistant_text_preview(self):
        parsed = json.loads(ASSISTANT_TEXT)
        preview = _preview_antigravity(parsed, "assistant_text")
        assert "list the files" in preview

    def test_tool_call_preview_shows_tool_names(self):
        parsed = json.loads(ASSISTANT_WITH_TOOLS)
        preview = _preview_antigravity(parsed, "tool_call")
        assert "list_dir" in preview
        assert "read_file" in preview

    def test_tool_result_preview_shows_type(self):
        parsed = json.loads(TOOL_RESULT)
        preview = _preview_antigravity(parsed, "tool_result")
        assert "LIST_DIRECTORY" in preview
        assert "main.py" in preview

    def test_empty_content_returns_empty(self):
        parsed = {"source": "MODEL", "type": "PLANNER_RESPONSE", "content": ""}
        preview = _preview_antigravity(parsed, "assistant_text")
        assert preview == ""

    def test_preview_truncated_to_500(self):
        parsed = {"source": "MODEL", "type": "PLANNER_RESPONSE", "content": "x" * 1000}
        preview = _preview_antigravity(parsed, "assistant_text")
        assert len(preview) <= 500


# ── Tool info tests ───────────────────────────────────────────────────────────


class TestToolInfoAntigravity:
    def test_tool_call_extracts_first_name(self):
        parsed = json.loads(ASSISTANT_WITH_TOOLS)
        name, tool_id = _tool_info_antigravity(parsed)
        assert name == "list_dir"
        assert tool_id is None

    def test_tool_result_extracts_type_as_name(self):
        parsed = json.loads(TOOL_RESULT)
        name, tool_id = _tool_info_antigravity(parsed)
        assert name == "list_directory"
        assert tool_id is None

    def test_assistant_text_returns_none(self):
        parsed = json.loads(ASSISTANT_TEXT)
        name, tool_id = _tool_info_antigravity(parsed)
        assert name is None
        assert tool_id is None

    def test_user_prompt_returns_none(self):
        parsed = json.loads(USER_PROMPT)
        name, tool_id = _tool_info_antigravity(parsed)
        assert name is None
        assert tool_id is None


# ── Timestamp tests ───────────────────────────────────────────────────────────


class TestTimestampAntigravity:
    def test_extracts_created_at(self):
        parsed = json.loads(USER_PROMPT)
        ts = _ts_antigravity(parsed)
        assert ts == "2026-06-01 14:30:00.000"

    def test_no_created_at_returns_none(self):
        assert _ts_antigravity({}) is None

    def test_preserves_milliseconds(self):
        parsed = {"created_at": "2026-06-01T14:30:05.123Z"}
        ts = _ts_antigravity(parsed)
        assert ts == "2026-06-01 14:30:05.123"

    def test_adds_millis_if_missing(self):
        parsed = {"created_at": "2026-06-01T14:30:05Z"}
        ts = _ts_antigravity(parsed)
        assert ts == "2026-06-01 14:30:05.000"


# ── Usage extraction tests ────────────────────────────────────────────────────


class TestUsageAntigravity:
    def test_returns_zeros(self):
        """Antigravity transcripts have no token counts."""
        result = _usage_antigravity(json.loads(ASSISTANT_TEXT))
        assert result["input_tokens"] == 0
        assert result["output_tokens"] == 0
        assert result["cache_read_tokens"] == 0
        assert result["cache_write_tokens"] == 0
        assert result["model"] == ""

    def test_returns_zeros_for_empty(self):
        result = _usage_antigravity({})
        assert result["input_tokens"] == 0


# ── UUID extraction tests ─────────────────────────────────────────────────────


class TestUuidAntigravity:
    def test_extracts_step_index(self):
        parsed = json.loads(USER_PROMPT)
        uuid, parent_uuid = _uuid_antigravity(parsed)
        assert uuid == "0"
        assert parent_uuid is None

    def test_missing_step_index(self):
        uuid, parent_uuid = _uuid_antigravity({})
        assert uuid is None
        assert parent_uuid is None

    def test_step_index_as_string(self):
        parsed = {"step_index": 42}
        uuid, parent_uuid = _uuid_antigravity(parsed)
        assert uuid == "42"


# ── Full parse_rows tests ─────────────────────────────────────────────────────


class TestParseRows:
    def test_empty_input(self):
        assert parse_rows([]) == []

    def test_user_prompt_event(self):
        rows = [
            {"raw_line": USER_PROMPT, "ingested_at": "2026-06-01 14:30:00.000", "timestamp": "", "ide": "antigravity"}
        ]
        events = parse_rows(rows)
        assert len(events) == 1
        assert events[0]["event_name"] == "hook_userpromptsubmit"
        assert "what files are in this directory" in events[0]["attributes"]["tool_input"]

    def test_assistant_text_event(self):
        rows = [
            {
                "raw_line": ASSISTANT_TEXT,
                "ingested_at": "2026-06-01 14:30:05.000",
                "timestamp": "",
                "ide": "antigravity",
            }
        ]
        events = parse_rows(rows)
        assert len(events) == 1
        assert events[0]["event_name"] == "hook_assistant_response"
        assert "list the files" in events[0]["body"]

    def test_tool_call_events(self):
        rows = [
            {
                "raw_line": ASSISTANT_WITH_TOOLS,
                "ingested_at": "2026-06-01 14:30:10.000",
                "timestamp": "",
                "ide": "antigravity",
            }
        ]
        events = parse_rows(rows)
        assert len(events) == 2
        assert events[0]["event_name"] == "hook_posttooluse"
        assert events[0]["body"] == "list_dir"
        assert events[1]["body"] == "read_file"

    def test_tool_result_attaches_to_parent(self):
        """Tool result should attach to the preceding tool call event."""
        rows = [
            {
                "raw_line": ASSISTANT_WITH_TOOLS,
                "ingested_at": "2026-06-01 14:30:10.000",
                "timestamp": "",
                "ide": "antigravity",
            },
            {"raw_line": TOOL_RESULT, "ingested_at": "2026-06-01 14:30:12.000", "timestamp": "", "ide": "antigravity"},
        ]
        events = parse_rows(rows)
        # 2 tool call events from ASSISTANT_WITH_TOOLS, tool result attaches to one
        assert len(events) == 2
        # The tool result should have been attached to one of the tool calls
        attached = any(e.get("attributes", {}).get("tool_response") for e in events)
        assert attached

    def test_system_lines_skipped(self):
        rows = [
            {
                "raw_line": SYSTEM_HISTORY,
                "ingested_at": "2026-06-01 14:30:00.000",
                "timestamp": "",
                "ide": "antigravity",
            },
            {
                "raw_line": SYSTEM_PROMPT,
                "ingested_at": "2026-06-01 14:30:00.000",
                "timestamp": "",
                "ide": "antigravity",
            },
        ]
        events = parse_rows(rows)
        assert events == []

    def test_error_tool_result_marks_status(self):
        rows = [
            {
                "raw_line": ASSISTANT_WITH_TOOLS,
                "ingested_at": "2026-06-01 14:30:10.000",
                "timestamp": "",
                "ide": "antigravity",
            },
            {
                "raw_line": TOOL_RESULT_ERROR,
                "ingested_at": "2026-06-01 14:30:15.000",
                "timestamp": "",
                "ide": "antigravity",
            },
        ]
        events = parse_rows(rows)
        error_events = [e for e in events if e.get("attributes", {}).get("tool_status") == "error"]
        assert len(error_events) == 1

    def test_invalid_raw_line_produces_basic_event(self):
        rows = [
            {
                "raw_line": "not valid json",
                "ingested_at": "2026-06-01 14:30:00.000",
                "timestamp": "",
                "ide": "antigravity",
            }
        ]
        events = parse_rows(rows)
        assert len(events) == 1

    def test_empty_raw_line_produces_basic_event(self):
        rows = [{"raw_line": "", "ingested_at": "2026-06-01 14:30:00.000", "timestamp": "", "ide": "antigravity"}]
        events = parse_rows(rows)
        assert len(events) == 1

    def test_standalone_tool_result_without_parent(self):
        """Tool result without a preceding tool call should emit standalone event."""
        rows = [
            {"raw_line": TOOL_RESULT, "ingested_at": "2026-06-01 14:30:12.000", "timestamp": "", "ide": "antigravity"}
        ]
        events = parse_rows(rows)
        assert len(events) == 1
        assert events[0]["event_name"] == "hook_posttooluse"
        assert events[0]["body"] == "LIST_DIRECTORY"

    def test_full_conversation_flow(self):
        """End-to-end: user prompt -> tool call -> tool result -> assistant text."""
        rows = [
            {"raw_line": USER_PROMPT, "ingested_at": "2026-06-01 14:30:00.000", "timestamp": "", "ide": "antigravity"},
            {
                "raw_line": ASSISTANT_WITH_TOOLS,
                "ingested_at": "2026-06-01 14:30:10.000",
                "timestamp": "",
                "ide": "antigravity",
            },
            {"raw_line": TOOL_RESULT, "ingested_at": "2026-06-01 14:30:12.000", "timestamp": "", "ide": "antigravity"},
            {
                "raw_line": ASSISTANT_TEXT,
                "ingested_at": "2026-06-01 14:30:20.000",
                "timestamp": "",
                "ide": "antigravity",
            },
        ]
        events = parse_rows(rows)
        event_names = [e["event_name"] for e in events]
        assert "hook_userpromptsubmit" in event_names
        assert "hook_posttooluse" in event_names
        assert "hook_assistant_response" in event_names
