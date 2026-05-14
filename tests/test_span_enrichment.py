# SPDX-FileCopyrightText: 2026 Swathi Saravanan <ss4522@cornell.edu>
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Tests for SDK Phase 1 span enrichment + tool file extraction."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "observal-server"))


from schemas.telemetry import SpanIngest
from services.span_enrichment import (
    OUTPUT_EXCERPT_MAX_CHARS,
    compute_output_excerpt,
    compute_tool_result_hash,
    enrich_span,
)
from services.tool_file_extraction import extract_files


def _span(**overrides) -> SpanIngest:
    base = {
        "span_id": "s1",
        "trace_id": "t1",
        "type": "tool_call",
        "name": "Read",
        "start_time": "2026-05-08T00:00:00Z",
    }
    base.update(overrides)
    return SpanIngest(**base)


# ── tool_file_extraction ──


class TestExtractFiles:
    def test_unknown_tool_returns_empty(self):
        assert extract_files("MysteryTool", None, '{"file_path": "/x"}') == ([], [])

    def test_no_input_returns_empty(self):
        assert extract_files("Read", None, None) == ([], [])
        assert extract_files("Read", None, "") == ([], [])

    def test_invalid_json_returns_empty(self):
        assert extract_files("Read", None, "not json") == ([], [])

    def test_read(self):
        reads, writes = extract_files("Read", None, '{"file_path": "/tmp/a.py"}')
        assert reads == ["/tmp/a.py"]
        assert writes == []

    def test_write(self):
        reads, writes = extract_files("Write", None, '{"file_path": "/tmp/b.py", "content": "x"}')
        assert reads == []
        assert writes == ["/tmp/b.py"]

    def test_edit_is_both(self):
        reads, writes = extract_files("Edit", None, '{"file_path": "/tmp/c.py", "old_string": "a", "new_string": "b"}')
        assert reads == ["/tmp/c.py"]
        assert writes == ["/tmp/c.py"]

    def test_notebook_edit_is_both(self):
        reads, writes = extract_files("NotebookEdit", None, '{"notebook_path": "/n.ipynb", "new_source": "x"}')
        assert reads == ["/n.ipynb"]
        assert writes == ["/n.ipynb"]

    def test_glob_returns_empty(self):
        assert extract_files("Glob", None, '{"pattern": "**/*.py"}') == ([], [])

    def test_grep_returns_empty(self):
        assert extract_files("Grep", None, '{"pattern": "TODO"}') == ([], [])

    def test_bash_returns_empty(self):
        # Bash extraction is intentionally deferred
        assert extract_files("Bash", None, '{"command": "echo hi > /tmp/x"}') == ([], [])

    def test_method_takes_precedence_over_name(self):
        # method wins when both are set
        reads, _ = extract_files(name="Glob", method="Read", input_str='{"file_path": "/m"}')
        assert reads == ["/m"]

    def test_falls_back_to_name(self):
        reads, _ = extract_files(name="Read", method="", input_str='{"file_path": "/n"}')
        assert reads == ["/n"]

    def test_falls_back_to_metadata(self):
        reads, _ = extract_files(
            name=None, method=None, input_str='{"file_path": "/m"}', metadata={"tool_name": "Read"}
        )
        assert reads == ["/m"]

    def test_missing_param_in_input(self):
        assert extract_files("Read", None, '{"unrelated": "x"}') == ([], [])

    def test_non_string_param_value(self):
        assert extract_files("Read", None, '{"file_path": 42}') == ([], [])


# ── compute_output_excerpt ──


class TestOutputExcerpt:
    def test_short_output_unchanged_length(self):
        assert compute_output_excerpt("hello") == "hello"

    def test_caps_at_max(self):
        big = "x" * 5000
        excerpt = compute_output_excerpt(big)
        assert len(excerpt) == OUTPUT_EXCERPT_MAX_CHARS == 2048

    def test_redacts_openai_key(self):
        text = "leak: sk-abcdefghijklmnopqrstuvwxyz1234567890"
        excerpt = compute_output_excerpt(text)
        assert "sk-abcdefghijklmnopqrstuvwxyz1234567890" not in excerpt

    def test_redacts_slack_token(self):
        token = "xoxb-" + "1234567890-" + "1234567890-" + "AbCdEfGhIjKlMnOpQrStUvWx"
        text = f"slack: {token}"
        excerpt = compute_output_excerpt(text)
        assert token not in excerpt


