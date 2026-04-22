# Evaluation engine

The operator's guide to standing up the eval engine. For the user-facing workflow, see [Use Cases → Evaluate and compare agents](../use-cases/evaluate-agents.md); for the architecture, see [Concepts → Evaluation engine](../concepts/evaluation.md).

## What it needs

Evaluation uses an LLM as a judge for three of the six dimensions (goal completion, factual grounding, thought process). The other three are rule-based and need no model.

**If you skip this page, eval still works** — the server falls back to heuristic-only scoring. It's useful as a smoke test but not a replacement for real judgment. Configure a real eval model before trusting grades.

## Two backends

### AWS Bedrock

```
EVAL_MODEL_NAME=us.anthropic.claude-3-5-haiku-20241022-v1:0
EVAL_MODEL_PROVIDER=bedrock

AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
AWS_SESSION_TOKEN=...            # only for temporary credentials
AWS_REGION=us-east-1
```

Uses `boto3` and the Bedrock Converse API. The IAM principal needs `bedrock:InvokeModel` on the configured model.

### OpenAI-compatible

Works with OpenAI, Azure OpenAI, Ollama, vLLM — anything that implements `/v1/chat/completions`.

```
EVAL_MODEL_URL=https://api.openai.com/v1
EVAL_MODEL_API_KEY=sk-...
EVAL_MODEL_NAME=gpt-4o
EVAL_MODEL_PROVIDER=openai
```

Local Ollama example:

```
EVAL_MODEL_URL=http://localhost:11434/v1
EVAL_MODEL_API_KEY=
EVAL_MODEL_NAME=llama3
EVAL_MODEL_PROVIDER=openai
```

### Moonshot / Kimi

Kimi K2.5 (and K2) are accessible through Moonshot's OpenAI-compatible API. Set `EVAL_MODEL_PROVIDER=moonshot` and the base URL defaults to `https://api.moonshot.ai/v1`; the server also injects `{"thinking": {"type": "disabled"}}` into the request so the model returns a single deterministic JSON response instead of streaming reasoning tokens.

```
EVAL_MODEL_PROVIDER=moonshot
EVAL_MODEL_API_KEY=sk-...
EVAL_MODEL_NAME=kimi-k2.5-preview
```

Override `EVAL_MODEL_URL` only if you're using a third-party Moonshot-compatible gateway.

### Auto-detect

If `EVAL_MODEL_PROVIDER` is empty: model names containing `anthropic` route to Bedrock, names containing `kimi` route to Moonshot, everything else uses the generic OpenAI-compatible path.

## Choosing the judge model

| Consideration | Recommendation |
| --- | --- |
| Judge should be at least as capable as the agent | Same tier or better |
| Cost — every dimension is one LLM call | Use a small/fast model like Claude 3.5 Haiku, GPT-4o-mini, or a local 70B+ |
| Reproducibility | Set a low temperature (0.1 is typical); the judge code already does this |
| Privacy | If traces contain sensitive data, host an offline model (Ollama, vLLM) |

## Offline / air-gapped setups

Run Ollama or vLLM on your network, point `EVAL_MODEL_URL` at it. The whole eval path stays inside your perimeter — the server never reaches out to a cloud LLM.

## Verify the config

```bash
# 1. Run eval on a known trace
observal admin eval run <agent-id> --trace <trace-id>

# 2. Inspect the scorecard
observal admin eval scorecards <agent-id>
observal admin eval show <scorecard-id>
```

If scores come back as null or uniformly perfect, check server logs:

```bash
docker logs -f observal-api
```

Common errors:

* `boto3: NoCredentialsError` — AWS credentials missing or wrong region
* `openai.AuthenticationError` — wrong API key
* `httpx.ConnectError` — `EVAL_MODEL_URL` unreachable

## Scoring cost

Every scorecard is 3–4 LLM calls (one per judged dimension, plus the sanitizer/adversarial checks which are structural). At OpenAI gpt-4o-mini prices (~$0.00015/1K input, ~$0.0006/1K output) and ~2K tokens in / 500 tokens out per call, a scorecard costs roughly **$0.003**. Cheap individually; add up at scale. Run eval selectively or schedule off-hours.

## Tuning weights and penalties

Dimensions are combined with configurable weights. Adjust via the CLI:

```bash
observal admin weights
observal admin weight-set goal_completion 0.30
observal admin weight-set factual_grounding 0.30
observal admin weight-set tool_efficiency 0.15
observal admin weight-set tool_failures 0.10
observal admin weight-set thought_process 0.10
observal admin weight-set adversarial_robustness 0.05
```

Weights must sum to 1.0.

Penalties fire on rule matches (e.g. "agent called the same tool with identical args 3 times"):

```bash
observal admin penalties
observal admin penalty-set duplicate-call --amount 5 --active
```

## Canaries

Canaries inject synthetic tokens into trace inputs and detect whether agents parrot them. See the [Canary injection section](../cli/admin.md#canary-injection-eval-integrity) of the admin CLI reference.

## RAGAS evaluation (optional)

For GraphRAG retrieval spans, Observal implements the four core [RAGAS](https://docs.ragas.io/) metrics — faithfulness, answer relevancy, context precision, context recall. They use the same `EVAL_MODEL_*` configuration.

Trigger:

```bash
curl -X POST http://localhost:8000/api/v1/dashboard/graphrag-ragas-eval \
  -H "X-API-Key: $OBSERVAL_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"graphrag_id": "<id>", "limit": 20}'
```

Context recall requires `ground_truths` — a map of `span_id → expected_answer`. Without it, recall is skipped.

Results appear at the `/graphrag-metrics` page in the web UI.

## Next

→ [Telemetry pipeline](telemetry-pipeline.md)
