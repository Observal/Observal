# SPDX-FileCopyrightText: 2026 Observal Contributors
# SPDX-License-Identifier: Apache-2.0

"""Pi skill evidence extraction, checked against the recorded Pi 0.99.2 sessions."""

from __future__ import annotations

import json
from pathlib import Path

from services.session_parsers.skill_evidence import extract_skill_evidence

FIXTURES = Path(__file__).parent / "fixtures" / "component_insights" / "pi"


def _rows(lines: list[str]) -> list[dict]:
    return [{"is_source_record": 1, "line_offset": index, "raw_line": line} for index, line in enumerate(lines)]


def _fixture(name: str) -> list[str]:
    return (FIXTURES / name).read_text(encoding="utf-8").splitlines()


def _facts(lines: list[str]) -> list[tuple]:
    extraction = extract_skill_evidence("pi", _rows(lines))
    assert extraction.status == "supported"
    return [(e.kind, e.scope, e.alias, e.source_line_offset, e.result_state) for e in extraction.evidence]


def test_model_chosen_load_is_available_then_loaded():
    assert _facts(_fixture("skill_session_model_read.jsonl")) == [
        ("available", "user", "observal-probe", 3, "unknown"),
        ("loaded", "user", "observal-probe", 5, "success"),
    ]


def test_slash_command_is_available_invoked_and_loaded():
    assert _facts(_fixture("skill_session_slash_command.jsonl")) == [
        ("available", "user", "observal-probe", 3, "unknown"),
        ("invoked", "user", "observal-probe", 4, "unknown"),
        ("loaded", "user", "observal-probe", 5, "success"),
    ]


def test_facts_carry_no_paths_or_skill_text():
    extraction = extract_skill_evidence("pi", _rows(_fixture("skill_session_slash_command.jsonl")))
    rendered = repr(extraction)
    assert "/home/fixture" not in rendered and "PROBE-7F3A" not in rendered and "SKILL.md" not in rendered


def _edit(lines: list[str], index: int, edit) -> list[str]:
    record = json.loads(lines[index])
    edit(record)
    return [*lines[:index], json.dumps(record), *lines[index + 1 :]]


def test_a_read_of_a_path_that_was_not_advertised_is_not_a_load():
    lines = _fixture("skill_session_model_read.jsonl")

    def elsewhere(record):
        record["message"]["content"][0]["arguments"]["path"] = "/home/fixture/notes/SKILL.md"

    assert [f[0] for f in _facts(_edit(lines, 5, elsewhere))] == ["available"]


def test_skills_outside_pi_install_layout_yield_no_evidence():
    """A ~/.agents/skills copy is not an Observal Pi install: fail closed."""
    lines = _fixture("skill_session_model_read.jsonl")
    agents_copy = "/home/fixture/.agents/skills/observal-probe/SKILL.md"

    def advertise_agents_copy(record):
        sections = record["message"]["sections"]
        sections["skills"] = sections["skills"].replace(
            "/home/fixture/.pi/agent/skills/observal-probe/SKILL.md", agents_copy
        )

    def read_agents_copy(record):
        record["message"]["content"][0]["arguments"]["path"] = agents_copy

    assert _facts(_edit(_edit(lines, 3, advertise_agents_copy), 5, read_agents_copy)) == []


def test_project_scope_install_is_recognised_under_the_session_cwd():
    lines = _fixture("skill_session_model_read.jsonl")
    project_copy = "/home/fixture/project/.pi/skills/observal-probe/SKILL.md"

    def advertise(record):
        sections = record["message"]["sections"]
        sections["skills"] = sections["skills"].replace(
            "/home/fixture/.pi/agent/skills/observal-probe/SKILL.md", project_copy
        )

    def read(record):
        record["message"]["content"][0]["arguments"]["path"] = project_copy

    assert _facts(_edit(_edit(lines, 3, advertise), 5, read)) == [
        ("available", "project", "observal-probe", 3, "unknown"),
        ("loaded", "project", "observal-probe", 5, "success"),
    ]


def test_a_failed_read_and_an_unlinked_read_are_reported_as_such():
    lines = _fixture("skill_session_model_read.jsonl")

    def fail(record):
        record["message"]["isError"] = True

    assert _facts(_edit(lines, 6, fail))[-1][-1] == "error"

    def unlink(record):
        record["message"]["toolCallId"] = "some-other-call"

    assert _facts(_edit(lines, 6, unlink))[-1][-1] == "unknown"


def test_harness_without_an_extractor_is_unsupported_not_empty():
    from observal_shared.harness_registry import HARNESS_REGISTRY

    unsupported = next(
        name for name, entry in sorted(HARNESS_REGISTRY.items()) if not entry.get("skill_evidence_extractor")
    )
    assert extract_skill_evidence(unsupported, []).status == "unsupported"


def test_malformed_records_are_counted_not_guessed():
    extraction = extract_skill_evidence("pi", _rows(["not json", *_fixture("skill_session_model_read.jsonl")]))
    assert extraction.malformed_source_records == 1
    assert [e.kind for e in extraction.evidence] == ["available", "loaded"]
