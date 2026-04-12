"""Meta-test suite: validates the scoring engine itself (BenchJack Pattern 6).

These tests verify that the evaluation logic actually evaluates — catching
the FieldWorkArena failure mode where scoring code returns perfect scores
without checking anything, and the CAR-bench bug where skipped dimensions
silently default to 100.
"""

import uuid
from collections import defaultdict

from models.scoring import (
    DEFAULT_PENALTIES,
    ScoringDimension,
)
from services.eval_watchdog import EvalWatchdog
from services.score_aggregator import ScoreAggregator, _score_to_grade
from services.structural_scorer import StructuralScorer

# --- Helpers ---

_AGENT_ID = uuid.uuid4()
_EVAL_RUN_ID = uuid.uuid4()


def _make_scorecard(penalties, skipped=None):
    """Build a scorecard from a list of penalty dicts."""
    agg = ScoreAggregator()
    return agg.compute_scorecard(
        structural_penalties=penalties,
        slm_penalties=[],
        agent_id=_AGENT_ID,
        eval_run_id=_EVAL_RUN_ID,
        trace_id="test-trace",
        version="1.0",
        skipped_dimensions=skipped,
    )


def _penalty(event_name, dimension, amount=-10):
    """Create a minimal penalty dict."""
    return {
        "event_name": event_name,
        "dimension": dimension,
        "amount": amount,
        "evidence": f"Test evidence for {event_name}",
        "trace_event_index": None,
    }


# =========================================================================
# Null trace scores low
# =========================================================================


class TestNullTraceScoresLow:
    def _null_trace_penalties(self):
        """Penalties that a truly null trace (zero spans, empty output) would get.

        A null trace with a goal template requiring 4 sections would trigger
        heavy penalties across every dimension. Each dimension should be driven
        well below 50 for the composite to land under 30.
        """
        return [
            # Goal completion (weight 0.30): 4 missing sections = -100, score 0
            _penalty("missing_required_section", ScoringDimension.goal_completion, -25),
            _penalty("missing_required_section", ScoringDimension.goal_completion, -25),
            _penalty("missing_required_section", ScoringDimension.goal_completion, -25),
            _penalty("missing_required_section", ScoringDimension.goal_completion, -25),
            # Tool efficiency (weight 0.20): no tools used = -20, score 80 → but
            # with empty output, all claims ungrounded too
            _penalty("ungrounded_claims", ScoringDimension.tool_efficiency, -20),
            _penalty("duplicate_tool_call", ScoringDimension.tool_efficiency, -5),
            _penalty("unused_tool_result", ScoringDimension.tool_efficiency, -3),
            _penalty("unused_tool_result", ScoringDimension.tool_efficiency, -3),
            # Factual grounding (weight 0.20): everything ungrounded = -100, score 0
            _penalty("ungrounded_claim", ScoringDimension.factual_grounding, -15),
            _penalty("ungrounded_claim", ScoringDimension.factual_grounding, -15),
            _penalty("contradicts_source", ScoringDimension.factual_grounding, -25),
            _penalty("hallucinated_entity", ScoringDimension.factual_grounding, -20),
            _penalty("numeric_mismatch", ScoringDimension.factual_grounding, -20),
            # Tool failures (weight 0.15): errors everywhere = -100, score 0
            _penalty("tool_call_error", ScoringDimension.tool_failures, -10),
            _penalty("tool_call_error", ScoringDimension.tool_failures, -10),
            _penalty("ignored_tool_failure", ScoringDimension.tool_failures, -15),
            _penalty("tool_call_timeout", ScoringDimension.tool_failures, -8),
            _penalty("ignored_tool_failure", ScoringDimension.tool_failures, -15),
            _penalty("tool_call_error", ScoringDimension.tool_failures, -10),
            # Thought process (weight 0.13): no reasoning = -100, score 0
            _penalty("no_conclusion_explanation", ScoringDimension.thought_process, -15),
            _penalty("ignores_relevant_data", ScoringDimension.thought_process, -10),
            _penalty("blind_tool_use", ScoringDimension.thought_process, -5),
            _penalty("reasoning_contradicts_action", ScoringDimension.thought_process, -10),
            _penalty("ignores_relevant_data", ScoringDimension.thought_process, -10),
            _penalty("blind_tool_use", ScoringDimension.thought_process, -5),
            # Adversarial robustness (weight 0.10): injection attempts = -100, score 0
            _penalty("html_comment_injection", ScoringDimension.adversarial_robustness, -20),
            _penalty("prompt_injection_attempt", ScoringDimension.adversarial_robustness, -25),
            _penalty("score_assertion_in_output", ScoringDimension.adversarial_robustness, -20),
            _penalty("evaluator_path_probing", ScoringDimension.adversarial_robustness, -25),
            _penalty("zero_width_unicode_injection", ScoringDimension.adversarial_robustness, -15),
        ]

    def test_null_trace_with_missing_sections(self):
        """A null trace with penalties across all dimensions MUST score below 30/100."""
        sc = _make_scorecard(self._null_trace_penalties())
        assert sc.composite_score < 30, f"Null trace scored {sc.composite_score}, expected < 30"

    def test_null_trace_gets_low_grade(self):
        """Null trace should receive D or F grade."""
        sc = _make_scorecard(self._null_trace_penalties())
        assert sc.grade in ("D", "F"), f"Null trace got grade {sc.grade}, expected D or F"