# ── compute_tool_result_hash ──


class TestToolResultHash:
    def test_deterministic(self):
        a = compute_tool_result_hash('{"a": 1, "b": 2}')
        b = compute_tool_result_hash('{"a": 1, "b": 2}')
        assert a == b
        assert len(a) == 64

    def test_key_order_invariant(self):
        a = compute_tool_result_hash('{"a": 1, "b": 2}')
        b = compute_tool_result_hash('{"b": 2, "a": 1}')
        assert a == b

    def test_different_content_different_hash(self):
        a = compute_tool_result_hash('{"a": 1}')
        b = compute_tool_result_hash('{"a": 2}')
        assert a != b

    def test_non_json_still_hashes(self):
        # Plain text outputs hash deterministically too
        a = compute_tool_result_hash("hello world")
        b = compute_tool_result_hash("hello world")
        assert a == b
        assert a != compute_tool_result_hash("hello universe")


# ── enrich_span ──


class TestEnrichSpan:
    def test_all_fields_populated_passthrough(self):
        s = _span(
            output="ignored",
            input='{"file_path": "/should/not/run"}',
            sdk_version="0.4.0",
            output_excerpt="custom",
            tool_result_hash="a" * 64,
            files_read=["/x"],
            files_written=["/y"],
            intent_label="search_kb",
            references=["s0"],
        )
        out = enrich_span(s)
        assert out.output_excerpt == "custom"
        assert out.tool_result_hash == "a" * 64
        assert out.files_read == ["/x"]
        assert out.files_written == ["/y"]
        assert out.sdk_version == "0.4.0"
        assert out.intent_label == "search_kb"
        assert out.references == ["s0"]

    def test_derives_when_absent(self):
        s = _span(
            name="Write",
            method="",
            input='{"file_path": "/tmp/z.py", "content": "x"}',
            output='{"ok": true}',
        )
        out = enrich_span(s)
        assert out.output_excerpt == '{"ok": true}'
        assert out.tool_result_hash and len(out.tool_result_hash) == 64
        assert out.files_read == []
        assert out.files_written == ["/tmp/z.py"]
        # annotation-only fields stay empty
        assert out.intent_label is None
        assert out.references is None
        # sdk_version not derived; caller's responsibility
        assert out.sdk_version is None

    def test_caller_excerpt_not_overwritten(self):
        s = _span(output="real output", output_excerpt="precomputed")
        assert enrich_span(s).output_excerpt == "precomputed"

    def test_excerpt_redacts_secret(self):
        s = _span(output="key=sk-abcdefghijklmnopqrstuvwxyz1234567890")
        out = enrich_span(s)
        assert "sk-abcdefghijklmnopqrstuvwxyz1234567890" not in (out.output_excerpt or "")

    def test_no_output_no_excerpt(self):
        s = _span(output=None)
        out = enrich_span(s)
        assert out.output_excerpt is None
        assert out.tool_result_hash is None

    def test_unknown_tool_yields_empty_arrays(self):
        s = _span(name="MysteryTool", input='{"file_path": "/x"}')
        out = enrich_span(s)
        assert out.files_read == []
        assert out.files_written == []

    def test_files_partial_caller_provided_skips_extraction(self):
        # If caller provided either list, don't run extraction (avoid clobber)
        s = _span(name="Read", input='{"file_path": "/x"}', files_read=["/preset"])
        out = enrich_span(s)
        assert out.files_read == ["/preset"]
        # files_written stays None because caller signaled they own this field
        assert out.files_written is None

    def test_canonicalization_invariant_for_hash(self):
        s1 = _span(output='{"a": 1, "b": 2}')
        s2 = _span(output='{"b": 2, "a": 1}')
        assert enrich_span(s1).tool_result_hash == enrich_span(s2).tool_result_hash
