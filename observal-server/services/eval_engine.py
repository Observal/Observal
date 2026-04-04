"""Eval engine v2: managed LLM-as-judge with pluggable backend.

Reads traces/spans from ClickHouse, runs eval templates, writes scores back.
Designed as a pluggable interface so ITJ can replace LLM-as-judge later.
"""

import json
import logging
import uuid
from abc import ABC, abstractmethod
from datetime import UTC, datetime

import httpx

from config import settings
from services.clickhouse import insert_scores, query_spans, query_trace_by_id

logger = logging.getLogger(__name__)

DEFAULT_PROJECT = "default"

# --- Managed eval templates (no custom authoring) ---

EVAL_TEMPLATES: dict[str, dict] = {
    "tool_selection_accuracy": {
        "id": "tpl-tool-selection",
        "name": "Tool Selection Accuracy",
        "applies_to": "tool_call",
        "prompt": 'Given the user\'s goal and available tools, was the correct tool selected?\nTrace: {trace}\nSpan: {span}\nScore 0.0 (wrong tool) to 1.0 (perfect selection). Respond with JSON: {{"score": <float>, "reason": "<brief>"}}',
    },
    "tool_output_utility": {
        "id": "tpl-tool-utility",
        "name": "Tool Output Utility",
        "applies_to": "tool_call",
        "prompt": 'Did the tool\'s output advance the user\'s goal?\nTrace: {trace}\nSpan: {span}\nScore 0.0 (useless) to 1.0 (essential). Respond with JSON: {{"score": <float>, "reason": "<brief>"}}',
    },
    "reasoning_clarity": {
        "id": "tpl-reasoning",
        "name": "Reasoning Clarity",
        "applies_to": "reasoning_step",
        "prompt": 'Evaluate the logical soundness of this reasoning step.\nTrace: {trace}\nSpan: {span}\nScore 0.0 (incoherent) to 1.0 (clear and logical). Respond with JSON: {{"score": <float>, "reason": "<brief>"}}',
    },
    "response_quality": {
        "id": "tpl-response-quality",
        "name": "Response Quality",
        "applies_to": "agent_turn",
        "prompt": 'Evaluate the overall quality of this agent response.\nTrace: {trace}\nSpan: {span}\nScore 0.0 (poor) to 1.0 (excellent). Respond with JSON: {{"score": <float>, "reason": "<brief>"}}',
    },
    "graph_faithfulness": {
        "id": "tpl-graph-faith",
        "name": "Graph Faithfulness",
        "applies_to": "graph_traverse",
        "prompt": 'Does the output contradict the knowledge graph relationships?\nTrace: {trace}\nSpan: {span}\nScore 0.0 (contradicts graph) to 1.0 (faithful). Respond with JSON: {{"score": <float>, "reason": "<brief>"}}',
    },
    "recall_accuracy": {
        "id": "tpl-recall",
        "name": "Recall Accuracy",
        "applies_to": "memory_retrieve",
        "prompt": 'Is the retrieved memory relevant to the current context?\nTrace: {trace}\nSpan: {span}\nScore 0.0 (irrelevant) to 1.0 (highly relevant). Respond with JSON: {{"score": <float>, "reason": "<brief>"}}',
    },
}


# --- Pluggable backend interface ---


class EvalBackend(ABC):
    """Abstract eval backend. LLM-as-judge now, ITJ later."""

    @abstractmethod
    async def score(self, template: dict, trace: dict, span: dict) -> dict:
        """Return {"score": float, "reason": str}."""
        ...


class LLMJudgeBackend(EvalBackend):
    """LLM-as-judge backend using OpenAI-compatible or Bedrock APIs."""

    async def score(self, template: dict, trace: dict, span: dict) -> dict:
        prompt = template["prompt"].format(
            trace=json.dumps(trace, default=str)[:2000],
            span=json.dumps(span, default=str)[:2000],
        )
        result = await _call_model(prompt)
        if isinstance(result, dict) and "score" in result:
            return {"score": float(result["score"]), "reason": result.get("reason", "")}
        return {"score": 0.5, "reason": "Model returned invalid response"}


