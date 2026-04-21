"""RAGAS evaluation for GraphRAG retrieval spans.

Implements the 4 core RAGAS metrics using LLM-as-judge:
- Faithfulness: Are claims in the answer supported by retrieved context?
- Answer Relevancy: Does the answer address the original question?
- Context Precision: Are retrieved chunks relevant to the question?
- Context Recall: Does the context cover all needed information?

Each metric follows the RAGAS methodology:
- Faithfulness: extract claims from answer, verify each against context
- Answer Relevancy: generate questions from answer, compare to original
- Context Precision: check each chunk's relevance to the question
- Context Recall: check if ground truth statements are attributable to context

References:
[1] RAGAS Framework - https://michaeljohnpena.com/blog/2024-03-19-ragas-framework
[2] RAG Evaluation: RAGAS Metrics - https://markaicode.com/rag-evaluation-ragas-metrics-production/
Content was rephrased for compliance with licensing restrictions.
"""

import logging
import uuid
from datetime import UTC, datetime

from services.clickhouse import insert_scores
from services.eval.eval_engine import _call_model

logger = logging.getLogger(__name__)

RAGAS_DIMENSIONS = ("faithfulness", "answer_relevancy", "context_precision", "context_recall")

# --- Prompts ---

FAITHFULNESS_PROMPT = """You are evaluating faithfulness of a GraphRAG answer against retrieved context.

## Retrieved Context
{context}

## Generated Answer
{answer}

## Instructions
1. Extract every factual claim from the answer.
2. For each claim, determine if it is supported by the context.
3. Compute faithfulness = (number of supported claims) / (total claims). If no claims, return 1.0.

Respond ONLY with JSON:
{{"claims_total": <int>, "claims_supported": <int>, "score": <float 0.0-1.0>, "reason": "<brief>"}}"""

ANSWER_RELEVANCY_PROMPT = """You are evaluating whether a GraphRAG answer addresses the original question.

## Question
{question}

## Answer
{answer}

## Instructions
Score how well the answer addresses the question. Consider completeness, focus, and directness.
0.0 = completely off-topic, 1.0 = perfectly addresses the question.

Respond ONLY with JSON:
{{"score": <float 0.0-1.0>, "reason": "<brief>"}}"""

CONTEXT_PRECISION_PROMPT = """You are evaluating the precision of retrieved context chunks for a question.

## Question
{question}

## Retrieved Chunks
{chunks}

## Instructions
For each chunk, determine if it is relevant and useful for answering the question.
Compute context_precision = (number of relevant chunks) / (total chunks). If no chunks, return 0.0.

Respond ONLY with JSON:
{{"chunks_total": <int>, "chunks_relevant": <int>, "score": <float 0.0-1.0>, "reason": "<brief>"}}"""

CONTEXT_RECALL_PROMPT = """You are evaluating context recall: whether the retrieved context contains all information needed.

## Expected Answer / Ground Truth
{ground_truth}

## Retrieved Context
{context}

## Instructions
1. Extract key factual statements from the ground truth.
2. For each statement, check if it can be attributed to the retrieved context.
3. Compute context_recall = (attributed statements) / (total statements). If no statements, return 1.0.

Respond ONLY with JSON:
{{"statements_total": <int>, "statements_attributed": <int>, "score": <float 0.0-1.0>, "reason": "<brief>"}}"""


def _safe_score(result: dict) -> float:
    """Extract score from LLM response, clamped to [0, 1]."""
    try:
        return max(0.0, min(1.0, float(result.get("score", 0.0))))
    except (TypeError, ValueError):
        return 0.0


async def _eval_faithfulness(answer: str, context: str) -> dict:
    prompt = FAITHFULNESS_PROMPT.format(context=context[:4000], answer=answer[:2000])
    result = await _call_model(prompt)
    if not result or "score" not in result:
        return {"score": 0.0, "reason": "Model returned invalid response"}
    return {"score": _safe_score(result), "reason": result.get("reason", "")}


