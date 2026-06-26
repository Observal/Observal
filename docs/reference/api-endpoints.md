<!-- SPDX-FileCopyrightText: 2026 Apoorv Garg <apoorvgarg.21@gmail.com> -->
<!-- SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com> -->
<!-- SPDX-License-Identifier: AGPL-3.0-only -->

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

## Telemetry

| Method | Path | Description |
| --- | --- | --- |
| `POST` | `/telemetry/ingest` | Batch ingest traces, spans, scores |
| `POST` | `/telemetry/events` | Legacy event ingestion |
| `GET` | `/telemetry/status` | Data flow status |
| `GET` | `/crypto/public-key` | Server public key for payload encryption |

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
| `/api/v1/graphql` | Traces, spans, scores, metrics (query + subscription) |

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
