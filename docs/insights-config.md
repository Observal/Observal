<!--
SPDX-FileCopyrightText: 2026 Vishnu Muthiah <vishnu.muthiah04@gmail.com>
SPDX-License-Identifier: AGPL-3.0-only
-->


# AI Insights Configuration

You need to configure an LLM provider so that Observal can generate trace summaries, detect anomalies, and produce natural-language explanations of agent behavior.

## Get Insights running in 5 minutes

1. Get an API key from your LLM provider (Anthropic, OpenAI-compatible, or Azure).
2. Go to **Settings > Insights** in the Observal admin panel.
3. Paste the key into the **API Key** field.
4. Set **Model ID** to a model (e.g., `anthropic/claude-sonnet-4-20250514` for a good balance of speed and quality).
5. Leave all other fields at defaults.
6. Save.

**Checkpoint:** Navigate to any trace in the trace viewer. Within 30 seconds, an "Insights" panel should appear with a natural-language summary. If you see "Insights unavailable — no model configured," double-check that the API key and Model ID are saved.

## Verify it works

```bash
curl -s http://localhost:8000/readyz
```

Expected: `{"status":"ok",...}` or `{"status":"degraded",...}` with component statuses. If insights is configured, the response will include `"initialized": true`.


## Field Reference

### API Key {#api-key}

The secret key used to authenticate with your LLM provider.

**Affects:** All Insights generation (section summaries, synthesis, anomaly detection). Without a valid key, Insights is fully disabled and the "Insights" panel shows "unavailable" on all traces.

**Security notes:**
- The key is stored AES-256 encrypted at rest and never displayed after initial save.
- Rotate immediately if you see `401 Unauthorized` errors in the Insights worker logs — it likely means the key was revoked upstream.

**Values:**

| Value | Effect |
|-------|--------|
| `sk-ant-api03-...` (Anthropic) | Enables Insights via the Anthropic Messages API |
| `sk-proj-...` (OpenAI-compatible) | Routes through OpenAI-compatible providers; set API Base URL accordingly |
| _(empty)_ | Insights fully disabled; no LLM calls are made |

**When to set:** On initial setup, or when rotating credentials after a key leak or expiry.

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| "Insights unavailable" badge on traces | Key missing or empty | Add a valid API key |
| `401` in worker logs | Key revoked or expired | Generate and save a new key |
| `429` in worker logs | Rate limit hit | Reduce batch size or upgrade plan |

### API Base URL {#api-base-url}

Override the default provider endpoint. Leave blank to use the provider's standard URL.

**Affects:** The HTTP endpoint where all Insights LLM requests are sent. Changing this reroutes every model call (sections, synthesis, anomaly detection) to a different gateway or region.

**Values:**

| Value | Effect |
|-------|--------|
| _(blank)_ (default) | Uses the provider's standard endpoint (e.g., `https://api.anthropic.com`) |
| `https://llm-gateway.internal.yourcompany.com/v1` | Routes through a corporate proxy or self-hosted gateway |
| `https://your-resource.openai.azure.com/openai/deployments/gpt-4o` | Azure OpenAI deployment |

**When to set:**
- You run a self-hosted model gateway (e.g., LiteLLM, vLLM, Azure OpenAI).
- You route through a corporate proxy that rewrites requests.
- You use a regional endpoint for data-residency compliance.

**Common mistakes:**
- Including a trailing slash — the SDK appends paths like `/messages`, so a trailing slash produces `//messages`.
- Pointing to an HTML page instead of the API root — the URL should respond to POST, not return a webpage.

### Model Configuration {#model-configuration}

| Field | Purpose | Default |
|-------|---------|---------|
| Model ID | The model name string sent in API requests | _(empty — must be configured)_ |
| Max output tokens | Cap on generated summary length | `16384` (sections model), `4096` (synthesis) |
| Temperature | Randomness (0 = deterministic, 1 = creative) | `0.1` |

**When to adjust temperature:** Almost never. The default `0.1` gives consistent, reproducible summaries. Raise it only if summaries feel too repetitive across similar traces.

#### Sections Model {#sections-model}

The model (or model role) that breaks a trace into logical sections and summarizes each one individually.

**Affects:** Quality and detail of per-section summaries in the Insights panel. This is the most token-intensive role (up to 16384 output tokens per trace). Cost scales linearly with trace complexity.

**Values:**

| Value | Effect |
|-------|--------|
| `anthropic/claude-sonnet-4-20250514` (recommended) | Best cost/quality balance for section summaries |
| `anthropic/claude-haiku-4-5-20251001` | 5x cheaper, shorter summaries; fine for simple traces |
| `anthropic/claude-opus-4-20250514` | Deepest analysis; use for complex multi-tool agent traces |

**When to set:** On initial configuration, or when optimizing cost vs. quality for your workload volume.

#### Synthesis Model {#synthesis-model}

The model that combines all section summaries into a single narrative explanation of the entire trace.

**Affects:** The top-level "Summary" paragraph shown in the Insights panel. Uses fewer tokens (max 4096 output) since it operates on pre-summarized sections, not raw spans.

**Values:**

| Value | Effect |
|-------|--------|
| `anthropic/claude-sonnet-4-20250514` (recommended) | Coherent, well-structured narrative |
| `anthropic/claude-haiku-4-5-20251001` | Shorter synthesis; suitable when section summaries are already sufficient |
| `anthropic/claude-opus-4-20250514` | Richer cross-section reasoning; best for traces with complex inter-tool dependencies |

