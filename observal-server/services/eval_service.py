import json
import logging
import uuid

import httpx

from config import settings
from models.agent import Agent
from models.eval import Scorecard, ScorecardDimension
from models.scoring import DEFAULT_PENALTIES
from services.adversarial_scorer import AdversarialScorer
from services.canary import CanaryConfig, CanaryDetector
from services.clickhouse import _query
from services.eval_engine import FallbackBackend, get_backend
from services.eval_watchdog import EvalWatchdog
from services.sanitizer import TraceSanitizer
from services.score_aggregator import ScoreAggregator
from services.slm_scorer import SLMScorer
from services.structural_scorer import StructuralScorer

logger = logging.getLogger(__name__)

DIMENSIONS = [
    "task_completion",
    "tool_usage_efficiency",
    "response_quality",
    "factual_grounding",
    "user_satisfaction",
]

# Build penalty amount lookup from catalog
_PENALTY_AMOUNTS: dict[str, int] = {p["event_name"]: p["amount"] for p in DEFAULT_PENALTIES}

JUDGE_PROMPT = """You are an AI evaluation judge. Given an agent's goal template and a trace of its execution, evaluate the agent's performance.

## Agent Goal
{goal_description}

## Required Output Sections
{sections}

## Trace Data
{trace}

## Instructions
Score each dimension 0-10 with a brief justification. Identify the primary bottleneck.
Respond ONLY with valid JSON in this exact format:
{{
  "overall_score": <float 0-10>,
  "dimensions": {{
    "task_completion": {{"score": <float>, "notes": "<brief justification>"}},
    "tool_usage_efficiency": {{"score": <float>, "notes": "<brief justification>"}},
    "response_quality": {{"score": <float>, "notes": "<brief justification>"}},
    "factual_grounding": {{"score": <float>, "notes": "<brief justification>"}},
    "user_satisfaction": {{"score": <float>, "notes": "<brief justification>"}}
  }},
  "recommendations": "<actionable recommendations>",
  "bottleneck": "<primary bottleneck area>"
}}"""


def _score_to_grade(score: float) -> str:
    if score >= 9:
        return "A+"
    if score >= 8:
        return "A"
    if score >= 7:
        return "B"
    if score >= 6:
        return "C"
    if score >= 5:
        return "D"
    return "F"


async def fetch_traces(agent_id: str, limit: int = 20, trace_id: str | None = None) -> list[dict]:
    """Fetch recent agent interaction traces from ClickHouse."""
    if trace_id:
        sql = "SELECT * FROM agent_interactions WHERE agent_id = {aid:String} AND event_id = {tid:String} FORMAT JSON"
        params = {"param_aid": agent_id, "param_tid": trace_id}
    else:
        sql = f"SELECT * FROM agent_interactions WHERE agent_id = {{aid:String}} ORDER BY timestamp DESC LIMIT {int(limit)} FORMAT JSON"
        params = {"param_aid": agent_id}

    try:
        r = await _query(sql, params)
        if r.status_code == 200:
            return r.json().get("data", [])
    except Exception as e:
        logger.warning(f"Failed to fetch traces: {e}")
    return []


async def call_eval_model(prompt: str) -> dict:
    """Call the evaluation model. Supports Bedrock and OpenAI-compatible APIs."""
    provider = getattr(settings, "EVAL_MODEL_PROVIDER", "") or ""
    eval_model = getattr(settings, "EVAL_MODEL_NAME", "") or ""

    if not eval_model:
        return {}

    if provider == "bedrock" or (not provider and "anthropic" in eval_model):
        return await _call_bedrock(prompt, eval_model)
    return await _call_openai_compatible(prompt, eval_model)


async def _call_bedrock(prompt: str, model_id: str) -> dict:
    """Call AWS Bedrock Converse API."""
    import asyncio

    def _sync_call():
        import boto3

        region = getattr(settings, "AWS_REGION", "us-east-1")
        client = boto3.client("bedrock-runtime", region_name=region)
        response = client.converse(
            modelId=model_id,
            messages=[{"role": "user", "content": [{"text": prompt}]}],
            inferenceConfig={"temperature": 0.1, "maxTokens": 4096},
        )
        text = response["output"]["message"]["content"][0]["text"]
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0]
        elif "```" in text:
            text = text.split("```")[1].split("```")[0]
        return json.loads(text.strip())

    try:
        return await asyncio.get_event_loop().run_in_executor(None, _sync_call)
    except Exception as e:
        logger.error(f"Bedrock eval call failed: {e}")
        return {}