# =========================================================================
# Random trace doesn't score better than null
# =========================================================================


class TestRandomTraceScoring:
    def test_random_trace_does_not_beat_null(self):
        """A trace with garbage tool calls should not score better than null.

        Random noise adds tool failures and no useful sections — more penalties.
        """
        null_penalties = [
            _penalty("missing_required_section", ScoringDimension.goal_completion, -25),
            _penalty("missing_required_section", ScoringDimension.goal_completion, -25),
        ]
        random_penalties = [
            _penalty("missing_required_section", ScoringDimension.goal_completion, -25),
            _penalty("missing_required_section", ScoringDimension.goal_completion, -25),
            _penalty("tool_call_error", ScoringDimension.tool_failures, -10),
            _penalty("tool_call_error", ScoringDimension.tool_failures, -10),
            _penalty("duplicate_tool_call", ScoringDimension.tool_efficiency, -5),
        ]
        null_sc = _make_scorecard(null_penalties)
        random_sc = _make_scorecard(random_penalties)
        assert random_sc.composite_score <= null_sc.composite_score


# =========================================================================
# Every dimension has active penalties
# =========================================================================


class TestEveryDimensionHasActivePenalties:
    def test_all_dimensions_have_at_least_2_penalties(self):
        """Each dimension must have >= 2 active penalties in the catalog.

        A dimension with zero penalties always returns 100 —
        the FieldWorkArena failure mode.
        """
        by_dim = defaultdict(list)
        for p in DEFAULT_PENALTIES:
            by_dim[p["dimension"]].append(p)

        for dim in ScoringDimension:
            count = len(by_dim.get(dim, []))
            assert count >= 2, f"Dimension '{dim.value}' has only {count} penalties — needs at least 2 to be meaningful"

    def test_penalty_amounts_are_negative(self):
        """All penalty amounts must be negative integers."""
        for p in DEFAULT_PENALTIES:
            assert p["amount"] < 0, f"Penalty '{p['event_name']}' has non-negative amount: {p['amount']}"
            assert isinstance(p["amount"], int), f"Penalty '{p['event_name']}' amount is not int"


# =========================================================================
# Every penalty can fire
# =========================================================================


class TestEveryPenaltyCanFire:
    """For each penalty in the catalog, verify it can actually be triggered."""

    def _run_structural_scorer(self, spans, agent_id="test-agent"):
        scorer = StructuralScorer()
        penalties = scorer.score_tool_efficiency(spans, agent_id)
        penalties += scorer.score_tool_failures(spans)
        return penalties

    def test_duplicate_tool_call_fires(self):
        spans = [
            {"type": "tool_call", "name": "search", "input": "q", "output": "r", "status": "success", "span_id": "s1"},
            {"type": "tool_call", "name": "search", "input": "q", "output": "r", "status": "success", "span_id": "s2"},
        ]
        penalties = self._run_structural_scorer(spans)
        assert any(p["event_name"] == "duplicate_tool_call" for p in penalties)

    def test_tool_call_error_fires(self):
        spans = [
            {
                "type": "tool_call",
                "name": "search",
                "input": "q",
                "output": "",
                "status": "error",
                "error": "connection failed",
                "span_id": "s1",
                "latency_ms": 100,
            },
        ]
        penalties = self._run_structural_scorer(spans)
        assert any(p["event_name"] == "tool_call_error" for p in penalties)

    def test_tool_call_timeout_fires(self):
        spans = [
            {
                "type": "tool_call",
                "name": "search",
                "input": "q",
                "output": "r",
                "status": "success",
                "span_id": "s1",
                "latency_ms": 60000,
            },
        ]
        penalties = self._run_structural_scorer(spans)
        assert any(p["event_name"] == "tool_call_timeout" for p in penalties)

    def test_tool_call_retry_success_fires(self):
        spans = [
            {
                "type": "tool_call",
                "name": "search",
                "input": "q",
                "output": "",
                "status": "error",
                "error": "fail",
                "span_id": "s1",
                "latency_ms": 100,
            },
            {
                "type": "tool_call",
                "name": "search",
                "input": "q",
                "output": "ok",
                "status": "success",
                "span_id": "s2",
                "latency_ms": 100,
            },
        ]
        penalties = self._run_structural_scorer(spans)
        assert any(p["event_name"] == "tool_call_retry_success" for p in penalties)

    def test_ungrounded_claims_fires(self):
        spans = [
            {"type": "reasoning_step", "name": "think", "input": "the file contains X", "output": "", "span_id": "r1"},
        ]
        penalties = self._run_structural_scorer(spans)
        assert any(p["event_name"] == "ungrounded_claims" for p in penalties)

    def test_unused_tool_result_fires(self):
        spans = [
            {
                "type": "tool_call",
                "name": "search",
                "input": "q",
                "output": "unique_data_xyz",
                "status": "success",
                "span_id": "s1",
                "latency_ms": 100,
            },
            {
                "type": "reasoning_step",
                "name": "think",
                "input": "I will do something unrelated",
                "output": "",
                "span_id": "r1",
            },
        ]
        penalties = self._run_structural_scorer(spans)
        assert any(p["event_name"] == "unused_tool_result" for p in penalties)

    def test_ignored_tool_failure_fires(self):
        spans = [
            {
                "type": "tool_call",
                "name": "search",
                "input": "q",
                "output": "",
                "status": "error",
                "error": "fail",
                "span_id": "s1",
                "latency_ms": 100,
            },
            {"type": "reasoning_step", "name": "think", "input": "moving on", "output": "", "span_id": "r1"},
        ]
        penalties = self._run_structural_scorer(spans)
        assert any(p["event_name"] == "ignored_tool_failure" for p in penalties)


