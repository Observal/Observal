# SPDX-FileCopyrightText: 2026 SrihariLegend <sriharilegend23@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""
Kernel Scorer v3 — Efficiency-Only Scoring

Measures process efficiency of agentic coding sessions.
Output correctness/completeness is evaluated separately by the LLM judge.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, fields

SCORER_VERSION = "3.0.0"


# ---------------------------------------------------------------------------
# Normalizers
# ---------------------------------------------------------------------------


def _raw_sigmoid(value: float, midpoint: float, steepness: float) -> float:
    """Core sigmoid: returns value in (0, 1). Handles overflow."""
    if not isinstance(value, (int, float)) or math.isnan(value) or math.isinf(value):
        return 0.5
    if not isinstance(midpoint, (int, float)) or math.isnan(midpoint) or math.isinf(midpoint):
        return 0.5
    if not isinstance(steepness, (int, float)) or math.isnan(steepness) or math.isinf(steepness):
        return 0.5
    z = steepness * (value - midpoint)
    if z > 500:
        return 1.0
    if z < -500:
        return 0.0
    return 1.0 / (1.0 + math.exp(-z))


def sigmoid_normalize(value: float, midpoint: float, steepness: float, invert: bool = False) -> float:
    """Map any finite numeric input to [0, 1] via logistic function.

    Kept for backward compatibility. New code should use
    normalize_higher_better / normalize_lower_better.
    """
    raw = _raw_sigmoid(value, midpoint, steepness)
    # _raw_sigmoid returns 0.5 for degenerate inputs; map to 0.0 for compat
    if not isinstance(value, (int, float)) or math.isnan(value) or math.isinf(value):
        return 0.0
    if not isinstance(midpoint, (int, float)) or math.isnan(midpoint) or math.isinf(midpoint):
        return 0.0
    if not isinstance(steepness, (int, float)) or math.isnan(steepness) or math.isinf(steepness):
        return 0.0
    return 1.0 - raw if invert else raw


def normalize_higher_better(value: float, params: SigmoidParams) -> float:
    """Two-part normalizer for metrics where higher is better.

    - value >= 1.0  ->  1.0
    - value >= excel_threshold  ->  linear ramp from (thresh, excel_score) to (1.0, 1.0)
    - value < excel_threshold   ->  sigmoid scaled to meet linear ramp at threshold
    """
    if not isinstance(value, (int, float)) or math.isnan(value) or math.isinf(value):
        return 0.0
    if value >= 1.0:
        return 1.0
    et = params.excel_threshold
    es = params.excel_score
    if et < 1.0 and value >= et:
        return es + (1.0 - es) * (value - et) / (1.0 - et)
    # Scale sigmoid so that at value=et the output equals es
    raw = _raw_sigmoid(value, params.midpoint, params.steepness)
    s_et = _raw_sigmoid(et, params.midpoint, params.steepness)
    if s_et > 0:
        return raw * (es / s_et)
    return raw


def normalize_lower_better(value: float, params: SigmoidParams) -> float:
    """Two-part normalizer for metrics where lower is better.

    - value <= 0.0  ->  1.0
    - value <= excel_threshold  ->  linear ramp from (0, 1.0) to (thresh, excel_score)
    - value > excel_threshold   ->  inverted sigmoid scaled to meet linear ramp at threshold
    """
    if not isinstance(value, (int, float)) or math.isnan(value) or math.isinf(value):
        return 0.0
    if value <= 0.0:
        return 1.0
    et = params.excel_threshold
    es = params.excel_score
    if et > 0.0 and value <= et:
        return 1.0 - (1.0 - es) * (value / et)
    # Scale inverted sigmoid so that at value=et the output equals es
    raw = 1.0 - _raw_sigmoid(value, params.midpoint, params.steepness)
    s_et = _raw_sigmoid(et, params.midpoint, params.steepness)
    inv_at_et = 1.0 - s_et
    if inv_at_et > 0:
        return raw * (es / inv_at_et)
    return raw


