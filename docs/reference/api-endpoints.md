<!-- SPDX-FileCopyrightText: 2026 Apoorv Garg <apoorvgarg.21@gmail.com> -->
<!-- SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com> -->
<!-- SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com> -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# API endpoints

REST and GraphQL surface of the Observal server. Unless noted, endpoints require authentication via Bearer token or API key (`Authorization: Bearer <token>` or `X-API-Key: <key>`).

Base path: `/api/v1`.

## Auth

| Method | Path | Description |
| --- | --- | --- |
| `POST` | `/auth/bootstrap` | Auto-create admin on fresh server (localhost only) |
| `POST` | `/auth/register` | Self-registration (email + password; `deployment.sso_only=false` only) |
| `POST` | `/auth/login` | Login with API key or email + password |
| `POST` | `/auth/exchange` | Exchange one-time OAuth code for credentials |
| `GET` | `/auth/whoami` | Current user info |
| `POST` | `/auth/token` | Exchange credentials for JWT access + refresh tokens |
| `POST` | `/auth/token/refresh` | Rotate refresh token for new access token |
| `POST` | `/auth/token/revoke` | Revoke a refresh token |
| `POST` | `/auth/request-reset` | Request password reset (code logged to server console) |
| `POST` | `/auth/reset-password` | Reset password with code + new password |
| `GET` | `/auth/oauth/login` | Initiate OAuth SSO flow |
| `GET` | `/auth/oauth/callback` | OAuth callback handler |

## Registry

Per type: `mcps`, `agents`, `skills`, `hooks`, `prompts`, `sandboxes`.

All `{id}` parameters accept a UUID or a name.

| Method | Path | Description |
| --- | --- | --- |
| `POST` | `/{type}` | Submit / create |
| `GET` | `/{type}` | List approved items |
| `GET` | `/{type}/{id}` | Get details |
| `POST` | `/{type}/{id}/install` | Get harness config snippet |
| `DELETE` | `/{type}/{id}` | Delete |
| `GET` | `/{type}/{id}/metrics` | Metrics |
| `POST` | `/agents/{id}/pull` | Pull agent (installs all components) |

`POST /{type}/{id}/install` accepts `version` for agents, MCP servers, skills, and hooks. The response reports the `version` that was installed; component installs also return its `version_id` and content `digest`.

### Agent versions and locks

Each agent version pins exact component versions. Installs generate every component from its pinned version. Agent versions released before pinning can have unlocked components: those install at their latest approved release, are reported with `source: fallback-latest` in the install `lock`, and are refused by a `strict` install.

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/agents/{id}/versions` | Version history |
| `POST` | `/agents/{id}/versions` | Release a version for review. Components keep the current release's pins unless a component names a `version` or `refresh_components` is true |
| `GET` | `/agents/{id}/versions/{version}/lock` | The version's lock: exact component versions, version ids, and digests. Frozen once approved |
| `GET` | `/agents/{id}/versions/{version}/outdated` | For each pin, the latest approved release and whether the pin is behind |
| `PUT` | `/agents/{id}` | Edits version-owned fields only while the latest version is a draft, pending, or rejected; otherwise `409` |

A component reference's `version` must name an approved (or archived) release. Drafts may also pin a release that is not approved yet, but only a caller who may read it (its owner, co-authors, admins, and reviewers); to anyone else it does not exist, as on the component version routes.

`POST /agents/{id}/install` also accepts `strict`. Its response includes `version` (the agent version installed) and `lock`: `status` (`locked`, `partial`, or `unlocked`), `digest`, `components` with each one's `source`, and `problems`. With `strict: true`, any problem is a `409` and nothing is generated.

### Scan

| Method | Path | Description |
| --- | --- | --- |
| `POST` | `/scan` | Bulk register items from harness config scan |

### Review

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/review` | List pending submissions |
| `GET` | `/review/{id}` | Submission details |
| `POST` | `/review/{id}/approve` | Approve |
| `POST` | `/review/{id}/reject` | Reject |

## Discovery (ARD)