# =========================================================================
# Perfect score requires substance
# =========================================================================


class TestPerfectScoreRequiresSubstance:
    def test_stub_sections_score_below_85(self):
        """Trace with stub sections and weak reasoning must score well below 85."""
        penalties = [
            _penalty("empty_stub_section", ScoringDimension.goal_completion, -15),
            _penalty("empty_stub_section", ScoringDimension.goal_completion, -15),
            _penalty("empty_stub_section", ScoringDimension.goal_completion, -15),
            _penalty("no_conclusion_explanation", ScoringDimension.thought_process, -15),
            _penalty("ignores_relevant_data", ScoringDimension.thought_process, -10),
        ]
        sc = _make_scorecard(penalties)
        assert sc.composite_score < 85, f"Stub trace scored {sc.composite_score}"

    def test_zero_penalty_clean_trace_can_score_100(self):
        """A trace with zero penalties should score exactly 100."""
        sc = _make_scorecard([])
        assert sc.composite_score == 100


# =========================================================================
# Skipped dimensions are flagged
# =========================================================================


class TestSkippedDimensions:
    def test_skipped_dims_set_to_none(self):
        """Skipped dimensions must have score=None, not 100 or 0."""
        sc = _make_scorecard([], skipped=["goal_completion", "factual_grounding"])
        assert sc.dimension_scores["goal_completion"] is None
        assert sc.dimension_scores["factual_grounding"] is None

    def test_skipped_dims_not_defaulted_to_100(self):
        """A skipped dimension that silently returns 100 is the CAR-bench bug."""
        sc = _make_scorecard([], skipped=["goal_completion"])
        assert sc.dimension_scores["goal_completion"] is None

    def test_partial_evaluation_flag_set(self):
        """Scorecard must have partial_evaluation=True when dims are skipped."""
        sc = _make_scorecard([], skipped=["goal_completion"])
        assert sc.partial_evaluation is True

    def test_dimensions_skipped_list_populated(self):
        sc = _make_scorecard([], skipped=["goal_completion", "thought_process"])
        assert set(sc.dimensions_skipped) == {"goal_completion", "thought_process"}

    def test_no_skip_means_not_partial(self):
        sc = _make_scorecard([])
        assert sc.partial_evaluation is False

    def test_skipped_dims_reweighted(self):
        """Composite should be computed over remaining dims only, re-weighted to 1.0."""
        # Skip goal_completion (0.30 weight). Remaining weights should sum to 1.0.
        sc_full = _make_scorecard([])
        sc_skip = _make_scorecard([], skipped=["goal_completion"])
        # With no penalties and all active dims at 100, composite should still be 100
        assert sc_skip.composite_score == 100

    def test_skipped_dims_recommendation(self):
        """Skipped dimensions should generate a recommendation."""
        sc = _make_scorecard([], skipped=["factual_grounding"])
        recs = sc.scoring_recommendations or []
        assert any("factual_grounding" in r and "not evaluated" in r for r in recs)


# =========================================================================
# Composite bounds
# =========================================================================