def normalize_entropy(raw_entropy: float, distinct_targets: int) -> float:
    """Normalize raw entropy bits to [0, 1] relative to trace scope.

    Divides by log2(distinct_targets + 1) — the theoretical maximum entropy
    for the number of distinct targets the agent interacted with.
    """
    if distinct_targets <= 1 or raw_entropy <= 0:
        return 0.0
    max_entropy = math.log2(distinct_targets + 1)
    if max_entropy <= 0:
        return 0.0
    return min(1.0, raw_entropy / max_entropy)


# ---------------------------------------------------------------------------
# Calibration Dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SigmoidParams:
    midpoint: float
    steepness: float
    invert: bool = False
    excel_threshold: float = 0.90
    excel_score: float = 0.95

    def to_dict(self) -> dict:
        return {
            "midpoint": self.midpoint,
            "steepness": self.steepness,
            "invert": self.invert,
            "excel_threshold": self.excel_threshold,
            "excel_score": self.excel_score,
        }

    @classmethod
    def from_dict(cls, d: dict) -> SigmoidParams:
        return cls(
            midpoint=d["midpoint"],
            steepness=d["steepness"],
            invert=d.get("invert", False),
            excel_threshold=d.get("excel_threshold", 0.90),
            excel_score=d.get("excel_score", 0.95),
        )


@dataclass
class Calibration:
    # Efficiency sigmoid params
    per: SigmoidParams = field(default_factory=lambda: SigmoidParams(0.5, 6.0, excel_threshold=0.90, excel_score=0.95))
    twr: SigmoidParams = field(
        default_factory=lambda: SigmoidParams(0.3, 6.0, invert=True, excel_threshold=0.10, excel_score=0.95)
    )
    fpsr: SigmoidParams = field(default_factory=lambda: SigmoidParams(0.5, 6.0, excel_threshold=0.90, excel_score=0.95))
    duplicate_ratio: SigmoidParams = field(
        default_factory=lambda: SigmoidParams(0.1, 10.0, invert=True, excel_threshold=0.05, excel_score=0.95)
    )
    cycle_ratio: SigmoidParams = field(
        default_factory=lambda: SigmoidParams(0.15, 8.0, invert=True, excel_threshold=0.05, excel_score=0.95)
    )
    redundant_read_ratio: SigmoidParams = field(
        default_factory=lambda: SigmoidParams(0.1, 8.0, invert=True, excel_threshold=0.05, excel_score=0.95)
    )
    write_without_verify: SigmoidParams = field(
        default_factory=lambda: SigmoidParams(0.6, 4.0, invert=True, excel_threshold=0.20, excel_score=0.95)
    )
    file_churn: SigmoidParams = field(
        default_factory=lambda: SigmoidParams(0.3, 6.0, invert=True, excel_threshold=0.10, excel_score=0.95)
    )

    efficiency_weights: dict[str, float] = field(
        default_factory=lambda: {
            "per": 0.20,
            "twr": 0.15,
            "fpsr": 0.15,
            "duplicate": 0.08,
            "cycle": 0.10,
            "redundant_read": 0.07,
            "write_without_verify": 0.12,
            "file_churn": 0.13,
        }
    )

    # Minimum-penalized geometric mean parameters
    critical_reference: float = 0.3
    penalty_strength: float = 2.0

    def to_dict(self) -> dict:
        result: dict = {}
        for f in fields(self):
            val = getattr(self, f.name)
            if isinstance(val, SigmoidParams):
                result[f.name] = val.to_dict()
            else:
                result[f.name] = val
        return result

    @classmethod
    def from_dict(cls, d: dict) -> Calibration:
        kwargs: dict = {}
        _inst = cls()
        for f in fields(cls):
            if f.name not in d:
                continue
            default_val = getattr(_inst, f.name)
            if isinstance(default_val, SigmoidParams):
                kwargs[f.name] = SigmoidParams.from_dict(d[f.name])
            else:
                kwargs[f.name] = d[f.name]
        return cls(**kwargs)


