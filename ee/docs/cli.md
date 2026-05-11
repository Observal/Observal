<!-- SPDX-FileCopyrightText: 2026 Apoorv Garg <apoorvgarg.21@gmail.com> -->
<!-- SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com> -->
<!-- SPDX-License-Identifier: AGPL-3.0-only -->

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
| `SSO_ONLY` | `false` | When true, disables password auth entirely; only SSO login allowed |
| `SAML_IDP_ENTITY_ID` | disabled | IdP entity ID for SAML SSO |
| `SAML_IDP_SSO_URL` | disabled | IdP single sign-on URL |
| `SAML_IDP_X509_CERT` | disabled | IdP signing certificate (base64) |
| `SAML_SP_ENTITY_ID` | auto | SP entity ID (derived from FRONTEND_URL if empty) |
| `SAML_SP_ACS_URL` | auto | SP ACS URL (derived from FRONTEND_URL if empty) |
| `SAML_JIT_PROVISIONING` | `true` | Auto-create users on first SAML login |
| `SAML_DEFAULT_ROLE` | `user` | Default role for JIT-provisioned users |
| `SAML_SP_KEY_ENCRYPTION_PASSWORD` | disabled | Encrypt SP private key at rest |

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

Authentication uses a shared bearer token stored as a SHA-256 hash in the scim_tokens table.

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/v1/scim/Users` | List provisioned users |
| `POST` | `/api/v1/scim/Users` | Create a user from IdP |
| `GET` | `/api/v1/scim/Users/{id}` | Get a specific user |
| `PUT` | `/api/v1/scim/Users/{id}` | Update a user |
| `DELETE` | `/api/v1/scim/Users/{id}` | Deprovision a user |

For detailed setup instructions, see [scim-setup.md](scim-setup.md).

---

## SAML 2.0 SSO

SAML endpoints for identity providers that don't support OIDC.

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/v1/sso/saml/login` | SP-initiated login |
| `POST` | `/api/v1/sso/saml/acs` | Receives IdP response |
| `GET` | `/api/v1/sso/saml/metadata` | SP metadata XML |

For detailed setup instructions, see [saml-setup.md](saml-setup.md).

---

## CLI SSO Authentication

When SSO is the only login method, the CLI uses the OAuth 2.0 Device
Authorization Grant (RFC 8628) to authenticate through a browser.

```bash
observal auth login --sso
```

For CI/CD environments without a browser, set the `OBSERVAL_TOKEN`
environment variable instead.

For detailed instructions, see [cli-sso.md](cli-sso.md).

---

## Enterprise Guard Middleware

When `DEPLOYMENT_MODE=enterprise`, the following routes are blocked:

- `POST /api/v1/auth/bootstrap`, admin bootstrapping disabled (use IdP)

Self-registration is removed in enterprise mode. Users are provisioned via IdP
(OIDC or SAML JIT provisioning on first login) or via SCIM for automated
lifecycle management. In local mode, admins can create users directly through
the admin panel.

All other routes function normally with SSO-based authentication.