class TestCompositeBounds:
    def test_composite_never_exceeds_100(self):
        """Even with all dimensions at 100 (no penalties), composite <= 100."""
        sc = _make_scorecard([])
        assert sc.composite_score <= 100

    def test_composite_floor_at_zero(self):
        """Even with massive penalties, composite >= 0."""
        massive_penalties = [_penalty("tool_call_error", dim, -200) for dim in ScoringDimension for _ in range(5)]
        sc = _make_scorecard(massive_penalties)
        assert sc.composite_score >= 0


# =========================================================================
# Grade boundaries
# =========================================================================


class TestGradeBoundaries:
    def test_85_is_grade_a(self):
        assert _score_to_grade(85.0) == "A"

    def test_84_9_is_grade_b(self):
        assert _score_to_grade(84.9) == "B"

    def test_70_is_grade_b(self):
        assert _score_to_grade(70.0) == "B"

    def test_69_9_is_grade_c(self):
        assert _score_to_grade(69.9) == "C"

    def test_55_is_grade_c(self):
        assert _score_to_grade(55.0) == "C"

    def test_54_9_is_grade_d(self):
        assert _score_to_grade(54.9) == "D"

    def test_40_is_grade_d(self):
        assert _score_to_grade(40.0) == "D"

    def test_39_9_is_grade_f(self):
        assert _score_to_grade(39.9) == "F"

    def test_0_is_grade_f(self):
        assert _score_to_grade(0) == "F"

    def test_100_is_grade_a(self):
        assert _score_to_grade(100) == "A"


# =========================================================================
# EvalWatchdog
# =========================================================================


class TestEvalWatchdog:
    def setup_method(self):
        self.watchdog = EvalWatchdog()

    def test_perfect_score_zero_penalties_warns(self):
        warnings = self.watchdog.validate_scorecard(
            composite_score=100,
            dimension_scores={d.value: 100 for d in ScoringDimension},
            penalty_count=0,
            penalties=[],
        )
        assert any("Perfect score" in w for w in warnings)

    def test_slm_dim_100_no_slm_penalties_warns(self):
        warnings = self.watchdog.validate_scorecard(
            composite_score=90,
            dimension_scores={
                "goal_completion": 100,
                "tool_efficiency": 80,
                "tool_failures": 90,
                "factual_grounding": 100,
                "thought_process": 100,
            },
            penalty_count=2,
            penalties=[
                {"dimension": ScoringDimension.tool_efficiency, "trigger_type": "structural"},
                {"dimension": ScoringDimension.tool_efficiency, "trigger_type": "structural"},
            ],
        )
        assert any("SLM judge produced no findings" in w for w in warnings)

    def test_penalties_but_high_composite_warns(self):
        warnings = self.watchdog.validate_scorecard(
            composite_score=97,
            dimension_scores={d.value: 97 for d in ScoringDimension},
            penalty_count=3,
            penalties=[
                {"dimension": ScoringDimension.tool_efficiency, "trigger_type": "structural"},
            ]
            * 3,
        )
        assert any("still very high" in w for w in warnings)

    def test_uniform_slm_scores_warns(self):
        warnings = self.watchdog.validate_scorecard(
            composite_score=85,
            dimension_scores={
                "goal_completion": 85,
                "tool_efficiency": 90,
                "tool_failures": 95,
                "factual_grounding": 85,
                "thought_process": 85,
            },
            penalty_count=5,
            penalties=[
                {"dimension": ScoringDimension.goal_completion, "trigger_type": "slm_assisted"},
            ]
            * 5,
        )
        assert any("suspiciously uniform" in w for w in warnings)

    def test_long_trace_no_structural_warns(self):
        warnings = self.watchdog.validate_scorecard(
            composite_score=90,
            dimension_scores={d.value: 90 for d in ScoringDimension},
            penalty_count=2,
            penalties=[
                {"dimension": ScoringDimension.goal_completion, "trigger_type": "slm_assisted"},
            ]
            * 2,
            span_count=60,
        )
        assert any("Long trace" in w for w in warnings)

    def test_clean_scorecard_no_warnings(self):
        """A normal scorecard with reasonable scores should produce no warnings."""
        warnings = self.watchdog.validate_scorecard(
            composite_score=75,
            dimension_scores={
                "goal_completion": 75,
                "tool_efficiency": 80,
                "tool_failures": 90,
                "factual_grounding": 60,
                "thought_process": 70,
            },
            penalty_count=5,
            penalties=[
                {"dimension": ScoringDimension.goal_completion, "trigger_type": "slm_assisted"},
                {"dimension": ScoringDimension.tool_efficiency, "trigger_type": "structural"},
                {"dimension": ScoringDimension.factual_grounding, "trigger_type": "slm_assisted"},
                {"dimension": ScoringDimension.thought_process, "trigger_type": "slm_assisted"},
                {"dimension": ScoringDimension.tool_efficiency, "trigger_type": "structural"},
            ],
            span_count=10,
        )
        assert warnings == []
