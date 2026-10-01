# SPDX-FileCopyrightText: 2026 SrihariLegend <sriharilegend23@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""DeepSeek Harness v4 classification and trace rendering."""

from __future__ import annotations

import json

import pytest

from services.session_ingest import _extract_usage_tokens, _extract_uuid
from services.session_parsers import parse_raw_events
from services.session_parsers.ingest_classify import classify, extract_preview, extract_timestamp, extract_tool_info

_TIME = 1780000000123


def _record(kind: str, data: object = None, **kwargs) -> dict:
    return {"type": kind, "seq": 0, "time": _TIME, "data": data if data is not None else {}, **kwargs}


def _row(record: dict | str) -> dict:
    return {
        "harness": "deepseek",
        "raw_line": json.dumps(record) if isinstance(record, dict) else record,
        "timestamp": "1970-01-01 00:00:00.000",
        "ingested_at": "2026-05-28 00:00:01.000",
        "event_type": "system",
    }


def _assistant(content: list, usage: object = None, **kwargs) -> dict:
    data = {
        "turn": 1,
        "step": 0,
        "message": {
            "id": "assistant-1",
            "role": "assistant",
            "content": content,
            "source": {"kind": "model", "provider": "deepseek", "model": "deepseek-chat"},
        },
        "stream": [
            {"type": "text-chunks", "time0": _TIME, "index": 0, "dt": [], "texts": ["DO NOT DUPLICATE"]},
            {"type": "reasoning-chunks", "time0": _TIME, "index": 1, "dt": [], "texts": ["DO NOT DUPLICATE"]},
            {"type": "tool-call-chunks", "time0": _TIME, "index": 2, "dt": [], "args": ["DO NOT DUPLICATE"]},
        ],
        **kwargs,
    }
    if usage is not None:
        data["usage"] = usage
    return _record("assistant/message", data, surfaceOp="append")


def test_ingest_columns_use_deepseek_usage_without_recounting_stream():
    assistant = _assistant(
        [{"type": "text", "text": "Done"}],
        {
            "inputTokens": 10,
            "outputTokens": 5,
            "cacheReadTokens": 2,
            "cacheWriteTokens": 3,
        },
    )
    assistant["data"]["stream"].append(
        {
            "type": "chunk",
            "time": _TIME,
            "chunk": {
                "type": "usage",
                "usage": {"inputTokens": 999, "outputTokens": 999},
            },
        }
    )
    assert _extract_usage_tokens(assistant, "deepseek") == {
        "input_tokens": 10,
        "output_tokens": 5,
        "cache_read_tokens": 2,
        "cache_write_tokens": 3,
        "model": "deepseek-chat",
    }
    assert _extract_usage_tokens(_record("user/message", {"usage": {"inputTokens": 99}}), "deepseek") == {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
        "model": "",
    }


def test_ingest_columns_capture_usage_reported_on_uncommitted_attempt():
    attempt = _record(
        "assistant/attempt",
        {
            "turn": 1,
            "step": 0,
            "stream": [
                {
                    "type": "chunk",
                    "time": _TIME,
                    "chunk": {
                        "type": "usage",
                        "usage": {
                            "inputTokens": 4,
                            "outputTokens": 1,
                            "cacheReadTokens": 2,
                            "cacheWriteTokens": 0,
                        },
                    },
                },
                {
                    "type": "chunk",
                    "time": _TIME,
                    "chunk": {
                        "type": "finish",
                        "reason": {
                            "kind": "error",
                            "failure": {"code": "NETWORK", "message": "Timed out"},
                        },
                    },
                },
            ],
        },
    )
    assert _extract_usage_tokens(attempt, "deepseek") == {
        "input_tokens": 4,
        "output_tokens": 1,
        "cache_read_tokens": 2,
        "cache_write_tokens": 0,
        "model": "",
    }


@pytest.mark.parametrize(
    "bad_usage",
    [None, [], 12, {"inputTokens": "5", "outputTokens": True, "cacheReadTokens": -1, "cacheWriteTokens": {}}],
)
def test_ingest_usage_rejects_malformed_counts(bad_usage):
    assistant = _assistant([], bad_usage)
    assistant["data"]["message"]["source"] = []
    assert _extract_usage_tokens(assistant, "deepseek") == {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
        "model": "",
    }
    attempt = _record(
        "assistant/attempt",
        {
            "stream": [
                None,
                "bad",
                {
                    "type": "chunk",
                    "chunk": {"type": "usage", "usage": bad_usage},
                },
            ]
        },
    )
    assert _extract_usage_tokens(attempt, "deepseek")["input_tokens"] == 0