async def _call_openai_compatible(prompt: str, model: str) -> dict:
    """Call an OpenAI-compatible API."""
    eval_url = getattr(settings, "EVAL_MODEL_URL", "") or "http://localhost:11434/v1"
    eval_key = getattr(settings, "EVAL_MODEL_API_KEY", "") or ""

    headers = {"Content-Type": "application/json"}
    if eval_key:
        headers["Authorization"] = f"Bearer {eval_key}"

    async with httpx.AsyncClient(timeout=120) as client:
        try:
            r = await client.post(
                f"{eval_url}/chat/completions",
                headers=headers,
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.1,
                    "response_format": {"type": "json_object"},
                },
            )
            r.raise_for_status()
            content = r.json()["choices"][0]["message"]["content"]
            return json.loads(content)
        except Exception as e:
            logger.error(f"Eval model call failed: {e}")
            return {}


def build_fallback_scorecard(trace: dict) -> dict:
    """Generate a heuristic-based scorecard when no LLM is available."""
    latency = int(trace.get("latency_ms", 0))
    tool_calls = int(trace.get("tool_calls", 0))
    action = trace.get("user_action", "")

    accepted = 1.0 if action == "accepted" else 0.0
    latency_score = max(0, min(10, 10 - (latency / 1000)))
    tool_score = max(0, min(10, tool_calls * 2)) if tool_calls > 0 else 3

    overall = round(min(10.0, max(0.0, (accepted * 10 + latency_score + tool_score + 5 + 5) / 5)), 1)

    return {
        "overall_score": overall,
        "dimensions": {
            "task_completion": {"score": accepted * 10, "notes": f"User action: {action}"},
            "tool_usage_efficiency": {"score": round(tool_score, 1), "notes": f"{tool_calls} tool calls"},
            "response_quality": {"score": 5.0, "notes": "Heuristic default: no LLM evaluation available"},
            "factual_grounding": {"score": 5.0, "notes": "Heuristic default: no LLM evaluation available"},
            "user_satisfaction": {"score": round(latency_score, 1), "notes": f"Latency: {latency}ms"},
        },
        "recommendations": "Enable LLM evaluation for detailed analysis.",
        "bottleneck": "prompt" if accepted == 0.0 else "none",
    }


async def evaluate_trace(agent: Agent, trace: dict) -> dict:
    """Evaluate a single trace against the agent's goal template."""
    goal_desc = agent.goal_template.description if agent.goal_template else "No goal template"
    sections = ""
    if agent.goal_template:
        for s in agent.goal_template.sections:
            grounding = " [grounding required]" if s.grounding_required else ""
            sections += f"- {s.name}{grounding}\n"

    trace_str = json.dumps(trace, indent=2, default=str)
    prompt = JUDGE_PROMPT.format(goal_description=goal_desc, sections=sections, trace=trace_str)

    result = await call_eval_model(prompt)
    if not result or "overall_score" not in result:
        result = build_fallback_scorecard(trace)

    return result


def parse_scorecard(result: dict, agent: Agent, eval_run_id: uuid.UUID, trace_id: str) -> Scorecard:
    """Parse LLM output into a Scorecard ORM object."""
    overall = float(result.get("overall_score", 0))
    sc = Scorecard(
        agent_id=agent.id,
        eval_run_id=eval_run_id,
        trace_id=trace_id,
        version=agent.version,
        overall_score=overall,
        overall_grade=_score_to_grade(overall),
        recommendations=result.get("recommendations"),
        bottleneck=result.get("bottleneck"),
        raw_output=result,
    )

    dims = result.get("dimensions", {})
    for dim_name in DIMENSIONS:
        dim_data = dims.get(dim_name, {})
        score = float(dim_data.get("score", 0))
        sc.dimensions.append(
            ScorecardDimension(
                dimension=dim_name,
                score=score,
                grade=_score_to_grade(score),
                notes=dim_data.get("notes"),
            )
        )

    return sc


# ---------------------------------------------------------------------------
# New structured eval pipeline (5-dimension penalty-based scoring)
# ---------------------------------------------------------------------------


