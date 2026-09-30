<!-- SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com> -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Data & Retention Settings

Control deployment-wide telemetry retention and how aggressively expensive API responses are cached.

## Purge Traces and Insights {#purge-traces-and-insights}

The **Purge Traces & Insights** danger-zone action permanently deletes telemetry and generated insight data for the deployment.

It removes:

- ClickHouse session events and session aggregates for project `default`.
- Agent insight reports and insight caches/facets for all agents.

It does **not** delete registry agents, versions, skills, hooks, prompts, users, reviews, or audit/security logs.

Use this only when you intentionally need a clean telemetry slate, for example before handing over a demo instance or after importing accidental/private trace data. The action cannot be undone from Observal; take database backups first if you may need the data later.

## Application retention policy {#application-retention}

The admin retention controls store deployment-wide policy values in the following settings:

| Setting | Effect |
|---------|--------|
| `retention.enabled` | Enables scheduled application-level purging |
| `retention.trace_days` | Deletes session events older than this many days |
| `retention.score_days` | Deletes completed and stale insight reports older than this many days |
| `retention.max_trace_count` | Limits the number of retained sessions |

The policy values are independent of registry ownership. Leave a threshold empty when that limit is not needed. If `retention.score_days` is empty, the purge uses twice `retention.trace_days`, with a 30-day minimum.

When `retention.trace_days` or `retention.max_trace_count` is set, every scheduled run also removes data derived from sessions whose source events are gone: session summaries and checkpoints, component activity and publication markers, capability actions older than the cutoff, and scoped Insights facet caches. Matching uses the full project, user, harness, and session identity, so another user's session with the same ID is not affected. A layer snapshot and its component mapping are kept while any retained session for that user still references the snapshot hash. Component and agent reports continue to follow `retention.score_days`.

This derived cleanup runs on every run, not only on runs that delete source events, so a cleanup step that failed earlier is retried even after a count-limited deployment drops back under its limit. On a run that deletes no source events, recently uploaded snapshots and recent capability actions are protected by the older of the oldest retained session event and a 7-day grace period. If a source delete fails or the source cannot be read, derived cleanup is skipped for that run.

Two legacy Insights tables that current versions no longer write are cleaned conservatively:

- `insight_session_meta` has no project, user, or harness identity. A row is removed only if it was computed before the cutoff and its session ID has no retained session event under any project, user, or harness.
- `insight_meta_cache` rows whose period starts before the cutoff, or whose period cannot be parsed, are removed. They are caches and are recomputed if needed.

Scheduled retention does not implement deletion requested for a specific user or listing, and the **Purge Traces & Insights** action does not yet cover the component tables described above.

## ClickHouse TTL {#data-retention}

`data.retention_days` remains the separate ClickHouse TTL setting. It controls automatic expiry of raw session content and defaults to 90 days. Application retention values cannot exceed this ceiling when it is enabled.

| Value | Effect |
|-------|--------|
| `90` (default) | Keep raw telemetry for 90 days |
| `30` | Short TTL for privacy-sensitive deployments |
| `365` | Long TTL for annual analysis |
| `0` | Keep raw telemetry indefinitely, not recommended unless storage is actively managed |

**When to lower:** The deployment has strict data minimization rules, or ClickHouse storage is growing too quickly.

**When to raise:** You need longer trend windows for audits, investigations, or longitudinal agent performance analysis.

## Default Cache TTL {#default-cache-ttl}

Default cache duration, in seconds, for ordinary API responses.

| Value | Effect |
|-------|--------|
| `30` (default) | Good balance between freshness and database load |
| `5` | Very fresh data, higher database pressure |
| `120` | Lower database load, more stale list/detail pages |

## Dashboard Cache TTL {#dashboard-cache-ttl}

Cache duration, in seconds, for expensive dashboard aggregation queries.

| Value | Effect |
|-------|--------|
| `60` (default) | Dashboards feel fresh without hammering ClickHouse |
| `15` | Near-live dashboard updates, higher query load |
| `300` | Lower query load for large deployments, charts can lag by several minutes |

## OTEL Cache TTL {#otel-cache-ttl}

Cache duration, in seconds, for trace and session list endpoints.

| Value | Effect |
|-------|--------|
| `15` (default) | Keeps trace lists responsive while preserving near-live monitoring |
| `5` | Useful during active debugging |
| `60` | Better for large deployments where trace lists are expensive |