**When to set:** When you want to use a different model for synthesis than for sections (cost optimization), or when synthesis quality is insufficient for your trace complexity.

#### Facets Model {#facets-model}

The model used for facet-level analysis. Facets are structured data points extracted from each session by this model — they identify anomalies, extract key attributes, and classify span behavior within each section. For example: "tool_call_failed: true", "response_latency: slow", "user_sentiment: frustrated" — these are then aggregated across sessions to surface patterns in Insight reports.

**Affects:** Anomaly detection accuracy and the richness of per-facet metadata tags. Runs once per facet (trace section), so cost scales with the number of facets per trace.

**Values:**

| Value | Effect |
|-------|--------|
| `anthropic/claude-sonnet-4-20250514` (recommended) | Reliable anomaly detection with good classification |
| `anthropic/claude-haiku-4-5-20251001` | Faster, cheaper; may miss subtle anomalies in complex spans |
| `anthropic/claude-opus-4-20250514` | Highest anomaly detection recall; justified for safety-critical workloads |

**When to set:** When anomaly detection is missing issues you care about (upgrade), or when you're paying too much for facet analysis on simple traces (downgrade).

#### Batch Processing {#batch-processing}

Whether Insights report generation runs periodically (batched) or is disabled.

**Affects:** Whether new insight reports are generated automatically. Insights is a periodic report generator that runs every N days (configured by Batch Period) when enough sessions have accumulated since the last report.

**Values:**

| Value | Effect |
|-------|--------|
| `true` (default) | Insight reports are generated periodically based on the batch period and min sessions threshold |
| `false` | No automatic report generation; Insights must be triggered manually |

**When to set:** Disable if you want to control exactly when Insights reports are generated. Enable (default) for automatic periodic report generation.

#### Batch Period {#batch-period}

How often (in days) the system checks for and generates new insight reports. This is the `insights.batch_period_days` setting.

**Affects:** The frequency of insight report generation. The worker runs every N days, checks if enough sessions have accumulated since the last report, and generates a new report if the minimum sessions threshold is met.

**Values:**

| Value | Effect |
|-------|--------|
| `14` (default) | A new insight report is generated every 14 days (if min sessions threshold is met) |
| `7` | Weekly reports; more frequent analysis but higher LLM costs |
| `30` | Monthly reports; cost-optimized for low-volume deployments |

**When to set:** You want more frequent insight reports (shorten), or you want to reduce LLM API costs (lengthen).

#### Min Sessions {#min-sessions}

Minimum number of sessions that must accumulate since the last report before a new report is generated.

**Affects:** Prevents generating reports when there is insufficient new data. When the batch period elapses, the worker checks if at least this many sessions have been recorded since the last report. If not, report generation is skipped until the next period.

**Values:**

| Value | Effect |
|-------|--------|
| `5` (default) | Requires at least 5 new sessions before generating a report |
| `1` | Generate a report even with minimal new data; use for low-traffic deployments |
| `20` | Only generate reports when substantial new data exists; cost-efficient for high-volume deployments |

**When to set:** Low-traffic deployments where sessions accumulate slowly (lower so reports aren't skipped repeatedly), or high-volume deployments where you want reports only when meaningful data exists (raise).

#### Max Facet Calls {#max-facet-calls}

Maximum number of LLM API calls allowed per trace for facet analysis.

**Affects:** Cost cap per trace. Complex traces with many sections could generate dozens of facet calls; this setting prevents runaway costs from a single abnormally large trace.

**Values:**

| Value | Effect |
|-------|--------|
| `100` (default) | Allows detailed analysis of traces with up to 100 sections |
| `50` | Conservative cap; saves cost but may truncate analysis of complex multi-tool traces |
| `200` | Permissive; use for traces with very deep call trees (e.g., recursive agent patterns) |

**When to set:** You see "Facet analysis truncated" warnings in Insights output (increase), or LLM costs are higher than expected due to complex traces (decrease).

### Concurrency {#concurrency}

Controls how many facets (trace sections) are processed in parallel when generating Insights.

| Field | Purpose | Default |
|-------|---------|---------|
| Facet concurrency | Parallel facet processing threads | `25` |

#### Facet Concurrency {#facet-concurrency}

Number of parallel LLM requests the Insights worker makes when processing facets within a batch.

**Affects:** Insights generation speed and LLM API rate-limit consumption. Higher concurrency = faster Insights but more simultaneous API calls. Each in-flight facet holds its trace payload in worker memory.

**Values:**

| Value | Effect |
|-------|--------|
| `25` (default) | Good balance for Anthropic's standard rate limits (~50 req/min) |
| `10` | Conservative; use with lower-tier API plans or shared API keys |
| `50` | Aggressive; halves Insights latency but may trigger `429` on most plans |
| `5` | Minimal load; suitable for development/testing environments |

**When to set:**
- **High latency on Insights** — Increase concurrency (but watch rate limits).
- **`429 Too Many Requests` errors** — Decrease concurrency.
- **Out-of-memory on the worker pod** — Decrease concurrency; each facet holds trace payloads in memory during summarization.

> **Caution:** Setting concurrency above your provider's per-key rate limit will cause cascading retries. Check your provider dashboard for current limits before increasing.