class FallbackBackend(EvalBackend):
    """Heuristic fallback when no LLM is configured."""

    async def score(self, template: dict, trace: dict, span: dict) -> dict:
        status = span.get("status", "success")
        latency = int(span.get("latency_ms") or 0)
        score = 0.8 if status == "success" else 0.2
        if latency > 5000:
            score -= 0.2
        return {"score": max(0, min(1, score)), "reason": f"Heuristic: status={status}, latency={latency}ms"}


def get_backend() -> EvalBackend:
    """Get the configured eval backend."""
    if getattr(settings, "EVAL_MODEL_NAME", ""):
        return LLMJudgeBackend()
    return FallbackBackend()


# --- Model calling ---


async def _call_model(prompt: str) -> dict:
    provider = getattr(settings, "EVAL_MODEL_PROVIDER", "") or ""
    model = getattr(settings, "EVAL_MODEL_NAME", "") or ""
    if not model:
        return {}
    if provider == "bedrock" or (not provider and "anthropic" in model):
        return await _call_bedrock(prompt, model)
    return await _call_openai(prompt, model)


async def _call_bedrock(prompt: str, model_id: str) -> dict:
    import asyncio

    def _sync():
        import boto3

        client = boto3.client("bedrock-runtime", region_name=getattr(settings, "AWS_REGION", "us-east-1"))
        r = client.converse(
            modelId=model_id,
            messages=[{"role": "user", "content": [{"text": prompt}]}],
            inferenceConfig={"temperature": 0.1, "maxTokens": 1024},
        )
        text = r["output"]["message"]["content"][0]["text"]
        return _extract_json(text)

    try:
        return await asyncio.get_event_loop().run_in_executor(None, _sync)
    except Exception as e:
        logger.error(f"Bedrock eval failed: {e}")
        return {}


async def _call_openai(prompt: str, model: str) -> dict:
    url = getattr(settings, "EVAL_MODEL_URL", "") or "http://localhost:11434/v1"
    key = getattr(settings, "EVAL_MODEL_API_KEY", "") or ""
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post(
                f"{url}/chat/completions",
                headers=headers,
                json={"model": model, "messages": [{"role": "user", "content": prompt}], "temperature": 0.1},
            )
            r.raise_for_status()
            return _extract_json(r.json()["choices"][0]["message"]["content"])
    except Exception as e:
        logger.error(f"OpenAI eval failed: {e}")
        return {}


def _extract_json(text: str) -> dict:
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0]
    elif "```" in text:
        text = text.split("```")[1].split("```")[0]
    try:
        return json.loads(text.strip())
    except (json.JSONDecodeError, IndexError):
        return {}


# --- Eval runner ---


async def run_eval_on_trace(
    agent_id: str,
    trace_id: str,
    project_id: str = DEFAULT_PROJECT,
) -> list[dict]:
    """Run all applicable eval templates on a trace's spans. Returns scores written."""
    backend = get_backend()
    trace = await query_trace_by_id(project_id, trace_id)
    if not trace:
        logger.warning(f"Trace {trace_id} not found")
        return []

    spans = await query_spans(project_id, trace_id, limit=500)
    if not spans:
        return []

    now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    scores_to_insert = []

    for span in spans:
        span_type = span.get("type", "")
        for tpl_name, tpl in EVAL_TEMPLATES.items():
            if tpl["applies_to"] != span_type:
                continue
            try:
                result = await backend.score(tpl, trace, span)
                scores_to_insert.append(
                    {
                        "score_id": str(uuid.uuid4()),
                        "trace_id": trace_id,
                        "span_id": span.get("span_id", ""),
                        "project_id": project_id,
                        "mcp_id": span.get("mcp_id"),
                        "agent_id": agent_id,
                        "user_id": trace.get("user_id", ""),
                        "name": tpl_name,
                        "source": "eval",
                        "data_type": "numeric",
                        "value": result.get("score", 0),
                        "comment": result.get("reason", ""),
                        "eval_template_id": tpl["id"],
                        "metadata": {},
                        "timestamp": now,
                    }
                )
            except Exception as e:
                logger.error(f"Eval template {tpl_name} failed on span {span.get('span_id')}: {e}")

    if scores_to_insert:
        try:
            await insert_scores(scores_to_insert)
        except Exception as e:
            logger.error(f"Failed to insert eval scores: {e}")

    return scores_to_insert


def list_templates() -> list[dict]:
    """List all managed eval templates."""
    return [{"name": k, **v} for k, v in EVAL_TEMPLATES.items()]