def test_ingest_columns_use_v4_ids_and_pair_tool_results():
    assert _extract_uuid({"type": "session", "id": "session-1", "parentSession": "parent"}, "deepseek") == (
        "session-1",
        "parent",
    )
    assert _extract_uuid(_record("user/message", {"id": "user-1"}), "deepseek") == ("user-1", None)
    assert _extract_uuid(_assistant([]), "deepseek") == ("assistant-1", None)
    assert _extract_uuid(_record("tool/call", {"callId": "call-1"}), "deepseek") == ("call-1", None)
    result = _record("tool/result", {"message": {"id": "result-1", "toolCallId": "call-1"}})
    assert _extract_uuid(result, "deepseek") == ("result-1", "call-1")
    assert _extract_uuid(_record("step/start", {"turn": 1}), "deepseek") == ("seq:0", None)
    assert _extract_uuid({"type": "tool/result", "seq": True, "data": {"message": []}}, "deepseek") == (
        None,
        None,
    )


def test_v4_session_messages_usage_and_turn_boundaries():
    header = {
        "type": "session",
        "version": 4,
        "id": "s-1",
        "createdAt": _TIME - 1,
        "cwd": "/workspace",
        "parentSession": "s-parent",
        "isSeeded": False,
        "delegationDepth": 1,
    }
    user = _record(
        "user/message",
        {
            "id": "u-1",
            "role": "user",
            "source": {"kind": "user"},
            "content": [{"type": "text", "text": "Fix this"}],
        },
        surfaceOp="append",
    )
    assistant = _assistant(
        [
            {"type": "reasoning", "text": "First think"},
            {"type": "text", "text": "Done"},
            {"type": "text", "text": "Next"},
        ],
        {
            "inputTokens": 10,
            "outputTokens": 5,
            "totalTokens": 17,
            "cacheReadTokens": 2,
            "cacheWriteTokens": 0,
            "reasoningTokens": 3,
        },
    )
    events = parse_raw_events(
        [
            _row(header),
            _row(_record("turn/start", {"turn": 1})),
            _row(user),
            _row(assistant),
            _row(_record("turn/end", {"turn": 1, "reason": {"kind": "completed"}})),
        ]
    )
    assert [e["event_name"] for e in events] == [
        "hook_sessionstart",
        "hook_sessionstart",
        "hook_userpromptsubmit",
        "hook_assistant_thinking",
        "hook_assistant_response",
        "hook_stop",
    ]
    assert events[0]["timestamp"] == "2026-05-28 20:26:40.122"
    assert events[0]["attributes"]["parentSession"] == "s-parent"
    assert events[2]["attributes"]["tool_input"] == "Fix this"
    assert events[3]["attributes"]["tool_response"] == "First think"
    assert events[4]["attributes"]["tool_response"] == "Done\nNext"
    assert events[4]["attributes"]["cache_read_tokens"] == "2"
    assert events[4]["attributes"]["cache_creation_tokens"] == "0"
    assert events[4]["attributes"]["reasoning_tokens"] == "3"
    assert events[4]["attributes"]["provider"] == "deepseek"
    assert events[-1]["attributes"]["reason"] == "completed"
    assert "DO NOT DUPLICATE" not in str(events)


def test_tools_pair_results_and_retain_orphans_and_error_details():
    call = _record(
        "tool/call", {"turn": 1, "step": 0, "callId": "c-1", "name": "shell", "arguments": '{"command":"ls"}'}
    )
    tool_content = {
        "role": "tool",
        "toolCallId": "c-1",
        "content": [{"type": "text", "text": "Failed"}],
        "isError": True,
    }
    result = _record(
        "tool/result",
        {
            "turn": 1,
            "step": 0,
            "message": tool_content,
            "error": {"name": "ToolError", "code": "EXIT", "reason": "not found"},
            "meta": {"exitCode": 1},
        },
        surfaceOp={"op": "replace", "startSeq": 2, "endSeq": 2},
        sourceEventSeqs=[2],
    )
    orphan = _record("tool/result", {"turn": 2, "step": 1, "message": {**tool_content, "toolCallId": "missing"}})
    assistant = _assistant(
        [{"type": "tool-call", "id": "c-1", "name": "shell", "arguments": "{}"}], {"inputTokens": 1, "outputTokens": 2}
    )
    events = parse_raw_events([_row(assistant), _row(call), _row(result), _row(orphan)])
    assert [e["event_name"] for e in events] == ["hook_token_usage", "hook_posttooluse", "hook_posttooluse"]
    attrs = events[1]["attributes"]
    assert attrs["tool_input"] == '{"command":"ls"}'
    assert attrs["tool_response"] == "Failed"
    assert attrs["tool_use_id"] == "c-1"
    assert attrs["is_error"] == "true"
    assert attrs["error_code"] == "EXIT"
    assert attrs["error_reason"] == "not found"
    assert json.loads(attrs["meta"]) == {"exitCode": 1}
    assert attrs["surface_op"] == "replace"
    assert json.loads(attrs["source_event_seqs"]) == [2]
    assert attrs["tool_result_timestamp"] == events[1]["timestamp"]
    assert events[2]["attributes"]["tool_use_id"] == "missing"


