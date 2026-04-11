"""Unit tests for the score aggregation engine."""

import uuid

from models.scoring import ScoringDimension
from services.score_aggregator import ScoreAggregator, _score_to_grade


class TestScoreToGrade:
    def test_grade_a(self):
        assert _score_to_grade(90) == "A"

    def test_grade_b(self):
        assert _score_to_grade(75) == "B"

    def test_grade_c(self):
        assert _score_to_grade(60) == "C"

    def test_grade_d(self):
        assert _score_to_grade(45) == "D"

    def test_grade_f(self):
        assert _score_to_grade(30) == "F"

    def test_boundary_a(self):
        assert _score_to_grade(85) == "A"

    def test_boundary_f(self):
        assert _score_to_grade(39) == "F"


class TestComputeScorecard:
    def setup_method(self):
        self.aggregator = ScoreAggregator()
        self.agent_id = uuid.uuid4()
        self.eval_run_id = uuid.uuid4()

    def test_perfect_score_no_penalties(self):
        sc = self.aggregator.compute_scorecard(
            structural_penalties=[],
            slm_penalties=[],
            agent_id=self.agent_id,
            eval_run_id=self.eval_run_id,
            trace_id="t1",
            version="1.0",
        )
        assert sc.composite_score == 100.0
        assert sc.grade == "A"
        assert sc.display_score == 10.0
        assert sc.penalty_count == 0

    def test_penalties_reduce_score(self):
        penalties = [
            {
                "event_name": "duplicate_tool_call",
                "dimension": ScoringDimension.tool_efficiency,
                "amount": -5,
                "evidence": "dup",
            },
            {
                "event_name": "tool_call_error",
                "dimension": ScoringDimension.tool_failures,
                "amount": -10,
                "evidence": "err",
            },
        ]
        sc = self.aggregator.compute_scorecard(
            structural_penalties=penalties,
            slm_penalties=[],
            agent_id=self.agent_id,
            eval_run_id=self.eval_run_id,
            trace_id="t1",
            version="1.0",
        )
        assert sc.composite_score < 100
        assert sc.penalty_count == 2
        assert sc.dimension_scores["tool_efficiency"] == 95  # 100 - 5
        assert sc.dimension_scores["tool_failures"] == 90  # 100 - 10
        assert sc.dimension_scores["goal_completion"] == 100

    def test_score_floors_at_zero(self):
        penalties = [
            {
                "event_name": "contradicts_source",
                "dimension": ScoringDimension.factual_grounding,
                "amount": -25,
                "evidence": "e1",
            },
            {
                "event_name": "numeric_mismatch",
                "dimension": ScoringDimension.factual_grounding,
                "amount": -20,
                "evidence": "e2",
            },
            {
                "event_name": "hallucinated_entity",
                "dimension": ScoringDimension.factual_grounding,
                "amount": -20,
                "evidence": "e3",
            },
            {
                "event_name": "ungrounded_claim",
                "dimension": ScoringDimension.factual_grounding,
                "amount": -15,
                "evidence": "e4",
            },
            {
                "event_name": "ungrounded_claim",
                "dimension": ScoringDimension.factual_grounding,
                "amount": -15,
                "evidence": "e5",
            },
            {
                "event_name": "hallucinated_entity",
                "dimension": ScoringDimension.factual_grounding,
                "amount": -20,
                "evidence": "e6",
            },
        ]
        sc = self.aggregator.compute_scorecard(
            structural_penalties=[],
            slm_penalties=penalties,
            agent_id=self.agent_id,
            eval_run_id=self.eval_run_id,
            trace_id="t1",
            version="1.0",
        )
        assert sc.dimension_scores["factual_grounding"] == 0

    def test_backwards_compat_dimensions(self):
        sc = self.aggregator.compute_scorecard(
            structural_penalties=[],
            slm_penalties=[],
            agent_id=self.agent_id,
            eval_run_id=self.eval_run_id,
            trace_id="t1",
            version="1.0",
        )
        assert len(sc.dimensions) == 5
        dim_names = {d.dimension for d in sc.dimensions}
        assert "goal_completion" in dim_names
        assert "tool_efficiency" in dim_names

    def test_recommendations_generated(self):
        penalties = [
            {
                "event_name": "tool_call_error",
                "dimension": ScoringDimension.tool_failures,
                "amount": -10,
                "evidence": "err",
            },
            {
                "event_name": "tool_call_timeout",
                "dimension": ScoringDimension.tool_failures,
                "amount": -8,
                "evidence": "timeout",
            },
        ]
        sc = self.aggregator.compute_scorecard(
            structural_penalties=penalties,
            slm_penalties=[],
            agent_id=self.agent_id,
            eval_run_id=self.eval_run_id,
            trace_id="t1",
            version="1.0",
        )
        assert sc.scoring_recommendations is not None
        assert len(sc.scoring_recommendations) > 0

    def test_bottleneck_identifies_worst(self):
        penalties = [
            {
                "event_name": "missing_required_section",
                "dimension": ScoringDimension.goal_completion,
                "amount": -25,
                "evidence": "e",
            },
        ]
        sc = self.aggregator.compute_scorecard(
            structural_penalties=[],
            slm_penalties=penalties,
            agent_id=self.agent_id,
            eval_run_id=self.eval_run_id,
            trace_id="t1",
            version="1.0",
        )
        assert sc.bottleneck == "goal_completion"


