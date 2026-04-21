# Evaluation engine

How Observal scores agents. Architecture, scoring dimensions, and the adversarial hardening that makes scores trustworthy.

## Architecture

The eval pipeline processes one recorded trace through several scorers in sequence, then aggregates into a scorecard with a letter grade.

```
Trace
  ▼
┌──────────────────┐
│ TraceSanitizer   │  strip prompt-injection attempts
└─────────┬────────┘
          ▼
┌──────────────────┐
│ CanaryDetector   │  detect parroted canary tokens
└─────────┬────────┘
          ▼
┌──────────────────┐
│ StructuralScorer │  rule-based: tool efficiency, failures, duplicates
└─────────┬────────┘
          ▼
┌──────────────────┐
│ SLMScorer        │  LLM judge: goal completion, factual grounding, thought process
└─────────┬────────┘
          ▼
┌──────────────────┐
│ AdversarialScorer│  detect benchmark gaming / evaluator probing
└─────────┬────────┘
          ▼
┌──────────────────┐
│ EvalWatchdog     │  meta-check: did scoring actually score anything?
└─────────┬────────┘
          ▼
┌──────────────────┐
│ ScoreAggregator  │  weighted combination, penalties, grade
└─────────┬────────┘
          ▼
       Scorecard
```

Each scorer is independently testable and replaceable. The pipeline is the backbone of `observal admin eval run`.

## The six dimensions

Each produces a 0–10 score.

| Dimension | Scorer | Method |
| --- | --- | --- |
| Goal completion | `SLMScorer` | LLM judge evaluates whether the agent achieved the user's goal |
| Tool call efficiency | `StructuralScorer` | Rule-based: duplicate calls, unused results, excessive retries |
| Tool call failures | `StructuralScorer` | Rule-based: error rate, retry patterns |
| Factual grounding | `SLMScorer` | LLM judge verifies claims against tool output |
| Thought process | `SLMScorer` | LLM judge evaluates reasoning quality |
| Adversarial robustness | `AdversarialScorer` | Rule-based: injection detection, evaluator probing |

The aggregator combines them with configurable weights, applies penalties, and maps the result to A–F.

## BenchJack hardening

Agents can try to game their own evaluations. The BenchJack project documented several attacks; Observal's eval engine mitigates each.

| Pattern | Attack | Mitigation |
| --- | --- | --- |
| 1 | Score inflation via dummy outputs | `EvalWatchdog` detects dimensions that return perfect scores without evidence |
| 2 | Skipped dimensions defaulting to 100 | `EvalWatchdog` flags missing dimensions |
| 4 | Prompt injection in agent output | `TraceSanitizer` strips injection attempts before they reach the LLM judge |
| 5 | Fragile string matching | `MatchingEngine` uses normalized comparison with fuzzy matching |
| 6 | Scoring code that does not actually score | Meta-tests (`test_eval_completeness.py`) validate the scoring engine itself |
| Self-test | All of the above | `test_adversarial_self.py` runs BenchJack attacks against Observal's own pipeline |

## Canary detection

The `CanaryDetector` injects synthetic tokens into trace inputs and checks whether agents parrot them back. Three types, two injection points.

| Type | What gets injected |
| --- | --- |
| `numeric` | A numeric token (e.g. `canary-4712`) |
| `entity` | A named entity (fake PR ID, fake file name) |
| `instruction` | A synthetic instruction the agent should ignore |

| Injection point | Where it lands |
| --- | --- |
| `tool_output` | Appended to a tool response |
| `context` | Added to the agent's prompt/context |

An agent that parrots the canary is likely not reasoning about the inputs at all. Reports surface via `observal admin canary-reports`.

## Weights and penalties

### Weights

Each dimension has a weight between 0.0 and 1.0. All weights must sum to 1.0.

Inspect and set:

```bash
observal admin weights
observal admin weight-set factual_grounding 0.35
```

Weights define what "good" means for your use case. A code-generation agent probably cares more about factual grounding than thought process.

### Penalties

Flat point deductions that fire when a rule matches. Examples:

* `duplicate-call` — same tool called 3+ times with identical args
* `excessive-retries` — more than N retries on the same call
* `unused-tool-result` — tool output never referenced in the final answer

Inspect and tune:

```bash
observal admin penalties
observal admin penalty-set duplicate-call --amount 5 --active
observal admin penalty-set duplicate-call --active=false   # disable without deleting
```

## Fallback: heuristic scoring

If no eval model is configured (`EVAL_MODEL_NAME` empty), the SLM dimensions fall back to heuristic scoring driven by trace metadata — tool call counts, latency, etc.

Useful as a smoke test; not a substitute for real judgment. Configure a real eval model before trusting grades. See [Self-Hosting → Evaluation engine](../self-hosting/evaluation-engine.md).

## RAGAS (bonus)

For GraphRAG retrieval spans, Observal implements four [RAGAS](https://docs.ragas.io/) metrics:

| Metric | What it does |
| --- | --- |
| Faithfulness | Extracts claims from the answer, verifies each against retrieved context |
| Answer relevancy | Evaluates whether the answer addresses the original query |
| Context precision | Checks each retrieved chunk's relevance |
| Context recall | Checks whether ground-truth statements are attributable to the context (requires ground truths) |

All four use LLM-as-judge under the same `EVAL_MODEL_*` configuration. Trigger via the API (`POST /api/v1/dashboard/graphrag-ragas-eval`).

## File map

For engineers who want to poke at the code.

### Backend services (`observal-server/services/eval/`)

| File | Purpose |
| --- | --- |
| `eval_service.py` | Top-level orchestrator — wires every scorer and runs the pipeline |
| `eval_engine.py` | LLM backend abstraction (`LLMJudgeBackend`, `FallbackBackend`) |
| `eval_watchdog.py` | Meta-checker for scoring anomalies |
| `sanitizer.py` | `TraceSanitizer` — strips injections before scoring |
| `adversarial_scorer.py` | Structural scorer for adversarial robustness |
| `canary.py` | `CanaryDetector` — inject and detect canaries |
| `score_aggregator.py` | Weighted aggregation, penalties, grade mapping |
| `slm_scorer.py` | LLM-as-judge scoring for subjective dimensions |
| `structural_scorer.py` | Rule-based scoring + `MatchingEngine` |
| `ragas_eval.py` | RAGAS metrics for GraphRAG spans |

### Models and schemas

| File | Purpose |
| --- | --- |
| `models/eval.py` | `EvalRun`, `Scorecard`, `ScorecardDimension` |
| `models/scoring.py` | `ScoringDimension`, weights, penalty definitions |
| `models/sanitization.py` | `SanitizationReport` |
| `schemas/eval.py` | Pydantic request/response schemas |
| `schemas/judge_output.py` | Structured output schemas for SLM judge |

### API

| File | Purpose |
| --- | --- |
| `api/routes/eval.py` | REST endpoints: trigger evals, fetch scorecards |

### Tests

Live in `tests/eval/`. Meta-tests validate the scorers themselves.

## Running eval tests

```bash
cd observal-server
uv run pytest ../tests/eval/ -q              # all eval tests
uv run pytest ../tests/eval/ -v -k canary    # just canary tests
```

## Related

* [Use Cases → Evaluate and compare agents](../use-cases/evaluate-agents.md) — the playbook
* [Self-Hosting → Evaluation engine](../self-hosting/evaluation-engine.md) — operator setup
* [`observal admin eval`](../cli/admin.md#evaluation-engine)
