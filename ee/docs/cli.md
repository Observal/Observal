# Observal Enterprise CLI & API Reference

Enterprise features are enabled by setting `DEPLOYMENT_MODE=enterprise` in your `.env`. These features require the [Observal Enterprise License](../LICENSE).

For the core CLI reference, see [docs/cli/README.md](../../docs/cli/README.md). For setup instructions, see [docs/self-hosting/README.md](../../docs/self-hosting/README.md).

---

## Enterprise Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `DEPLOYMENT_MODE` | `local` | Set to `enterprise` to enable SSO-only auth, SCIM, and audit logging |
| `OAUTH_CLIENT_ID` | disabled | OAuth/OIDC client ID (required in enterprise mode) |
| `OAUTH_CLIENT_SECRET` | disabled | OAuth/OIDC client secret |
| `OAUTH_SERVER_METADATA_URL` | disabled | OIDC discovery URL |

In enterprise mode, self-registration and password-based login are disabled. All authentication goes through your configured identity provider (IdP).

---

## Audit Log API

Enterprise mode automatically logs all admin and write operations to ClickHouse. Audit logs are queryable via the API and exportable as CSV.

### `GET /api/v1/admin/audit-log`

Query audit log entries. Requires admin role.

| Parameter | Type | Description |
|-----------|------|-------------|
| `actor` | string | Filter by actor email |
| `action` | string | Filter by action (e.g. `create`, `delete`, `approve`) |
| `resource_type` | string | Filter by resource type (e.g. `mcp`, `agent`, `user`) |
| `start_date` | datetime | Start date filter |
| `end_date` | datetime | End date filter |
| `limit` | int | Max results (1-500, default 50) |
| `offset` | int | Pagination offset |

```bash
curl "http://localhost:8000/api/v1/admin/audit-log?actor=admin@example.com&limit=20" \
  -H "X-API-Key: $OBSERVAL_KEY"
```

### `GET /api/v1/admin/audit-log/export`

Export audit logs as CSV. Same filters as the query endpoint.

```bash
curl "http://localhost:8000/api/v1/admin/audit-log/export?start_date=2026-01-01" \
  -H "X-API-Key: $OBSERVAL_KEY" -o audit_log.csv
```

---

## SCIM 2.0 Provisioning

SCIM endpoints allow your IdP (Okta, Azure AD, etc.) to automatically provision and deprovision users.

> **Status:** Not yet implemented. All endpoints return `501 Not Implemented`.

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/v1/scim/Users` | List provisioned users |
| `POST` | `/api/v1/scim/Users` | Create a user from IdP |
| `GET` | `/api/v1/scim/Users/{id}` | Get a specific user |
| `PUT` | `/api/v1/scim/Users/{id}` | Update a user |
| `DELETE` | `/api/v1/scim/Users/{id}` | Deprovision a user |

---

## SAML 2.0 SSO

SAML endpoints for identity providers that don't support OIDC.

> **Status:** Not yet implemented. All endpoints return `501 Not Implemented`.

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/v1/sso/saml/login` | Initiate SAML SSO login |
| `POST` | `/api/v1/sso/saml/acs` | Assertion Consumer Service callback |
| `GET` | `/api/v1/sso/saml/metadata` | Service Provider metadata XML |

---

## Enterprise Guard Middleware

When `DEPLOYMENT_MODE=enterprise`, the following routes are blocked:

- `POST /api/v1/auth/bootstrap` — admin bootstrapping disabled (use IdP)
- `POST /api/v1/auth/register` — self-registration disabled (use SCIM or IdP)

All other routes function normally with SSO-based authentication.
