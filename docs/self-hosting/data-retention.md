<!--
SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
SPDX-License-Identifier: AGPL-3.0-only
-->

# Data & Retention Settings

Control how long telemetry is stored and how aggressively expensive API responses are cached.

## Data Retention {#data-retention}

Maximum age, in days, for telemetry data such as traces, spans, scores, and derived analytics.

| Value | Effect |
|-------|--------|
| `90` (default) | Keep telemetry for 90 days |
| `30` | Short retention for privacy-sensitive deployments |
| `365` | Long retention for annual analysis |
| `0` | Keep forever, not recommended unless storage is actively managed |

**When to lower:** Your organization has strict data minimization rules, or ClickHouse storage is growing too quickly.

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
