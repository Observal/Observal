# SPDX-FileCopyrightText: 2026 Swathi Saravanan <ss4522@cornell.edu>
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Council SLM evidence extractors.

Each extractor asks one binary or schema-constrained question over a
narrow span excerpt and returns a structured fact. **Never returns a
number.** Scoring is the job of `rules.py`.

Tests inject `llm_call` so production calls into `eval_engine._call_model`
or any compatible callable. The contract: `await llm_call(prompt) -> dict`.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

from services.eval.council.cache import CouncilCache, FactCacheKey

if TYPE_CHECKING:
    from services.eval.trace_dag.models import TraceDAG, TraceNode


class LLMCallable(Protocol):
    async def __call__(self, prompt: str) -> dict[str, Any]: ...


@dataclass(frozen=True)
class CouncilQuestion:
    question_id: str
    """Stable identifier — used as part of the cache key."""

    schema_hint: dict[str, str]
    """Brief description of expected output keys, included in the prompt."""

    prompt_template: str
    """Format string that takes `excerpt` and optional `claim`/`context` keys."""


@dataclass(frozen=True)
class CitationFact:
    cited: bool
    evidence_span_id: str | None


@dataclass(frozen=True)
class CouncilFact:
    span_id: str
    question_id: str
    model_snapshot: str
    payload: dict[str, Any]


# ── Extractor: cite_check ──

CITE_CHECK_QUESTION = CouncilQuestion(
    question_id="cite_check_v1",
    schema_hint={"cited": "bool", "evidence_span_id": "str|null"},
    prompt_template=(
        "You are a strict evidence checker. Output ONLY a JSON object. "
        "Given the agent's claim and a list of upstream tool results, decide "
        "whether the claim cites at least one of the tool results.\n\n"
        "Claim: {claim}\n\n"
        "Tool results (each `id: excerpt`):\n{context}\n\n"
        'Output JSON: {{"cited": bool, "evidence_span_id": <id or null>}}'
    ),
)


async def cite_check_extractor(
    *,
    span: TraceNode,
    upstream: list[TraceNode],
    llm_call: LLMCallable,
    cache: CouncilCache,
    model_snapshot: str,
) -> CouncilFact:
    """Does this span's claim cite any upstream span's tool result?"""
    key = FactCacheKey(span_id=span.span_id, question_id=CITE_CHECK_QUESTION.question_id, model_snapshot=model_snapshot)
    hit = cache.get(key)
    if hit is not None:
        return CouncilFact(
            span_id=span.span_id, question_id=key.question_id, model_snapshot=model_snapshot, payload=hit
        )

    claim = (span.output_excerpt or span.output or "").strip()[:1024]
    context_lines = []
    for u in upstream:
        excerpt = (u.output_excerpt or u.output or "").strip()[:512]
        context_lines.append(f"{u.span_id}: {excerpt}")
    prompt = CITE_CHECK_QUESTION.prompt_template.format(claim=claim, context="\n".join(context_lines) or "(none)")

    result = await llm_call(prompt)
    if not isinstance(result, dict):
        result = {}

    payload = {
        "cited": bool(result.get("cited", False)),
        "evidence_span_id": result.get("evidence_span_id") or None,
    }
    cache.put(key, payload)
    return CouncilFact(
        span_id=span.span_id, question_id=key.question_id, model_snapshot=model_snapshot, payload=payload
    )


# ── Extractor: grounded_quantities ──

GROUNDED_QUANTITIES_QUESTION = CouncilQuestion(
    question_id="grounded_quantities_v1",
    schema_hint={"ungrounded_quantities": "list[str]"},
    prompt_template=(
        "Output ONLY a JSON object. List numeric quantities (numbers, percentages, dates) "
        "that appear in the agent's final answer but cannot be found in the retrieval excerpts.\n\n"
        "Final answer: {claim}\n\n"
        "Retrieval excerpts:\n{context}\n\n"
        'Output JSON: {{"ungrounded_quantities": [<quantity>, ...]}}'
    ),
)


async def grounded_quantities_extractor(
    *,
    span: TraceNode,
    retrieval: list[TraceNode],
    llm_call: LLMCallable,
    cache: CouncilCache,
    model_snapshot: str,
) -> CouncilFact:
    """List quantities in the final answer not present in retrieval."""
    key = FactCacheKey(
        span_id=span.span_id,
        question_id=GROUNDED_QUANTITIES_QUESTION.question_id,
        model_snapshot=model_snapshot,
    )
    hit = cache.get(key)
    if hit is not None:
        return CouncilFact(
            span_id=span.span_id, question_id=key.question_id, model_snapshot=model_snapshot, payload=hit
        )

    claim = (span.output_excerpt or span.output or "").strip()[:1024]
    context = "\n".join(((r.output_excerpt or r.output or "")[:512]) for r in retrieval) or "(none)"
    prompt = GROUNDED_QUANTITIES_QUESTION.prompt_template.format(claim=claim, context=context)

    result = await llm_call(prompt)
    if not isinstance(result, dict):
        result = {}

    raw = result.get("ungrounded_quantities") or []
    payload = {"ungrounded_quantities": [str(x) for x in raw if isinstance(x, (str, int, float))]}
    cache.put(key, payload)
    return CouncilFact(
        span_id=span.span_id, question_id=key.question_id, model_snapshot=model_snapshot, payload=payload
    )


# ── Runner ──


ExtractorFn = Callable[..., Awaitable[CouncilFact]]


async def run_extractors(
    dag: TraceDAG,
    extractors: list[tuple[ExtractorFn, dict[str, Any]]],
    *,
    llm_call: LLMCallable,
    cache: CouncilCache,
    model_snapshot: str,
) -> list[CouncilFact]:
    """Sequentially run a list of (extractor, kwargs) pairs over the DAG.

    Each kwargs dict is merged with `{llm_call, cache, model_snapshot}`
    and passed to the extractor. The extractor decides which spans it
    applies to (caller selects spans via kwargs['span']).
    """
    facts: list[CouncilFact] = []
    for fn, kwargs in extractors:
        merged = {**kwargs, "llm_call": llm_call, "cache": cache, "model_snapshot": model_snapshot}
        fact = await fn(**merged)
        facts.append(fact)
    _ = dag  # available for callers that filter spans before constructing extractor list
    return facts
