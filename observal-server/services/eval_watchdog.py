"""EvalWatchdog: post-scoring validation to catch meaningless results.

Implements BenchJack Pattern 6 mitigation — ensures that every scoring
pipeline run actually applies meaningful evaluation, catching the
FieldWorkArena failure mode (scoring code that returns perfect scores
without checking anything).
"""

import logging

from models.scoring import PenaltyTriggerType, ScoringDimension

logger = logging.getLogger(__name__)

# Dimensions that have SLM-assisted penalties
SLM_DIMENSIONS = {
    ScoringDimension.goal_completion,
    ScoringDimension.factual_grounding,
    ScoringDimension.thought_process,
}


class EvalWatchdog:
    """Runs after every scoring pipeline execution.

    Catches cases where scoring silently produced meaningless results.
    Returns warnings that are logged and attached to the scorecard.
    """

    def validate_scorecard(
        self,
        composite_score: float,
        dimension_scores: dict[str, float | None],
        penalty_count: int,
        penalties: list[dict],
        span_count: int = 0,
    ) -> list[str]:
        """Validate a scorecard and return a list of warning strings.

        Checks for suspicious patterns that indicate scoring may not be working correctly.
        """
        warnings: list[str] = []

        # 1. Perfect score with zero penalties
        if composite_score == 100 and penalty_count == 0:
            warnings.append(
                "Perfect score with zero penalties. Verify penalty catalog coverage for this agent's goal template."
            )

        # 2. SLM dimension at 100 with no SLM penalties applied
        slm_penalty_dims = set()
        for p in penalties:
            dim = p.get("dimension")
            if isinstance(dim, ScoringDimension):
                dim_value = dim.value
            elif isinstance(dim, str):
                dim_value = dim
            else:
                continue
            trigger = p.get("trigger_type")
            if trigger in (PenaltyTriggerType.slm_assisted, "slm_assisted"):
                slm_penalty_dims.add(dim_value)

        for slm_dim in SLM_DIMENSIONS:
            score = dimension_scores.get(slm_dim.value)
            if score is not None and score == 100 and slm_dim.value not in slm_penalty_dims:
                warnings.append(
                    f"Dimension '{slm_dim.value}' scored 100 but SLM judge produced no findings. "
                    f"Possible judge failure."
                )

        # 3. Penalties applied but composite still very high
        if penalty_count > 0 and composite_score > 95:
            warnings.append(
                "Penalties applied but composite still very high. Check "
                "penalty amounts may be too small relative to dimension weights."
            )

        # 4. All SLM dimensions scored identically
        slm_scores = []
        for slm_dim in SLM_DIMENSIONS:
            score = dimension_scores.get(slm_dim.value)
            if score is not None:
                slm_scores.append(score)
        if len(slm_scores) >= 2 and len(set(slm_scores)) == 1:
            warnings.append("SLM dimensions suspiciously uniform. Possible judge template issue.")

        # 5. Long trace with no structural penalties
        structural_penalties = [
            p for p in penalties if p.get("trigger_type") in (PenaltyTriggerType.structural, "structural")
        ]
        if span_count > 50 and len(structural_penalties) == 0:
            warnings.append(
                "Long trace with no structural issues detected. Verify structural scorer is receiving spans correctly."
            )

        for w in warnings:
            logger.warning("EvalWatchdog: %s", w)

        return warnings
