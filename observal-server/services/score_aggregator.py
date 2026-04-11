"""Score aggregation engine: combines penalties into dimension scores and composite scorecards."""

import logging
import math
import uuid
from collections import defaultdict

from models.eval import Scorecard, ScorecardDimension
from models.scoring import (
    DEFAULT_DIMENSION_WEIGHTS,
    ScoringDimension,
)

logger = logging.getLogger(__name__)

# Grade thresholds (on 0-100 scale)
GRADE_THRESHOLDS = [
    (85, "A"),
    (70, "B"),
    (55, "C"),
    (40, "D"),
    (0, "F"),
]

# Old dimension name mapping for backwards compat with ScorecardDimension
DIMENSION_DISPLAY_NAMES = {
    ScoringDimension.goal_completion: "goal_completion",
    ScoringDimension.tool_efficiency: "tool_efficiency",
    ScoringDimension.tool_failures: "tool_failures",
    ScoringDimension.factual_grounding: "factual_grounding",
    ScoringDimension.thought_process: "thought_process",
}


def _score_to_grade(score: float) -> str:
    """Convert a 0-100 score to a letter grade."""
    for threshold, grade in GRADE_THRESHOLDS:
        if score >= threshold:
            return grade
    return "F"


def _old_grade(score_10: float) -> str:
    """Convert a 0-10 score to old-style grade for backwards compat."""
    if score_10 >= 9:
        return "A+"
    if score_10 >= 8:
        return "A"
    if score_10 >= 7:
        return "B"
    if score_10 >= 6:
        return "C"
    if score_10 >= 5:
        return "D"
    return "F"


