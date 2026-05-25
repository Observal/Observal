# SPDX-FileCopyrightText: 2026 Nithin <nithin30302@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Tests for Gemini CLI session parser compatibility.

Gemini CLI uses the same JSONL schema as Claude Code:
  { "type": "user"|"assistant"|"system", "message": {...}, "timestamp": "..." }

The IDE registry points gemini-cli at the claude-code parser, so this file
verifies:
  1. Registry routing dispatches without KeyError.
  2. A realistic fixture parses to the correct events with zero raw_line
     fallthroughs.
  3. ingest_classify correctly resolves the gemini-cli classifier triple.
  4. Both server and CLI registries carry the same session_parser value.
  5. Edge-cases (empty rows, bad JSON, meta types, unknown types) are safe.
"""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

# Add the server package to sys.path so we can import server-side modules.
sys.path.insert(0, str(Path(__file__).parent.parent / "observal-server"))

# pyrefly: ignore [missing-import]
from services.session_parsers import parse_raw_events

# pyrefly: ignore [missing-import]
from services.session_parsers.ingest_classify import get_classifier

# ---------------------------------------------------------------------------
# Fixture — realistic Gemini CLI session transcript
# ---------------------------------------------------------------------------

_IDE = "gemini-cli"

# Line 1: system init (session start)
_SYSTEM = json.dumps(
    {
        "type": "system",
        "content": "You are a helpful coding assistant.",
        "timestamp": "2026-05-25T10:00:00.000Z",
    }
)

# Line 2: user prompt
_USER_PROMPT = json.dumps(
    {
        "type": "user",
        "message": {
            "role": "user",
            "content": [{"type": "text", "text": "Read /tmp/hello.txt and tell me what it says"}],
        },
        "timestamp": "2026-05-25T10:00:01.000Z",
    }
)

# Line 3: assistant calls a tool (read_file)
_ASSISTANT_TOOL_CALL = json.dumps(
    {
        "type": "assistant",
        "message": {
            "role": "assistant",
            "content": [
                {"type": "text", "text": "I'll read that file for you."},
                {
                    "type": "tool_use",
                    "id": "tu_gemini_001",
                    "name": "read_file",
                    "input": {"path": "/tmp/hello.txt"},
                },
            ],
            "model": "gemini-2.0-flash",
            "usage": {"input_tokens": 120, "output_tokens": 45},
            "stop_reason": "tool_use",
        },
        "timestamp": "2026-05-25T10:00:02.500Z",
    }
)

# Line 4: user carries back tool_result
_USER_TOOL_RESULT = json.dumps(
    {
        "type": "user",
        "message": {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "tu_gemini_001",
                    "content": "Hello, world!",
                }
            ],
        },
        "timestamp": "2026-05-25T10:00:03.000Z",
    }
)

# Line 5: assistant final text response with token usage
_ASSISTANT_RESPONSE = json.dumps(
    {
        "type": "assistant",
        "message": {
            "role": "assistant",
            "content": [{"type": "text", "text": "The file says: Hello, world!"}],
            "model": "gemini-2.0-flash",
            "usage": {
                "input_tokens": 200,
                "output_tokens": 20,
                "cache_read_input_tokens": 50,
            },
            "stop_reason": "end_turn",
        },
        "timestamp": "2026-05-25T10:00:04.000Z",
    }
)

# Line 6: attachment
_ATTACHMENT_LINE = json.dumps(
    {
        "type": "attachment",
        "attachment": {"type": "file", "name": "schema.sql", "content": "CREATE TABLE ..."},
        "timestamp": "2026-05-25T10:00:05.000Z",
    }
)


# A tool-only assistant line (no text before tool_use) -- used by classifier test
# to verify that when tool_use is the FIRST block, classifier returns "tool_call".
_ASSISTANT_TOOL_ONLY = json.dumps(
    {
        "type": "assistant",
        "message": {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "id": "tu_gemini_002",
                    "name": "list_dir",
                    "input": {"path": "/tmp"},
                },
            ],
            "model": "gemini-2.0-flash",
            "usage": {"input_tokens": 80, "output_tokens": 10},
            "stop_reason": "tool_use",
        },
        "timestamp": "2026-05-25T10:00:06.000Z",
    }
)


def _make_row(raw_line: str, offset: int = 0) -> dict:
    """Wrap a raw JSONL string in a minimal ClickHouse-style row dict."""
    return {
        "ide": _IDE,
        "raw_line": raw_line,
        "timestamp": "1970-01-01 00:00:00.000",
        "ingested_at": "2026-05-25 04:30:00.000",
        "event_type": "",
        "content_preview": "",
        "content_length": len(raw_line),
        "tool_name": None,
        "tool_id": None,
        "uuid": None,
        "parent_uuid": None,
        "credits": None,
        "line_offset": offset,
    }


# Full fixture rows (ordered).
# Note: _META_LINE (type: "summary") is intentionally excluded from FIXTURE_ROWS.
# At read time, claude_code.parse_rows skips only its own _META_TYPES set
# {"agent-setting", "permission-mode", "debug", "meta"} -- "summary" is an
# *ingest-time* meta type stored in ClickHouse with event_type="meta" but falls
# through to basic_event at read time. Meta-skipping edge cases are tested in
# TestGeminiParserEdgeCases using the correct read-path meta types.
FIXTURE_ROWS = [
    _make_row(_SYSTEM, 0),
    _make_row(_USER_PROMPT, 1),
    _make_row(_ASSISTANT_TOOL_CALL, 2),
    _make_row(_USER_TOOL_RESULT, 3),
    _make_row(_ASSISTANT_RESPONSE, 4),
    _make_row(_ATTACHMENT_LINE, 5),
]


# ---------------------------------------------------------------------------
# 1. Registry routing
# ---------------------------------------------------------------------------


class TestGeminiParserRouting:
    """parse_raw_events must dispatch correctly for gemini-cli without KeyError."""

    def test_empty_rows_returns_empty(self):
        assert parse_raw_events([]) == []

    def test_fixture_does_not_raise(self):
        """Smoke-test: parsing the full fixture must not raise."""
        events = parse_raw_events(FIXTURE_ROWS)
        assert isinstance(events, list)

    def test_returns_only_dicts(self):
        events = parse_raw_events(FIXTURE_ROWS)
        for ev in events:
            assert isinstance(ev, dict), f"Expected dict, got {type(ev)}: {ev!r}"

    def test_every_event_has_required_keys(self):
        required = {"timestamp", "event_name", "body", "attributes", "service_name"}
        for ev in parse_raw_events(FIXTURE_ROWS):
            missing = required - ev.keys()
            assert not missing, f"Event missing keys {missing}: {ev!r}"

    def test_service_name_is_gemini_cli(self):
        for ev in parse_raw_events(FIXTURE_ROWS):
            assert ev["service_name"] == _IDE, f"service_name wrong: {ev!r}"


# ---------------------------------------------------------------------------
# 2. Fixture event correctness
# ---------------------------------------------------------------------------


class TestGeminiParserFixture:
    """Verify exact event types, counts, and tool merging for the fixture."""

    def _events(self) -> list[dict]:
        return parse_raw_events(FIXTURE_ROWS)

    def _event_names(self) -> list[str]:
        return [ev["event_name"] for ev in self._events()]

    def test_zero_raw_line_fallthroughs(self):
        """No event should be a raw basic_event fallthrough.

        basic_event() produces events with event_name == "" or whatever
        event_type is stored in the row (empty string in our fixture).  All
        fixture lines are valid JSON with known types so none should fall
        through.
        """
        events = self._events()
        fallthrough = [ev for ev in events if ev["event_name"] == ""]
        assert fallthrough == [], f"Unexpected basic_event fallthroughs: {fallthrough!r}"

    def test_fixture_event_count(self):
        """Verify the total event count for the full fixture.

        Expected breakdown (6 rows in FIXTURE_ROWS):
          - _SYSTEM (type: system)            → 1 event  (hook_sessionstart)
          - _USER_PROMPT (type: user, text)   → 1 event  (hook_userpromptsubmit)
          - _ASSISTANT_TOOL_CALL (text+tool)  → 2 events (hook_assistant_response
                                                           + hook_posttooluse)
          - _USER_TOOL_RESULT (tool_result)   → 0 events (merged into posttooluse)
          - _ASSISTANT_RESPONSE (text+tokens) → 1 event  (hook_assistant_response)
          - _ATTACHMENT_LINE (attachment)     → 1 event  (attachment)
        Total: 6 events
        """
        names = self._event_names()
        assert len(names) == 6, f"Expected 6 events, got {len(names)}: {names}"

    def test_system_line_emits_sessionstart(self):
        names = self._event_names()
        assert "hook_sessionstart" in names

    def test_user_prompt_emits_userpromptsubmit(self):
        names = self._event_names()
        assert "hook_userpromptsubmit" in names

    def test_assistant_tool_call_emits_posttooluse(self):
        names = self._event_names()
        assert "hook_posttooluse" in names

    def test_assistant_text_block_emits_response(self):
        names = self._event_names()
        assert "hook_assistant_response" in names

    def test_attachment_emits_attachment_event(self):
        names = self._event_names()
        assert "attachment" in names

    def test_tool_result_merged_into_tool_use(self):
        """tool_result content must be merged back into the posttooluse event,
        not emitted as a new standalone event."""
        events = self._events()
        tool_events = [ev for ev in events if ev["event_name"] == "hook_posttooluse"]
        assert len(tool_events) == 1, f"Expected 1 posttooluse event, got {len(tool_events)}"
        tool_ev = tool_events[0]
        assert "tool_response" in tool_ev["attributes"], "tool_response must be merged into posttooluse attributes"
        assert "Hello, world!" in tool_ev["attributes"]["tool_response"]

    def test_tool_use_attributes(self):
        events = self._events()
        tool_ev = next(ev for ev in events if ev["event_name"] == "hook_posttooluse")
        assert tool_ev["attributes"]["tool_name"] == "read_file"
        assert tool_ev["attributes"]["tool_use_id"] == "tu_gemini_001"
        parsed_input = json.loads(tool_ev["attributes"]["tool_input"])
        assert parsed_input == {"path": "/tmp/hello.txt"}

    def test_token_usage_on_assistant_response(self):
        """Token metadata must appear on the first text-block event."""
        events = self._events()
        # The first assistant text block (line 3) has token usage
        resp_events = [ev for ev in events if ev["event_name"] == "hook_assistant_response"]
        # The first response event (from line 3, text block before tool_use)
        first_resp = resp_events[0]
        assert "input_tokens" in first_resp["attributes"]
        assert first_resp["attributes"]["input_tokens"] == "120"
        assert "output_tokens" in first_resp["attributes"]
        assert first_resp["attributes"]["model"] == "gemini-2.0-flash"

    def test_timestamp_extraction_from_jsonl(self):
        """Timestamps from the JSONL should override the epoch sentinel row_ts."""
        events = self._events()
        for ev in events:
            assert "1970-01-01" not in ev["timestamp"], f"Event should not carry epoch sentinel timestamp: {ev!r}"

    def test_user_prompt_body(self):
        events = self._events()
        prompt_ev = next(ev for ev in events if ev["event_name"] == "hook_userpromptsubmit")
        assert "Read /tmp/hello.txt" in prompt_ev["body"]

    def test_attachment_attributes(self):
        events = self._events()
        attach_ev = next(ev for ev in events if ev["event_name"] == "attachment")
        assert attach_ev["attributes"]["attachment_type"] == "file"
        assert attach_ev["attributes"]["attachment_name"] == "schema.sql"


# ---------------------------------------------------------------------------
# 3. ingest_classify routing
# ---------------------------------------------------------------------------


class TestGeminiClassifier:
    """get_classifier must return the Claude Code triple for gemini-cli."""

    def test_get_classifier_does_not_raise(self):
        triple = get_classifier(_IDE)
        assert triple is not None

    def test_classifier_triple_is_three_callables(self):
        classify_fn, preview_fn, tool_info_fn = get_classifier(_IDE)
        assert callable(classify_fn)
        assert callable(preview_fn)
        assert callable(tool_info_fn)

    def test_classifier_identifies_user_prompt(self):
        classify_fn, _, _ = get_classifier(_IDE)
        parsed = json.loads(_USER_PROMPT)
        assert classify_fn(parsed) == "user_prompt"

    def test_classifier_identifies_tool_call(self):
        """When tool_use is the FIRST content block the classifier returns 'tool_call'.

        The Claude Code classifier returns the type of the *first* matching block.
        _ASSISTANT_TOOL_CALL has a text block before the tool_use block, so it
        returns 'assistant_text'.  Use _ASSISTANT_TOOL_ONLY (tool_use first) to
        exercise the 'tool_call' branch.
        """
        classify_fn, _, _ = get_classifier(_IDE)
        # text-first line → first block is text → classifier returns assistant_text
        parsed_mixed = json.loads(_ASSISTANT_TOOL_CALL)
        assert classify_fn(parsed_mixed) == "assistant_text"
        # tool-only line → first block is tool_use → classifier returns tool_call
        parsed_tool = json.loads(_ASSISTANT_TOOL_ONLY)
        assert classify_fn(parsed_tool) == "tool_call"

    def test_classifier_identifies_tool_result(self):
        classify_fn, _, _ = get_classifier(_IDE)
        parsed = json.loads(_USER_TOOL_RESULT)
        assert classify_fn(parsed) == "tool_result"

    def test_classifier_identifies_assistant_text(self):
        classify_fn, _, _ = get_classifier(_IDE)
        parsed = json.loads(_ASSISTANT_RESPONSE)
        assert classify_fn(parsed) == "assistant_text"

    def test_classifier_skips_meta(self):
        """The ingest-path classifier returns 'meta' for summary-type lines.

        Note: 'summary' is in ingest_classify._META_TYPES (write path), so it
        is classified as 'meta' and stored with event_type='meta' in ClickHouse.
        It is distinct from the read-path _META_TYPES in claude_code.parse_rows
        (which skips 'agent-setting', 'permission-mode', 'debug', 'meta').
        """
        classify_fn, _, _ = get_classifier(_IDE)
        parsed = {"type": "summary", "content": "session summary text"}
        result = classify_fn(parsed)
        assert result == "meta"


# ---------------------------------------------------------------------------
# 4. Registry key sync guard
# ---------------------------------------------------------------------------


class TestGeminiRegistryKey:
    """Both server and CLI registries must carry the same session_parser for gemini-cli."""

    def test_server_registry_has_session_parser(self):
        server_reg = importlib.import_module("schemas.ide_registry")
        spec = server_reg.IDE_REGISTRY["gemini-cli"]
        assert "session_parser" in spec, (
            "Server IDE_REGISTRY['gemini-cli'] is missing 'session_parser' key. "
            'Add "session_parser": "claude-code" to observal-server/schemas/ide_registry.py'
        )

    def test_server_session_parser_is_claude_code(self):
        server_reg = importlib.import_module("schemas.ide_registry")
        assert server_reg.IDE_REGISTRY["gemini-cli"]["session_parser"] == "claude-code"

    def test_cli_registry_has_session_parser(self):
        cli_reg = importlib.import_module("observal_cli.ide_registry")
        spec = cli_reg.IDE_REGISTRY["gemini-cli"]
        assert "session_parser" in spec

    def test_cli_session_parser_is_claude_code(self):
        cli_reg = importlib.import_module("observal_cli.ide_registry")
        assert cli_reg.IDE_REGISTRY["gemini-cli"]["session_parser"] == "claude-code"

    def test_server_and_cli_session_parser_match(self):
        server_reg = importlib.import_module("schemas.ide_registry")
        cli_reg = importlib.import_module("observal_cli.ide_registry")
        server_val = server_reg.IDE_REGISTRY["gemini-cli"]["session_parser"]
        cli_val = cli_reg.IDE_REGISTRY["gemini-cli"]["session_parser"]
        assert server_val == cli_val, f"session_parser mismatch: server={server_val!r}, cli={cli_val!r}"


# ---------------------------------------------------------------------------
# 5. Edge cases
# ---------------------------------------------------------------------------


class TestGeminiParserEdgeCases:
    """Parser must handle degenerate rows safely."""

    def test_empty_row_list(self):
        assert parse_raw_events([]) == []

    def test_row_without_raw_line(self):
        row = _make_row("")
        row["raw_line"] = ""
        events = parse_raw_events([row])
        # Falls through to basic_event
        assert len(events) == 1
        assert events[0]["event_name"] == ""

    def test_row_with_invalid_json(self):
        row = _make_row("not json at all {{{")
        events = parse_raw_events([row])
        assert len(events) == 1
        # basic_event fallback
        assert events[0]["service_name"] == _IDE

    def test_agent_setting_meta_type_is_skipped(self):
        """agent-setting is in _META_TYPES and must produce no event."""
        raw = json.dumps({"type": "agent-setting", "key": "foo", "value": "bar"})
        events = parse_raw_events([_make_row(raw)])
        assert events == []

    def test_debug_meta_type_is_skipped(self):
        raw = json.dumps({"type": "debug", "content": "debug info"})
        events = parse_raw_events([_make_row(raw)])
        assert events == []

    def test_unknown_type_falls_through_to_basic_event(self):
        """An unknown top-level type must not crash — it falls back to basic_event."""
        raw = json.dumps({"type": "gemini_specific_future_type", "data": {}})
        events = parse_raw_events([_make_row(raw)])
        assert len(events) == 1

    def test_assistant_thinking_block(self):
        """Thinking blocks (extended thinking) must emit hook_assistant_thinking."""
        raw = json.dumps(
            {
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "content": [
                        {"type": "thinking", "thinking": "Let me reason..."},
                        {"type": "text", "text": "The answer is 42."},
                    ],
                    "model": "gemini-2.0-flash",
                    "usage": {"input_tokens": 50, "output_tokens": 10},
                },
                "timestamp": "2026-05-25T10:01:00.000Z",
            }
        )
        events = parse_raw_events([_make_row(raw)])
        names = [ev["event_name"] for ev in events]
        assert "hook_assistant_thinking" in names
        assert "hook_assistant_response" in names

    def test_user_content_as_string(self):
        """User messages with a string content (not list) must parse without error."""
        raw = json.dumps(
            {
                "type": "user",
                "message": {"role": "user", "content": "Simple string prompt"},
                "timestamp": "2026-05-25T10:02:00.000Z",
            }
        )
        events = parse_raw_events([_make_row(raw)])
        assert len(events) == 1
        assert events[0]["event_name"] == "hook_userpromptsubmit"
        assert events[0]["attributes"]["tool_input"] == "Simple string prompt"

    def test_multiple_rows_correct_order(self):
        """Events must appear in the same order as the input rows."""
        rows = [_make_row(_USER_PROMPT, 0), _make_row(_ASSISTANT_RESPONSE, 1)]
        events = parse_raw_events(rows)
        names = [ev["event_name"] for ev in events]
        # user prompt comes before assistant response
        assert names.index("hook_userpromptsubmit") < names.index("hook_assistant_response")
