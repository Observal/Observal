<!-- SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com> -->
<!-- SPDX-License-Identifier: AGPL-3.0-only -->

# Enterprise Edition

Source-available enterprise features for Observal. This module is loaded only when `DEPLOYMENT_MODE=enterprise` is set.

> **License**: This directory is covered by a separate Enterprise License (see `ee/LICENSE`). A commercial license is required for production use. Community contributions are not accepted for this directory.

## What It Adds

| Feature | Status | Description |
|---------|--------|-------------|
| Audit Logging | Implemented | Writes all admin and auth events to a ClickHouse `audit_log` table. Queryable and exportable as CSV. |
| SAML 2.0 SSO | Stub (501) | Routes defined for SAML login, ACS callback, and SP metadata. Not yet implemented. |
| SCIM 2.0 Provisioning | Stub (501) | Routes defined for user sync from an identity provider. Not yet implemented. |
| Plugin Registry | Placeholder | Future home for Grafana, Prometheus, Datadog, and SIEM integrations. |

## How It Loads

```
observal-server/main.py
  if DEPLOYMENT_MODE == "enterprise":
      from ee import register_enterprise
      register_enterprise(app, settings)
```

`register_enterprise()` does the following on startup:

1. Validates enterprise config (OAuth credentials, secret key, frontend URL)
2. Mounts enterprise routes under `/api/v1/`
3. Registers audit event handlers on the event bus
4. If config validation fails, adds `EnterpriseGuardMiddleware` that returns 503 on SSO/SCIM routes

## Config Validation

Five settings are checked on startup. If any fail, the issues are stored in `app.state.enterprise_issues` and the guard middleware blocks enterprise-only routes.

| Setting | Requirement |
|---------|------------|
| `SECRET_KEY` | Must not be the default `"change-me-to-a-random-string"` |
| `OAUTH_CLIENT_ID` | Must be set |
| `OAUTH_CLIENT_SECRET` | Must be set |
| `OAUTH_SERVER_METADATA_URL` | Must be set (OIDC discovery endpoint) |
| `FRONTEND_URL` | Must not be localhost |

## Audit Logging

The audit service listens to 8 event types on the event bus:

- `UserCreated`, `UserDeleted`
- `LoginSuccess`, `LoginFailure`
- `RoleChanged`, `SettingsChanged`
- `AlertRuleChanged`, `AgentLifecycleEvent`

Each event is written to ClickHouse with actor info, resource details, HTTP metadata, and a freeform detail JSON field.

### Audit API

- `GET /api/v1/admin/audit-log` -- Query with filters (actor, action, resource type, date range). Paginated, admin-only.
- `GET /api/v1/admin/audit-log/export` -- Download filtered results as CSV. Admin-only.

## Directory Layout

```
ee/
├── __init__.py                    # register_enterprise() entrypoint
├── LICENSE                        # Enterprise license
├── docs/
│   └── cli.md                     # EE configuration reference
├── observal_server/
│   ├── middleware/
│   │   └── enterprise_guard.py    # 503 guard for misconfigured routes
│   ├── routes/
│   │   ├── audit.py               # Audit log query and export
│   │   ├── scim.py                # SCIM stub
│   │   └── sso_saml.py            # SAML stub
│   └── services/
│       ├── audit.py               # Event bus handlers, ClickHouse writes
│       └── config_validator.py    # Startup config checks
└── plugins/
    └── __init__.py                # Future integrations placeholder
```