DEFAULT_CALIBRATION = Calibration()


# ---------------------------------------------------------------------------
# Input Sanitization
# ---------------------------------------------------------------------------


def _sanitize_metric(value) -> float:
    """Clamp negatives to 0.0, replace NaN/inf with 0.0."""
    if value is None:
        return 0.0
    if not isinstance(value, (int, float)):
        return 0.0
    if math.isnan(value) or math.isinf(value):
        return 0.0
    if value < 0:
        return 0.0
    return float(value)


# ---------------------------------------------------------------------------
# Efficiency Scorer
# ---------------------------------------------------------------------------


def compute_efficiency(
    metrics: dict, waste_classifications: list[dict], calibration: Calibration
) -> tuple[float, dict]:
    """Weighted geometric mean of sigmoid-normalized sub-metrics."""
    total_events = _sanitize_metric(metrics.get("total_events", 0))
    if total_events == 0:
        return 0.0, {"sub_scores": {}, "weights_used": {}, "final": 0.0}

    per_raw = _sanitize_metric(metrics.get("path_efficiency_ratio", 0))
    twr_raw = metrics.get("token_waste_rate")
    fpsr_raw = metrics.get("first_pass_success_rate")
    dup_count = _sanitize_metric(metrics.get("duplicate_tool_call_count", 0))
    cycle_count = _sanitize_metric(metrics.get("repetition_cycles", 0))

    redundant_count = sum(
        1 for w in waste_classifications if isinstance(w, dict) and w.get("category") == "redundant_read"
    )

    dup_ratio = dup_count / total_events
    cycle_ratio_val = cycle_count / total_events
    redundant_ratio = redundant_count / total_events

    sub_scores: dict[str, float] = {}
    weights: dict[str, float] = {}

    sub_scores["per"] = normalize_higher_better(per_raw, calibration.per)
    weights["per"] = calibration.efficiency_weights.get("per", 0.25)

    if twr_raw is not None:
        twr_val = _sanitize_metric(twr_raw)
        sub_scores["twr"] = normalize_lower_better(twr_val, calibration.twr)
        weights["twr"] = calibration.efficiency_weights.get("twr", 0.20)

    if fpsr_raw is not None:
        fpsr_val = _sanitize_metric(fpsr_raw)
        sub_scores["fpsr"] = normalize_higher_better(fpsr_val, calibration.fpsr)
        weights["fpsr"] = calibration.efficiency_weights.get("fpsr", 0.20)

    sub_scores["duplicate"] = normalize_lower_better(dup_ratio, calibration.duplicate_ratio)
    weights["duplicate"] = calibration.efficiency_weights.get("duplicate", 0.10)

    sub_scores["cycle"] = normalize_lower_better(cycle_ratio_val, calibration.cycle_ratio)
    weights["cycle"] = calibration.efficiency_weights.get("cycle", 0.15)

    sub_scores["redundant_read"] = normalize_lower_better(redundant_ratio, calibration.redundant_read_ratio)
    weights["redundant_read"] = calibration.efficiency_weights.get("redundant_read", 0.07)

    wwv_raw = _sanitize_metric(metrics.get("write_without_verify_ratio", 0))
    sub_scores["write_without_verify"] = normalize_lower_better(wwv_raw, calibration.write_without_verify)
    weights["write_without_verify"] = calibration.efficiency_weights.get("write_without_verify", 0.12)

    churn_raw = _sanitize_metric(metrics.get("file_churn_rate", 0))
    sub_scores["file_churn"] = normalize_lower_better(churn_raw, calibration.file_churn)
    weights["file_churn"] = calibration.efficiency_weights.get("file_churn", 0.13)

    # Minimum-penalized weighted geometric mean
    total_weight = sum(weights.values())
    if total_weight <= 0:
        return 0.0, {"sub_scores": sub_scores, "weights_used": weights, "final": 0.0}

    log_sum = 0.0
    for key, score in sub_scores.items():
        w = weights[key] / total_weight
        if score <= 0:
            return 0.0, {"sub_scores": sub_scores, "weights_used": weights, "final": 0.0}
        log_sum += w * math.log(score)

    base = math.exp(log_sum)

    # Penalty: if worst sub-score is below critical_reference, penalize proportionally
    worst = min(sub_scores.values())
    cr = calibration.critical_reference
    ps = calibration.penalty_strength
    penalty = (worst / cr) ** ps if worst < cr and cr > 0 else 1.0

    result = max(0.0, min(1.0, base * penalty))

    return result, {
        "sub_scores": sub_scores,
        "weights_used": weights,
        "worst_sub_score": round(worst, 6),
        "penalty": round(penalty, 6),
        "final": round(result, 6),
    }