async def run_structured_eval(
    agent: Agent,
    trace: dict,
    spans: list[dict],
    eval_run_id: uuid.UUID,
    canary_config: CanaryConfig | None = None,
) -> Scorecard:
    """Run the BenchJack-hardened 6-dimension eval pipeline on a trace.

    Pipeline order:
    1. Adversarial detection FIRST (before any other scoring)
    2. Sanitize trace for SLM judge
    3. Structural scoring on original trace
    4. SLM scoring on sanitized trace
    5. Canary detection (if configured)
    6. Aggregate all penalties into scorecard
    7. Run EvalWatchdog on scorecard
    """
    sanitizer = TraceSanitizer()
    adversarial_scorer = AdversarialScorer(sanitizer)
    canary_detector = CanaryDetector()
    structural_scorer = StructuralScorer()
    aggregator = ScoreAggregator()
    watchdog = EvalWatchdog()

    trace_id = trace.get("trace_id", trace.get("event_id", str(uuid.uuid4())))

    # --- Step 1: Adversarial detection (before any other scoring) ---
    injection_attempts = sanitizer.detect_injection_attempts(trace)
    adversarial_penalties = adversarial_scorer.score(trace, canary_config)

    # Attach penalty amounts from catalog
    for p in adversarial_penalties:
        if "amount" not in p:
            p["amount"] = _PENALTY_AMOUNTS.get(p["event_name"], 0)

    logger.info(
        "Adversarial scan: %d injection attempts, %d penalties for trace %s",
        len(injection_attempts),
        len(adversarial_penalties),
        trace_id,
    )

    # --- Step 2: Sanitize trace for SLM judge ---
    sanitized_trace = sanitizer.sanitize_for_judge(trace)

    # --- Step 3: Structural scoring on ORIGINAL trace ---
    structural_penalties = structural_scorer.score_tool_efficiency(spans, str(agent.id))
    structural_penalties += structural_scorer.score_tool_failures(spans)

    for p in structural_penalties:
        if "amount" not in p:
            p["amount"] = _PENALTY_AMOUNTS.get(p["event_name"], 0)

    # --- Step 4: SLM scoring on SANITIZED trace ---
    slm_penalties: list[dict] = []
    skipped_dimensions: list[str] = []
    backend = get_backend()
    if not isinstance(backend, FallbackBackend):
        slm_scorer = SLMScorer(backend)
        try:
            goal_desc = ""
            required_sections: list[dict] = []
            if agent.goal_template:
                goal_desc = agent.goal_template.description
                required_sections = [
                    {"name": s.name, "grounding_required": s.grounding_required} for s in agent.goal_template.sections
                ]
            if required_sections:
                slm_penalties += await slm_scorer.score_goal_completion(
                    sanitized_trace, spans, goal_desc, required_sections
                )

            slm_penalties += await slm_scorer.score_factual_grounding(sanitized_trace, spans)
            slm_penalties += await slm_scorer.score_thought_process(spans)
        except Exception as e:
            logger.error(f"SLM scoring failed, skipping SLM dimensions: {e}")
            slm_penalties = []
            skipped_dimensions = ["goal_completion", "factual_grounding", "thought_process"]

        for p in slm_penalties:
            if "amount" not in p:
                p["amount"] = _PENALTY_AMOUNTS.get(p["event_name"], 0)
    else:
        skipped_dimensions = ["goal_completion", "factual_grounding", "thought_process"]

    # --- Step 5: Canary detection (if configured) ---
    canary_report = None
    canary_penalty = None
    if canary_config and canary_config.enabled:
        canary_penalty = canary_detector.check_for_parroted_canary(trace, canary_config)
        if canary_penalty:
            if "amount" not in canary_penalty:
                canary_penalty["amount"] = _PENALTY_AMOUNTS.get(canary_penalty["event_name"], 0)
            adversarial_penalties.append(canary_penalty)

        canary_report = canary_detector.generate_canary_report(trace_id, canary_config, canary_penalty)
        logger.info(
            "Canary check: behavior=%s, penalty=%s for trace %s",
            canary_report.agent_behavior,
            canary_report.penalty_applied,
            trace_id,
        )

    # --- Step 6: Aggregate all penalties ---
    scorecard = aggregator.compute_scorecard(
        structural_penalties=structural_penalties + adversarial_penalties,
        slm_penalties=slm_penalties,
        agent_id=agent.id,
        eval_run_id=eval_run_id,
        trace_id=trace_id,
        version=agent.version,
        skipped_dimensions=skipped_dimensions if skipped_dimensions else None,
    )

    # --- Step 7: Run EvalWatchdog ---
    all_penalties = structural_penalties + adversarial_penalties + slm_penalties
    warnings = watchdog.validate_scorecard(
        composite_score=scorecard.composite_score,
        dimension_scores=scorecard.dimension_scores,
        penalty_count=scorecard.penalty_count,
        penalties=all_penalties,
        span_count=len(spans),
    )
    scorecard.warnings = warnings
    if warnings:
        logger.warning("EvalWatchdog warnings for trace %s: %s", trace_id, warnings)

    # Store adversarial metadata in raw_output for API response
    scorecard.raw_output = {
        "adversarial_findings": {
            "injection_attempts_detected": len(injection_attempts),
            "injection_attempts": [
                {
                    "pattern_matched": a.pattern_matched,
                    "location": a.location,
                    "severity": a.severity,
                }
                for a in injection_attempts
            ],
            "items_sanitized": len(injection_attempts),
            "adversarial_score": scorecard.dimension_scores.get("adversarial_robustness", 100),
        },
        "canary_report": canary_report.model_dump() if canary_report else None,
    }

    return scorecard