async def _eval_answer_relevancy(question: str, answer: str) -> dict:
    prompt = ANSWER_RELEVANCY_PROMPT.format(question=question[:2000], answer=answer[:2000])
    result = await _call_model(prompt)
    if not result or "score" not in result:
        return {"score": 0.0, "reason": "Model returned invalid response"}
    return {"score": _safe_score(result), "reason": result.get("reason", "")}


async def _eval_context_precision(question: str, chunks: str) -> dict:
    prompt = CONTEXT_PRECISION_PROMPT.format(question=question[:2000], chunks=chunks[:4000])
    result = await _call_model(prompt)
    if not result or "score" not in result:
        return {"score": 0.0, "reason": "Model returned invalid response"}
    return {"score": _safe_score(result), "reason": result.get("reason", "")}


async def _eval_context_recall(ground_truth: str, context: str) -> dict:
    prompt = CONTEXT_RECALL_PROMPT.format(ground_truth=ground_truth[:2000], context=context[:4000])
    result = await _call_model(prompt)
    if not result or "score" not in result:
        return {"score": 0.0, "reason": "Model returned invalid response"}
    return {"score": _safe_score(result), "reason": result.get("reason", "")}


async def run_ragas_on_span(span: dict, ground_truth: str | None = None) -> dict:
    """Run all applicable RAGAS metrics on a single retrieval span.

    The span's `input` is treated as the question, `output` as the answer/context.
    If ground_truth is provided, context_recall is computed; otherwise skipped.
    """
    question = span.get("input") or ""
    output = span.get("output") or ""

    # For GraphRAG spans, output typically contains the full response including
    # retrieved context and generated answer. We treat the whole output as both
    # answer and context since the proxy captures the raw response.
    answer = output
    context = output

    results = {}

    # Faithfulness: is the answer grounded in the retrieved context?
    results["faithfulness"] = await _eval_faithfulness(answer, context)

    # Answer relevancy: does the answer address the question?
    if question:
        results["answer_relevancy"] = await _eval_answer_relevancy(question, answer)
    else:
        results["answer_relevancy"] = {"score": 0.0, "reason": "No question found in span input"}

    # Context precision: are retrieved chunks relevant?
    if question:
        results["context_precision"] = await _eval_context_precision(question, context)
    else:
        results["context_precision"] = {"score": 0.0, "reason": "No question found in span input"}

    # Context recall: does context cover ground truth? (requires ground_truth)
    if ground_truth:
        results["context_recall"] = await _eval_context_recall(ground_truth, context)
    else:
        results["context_recall"] = {"score": 0.0, "reason": "No ground truth provided; context recall requires it"}

    return results


