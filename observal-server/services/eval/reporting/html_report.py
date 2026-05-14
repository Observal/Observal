# SPDX-FileCopyrightText: 2026 Swathi Saravanan <ss4522@cornell.edu>
#
# SPDX-License-Identifier: AGPL-3.0-only

"""HTML report rendering — deterministic structured input → Jinja2 → HTML.

Sections per the unified prompt: header stats, At a Glance, Task Areas,
Charts, Big Wins, Friction Categories, Waste Hot Spots, Spec Suggestions,
On the Horizon, Fun Ending. Per-scorecard table at the bottom.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING, Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from services.eval.check_result.models import Status
from services.eval.insights.batch_narrative import (
    BatchNarrative,
    DeterministicMetrics,
)

if TYPE_CHECKING:
    from services.eval.aggregation.scorecard import Scorecard

_TEMPLATE_DIR = Path(__file__).parent / "templates"
_ENV = Environment(
    loader=FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=select_autoescape(["html"]),
    trim_blocks=False,
    lstrip_blocks=False,
)


def _scorecard_rows(scorecards: list[Scorecard]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for sc in scorecards:
        counts = Counter(c.status for c in sc.checks)
        out.append(
            {
                "mode": sc.scoring_mode.value,
                "score": sc.score,
                "pass_count": counts.get(Status.PASS, 0),
                "fail_count": counts.get(Status.FAIL, 0),
                "warn_count": counts.get(Status.WARN, 0),
            }
        )
    return out


def _waste_hot_spots_flat(metrics: DeterministicMetrics) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for kind, items in metrics.waste_hot_spots.items():
        for it in items:
            rows.append(
                {
                    "kind": kind,
                    "cost_usd": it.get("cost_usd"),
                    "evidence_span_ids": it.get("evidence_span_ids") or [],
                }
            )
    rows.sort(key=lambda r: -(r.get("cost_usd") or 0.0))
    return rows


def _spec_suggestions_text(scorecards: list[Scorecard]) -> str:
    """Copy-pasteable, like Claude Code's CLAUDE.md section.

    Suggestion = the most-frequently-MISSING / WRONG_PARAMS spec node ids.
    """
    counter: Counter[str] = Counter()
    for sc in scorecards:
        for c in sc.checks:
            spec_id = c.meta.get("spec_node_id") if isinstance(c.meta, dict) else None
            if not spec_id:
                continue
            if c.check_type.value in {"MISSING", "WRONG_PARAMS"}:
                counter[str(spec_id)] += 1
    if not counter:
        return ""
    lines = ["# Spec gaps observed in this batch", ""]
    for node_id, count in counter.most_common(10):
        lines.append(f"- **{node_id}** — {count} run(s) failed this check; ensure agents satisfy it.")
    return "\n".join(lines)


def render_batch_report(
    scorecards: list[Scorecard],
    *,
    narrative: BatchNarrative | None = None,
    template_name: str = "batch_report.html.j2",
) -> str:
    """Render a full HTML report.

    `narrative` carries the deterministic metrics + LLM-generated section
    prose. If absent (eg. test run with no LLM), pass `None` and a
    minimal empty-narrative report still renders.
    """
    metrics = (
        narrative.metrics
        if narrative is not None
        else DeterministicMetrics(
            session_count=0,
            trace_count=0,
            total_tokens_in=0,
            total_tokens_out=0,
            latency_p50=0.0,
            latency_p95=0.0,
            latency_p99=0.0,
            error_breakdown_by_tool={},
            tool_usage={},
            cost_usd=0.0,
            cost_unknown=True,
            interruptions_by_stop_reason={},
            waste_hot_spots={},
            per_session=[],
        )
    )
    section_text: dict[str, str] = {}
    if narrative is not None:
        for s in narrative.sections:
            section_text[s.section] = s.text
    synthesis = narrative.synthesis if narrative is not None else ""

    tool_usage_sorted = sorted(metrics.tool_usage.items(), key=lambda kv: -kv[1])

    failure_counts: Counter[str] = Counter()
    for sc in scorecards:
        for c in sc.checks:
            if c.status != Status.PASS:
                failure_counts[c.check_type.value] += 1

    template = _ENV.get_template(template_name)
    return template.render(
        metrics=metrics,
        narrative=narrative,
        synthesis=synthesis,
        section_text=section_text,
        scorecard_rows=_scorecard_rows(scorecards),
        waste_hot_spots_flat=_waste_hot_spots_flat(metrics),
        spec_suggestions_text=_spec_suggestions_text(scorecards),
        tool_usage_sorted=tool_usage_sorted,
        tool_usage_text="\n".join(f"{k}: {v}" for k, v in tool_usage_sorted) or "(none)",
        failure_categories_text="\n".join(f"{k}: {v}" for k, v in failure_counts.most_common()) or "(none)",
        languages_text="(language detection not implemented in Phase 2)",
    )
