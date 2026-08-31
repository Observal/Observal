# SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Insight text must never be parsed as Rich markup.

Report narratives are written by an LLM and routinely contain square
brackets — file paths like ``[/tmp]``, indexes like ``array[0]``, literal
markup examples. Rich reads those as style tags: an unmatched closing tag
raises ``MarkupError`` and kills ``observal ops insights show`` outright,
while a well-formed one silently deletes the text. Both are wrong.
"""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from observal_cli.cmd_insights import insights_app

runner = CliRunner()

AGENT_ID = "c6185803-8c32-4c39-b347-78f8281e306e"
REPORT_ID = "be5aa083-d84a-49e7-8a35-b37b3e687780"

# "[/tmp]" crashes Rich outright; "[bold]" is swallowed silently.
HOSTILE = "Clean up [/tmp] and index array[0] with [bold] markers"


@pytest.fixture(autouse=True)
def _wide_terminal(monkeypatch):
    monkeypatch.setenv("COLUMNS", "300")


def _serve(monkeypatch, narrative: dict):
    def fake_get(path: str, params: dict | None = None):
        if path == "/api/v1/agents/ultra-pi":
            return {"id": AGENT_ID, "name": "ultra-pi"}
        if path == f"/api/v1/agents/{AGENT_ID}/insights/reports":
            return [{"id": REPORT_ID, "status": "completed"}]
        if path == f"/api/v1/agents/{AGENT_ID}/insights/reports/{REPORT_ID}":
            return {
                "id": REPORT_ID,
                "agent_id": AGENT_ID,
                "status": "completed",
                "period_start": "2026-05-17T00:00:00Z",
                "period_end": "2026-05-31T00:00:00Z",
                "sessions_analyzed": 42,
                "llm_model_used": "test-model",
                "narrative": narrative,
            }
        raise AssertionError(f"unexpected path: {path}")

    monkeypatch.setattr("observal_cli.config.resolve_alias", lambda value: value)
    monkeypatch.setattr("observal_cli.cmd_insights.client.get", fake_get)


def _flat(output: str) -> str:
    """Collapse Rich's wrapping so assertions test content, not terminal width."""
    return " ".join(output.split())


# Every section renderer, with the hostile string in a field it interpolates.
SECTIONS = [
    ("at_a_glance", {"health": "healthy", "whats_working": HOSTILE}),
    ("at_a_glance", {"health": "healthy", "quick_win": HOSTILE}),
    ("what_they_work_on", {"areas": [{"name": "infra", "sessions": 3, "description": HOSTILE}]}),
    ("interaction_style", {"narrative": HOSTILE}),
    ("interaction_style", {"narrative": "ok", "key_pattern": HOSTILE}),
    ("usage_patterns", {"narrative": HOSTILE}),
    ("usage_patterns", {"tool_distribution": [{"tool": HOSTILE, "calls": 4, "error_rate": 0.0}]}),
    ("what_works", {"intro": HOSTILE}),
    ("what_works", {"strengths": [{"title": "t", "description": HOSTILE}]}),
    ("friction_analysis", {"categories": [{"title": "t", "severity": "high", "description": HOSTILE}]}),
    ("friction_analysis", {"categories": [{"title": "t", "severity": "high", "examples": [HOSTILE]}]}),
    ("suggestions", {"config_additions": [{"addition": HOSTILE, "why": "w", "where": "system_prompt"}]}),
    ("suggestions", {"features_to_try": [{"feature": "Skill", "name": "n", "one_liner": HOSTILE}]}),
    ("suggestions", {"usage_patterns": [{"title": "t", "suggestion": HOSTILE}]}),
    ("suggestions", {"usage_patterns": [{"title": "t", "suggestion": "s", "copyable_prompt": HOSTILE}]}),
    ("usage_cost_analysis", {"summary": HOSTILE}),
    ("usage_cost_analysis", {"opportunities": [{"title": "t", "description": HOSTILE}]}),
    ("regression_detection", {"has_previous_data": True, "summary": HOSTILE}),
    ("on_the_horizon", {"opportunities": [{"title": "t", "whats_possible": HOSTILE}]}),
    ("on_the_horizon", {"opportunities": [{"title": "t", "how_to_try": HOSTILE}]}),
    ("version_comparison", {"summary": HOSTILE}),
    ("version_comparison", {"summary": "s", "changes": [{"metric": "m", "evidence": HOSTILE}]}),
    ("fun_ending", {"headline": HOSTILE}),
    ("fun_ending", {"headline": "h", "detail": HOSTILE}),
]


@pytest.mark.parametrize(("section", "payload"), SECTIONS, ids=[f"{s}-{i}" for i, (s, _) in enumerate(SECTIONS)])
def test_bracketed_text_renders_literally(monkeypatch, section, payload):
    _serve(monkeypatch, {section: payload})

    result = runner.invoke(insights_app, ["show", "ultra-pi"])

    assert result.exit_code == 0, result.output
    assert HOSTILE in _flat(result.output), f"{section} dropped or mangled bracketed text"


class TestLegacySectionShapes:
    def test_string_section_does_not_crash_typed_renderer(self, monkeypatch):
        # Older reports stored some sections as prose; `.get` would explode.
        _serve(monkeypatch, {"suggestions": HOSTILE})

        result = runner.invoke(insights_app, ["show", "ultra-pi"])

        assert result.exit_code == 0, result.output
        assert HOSTILE in _flat(result.output)

    def test_list_section_does_not_crash_typed_renderer(self, monkeypatch):
        _serve(monkeypatch, {"suggestions": ["one", "two"]})

        result = runner.invoke(insights_app, ["show", "ultra-pi"])

        assert result.exit_code == 0, result.output