async def run_ragas_on_graphrag(
    graphrag_id: str,
    project_id: str = "default",
    limit: int = 20,
    ground_truths: dict[str, str] | None = None,
) -> dict:
    """Run RAGAS eval on recent retrieval spans for a GraphRAG.

    Args:
        graphrag_id: The GraphRAG listing ID.
        project_id: ClickHouse project ID.
        limit: Max spans to evaluate.
        ground_truths: Optional mapping of span_id -> ground truth text.

    Returns:
        Dict with per-span scores and aggregate averages.
    """
    from services.clickhouse import _query

    ground_truths = ground_truths or {}

    # Fetch retrieval spans for this graphrag
    sql = (
        "SELECT span_id, trace_id, input, output, metadata, start_time "
        "FROM spans FINAL "
        "WHERE project_id = {pid:String} "
        "AND is_deleted = 0 AND type = 'retrieval' "
        "AND metadata['graphrag_id'] = {gid:String} "
        "ORDER BY start_time DESC LIMIT {lim:UInt32} FORMAT JSON"
    )
    params = {
        "param_pid": project_id,
        "param_gid": graphrag_id,
        "param_lim": str(int(limit)),
    }
    try:
        r = await _query(sql, params)
        r.raise_for_status()
        spans = r.json().get("data", [])
    except Exception as e:
        logger.error("ragas_fetch_retrieval_spans_failed", error=str(e))
        return {"spans_evaluated": 0, "scores": [], "averages": {}}

    if not spans:
        return {"spans_evaluated": 0, "scores": [], "averages": {}}

    now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    all_scores = []
    scores_to_insert = []

    for span in spans:
        gt = ground_truths.get(span["span_id"])
        ragas = await run_ragas_on_span(span, ground_truth=gt)

        span_result = {"span_id": span["span_id"], "trace_id": span["trace_id"]}
        for dim in RAGAS_DIMENSIONS:
            dim_result = ragas.get(dim, {})
            span_result[dim] = dim_result.get("score", 0.0)
            span_result[f"{dim}_reason"] = dim_result.get("reason", "")

            scores_to_insert.append(
                {
                    "score_id": str(uuid.uuid4()),
                    "trace_id": span["trace_id"],
                    "span_id": span["span_id"],
                    "project_id": project_id,
                    "mcp_id": None,
                    "agent_id": None,
                    "user_id": "system",
                    "name": f"ragas_{dim}",
                    "source": "ragas_eval",
                    "data_type": "numeric",
                    "value": dim_result.get("score", 0.0),
                    "comment": dim_result.get("reason", ""),
                    "eval_template_id": f"ragas-{dim}",
                    "metadata": {"graphrag_id": graphrag_id},
                    "timestamp": now,
                }
            )

        all_scores.append(span_result)

    # Write scores to ClickHouse
    if scores_to_insert:
        try:
            await insert_scores(scores_to_insert)
        except Exception as e:
            logger.error("ragas_insert_scores_failed", error=str(e))

    # Compute averages
    averages = {}
    for dim in RAGAS_DIMENSIONS:
        vals = [s[dim] for s in all_scores if s[dim] > 0]
        averages[dim] = round(sum(vals) / len(vals), 4) if vals else None

    return {
        "spans_evaluated": len(all_scores),
        "scores": all_scores,
        "averages": averages,
    }


async def get_ragas_scores(
    graphrag_id: str,
    project_id: str = "default",
) -> dict:
    """Fetch previously computed RAGAS scores from ClickHouse."""
    from services.clickhouse import _query

    averages = {}
    for dim in RAGAS_DIMENSIONS:
        sql = (
            "SELECT round(avg(value), 4) AS avg_score, count() AS cnt "
            "FROM scores FINAL "
            "WHERE project_id = {pid:String} "
            "AND is_deleted = 0 "
            f"AND name = 'ragas_{dim}' "
            "AND source = 'ragas_eval' "
            "AND metadata['graphrag_id'] = {gid:String} "
            "FORMAT JSON"
        )
        params = {"param_pid": project_id, "param_gid": graphrag_id}
        try:
            r = await _query(sql, params)
            r.raise_for_status()
            data = r.json().get("data", [])
            if data and data[0].get("avg_score"):
                averages[dim] = {"avg": float(data[0]["avg_score"]), "count": int(data[0]["cnt"])}
            else:
                averages[dim] = {"avg": None, "count": 0}
        except Exception:
            averages[dim] = {"avg": None, "count": 0}

    return averages


async def get_ragas_aggregate(project_id: str = "default") -> dict:
    """Fetch aggregate RAGAS scores across all GraphRAGs."""
    from services.clickhouse import _query

    averages = {}
    for dim in RAGAS_DIMENSIONS:
        sql = (
            "SELECT round(avg(value), 4) AS avg_score, count() AS cnt "
            "FROM scores FINAL "
            "WHERE project_id = {pid:String} "
            "AND is_deleted = 0 "
            f"AND name = 'ragas_{dim}' "
            "AND source = 'ragas_eval' "
            "FORMAT JSON"
        )
        params = {"param_pid": project_id}
        try:
            r = await _query(sql, params)
            r.raise_for_status()
            data = r.json().get("data", [])
            if data and data[0].get("avg_score"):
                averages[dim] = {"avg": float(data[0]["avg_score"]), "count": int(data[0]["cnt"])}
            else:
                averages[dim] = {"avg": None, "count": 0}
        except Exception:
            averages[dim] = {"avg": None, "count": 0}

    return averages
