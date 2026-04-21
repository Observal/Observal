# Evaluate and compare agents

"Did my new prompt make the agent better?" is the hardest question in AI engineering. Observal answers it with structured evaluation across six dimensions on real traces — not a test harness, not a benchmark, real sessions your agents actually ran.

## The six dimensions

| Dimension | How it's scored |
| --- | --- |
| Goal completion | LLM-as-judge (did the agent achieve the task?) |
| Tool call efficiency | Rule-based (duplicates, unused results, excessive retries) |
| Tool call failures | Rule-based (error rate, retry patterns) |
| Factual grounding | LLM-as-judge (claims checked against tool output) |
| Thought process | LLM-as-judge (reasoning chain quality) |
| Adversarial robustness | Rule-based (injection detection, canary parroting, evaluator probing) |

Each dimension produces a score from 0 to 10. The aggregator combines them with configurable weights, applies penalties, and assigns a letter grade (A–F).

For the full architecture — sanitizer, canary detector, watchdog, BenchJack hardening — see [Concepts → Evaluation engine](../concepts/evaluation.md).

## Configure the eval model

Evaluation needs an LLM. Two paths:

**AWS Bedrock** (in `.env`):

```
EVAL_MODEL_NAME=us.anthropic.claude-3-5-haiku-20241022-v1:0
EVAL_MODEL_PROVIDER=bedrock
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
AWS_REGION=us-east-1
```

**OpenAI-compatible** (OpenAI, Azure OpenAI, Ollama, vLLM, anything that implements `/v1/chat/completions`):

```
EVAL_MODEL_URL=https://api.openai.com/v1
EVAL_MODEL_API_KEY=sk-...
EVAL_MODEL_NAME=gpt-4o
EVAL_MODEL_PROVIDER=openai
```

If no eval model is configured, the engine falls back to heuristic scoring — useful as a smoke test but not a replacement for real judgment. See [Self-Hosting → Evaluation engine](../self-hosting/evaluation-engine.md) for the full setup.

## Run an evaluation

Score every trace from an agent:

```bash
observal admin eval run <agent-id>
```

Score one specific trace:

```bash
observal admin eval run <agent-id> --trace <trace-id>
```

The eval engine sanitizes the trace (strips prompt injections), runs structural scoring, calls the LLM judge for subjective dimensions, checks for adversarial behavior, and aggregates the result into a scorecard.

## Read a scorecard

List scorecards for an agent:

```bash
observal admin eval scorecards <agent-id>
observal admin eval scorecards <agent-id> --version 1.2.0
```

Drill in:

```bash
observal admin eval show <scorecard-id>
```

You'll see the per-dimension scores, any penalties that fired, and the final letter grade.

## Compare versions

The whole point. Two versions of an agent, same kinds of tasks, who wins?

```bash
observal admin eval compare <agent-id> --a 1.0.0 --b 2.0.0
```

Output shows the delta per dimension and whether the change is statistically meaningful given sample size.

## Aggregate and track drift

```bash
observal admin eval aggregate <agent-id> --window 50
```

Rolling aggregate over the last N scorecards with drift detection. If goal completion drops 15% in the last 10 sessions, you'll see it here before users complain.

The web UI visualizes this: a trend chart at `/eval/<agent-id>`, plus a per-dimension radar chart and a penalty accordion.

## Tune weights and penalties

Dimensions aren't equally important for every team. A code-generation agent probably cares more about factual grounding than thought process. Tune:

```bash
observal admin weights                               # view current weights
observal admin weight-set factual_grounding 0.35     # override one

observal admin penalties                             # view penalty catalog
observal admin penalty-set duplicate-call --amount 5 --active
```

Weights are between 0.0 and 1.0 and must sum to 1.0. Penalties are flat deductions that fire when their rule matches (e.g. "agent called the same tool with identical args 3 times").

## Eval integrity: canaries

Canaries catch agents that try to game their evaluations — for example, parroting words from the prompt they were told were "important" instead of actually doing the work. Observal's `CanaryDetector` injects tokens and checks whether agents are parroting them.

```bash
observal admin canaries <agent-id>
observal admin canary-add <agent-id> --type numeric --point tool_output
observal admin canary-reports <agent-id>
```

Canary types: `numeric`, `entity`, `instruction`. Injection points: `tool_output`, `context`.

## Caveats

* LLM-as-judge is only as good as the judge model. A cheap model will miss nuance. Use the same generation that powers your agents, or better.
* Heuristic fallback is noisy — configure a real eval model before trusting grades.
* Scoring is not free. Every `eval run` is an LLM call per dimension. Run selectively or schedule off-hours.

## Next

→ [Debug agent failures](debug-agent-failures.md) — when scorecards flag a regression, traces are where you go.