class ScoreAggregator:
    """Aggregates penalties into dimension scores and composite scorecards."""

    def compute_scorecard(
        self,
        structural_penalties: list[dict],
        slm_penalties: list[dict],
        agent_id: uuid.UUID,
        eval_run_id: uuid.UUID,
        trace_id: str,
        version: str,
        weights: dict[ScoringDimension, float] | None = None,
    ) -> Scorecard:
        """Compute a scorecard from structural and SLM penalties.

        1. Group all penalties by dimension
        2. Per dimension: score = max(0, 100 - sum(abs(penalty.amount)))
        3. Weighted average for composite
        4. Generate recommendations from worst dimensions
        """
        all_penalties = structural_penalties + slm_penalties
        if weights is None:
            weights = dict(DEFAULT_DIMENSION_WEIGHTS)

        # Group penalties by dimension
        by_dimension: dict[ScoringDimension, list[dict]] = defaultdict(list)
        for p in all_penalties:
            dim = p.get("dimension")
            if isinstance(dim, str):
                try:
                    dim = ScoringDimension(dim)
                except ValueError:
                    continue
            if dim:
                by_dimension[dim].append(p)

        # Compute per-dimension scores
        dimension_scores: dict[str, float] = {}
        for dim in ScoringDimension:
            dim_penalties = by_dimension.get(dim, [])
            total_penalty = sum(abs(self._get_penalty_amount(p)) for p in dim_penalties)
            score = max(0, 100 - total_penalty)
            dimension_scores[dim.value] = score

        # Weighted composite
        composite = sum(dimension_scores[dim.value] * weights.get(dim, 0) for dim in ScoringDimension)
        composite = max(0, min(100, composite))

        # Display score (0-10)
        display_score = round(composite / 10, 1)

        # Grade
        grade = _score_to_grade(composite)

        # Recommendations from worst dimensions
        recommendations = self._generate_recommendations(dimension_scores, by_dimension)

        # Build Scorecard ORM object
        sc = Scorecard(
            agent_id=agent_id,
            eval_run_id=eval_run_id,
            trace_id=trace_id,
            version=version,
            overall_score=display_score,
            overall_grade=_old_grade(display_score),
            recommendations="; ".join(recommendations) if recommendations else None,
            bottleneck=self._find_bottleneck(dimension_scores),
            raw_output={"penalties": [_serialize_penalty(p) for p in all_penalties]},
            # New fields
            dimension_scores=dimension_scores,
            composite_score=round(composite, 2),
            display_score=display_score,
            grade=grade,
            scoring_recommendations=recommendations,
            penalty_count=len(all_penalties),
        )

        # Add ScorecardDimension records for backwards compat
        for dim in ScoringDimension:
            score = dimension_scores[dim.value]
            dim_display = round(score / 10, 1)
            sc.dimensions.append(
                ScorecardDimension(
                    dimension=DIMENSION_DISPLAY_NAMES[dim],
                    score=dim_display,
                    grade=_old_grade(dim_display),
                    notes=f"{len(by_dimension.get(dim, []))} penalties applied",
                )
            )

        return sc

    def compute_agent_aggregate(
        self,
        scorecards: list[dict],
        window_size: int = 50,
    ) -> dict:
        """Compute aggregate stats from recent scorecards.

        Args:
            scorecards: list of scorecard dicts with composite_score, dimension_scores, evaluated_at
            window_size: number of recent scorecards to consider
        """
        if not scorecards:
            return {
                "mean": 0,
                "std": 0,
                "ci_low": 0,
                "ci_high": 0,
                "dimension_averages": {},
                "drift_alert": False,
                "trend": [],
            }

        recent = scorecards[:window_size]
        composites = [s.get("composite_score", 0) for s in recent]

        mean = sum(composites) / len(composites)
        variance = sum((x - mean) ** 2 for x in composites) / len(composites)
        std = math.sqrt(variance)

        ci_low = max(0, mean - 1.96 * std)
        ci_high = min(100, mean + 1.96 * std)

        # Per-dimension averages
        dim_avgs: dict[str, float] = {}
        for dim in ScoringDimension:
            scores = [s.get("dimension_scores", {}).get(dim.value, 0) for s in recent if s.get("dimension_scores")]
            dim_avgs[dim.value] = round(sum(scores) / len(scores), 2) if scores else 0

        # Find weakest dimension
        weakest = min(dim_avgs, key=dim_avgs.get) if dim_avgs else None

        # Drift alert: compare recent mean to 30-day baseline
        drift_alert = False
        if len(scorecards) > window_size:
            baseline = scorecards[window_size : window_size + 50]
            if baseline:
                baseline_composites = [s.get("composite_score", 0) for s in baseline]
                baseline_mean = sum(baseline_composites) / len(baseline_composites)
                baseline_var = sum((x - baseline_mean) ** 2 for x in baseline_composites) / len(baseline_composites)
                baseline_std = math.sqrt(baseline_var)
                if baseline_std > 0 and abs(mean - baseline_mean) > baseline_std:
                    drift_alert = True

        # Trend data
        trend = [{"timestamp": s.get("evaluated_at", ""), "composite": s.get("composite_score", 0)} for s in recent]

        return {
            "mean": round(mean, 2),
            "std": round(std, 2),
            "ci_low": round(ci_low, 2),
            "ci_high": round(ci_high, 2),
            "dimension_averages": dim_avgs,
            "weakest_dimension": weakest,
            "drift_alert": drift_alert,
            "trend": trend,
        }

    def compute_session_aggregate(self, scorecards: list[dict]) -> dict:
        """Compute mean composite score across all traces in a session."""
        if not scorecards:
            return {"mean": 0, "count": 0}
        composites = [s.get("composite_score", 0) for s in scorecards]
        return {
            "mean": round(sum(composites) / len(composites), 2),
            "count": len(composites),
        }

    def _get_penalty_amount(self, penalty: dict) -> int:
        """Get the penalty amount, looking up from catalog if needed."""
        return penalty.get("amount", 0)

    def _generate_recommendations(
        self,
        dimension_scores: dict[str, float],
        by_dimension: dict[ScoringDimension, list[dict]],
    ) -> list[str]:
        """Generate actionable recommendations from the worst-scoring dimensions."""
        recommendations = []
        sorted_dims = sorted(dimension_scores.items(), key=lambda x: x[1])

        for dim_name, score in sorted_dims[:3]:
            if score >= 90:
                continue
            dim = ScoringDimension(dim_name)
            penalty_names = [p.get("event_name", "") for p in by_dimension.get(dim, [])]
            unique_names = list(dict.fromkeys(penalty_names))

            if dim == ScoringDimension.goal_completion:
                recommendations.append(
                    f"Improve goal completion (score: {score:.0f}). Issues: {', '.join(unique_names[:3])}."
                )
            elif dim == ScoringDimension.tool_efficiency:
                recommendations.append(
                    f"Improve tool efficiency (score: {score:.0f}). Issues: {', '.join(unique_names[:3])}."
                )
            elif dim == ScoringDimension.tool_failures:
                recommendations.append(
                    f"Reduce tool failures (score: {score:.0f}). Issues: {', '.join(unique_names[:3])}."
                )
            elif dim == ScoringDimension.factual_grounding:
                recommendations.append(
                    f"Improve factual grounding (score: {score:.0f}). Issues: {', '.join(unique_names[:3])}."
                )
            elif dim == ScoringDimension.thought_process:
                recommendations.append(
                    f"Improve thought process (score: {score:.0f}). Issues: {', '.join(unique_names[:3])}."
                )

        return recommendations

    def _find_bottleneck(self, dimension_scores: dict[str, float]) -> str:
        """Find the worst-scoring dimension."""
        if not dimension_scores:
            return "none"
        worst = min(dimension_scores, key=dimension_scores.get)
        return worst


def _serialize_penalty(p: dict) -> dict:
    """Serialize a penalty dict for JSON storage."""
    result = dict(p)
    if "dimension" in result:
        dim = result["dimension"]
        result["dimension"] = dim.value if hasattr(dim, "value") else str(dim)
    return result
