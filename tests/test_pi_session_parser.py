# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Tests for Pi session parser and classifiers."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "observal-server"))

from services.session_ingest import _usage_pi, _uuid_pi
from services.session_parsers.ingest_classify import (
    _classify_pi,
    _preview_pi,
    _tool_info_pi,
    _ts_pi,
)

# ── Sample Pi JSONL lines ─────────────────────────────────────────────────────

SESSION_HEADER = (
    '{"type":"session","version":3,"id":"019e5adf-dd81","timestamp":"2026-05-24T16:44:41.217Z","cwd":"/Users/test"}'
)
MODEL_CHANGE = '{"type":"model_change","id":"d6ec41d1","parentId":null,"timestamp":"2026-05-24T09:04:17.964Z","provider":"amazon-bedrock","modelId":"eu.anthropic.claude-opus-4-6-v1"}'
THINKING_LEVEL = '{"type":"thinking_level_change","id":"8bc16d27","parentId":"d6ec41d1","timestamp":"2026-05-24T09:04:17.964Z","thinkingLevel":"high"}'
USER_PROMPT = '{"type":"message","id":"e67e72b6","parentId":"8bc16d27","timestamp":"2026-05-24T09:04:17.968Z","message":{"role":"user","content":[{"type":"text","text":"what is 2+2"}],"timestamp":1779624000000}}'
ASSISTANT_THINKING = '{"type":"message","id":"e91018f9","parentId":"e67e72b6","timestamp":"2026-05-24T09:04:23.288Z","message":{"role":"assistant","content":[{"type":"thinking","thinking":"4."},{"type":"text","text":"The answer is 4."}],"api":"bedrock-converse-stream","provider":"amazon-bedrock","model":"eu.anthropic.claude-opus-4-6-v1","usage":{"input":3,"output":4,"cacheRead":100,"cacheWrite":200,"totalTokens":307,"cost":{"input":0.00001,"output":0.00006,"cacheRead":0.0001,"cacheWrite":0.001,"total":0.00117}},"stopReason":"stop","timestamp":1779624005000}}'
TOOL_CALL = '{"type":"message","id":"cba220e0","parentId":"075da560","timestamp":"2026-05-24T13:35:54.577Z","message":{"role":"assistant","content":[{"type":"toolCall","id":"tooluse_abc123","name":"read","arguments":{"path":"/tmp/test.txt"}}],"model":"eu.anthropic.claude-opus-4-6-v1","usage":{"input":10,"output":20,"cacheRead":0,"cacheWrite":0},"stopReason":"toolUse","timestamp":1779629754577}}'
TOOL_RESULT = '{"type":"message","id":"075da560","parentId":"cba220e0","timestamp":"2026-05-24T13:35:49.253Z","message":{"role":"toolResult","toolCallId":"tooluse_abc123","toolName":"read","content":[{"type":"text","text":"file contents here"}],"isError":false,"timestamp":1779629749253}}'
BASH_EXECUTION = '{"type":"message","id":"bash1","parentId":"prev1","timestamp":"2026-05-24T10:00:00.000Z","message":{"role":"bashExecution","command":"ls -la","output":"total 0\\ndrwxr-xr-x 2 user staff 64 May 24 10:00 .","exitCode":0,"cancelled":false,"truncated":false,"timestamp":1779624000000}}'
CUSTOM_ENTRY = '{"type":"custom","id":"h8i9j0k1","parentId":"g7h8i9j0","timestamp":"2026-05-24T14:20:00.000Z","customType":"my-extension","data":{"count":42}}'
COMPACTION = '{"type":"compaction","id":"f6g7h8i9","parentId":"e5f6g7h8","timestamp":"2026-05-24T14:10:00.000Z","summary":"User discussed project setup and configuration.","firstKeptEntryId":"c3d4e5f6","tokensBefore":50000}'
EMPTY_USER = '{"type":"message","id":"empty1","parentId":"prev1","timestamp":"2026-05-24T10:00:00.000Z","message":{"role":"user","content":[],"timestamp":1779624000000}}'