# ---------------------------------------------------------------------------
# Interpretation & Warnings
# ---------------------------------------------------------------------------

_METRIC_RANGES: dict[str, list[tuple[callable, str]]] = {
    "path_efficiency_ratio": [
        (lambda v: v >= 0.85, "Excellent (>=0.85)"),
        (lambda v: v >= 0.7, "Good (>=0.7)"),
        (lambda v: v >= 0.5, "Fair (>=0.5)"),
        (lambda v: True, "Poor (<0.5) — agent is taking many unnecessary steps"),
    ],
    "token_waste_rate": [
        (lambda v: v is None, "N/A (no token data)"),
        (lambda v: v <= 0.1, "Excellent (<=0.1)"),
        (lambda v: v <= 0.25, "Good (<=0.25)"),
        (lambda v: v <= 0.4, "Fair (<=0.4)"),
        (lambda v: True, "High (>0.4) — significant token waste on reverted/duplicate work"),
    ],
    "first_pass_success_rate": [
        (lambda v: v is None, "N/A (no writes)"),
        (lambda v: v >= 0.9, "Excellent (>=0.9)"),
        (lambda v: v >= 0.7, "Good (>=0.7)"),
        (lambda v: v >= 0.5, "Fair (>=0.5)"),
        (lambda v: True, "Poor (<0.5) — most writes get reverted"),
    ],
    "write_without_verify_ratio": [
        (lambda v: v <= 0.2, "Excellent (<=0.2)"),
        (lambda v: v <= 0.4, "Good (<=0.4)"),
        (lambda v: v <= 0.6, "Fair (<=0.6)"),
        (lambda v: True, "High (>0.6) — agent writes code without running builds or tests"),
    ],
    "file_churn_rate": [
        (lambda v: v <= 0.1, "Excellent (<=0.1)"),
        (lambda v: v <= 0.25, "Good (<=0.25)"),
        (lambda v: v <= 0.4, "Fair (<=0.4)"),
        (lambda v: True, "High (>0.4) — many files rewritten multiple times"),
    ],
    "repetition_cycles": [
        (lambda v: v == 0, "None detected"),
        (lambda v: v <= 2, "Minor (1-2 cycles)"),
        (lambda v: True, "Significant — agent is looping"),
    ],
    "duplicate_tool_call_count": [
        (lambda v: v == 0, "None"),
        (lambda v: v <= 2, "Minor (1-2 duplicates)"),
        (lambda v: True, "Significant — agent repeats identical tool calls"),
    ],
}


def _interpret_metrics(metrics: dict) -> dict[str, str]:
    interpretation: dict[str, str] = {}
    for key, ranges in _METRIC_RANGES.items():
        val = metrics.get(key)
        if val is None and key in ("token_waste_rate", "first_pass_success_rate"):
            interpretation[key] = "N/A"
            continue
        if val is None:
            val = 0
        for check, label in ranges:
            if check(val):
                interpretation[key] = label
                break
    return interpretation


