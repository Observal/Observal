# SPDX-FileCopyrightText: 2026 BlazeUp-AI contributors
# SPDX-License-Identifier: AGPL-3.0-only

"""Tests for the Cursor JSONL session parser."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "observal-server"))

import pytest

from services.session_parsers.cursor import parse_rows

FIXTURE = Path(__file__).parent / "fixtures" / "cursor_session.jsonl"
IDE = "cursor"


def _rows_from_fixture() -> list[dict]:
    rows = []
    for line in FIXTURE.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append({
            "raw_line": line,
            "ide": IDE,
            "timestamp": "2026-05-01 10:00:00.000",
            "ingested_at": "2026-05-01 10:00:01.000",
            "event_type": "",
            "content_preview": "",
            "tool_name": None,
            "tool_id": None,
            "uuid": None,
            "parent_uuid": None,
            "content_length": 0,
        })
    return rows

def _row(raw: dict, **overrides) -> dict:
    """Build a single ClickHouse-style row from a raw dict."""
    base = {
        "raw_line": json.dumps(raw),
        "ide": IDE,
        "timestamp": "2026-05-01 10:00:00.000",
        "ingested_at": "2026-05-01 10:00:01.000",
        "event_type": "",
        "content_preview": "",
        "tool_name": None,
        "tool_id": None,
        "uuid": None,
        "parent_uuid": None,
        "content_length": 0,
    }
    base.update(overrides)
    return base


def test_fixture_parsing():
    """Verify that parsing the complete fixture produces expected trace events."""
    rows = _rows_from_fixture()
    events = parse_rows(rows)
    assert len(events) >= 8
    for ev in events:
        assert ev.get("event_name"), f"Event missing event_name: {ev}"
        assert ev.get("service_name") == IDE
        assert ev.get("timestamp")


def test_user_plain_text():
    raw = {
        "role": "user",
        "timestamp": "2026-05-01T10:00:00.000Z",
        "message": {"content": [{"type": "text", "text": "Hello world"}]},
    }
    events = parse_rows([_row(raw)])
    assert len(events) == 1
    assert events[0]["event_name"] == "hook_userpromptsubmit"
    assert events[0]["attributes"]["tool_input"] == "Hello world"
    assert events[0]["body"] == "Hello world"


@pytest.mark.parametrize(
    "text, expected_in, expected_not_in",
    [
        ("<user_query>\nRefactor the auth middleware\n</user_query>", "Refactor the auth middleware", "<user_query>"),
        ("<user_query>Do X</user_query>\n<system_reminder>You are helpful.</system_reminder>", "Do X", "<system_reminder>"),
        ("<timestamp>2026-05-01T10:00:00.000Z</timestamp>\n<user_query>What time is it?</user_query>", "What time is it?", "<timestamp>"),
        ("<user_query>Review this</user_query>\n<attached_files>\nfile contents\n</attached_files>", "Review this", "<attached_files>"),
        ("<user_query>\nLine one\nLine two\n</user_query>", "Line one\nLine two", "<user_query>"),
    ]
)
def test_xml_tag_stripping(text, expected_in, expected_not_in):
    raw = {
        "role": "user",
        "timestamp": "2026-05-01T10:00:00.000Z",
        "message": {"content": [{"type": "text", "text": text}]},
    }
    events = parse_rows([_row(raw)])
    assert len(events) == 1
    body = events[0]["attributes"]["tool_input"]
    assert expected_not_in not in body
    assert expected_in in body


def test_user_plain_string_fallback():
    raw = {
        "role": "user",
        "timestamp": "2026-05-01T10:00:00.000Z",
        "message": {"content": "plain string content"},
    }
    events = parse_rows([_row(raw)])
    assert len(events) == 1
    assert events[0]["event_name"] == "hook_userpromptsubmit"
    assert events[0]["attributes"]["tool_input"] == "plain string content"


def test_assistant_response_and_tokens():
    raw = {
        "role": "assistant",
        "timestamp": "2026-05-01T10:01:00.000Z",
        "message": {
            "content": [{"type": "text", "text": "Here is the answer."}],
            "usage": {
                "input_tokens": 100,
                "output_tokens": 10,
                "cache_read_input_tokens": 300,
                "cache_creation_input_tokens": 100,
            },
            "model": "claude-sonnet-4-5",
            "stop_reason": "end_turn",
        },
    }
    events = parse_rows([_row(raw)])
    assert len(events) == 1
    ev = events[0]
    assert ev["event_name"] == "hook_assistant_response"
    assert "Here is the answer." in ev["attributes"]["tool_response"]
    attrs = ev["attributes"]
    assert attrs["input_tokens"] == "100"
    assert attrs["output_tokens"] == "10"
    assert attrs["model"] == "claude-sonnet-4-5"
    assert attrs["stop_reason"] == "end_turn"
    assert attrs["cache_read_tokens"] == "300"
    assert attrs["cache_creation_tokens"] == "100"


def test_assistant_thinking():
    long_thought = "x" * 200
    raw = {
        "role": "assistant",
        "timestamp": "2026-05-01T10:01:00.000Z",
        "message": {
            "content": [
                {"type": "thinking", "thinking": long_thought},
                {"type": "text", "text": "The result is 42."},
            ],
            "model": "claude-sonnet-4-5",
            "stop_reason": "end_turn",
        },
    }
    events = parse_rows([_row(raw)])
    names = [e["event_name"] for e in events]
    assert "hook_assistant_thinking" in names
    assert "hook_assistant_response" in names

    thinking_event = next(e for e in events if e["event_name"] == "hook_assistant_thinking")
    assert len(thinking_event["body"]) <= 100
    assert thinking_event["attributes"]["tool_response"] == long_thought


def test_tool_use_and_result_merging():
    # 1. Tool Use
    tool_use_row = _row({
        "role": "assistant",
        "timestamp": "2026-05-01T10:01:00.000Z",
        "message": {
            "content": [{"type": "tool_use", "id": "toolu_xyz", "name": "bash", "input": {"command": "ls"}}],
            "model": "claude-sonnet-4-5",
            "stop_reason": "tool_use",
        },
    })
    # 2. Tool Result (String)
    tool_result_row = _row({
        "role": "user",
        "timestamp": "2026-05-01T10:01:01.000Z",
        "message": {
            "content": [{"type": "tool_result", "tool_use_id": "toolu_xyz", "content": "file1.txt"}]
        },
    })
    events = parse_rows([tool_use_row, tool_result_row])
    assert len(events) == 1
    assert events[0]["event_name"] == "hook_posttooluse"
    assert events[0]["body"] == "bash"
    assert json.loads(events[0]["attributes"]["tool_input"]) == {"command": "ls"}
    assert "file1.txt" in events[0]["attributes"]["tool_response"]


def test_tool_result_list_content_and_orphans():
    tool_use_row = _row({
        "role": "assistant",
        "timestamp": "2026-05-01T10:01:00.000Z",
        "message": {
            "content": [{"type": "tool_use", "id": "toolu_list", "name": "search", "input": {"q": "test"}}],
            "model": "claude-sonnet-4-5",
            "stop_reason": "tool_use",
        },
    })
    tool_result_row = _row({
        "role": "user",
        "timestamp": "2026-05-01T10:01:01.000Z",
        "message": {
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "toolu_list",
                    "content": [{"type": "text", "text": "Result one"}],
                }
            ]
        },
    })
    # Orphan result 
    orphan_result_row = _row({
        "role": "user",
        "timestamp": "2026-05-01T10:01:01.000Z",
        "message": {
            "content": [{"type": "tool_result", "tool_use_id": "toolu_orphan", "content": "some output"}]
        },
    })
    events = parse_rows([tool_use_row, tool_result_row, orphan_result_row])
    tool_events = [e for e in events if e["event_name"] == "hook_posttooluse"]
    assert len(tool_events) == 1
    assert "Result one" in tool_events[0]["attributes"]["tool_response"]


def test_tool_turn_token_usage_and_multiple_tools():
    raw_tok = {
        "role": "assistant",
        "timestamp": "2026-05-01T10:01:00.000Z",
        "message": {
            "content": [{"type": "tool_use", "id": "toolu_tok", "name": "bash", "input": {"cmd": "pwd"}}],
            "usage": {"input_tokens": 400, "output_tokens": 25},
            "model": "claude-sonnet-4-5",
            "stop_reason": "tool_use",
        },
    }
    events_tok = parse_rows([_row(raw_tok)])
    assert "hook_token_usage" in [e["event_name"] for e in events_tok]
    tok_event = next(e for e in events_tok if e["event_name"] == "hook_token_usage")
    assert tok_event["attributes"]["input_tokens"] == "400"

    raw_mult = {
        "role": "assistant",
        "timestamp": "2026-05-01T10:01:00.000Z",
        "message": {
            "content": [
                {"type": "tool_use", "id": "toolu_a", "name": "read_file", "input": {"path": "a.txt"}},
                {"type": "tool_use", "id": "toolu_b", "name": "read_file", "input": {"path": "b.txt"}},
            ],
            "model": "claude-sonnet-4-5",
            "stop_reason": "tool_use",
        },
    }
    events_mult = parse_rows([_row(raw_mult)])
    tool_events = [e for e in events_mult if e["event_name"] == "hook_posttooluse"]
    assert len(tool_events) == 2
    assert {e["attributes"]["tool_use_id"] for e in tool_events} == {"toolu_a", "toolu_b"}


def test_edge_cases():
    assert parse_rows([]) == []

    # Missing raw line fallback
    row_missing = _row({"role": "user", "message": {"content": []}}, raw_line="")
    assert len(parse_rows([row_missing])) == 1

    # Invalid JSON fallback
    row_invalid = {
        "raw_line": "invalid json {",
        "ide": IDE,
        "timestamp": "2026-05-01 10:00:00.000",
        "ingested_at": "2026-05-01 10:00:01.000",
        "event_type": "fallback",
        "content_preview": "preview",
        "tool_name": None,
        "tool_id": None,
        "uuid": None,
        "parent_uuid": None,
        "content_length": 0,
    }
    events = parse_rows([row_invalid])
    assert len(events) == 1
    assert events[0]["body"] == "preview"

    # Unknown role fallback
    raw_unknown = {
        "role": "system",
        "timestamp": "2026-05-01T10:00:00.000Z",
        "message": {"content": "initializing"},
    }
    assert len(parse_rows([_row(raw_unknown)])) == 1


def test_timestamps():
    # ISO normalisation
    raw_iso = {
        "role": "user",
        "timestamp": "2026-05-01T09:30:45.123Z",
        "message": {"content": [{"type": "text", "text": "hi"}]},
    }
    assert parse_rows([_row(raw_iso)])[0]["timestamp"] == "2026-05-01 09:30:45.123"

    raw_no_ts = {
        "role": "user",
        "message": {"content": [{"type": "text", "text": "hi"}]},
    }
    row = _row(raw_no_ts, timestamp="2026-05-02 08:00:00.000")
    assert parse_rows([row])[0]["timestamp"] == "2026-05-02 08:00:00.000"


def test_registry_integration():
    import importlib
    from services.session_parsers import _PARSERS
    from services.session_parsers.cursor import parse_rows as cursor_parse

    server_reg = importlib.import_module("schemas.ide_registry")
    assert server_reg.IDE_REGISTRY["cursor"]["session_parser"] == "cursor"
    assert _PARSERS["cursor"] is cursor_parse
