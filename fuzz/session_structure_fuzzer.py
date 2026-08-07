#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 RAWx18 <rawx18.dev@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Structure-aware companion to ``session_jsonl_fuzzer``.

Byte mutation spends most of its budget on JSON syntax, so it rarely reaches
the branches that only fire for well-formed transcript records. This harness
uses Hypothesis to build JSON objects out of the discriminator keys and values
the eight session parsers actually switch on, which pushes coverage past the
decoder and into the per-harness handlers.

The module is a polyglot: run it under pytest to replay, shrink and minimise
any known failing example, or run it directly for Atheris to drive Hypothesis
with libFuzzer's mutations.

    pytest fuzz/session_structure_fuzzer.py
    python3 fuzz/session_structure_fuzzer.py -atheris_runs=100000
"""

import json
import sys

import atheris
from hypothesis import given, settings
from hypothesis import strategies as st

with atheris.instrument_imports():
    import _session

# Top-level and nested keys the parsers dispatch on, across all eight formats.
_KEYS = [
    "agentId",
    "arguments",
    "attachment",
    "content",
    "created_at",
    "credits",
    "data",
    "event",
    "id",
    "input",
    "kind",
    "message",
    "meta",
    "model",
    "modelId",
    "name",
    "parentId",
    "payload",
    "provider",
    "results",
    "role",
    "source",
    "status",
    "step_index",
    "summary",
    "text",
    "thinking",
    "thinkingLevel",
    "timestamp",
    "toolCallId",
    "toolUseId",
    "tool_calls",
    "tool_use_id",
    "ts",
    "type",
    "usage",
]

# Discriminator values that select a handler branch in at least one parser.
_TAGS = [
    "AssistantMessage",
    "CONVERSATION_HISTORY",
    "DONE",
    "ERROR",
    "KiroCredits",
    "LIST_DIRECTORY",
    "MODEL",
    "PLANNER_RESPONSE",
    "Prompt",
    "SYSTEM",
    "ToolResults",
    "USER_EXPLICIT",
    "USER_INPUT",
    "agent.thinking",
    "assistant",
    "assistant.message",
    "attachment",
    "branch_summary",
    "compaction",
    "custom_message",
    "event_msg",
    "function_call",
    "json",
    "message",
    "model_change",
    "response_item",
    "session.end",
    "session.start",
    "summary",
    "system",
    "text",
    "thinking",
    "thinking_level_change",
    "token_count",
    "toolCall",
    "toolResult",
    "toolUse",
    "tool.call",
    "tool.result",
    "tool_result",
    "tool_use",
    "user",
    "user.message",
]

_ATOMS = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(min_value=-(2**53), max_value=2**53),
    st.floats(allow_nan=False, allow_infinity=False),
    st.sampled_from(_TAGS),
    st.text(max_size=24),
)
_FIELD_NAMES = st.one_of(st.sampled_from(_KEYS), st.text(max_size=12))
_VALUES = st.recursive(
    _ATOMS,
    lambda children: st.lists(children, max_size=4) | st.dictionaries(_FIELD_NAMES, children, max_size=4),
    max_leaves=12,
)
_RECORDS = st.dictionaries(_FIELD_NAMES, _VALUES, min_size=1, max_size=6)


@given(harness=st.sampled_from(_session.HARNESSES), records=st.lists(_RECORDS, max_size=6))
@settings(deadline=None)
@atheris.instrument_func
def test_session_pipeline_contract(harness: str, records: list[dict]) -> None:
    """Well-formed transcript records must survive ingest and read-path parsing."""
    _session.replay(harness, [json.dumps(record) for record in records])


def main() -> None:
    atheris.Setup(sys.argv, atheris.instrument_func(test_session_pipeline_contract.hypothesis.fuzz_one_input))
    atheris.Fuzz()


if __name__ == "__main__":
    main()