Agentic Resource Discovery endpoints. Authentication is optional: anonymous
callers see public, approved resources only when `deployment.public_registry_enabled`
is on; authenticated callers see what the registry's visibility rules
already grant them (public, their teams', and their own drafts). Errors use the
ARD envelope `{"errorCode": "INVALID_ARGUMENT", "message": "..."}`. See
[ADR 0001](../adr/0001-agentic-resource-discovery.md).

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/.well-known/ard.json` | Manifest of the registry entry plus public approved resources |
| `GET` | `/.well-known/ai-catalog.json` | Predecessor path, same document |
| `POST` | `/api/v1/ard/search` | ARD Search. `score` is relevance only; `obs:approval`, `obs:availability`, `obs:supportedHarnesses` carry the rest |
| `GET` | `/api/v1/ard/agents` | ARD List: deterministic browse with `filter`, `orderBy`, `pageSize`, `pageToken` |
| `POST` | `/api/v1/ard/explore` | ARD Explore: `501` until facets ship |
| `GET` | `/api/v1/ard/entries/{identifier}` | One complete entry by `urn:air:` identifier (Observal-specific) |
| `GET` | `/api/v1/artifacts/{kind}/{uuid}/{version}` | Permanent versioned artifact; `Digest` and `X-Artifact-Digest` headers |

Search request body follows the spec: `{"query": {"text": "...", "filter": {...}}, "federation": "none", "pageSize": 5}`.
Supported filter terms: `type`, `tags`, `capabilities`, `publisher`, `version`,
`obs:kind`, `obs:supportedHarnesses`, `obs:lifecycle`, `obs:activatable`.

## Telemetry

| Method | Path | Description |
| --- | --- | --- |
| `POST` | `/telemetry/events` | Legacy event ingestion |
| `GET` | `/telemetry/status` | Data flow status |
| `POST` | `/ingest/session` | Idempotently ingest indexed session source records and return the highest contiguous acknowledgement |
| `GET` | `/ingest/session/checkpoint` | Get the caller's contiguous line/byte checkpoint for a harness session |

Session record identity is scoped by project, user, harness, session ID, and source line index. Retrying the same content at the same index is safe; different content at an already acknowledged index returns `409`.

Final session requests can include `session_hash` and `hashed_line_count`. The response includes `integrity_ok`, `server_hash`, and `repair_from_line`. A failed audit rewinds the durable checkpoint to the first affected range; the exporter then replays that range idempotently. Hashing and canonical manifest scans occur only for final/audit requests, not incremental ingest.

## Telemetry hooks

| Method | Path | Description |
| --- | --- | --- |
| `POST` | `/telemetry/hooks` | Ingest lifecycle hook events (used by Kiro shell hooks) |

## Alerts

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/alerts` | List alert rules |
| `POST` | `/alerts` | Create alert rule |
| `PATCH` | `/alerts/{id}` | Update alert rule |
| `DELETE` | `/alerts/{id}` | Delete alert rule |
| `GET` | `/alerts/{id}/history` | Alert firing history |
## Feedback

| Method | Path | Description |
| --- | --- | --- |
| `POST` | `/feedback` | Submit rating |
| `GET` | `/feedback/{type}/{id}` | Get feedback |
| `GET` | `/feedback/summary/{id}` | Rating summary |

## Admin

Requires `admin` or `super_admin` role.

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/admin/settings` | List settings |
| `PUT` | `/admin/settings/{key}` | Set a value |
| `GET` | `/admin/users` | List users |
| `POST` | `/admin/users` | Create user |
| `PUT` | `/admin/users/{id}/role` | Change role |
| `PUT` | `/admin/users/{id}/password` | Reset user password (admin) |
| `GET` | `/admin/weights` | Get dimension weights |
| `PUT` | `/admin/weights` | Set dimension weights |
| `GET` | `/admin/canaries/{agent_id}/reports` | Canary detection reports |

## GraphQL

Single endpoint, query + subscription via WebSocket.

| Path | Description |
| --- | --- |
| `/api/v1/graphql` | Session update subscriptions |

Subscriptions use `graphql-ws` protocol.

## Health

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/health` | Readiness - checks DB + ClickHouse |
| `GET` | `/healthz` | Liveness - is the API process alive |

## Rate limiting

Auth endpoints are subject to `RATE_LIMIT_AUTH` and `RATE_LIMIT_AUTH_STRICT`. Non-auth endpoints are not rate-limited by default; put a reverse proxy or API gateway in front if you need it.

## Request size limits

`MAX_REQUEST_SIZE_MB` (default `10`) caps body size on all endpoints. Large telemetry batches may need tuning.

## Related

* [Authentication and SSO](../self-hosting/authentication.md)
* [Hooks specification](hooks-spec.md)