class TestClassifyPi:
    def test_session_header_skipped(self):
        assert _classify_pi(json.loads(SESSION_HEADER)) is None

    def test_model_change_is_system(self):
        assert _classify_pi(json.loads(MODEL_CHANGE)) == "system"

    def test_thinking_level_is_system(self):
        assert _classify_pi(json.loads(THINKING_LEVEL)) == "system"

    def test_user_prompt(self):
        assert _classify_pi(json.loads(USER_PROMPT)) == "user_prompt"

    def test_empty_user_prompt_skipped(self):
        assert _classify_pi(json.loads(EMPTY_USER)) is None

    def test_assistant_with_thinking_is_thinking(self):
        assert _classify_pi(json.loads(ASSISTANT_THINKING)) == "thinking"

    def test_tool_call(self):
        assert _classify_pi(json.loads(TOOL_CALL)) == "tool_call"

    def test_tool_result(self):
        assert _classify_pi(json.loads(TOOL_RESULT)) == "tool_result"

    def test_bash_execution_is_tool_result(self):
        assert _classify_pi(json.loads(BASH_EXECUTION)) == "tool_result"

    def test_custom_entry_skipped(self):
        assert _classify_pi(json.loads(CUSTOM_ENTRY)) is None

    def test_compaction_is_meta(self):
        assert _classify_pi(json.loads(COMPACTION)) == "meta"


class TestPreviewPi:
    def test_user_prompt_preview(self):
        parsed = json.loads(USER_PROMPT)
        assert _preview_pi(parsed, "user_prompt") == "what is 2+2"

    def test_assistant_text_preview(self):
        parsed = json.loads(ASSISTANT_THINKING)
        # First block is thinking, so preview picks that
        preview = _preview_pi(parsed, "thinking")
        assert "4." in preview

    def test_tool_call_preview(self):
        parsed = json.loads(TOOL_CALL)
        preview = _preview_pi(parsed, "tool_call")
        assert "[tool_call: read]" in preview

    def test_tool_result_preview(self):
        parsed = json.loads(TOOL_RESULT)
        preview = _preview_pi(parsed, "tool_result")
        assert "[read]" in preview
        assert "file contents" in preview

    def test_bash_preview(self):
        parsed = json.loads(BASH_EXECUTION)
        preview = _preview_pi(parsed, "tool_result")
        assert preview == "$ ls -la"

    def test_model_change_preview(self):
        parsed = json.loads(MODEL_CHANGE)
        preview = _preview_pi(parsed, "system")
        assert "amazon-bedrock" in preview
        assert "claude-opus" in preview

    def test_compaction_preview(self):
        parsed = json.loads(COMPACTION)
        preview = _preview_pi(parsed, "meta")
        assert "project setup" in preview


class TestToolInfoPi:
    def test_tool_call_extracts_name_and_id(self):
        parsed = json.loads(TOOL_CALL)
        name, tool_id = _tool_info_pi(parsed)
        assert name == "read"
        assert tool_id == "tooluse_abc123"

    def test_tool_result_extracts_name_and_id(self):
        parsed = json.loads(TOOL_RESULT)
        name, tool_id = _tool_info_pi(parsed)
        assert name == "read"
        assert tool_id == "tooluse_abc123"

    def test_user_prompt_returns_none(self):
        parsed = json.loads(USER_PROMPT)
        name, tool_id = _tool_info_pi(parsed)
        assert name is None
        assert tool_id is None

    def test_non_message_returns_none(self):
        parsed = json.loads(MODEL_CHANGE)
        name, tool_id = _tool_info_pi(parsed)
        assert name is None
        assert tool_id is None


class TestTimestampPi:
    def test_extracts_iso_timestamp(self):
        parsed = json.loads(USER_PROMPT)
        ts = _ts_pi(parsed)
        assert ts == "2026-05-24 09:04:17.968"

    def test_no_timestamp_returns_none(self):
        assert _ts_pi({}) is None

    def test_adds_millis_if_missing(self):
        parsed = {"timestamp": "2026-05-24T10:00:00Z"}
        ts = _ts_pi(parsed)
        assert ts == "2026-05-24 10:00:00.000"


class TestUsagePi:
    def test_extracts_pi_usage_fields(self):
        parsed = json.loads(ASSISTANT_THINKING)
        result = _usage_pi(parsed)
        assert result["input_tokens"] == 3
        assert result["output_tokens"] == 4
        assert result["cache_read_tokens"] == 100
        assert result["cache_write_tokens"] == 200
        assert result["model"] == "eu.anthropic.claude-opus-4-6-v1"

    def test_missing_usage_returns_zeros(self):
        parsed = json.loads(USER_PROMPT)
        result = _usage_pi(parsed)
        assert result["input_tokens"] == 0
        assert result["output_tokens"] == 0


class TestUuidPi:
    def test_extracts_id_and_parent_id(self):
        parsed = json.loads(USER_PROMPT)
        uuid, parent_uuid = _uuid_pi(parsed)
        assert uuid == "e67e72b6"
        assert parent_uuid == "8bc16d27"

    def test_null_parent_id(self):
        parsed = json.loads(MODEL_CHANGE)
        uuid, parent_uuid = _uuid_pi(parsed)
        assert uuid == "d6ec41d1"
        assert parent_uuid is None