def _generate_warnings(metrics: dict, waste_classifications: list[dict]) -> list[str]:
    warnings: list[str] = []
    _sanitize_metric(metrics.get("total_events", 0))

    per = metrics.get("path_efficiency_ratio", 1.0)
    if per is not None and per < 0.5:
        warnings.append(f"Low path efficiency ({per:.2f}) — over half the agent's actions were ineffective.")

    twr = metrics.get("token_waste_rate")
    if twr is not None and twr > 0.4:
        warnings.append(f"High token waste rate ({twr:.2f}) — significant compute spent on reverted work.")

    fpsr = metrics.get("first_pass_success_rate")
    if fpsr is not None and fpsr < 0.5:
        warnings.append(f"Low first-pass success rate ({fpsr:.2f}) — most file writes get reverted.")

    wwv = metrics.get("write_without_verify_ratio", 0)
    if wwv and wwv > 0.6:
        warnings.append(
            f"High write-without-verify ratio ({wwv:.2f}) — agent writes code without running builds or tests."
        )

    churn = metrics.get("file_churn_rate", 0)
    if churn and churn > 0.4:
        warnings.append(f"High file churn ({churn:.2f}) — many files rewritten multiple times.")

    cycles = _sanitize_metric(metrics.get("repetition_cycles", 0))
    if cycles >= 3:
        warnings.append(f"{int(cycles)} repetition cycles detected — agent may be stuck in a loop.")

    dups = _sanitize_metric(metrics.get("duplicate_tool_call_count", 0))
    if dups >= 3:
        warnings.append(f"{int(dups)} duplicate tool calls — agent repeating identical operations.")

    redundant_count = sum(
        1 for w in waste_classifications if isinstance(w, dict) and w.get("category") == "redundant_read"
    )
    if redundant_count >= 3:
        warnings.append(f"{redundant_count} redundant reads — agent re-reading files it already has in context.")

    return warnings


# ---------------------------------------------------------------------------
# Entry Point
# ---------------------------------------------------------------------------


def score_trace(
    metrics: dict,
    findings: list[dict],
    waste_classifications: list[dict],
    config: dict | None = None,
) -> dict:
    """Score a trace for process efficiency.

    Returns efficiency score, per-metric interpretation with reference ranges,
    and actionable warnings. No composite grade — efficiency is one dimension;
    correctness/completeness is evaluated separately by the LLM judge.
    """
    config = config or {}

    if "calibration" in config:
        try:
            calibration = Calibration.from_dict(config["calibration"])
        except (TypeError, KeyError, ValueError):
            calibration = DEFAULT_CALIBRATION
    else:
        calibration = DEFAULT_CALIBRATION

    total_events = _sanitize_metric(metrics.get("total_events", 0))
    if total_events == 0:
        return {
            "efficiency_rating": 0.0,
            "efficiency_detail": {},
            "efficiency_metrics": {},
            "interpretation": {},
            "warnings": ["Empty trace — no agent actions to evaluate."],
            "scorer_version": SCORER_VERSION,
        }

    eff_score, eff_detail = compute_efficiency(metrics, waste_classifications, calibration)

    efficiency_metrics = {
        "path_efficiency_ratio": metrics.get("path_efficiency_ratio"),
        "token_waste_rate": metrics.get("token_waste_rate"),
        "first_pass_success_rate": metrics.get("first_pass_success_rate"),
        "repetition_cycles": metrics.get("repetition_cycles", 0),
        "duplicate_tool_call_count": metrics.get("duplicate_tool_call_count", 0),
        "write_without_verify_ratio": metrics.get("write_without_verify_ratio", 0),
        "file_churn_rate": metrics.get("file_churn_rate", 0),
    }

    return {
        "efficiency_rating": round(eff_score, 4),
        "efficiency_detail": eff_detail,
        "efficiency_metrics": efficiency_metrics,
        "interpretation": _interpret_metrics(metrics),
        "warnings": _generate_warnings(metrics, waste_classifications),
        "scorer_version": SCORER_VERSION,
    }