def test_attempt_failure_and_structural_records_do_not_fabricate_assistant_output():
    attempt = _record(
        "assistant/attempt",
        {
            "turn": 1,
            "step": 0,
            "stream": [
                {"type": "text-chunks", "time0": _TIME, "index": 0, "dt": [], "texts": ["uncommitted"]},
                {
                    "type": "chunk",
                    "time": _TIME,
                    "chunk": {
                        "type": "finish",
                        "reason": {
                            "kind": "error",
                            "failure": {"code": "NETWORK", "message": "Provider unavailable"},
                        },
                    },
                },
            ],
        },
    )
    events = parse_raw_events(
        [
            _row(_record("request/header", {"reason": "initial"})),
            _row(_record("step/start", {"turn": 1, "step": 0})),
            _row(attempt),
            _row(_record("new/extension", {"value": 1})),
        ]
    )
    assert [e["event_name"] for e in events] == ["system", "system", "hook_error", "system"]
    assert events[2]["attributes"]["error_code"] == "NETWORK"
    assert events[2]["body"] == "Provider unavailable"
    assert "uncommitted" not in str(events)


@pytest.mark.parametrize("value", [None, "123", True, -1, 10**40, [], {}])
def test_bad_timestamps_fall_back_without_crashing(value):
    line = _record("turn/end", {"reason": {"kind": "error"}, "turn": 1}, time=value)
    assert extract_timestamp("deepseek", line) is None
    assert parse_raw_events([_row(line)])[0]["timestamp"] == "2026-05-28 00:00:01.000"


def test_malformed_nested_fields_and_raw_json_remain_safe():
    records = [
        _assistant("bad", {"inputTokens": "unknown", "outputTokens": True}),
        _record("tool/result", {"message": [1], "error": "bad"}),
        _record("user/message", {"content": [None, [], {"type": [], "text": 42}]}),
        _record("assistant/attempt", {"stream": [None, 3, {"type": "chunk", "chunk": []}]}),
        {"type": [], "data": "bad"},
    ]
    events = parse_raw_events([*map(_row, records), _row("not json"), _row("[]")])
    assert len(events) >= len(records) + 2
    assert events[-1]["event_name"] == "system"


def test_turn_end_error_keeps_failure_details():
    end = _record(
        "turn/end",
        {
            "turn": 1,
            "reason": {
                "kind": "error",
                "error": {"code": "NETWORK", "message": "Provider unavailable"},
            },
        },
    )
    event = parse_raw_events([_row(end)])[0]
    assert event["event_name"] == "hook_stop"
    assert event["attributes"]["reason"] == "error"
    assert event["attributes"]["error_code"] == "NETWORK"
    assert extract_preview("deepseek", end, "system") == "Turn ended: error"


def test_dispatch_classifier_preview_timestamp_and_tool_info():
    call = _record("tool/call", {"name": "shell", "callId": "c-1", "arguments": "{}"})
    result = _record("tool/result", {"message": {"toolCallId": "c-1", "content": [{"type": "text", "text": "ok"}]}})
    assert classify("deepseek", {"type": "session", "version": 4}) == "system"
    assert classify("deepseek", _record("request/header", {})) == "meta"
    assert classify("deepseek", _assistant([{"type": "reasoning", "text": "Think"}])) == "thinking"
    assert classify("deepseek", call) == "tool_call"
    assert classify("deepseek", result) == "tool_result"
    assert classify("deepseek", {"type": "future/record", "data": {}}) == "system"
    assert extract_preview("deepseek", call, "tool_call") == "[tool_call: shell]"
    assert extract_preview("deepseek", result, "tool_result") == "ok"
    assert extract_tool_info("deepseek", call) == ("shell", "c-1")
    assert extract_tool_info("deepseek", result) == (None, "c-1")
    assert extract_timestamp("deepseek", call) == "2026-05-28 20:26:40.123"
    assert extract_timestamp("deepseek", {"type": "session", "createdAt": _TIME - 1}) == "2026-05-28 20:26:40.122"