class TestAgentAggregate:
    def setup_method(self):
        self.aggregator = ScoreAggregator()

    def test_empty_scorecards(self):
        result = self.aggregator.compute_agent_aggregate([])
        assert result["mean"] == 0
        assert result["drift_alert"] is False

    def test_single_scorecard(self):
        scorecards = [
            {
                "composite_score": 80,
                "dimension_scores": {
                    "goal_completion": 90,
                    "tool_efficiency": 70,
                    "tool_failures": 80,
                    "factual_grounding": 85,
                    "thought_process": 75,
                },
                "evaluated_at": "2026-01-01",
            }
        ]
        result = self.aggregator.compute_agent_aggregate(scorecards)
        assert result["mean"] == 80
        assert result["std"] == 0
        assert len(result["trend"]) == 1

    def test_multiple_scorecards(self):
        scorecards = [
            {"composite_score": 80, "dimension_scores": {"goal_completion": 80}, "evaluated_at": "2026-01-01"},
            {"composite_score": 90, "dimension_scores": {"goal_completion": 90}, "evaluated_at": "2026-01-02"},
            {"composite_score": 70, "dimension_scores": {"goal_completion": 70}, "evaluated_at": "2026-01-03"},
        ]
        result = self.aggregator.compute_agent_aggregate(scorecards)
        assert result["mean"] == 80
        assert result["std"] > 0
        assert result["ci_low"] < result["mean"]
        assert result["ci_high"] > result["mean"]

    def test_drift_detection(self):
        # Recent scores much higher than baseline (baseline has variance)
        recent = [
            {"composite_score": 95, "dimension_scores": {}, "evaluated_at": f"2026-02-{i:02d}"} for i in range(1, 51)
        ]
        baseline = [
            {"composite_score": 45 + (i % 10), "dimension_scores": {}, "evaluated_at": f"2026-01-{i:02d}"}
            for i in range(1, 51)
        ]
        result = self.aggregator.compute_agent_aggregate(recent + baseline)
        assert result["drift_alert"] is True


class TestSessionAggregate:
    def setup_method(self):
        self.aggregator = ScoreAggregator()

    def test_empty(self):
        result = self.aggregator.compute_session_aggregate([])
        assert result["mean"] == 0
        assert result["count"] == 0

    def test_average(self):
        scorecards = [{"composite_score": 80}, {"composite_score": 60}]
        result = self.aggregator.compute_session_aggregate(scorecards)
        assert result["mean"] == 70
        assert result["count"] == 2
