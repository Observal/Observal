<!-- SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com> -->
<!-- SPDX-FileCopyrightText: 2026 tsitu0 <tomsitu0102@gmail.com> -->
<!-- SPDX-License-Identifier: AGPL-3.0-only -->

# E2E Test Checklist - Enterprise Mode

This checklist covers enterprise-only features enabled by `OBSERVAL_LICENSE_KEY`. Run the [local checklist](e2e-test-checklist.md) first; it covers all base features (registry, agents, components, reviews, traces, ratings). This checklist layers enterprise-specific tests on top.

## Test Accounts

| # | Account | Role | Provisioned via | Purpose |
|---|---------|------|-----------------|---------|
| 1 | Super Admin | `super_admin` | Bootstrap / demo seed | Initial setup, SAML config, SCIM tokens |
| 2 | Admin | `admin` | SCIM or manual | SSO admin, audit log viewer, diagnostics |
| 3 | SSO User A | `user` | SAML JIT provisioning | First SSO login, verify account creation |
| 4 | SSO User B | `user` | SCIM provisioning | SCIM-created user, verify SAML login works |
| 5 | SCIM User C | `reviewer` | SCIM provisioning | Verify SCIM role assignment + update |

---

## Prerequisites

- Docker Engine >= 24.0 with Compose v2
- A SAML 2.0 IdP available for testing (e.g., [mocksaml](https://mocksaml.com), Keycloak, Okta dev tenant)
- CLI installed: `uv tool install --editable .`

---

## 1. Enterprise Environment Setup

- [ ] Copy `.env.example` to `.env`
- [ ] Set `OBSERVAL_LICENSE_KEY` in `.env`
- [ ] In **Admin → SSO**, set `deployment.sso_only=true` if testing SSO-only mode
- [ ] In **Admin → SSO**, configure SAML settings if testing SAML:
  - `saml.idp_entity_id`
  - `saml.idp_sso_url`
  - `saml.idp_x509_cert`
  - `saml.sp_entity_id=http://localhost:8000`
  - `saml.sp_acs_url=http://localhost:8000/api/v1/sso/saml/acs`
  - `saml.jit_provisioning=true`
  - `saml.default_role=user`
- [ ] Start the stack: `make rebuild-clean`
- [ ] Verify all containers healthy: `docker compose -f docker/docker-compose.yml ps`

## 2. Enterprise Guard Validation

- [ ] Hit `GET /api/v1/config/public`; verify `licensed: true`
- [ ] With incomplete SAML config, verify the enterprise guard middleware returns warnings
- [ ] Visit the login page; verify SSO login button is shown (not password form)
- [ ] Attempt `POST /api/v1/auth/register`; verify it is blocked (no self-registration in enterprise mode)
- [ ] Attempt `POST /api/v1/auth/login` with password; verify it is blocked when `deployment.sso_only=true`

## 3. Super Admin - SAML SSO Configuration (UI)

- [ ] Log in as Super Admin (via demo seed or bootstrap)
- [ ] Navigate to **SSO & SCIM** page (`/sso`)
- [ ] Configure SAML IdP settings:
  - [ ] Set IdP Entity ID
  - [ ] Set IdP SSO URL
  - [ ] Set IdP X.509 Certificate
  - [ ] Optionally set IdP SLO URL
  - [ ] Optionally set IdP Metadata URL
- [ ] Save SAML configuration
- [ ] Verify configuration shows as active with a green status badge
- [ ] Download SP metadata (`/api/v1/sso/saml/metadata`) and import into your IdP

## 4. Super Admin - SCIM Token Management (UI)

- [ ] On the **SSO & SCIM** page, go to SCIM Tokens section
- [ ] Create a SCIM token, copy the bearer token value
- [ ] Verify the token appears in the token list with creation timestamp
- [ ] Create a second SCIM token
- [ ] Delete one token; verify it disappears from the list
- [ ] Verify the remaining token still works (test in step 6)

## 5. SAML SSO Login Flow

- [ ] As SSO User A, click "Sign in with SSO" on the login page
- [ ] Verify redirect to IdP login page
- [ ] Authenticate at the IdP
- [ ] Verify redirect back to Observal ACS endpoint
- [ ] Verify JWT cookie is set and user lands on the dashboard
- [ ] Verify the user account was JIT-provisioned with `saml.default_role` (user)
- [ ] Verify the user appears in the Admin > Users list

### SSO Edge Cases

- [ ] Log out and log back in via SSO; verify no duplicate account created
- [ ] Attempt SSO login with an IdP user whose email already exists (SCIM-provisioned); verify it links to the existing account
- [ ] If IdP SLO URL is configured: log out via Observal, verify SLO request is sent

## 6. SCIM User Provisioning

Using the SCIM token from step 4, test the SCIM 2.0 API:

### Discovery

- [ ] `GET /scim/v2/ServiceProviderConfig`; verify supported features
- [ ] `GET /scim/v2/Schemas`; verify User schema returned
- [ ] `GET /scim/v2/ResourceTypes`; verify User resource type

### Create User

- [ ] `POST /scim/v2/Users` with SSO User B details; verify 201 response
  ```json
  {
    "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"],
    "userName": "userb@example.com",
    "name": { "givenName": "User", "familyName": "B" },
    "emails": [{ "value": "userb@example.com", "primary": true }],
    "active": true
  }
  ```
- [ ] Verify user appears in Admin > Users with correct details

### Create User with Role

- [ ] `POST /scim/v2/Users` with SCIM User C, set role to `reviewer` via custom attribute
- [ ] Verify user appears with `reviewer` role

### List & Get

- [ ] `GET /scim/v2/Users`; verify both SCIM users in the list
- [ ] `GET /scim/v2/Users?filter=userName eq "userb@example.com"`; verify filtering works
- [ ] `GET /scim/v2/Users/{id}`; verify individual user fetch

### Update User

- [ ] `PUT /scim/v2/Users/{id}` - update SCIM User C's name, verify change persisted
- [ ] `PATCH /scim/v2/Users/{id}` - change SCIM User C's role, verify change persisted

### Deactivate User

- [ ] `PATCH /scim/v2/Users/{id}`, set `active: false` for SCIM User C
- [ ] Verify SCIM User C cannot log in via SSO
- [ ] `PATCH /scim/v2/Users/{id}` - re-activate, verify login works again

### Delete User

- [ ] `DELETE /scim/v2/Users/{id}` - delete a test user, verify 204
- [ ] Verify user no longer appears in Admin > Users

## 7. SSO User B - Verify SCIM + SAML Integration

- [ ] SSO User B (created via SCIM) logs in via SAML SSO
- [ ] Verify login succeeds and account is correctly linked
- [ ] Verify user details (name, email) match what was set via SCIM

## 8. Admin - Diagnostics Page

- [ ] Log in as Admin
- [ ] Navigate to **Diagnostics** (`/diagnostics`)
- [ ] Verify status cards display:
  - [ ] Overall status (ok / degraded / unhealthy)
  - [ ] Database status + user count + demo account count
  - [ ] JWT keys status + algorithm
  - [ ] Enterprise config: verify no issues listed (or issues match actual state)
- [ ] Verify deployment mode shows "enterprise"

### API Validation

- [ ] `GET /api/v1/admin/diagnostics`; verify JSON response with all health checks
- [ ] Verify `checks.enterprise` section is present (only in enterprise mode)

## 9. Admin - Enterprise Settings

- [ ] Navigate to **Settings** (`/settings`)
- [ ] View existing enterprise settings (data retention, resource limits)
- [ ] Create a new setting (e.g., `resource.clickhouse_memory_limit`)
- [ ] Update an existing setting value
- [ ] Delete a setting
- [ ] Click "Apply Resource Settings"; verify ClickHouse settings are applied

### Trace Privacy

- [ ] `GET /api/v1/admin/org/trace-privacy`; verify current setting
- [ ] Enable trace privacy (`PUT /api/v1/admin/org/trace-privacy` with `trace_privacy: true`)
- [ ] Verify regular admins can only see their own traces (not other users')
- [ ] Verify super_admins still see all traces regardless
- [ ] Disable trace privacy; verify admins see all traces again

## 10. Admin - Audit Log

- [ ] Navigate to **Audit Log** (`/audit-log`)
- [ ] Verify events from previous actions appear (SSO config, SCIM operations, user creation)
- [ ] Test filters:
  - [ ] Filter by actor email
  - [ ] Filter by action (e.g., `admin.saml.update`, `scim.user.create`)
  - [ ] Filter by resource type
  - [ ] Filter by date range
- [ ] Verify pagination works (if enough events)
- [ ] Click **Export CSV**; verify file downloads with correct data

### API Validation

- [ ] `GET /api/v1/admin/audit-log`; verify JSON response
- [ ] `GET /api/v1/admin/audit-log?action=admin.saml.update`; verify filtered results
- [ ] `GET /api/v1/admin/audit-log/export`; verify CSV response

## 11. Admin - Security Events

- [ ] Navigate to **Security** (`/security-events`)
- [ ] Verify security events from previous actions appear (failed logins, config changes, SCIM operations)
- [ ] Test filters:
  - [ ] Filter by event type
  - [ ] Filter by severity (info / warning / critical)
  - [ ] Filter by actor email
- [ ] Verify severity color coding: info=muted, warning=amber, critical=destructive
- [ ] Verify pagination works

### Generate Security Events

- [ ] Attempt login with invalid credentials; verify a `LOGIN_FAILED` event appears
- [ ] Change a user's role; verify a `ROLE_CHANGED` event appears
- [ ] Delete a user; verify a `USER_DELETED` event appears
- [ ] Modify SAML config; verify a `SETTING_CHANGED` event appears

## 12. Admin - User Management (Enterprise)

- [ ] Navigate to **Users** (`/users`)
- [ ] Verify all users are listed (demo + SCIM + JIT-provisioned)
- [ ] Change a user's role via UI; verify it persists
- [ ] Verify password reset is blocked when `deployment.sso_only=true`
- [ ] Verify manual user creation is blocked when `deployment.sso_only=true`
- [ ] Delete a user via UI; verify they are removed

## 13. Audit Logging Coverage

Perform the following actions and verify each generates an audit log entry:

### Trace Access (PHI)

- [ ] View session list → `session.list`
- [ ] View session detail → `session.view`

### Review Workflow

- [ ] List reviews → `review.list`
- [ ] Approve a component → `review.approve`
- [ ] Reject a component → `review.reject`

### Admin Actions

- [ ] View diagnostics → `admin.diagnostics.view`
- [ ] View settings → `admin.settings.list`
- [ ] Update a setting → `admin.settings.update`
- [ ] View audit log → `admin.audit_log.view`
- [ ] Clear cache → `admin.cache.clear`

### SSO/SCIM

- [ ] SAML config update → `admin.saml.update`
- [ ] SCIM token create → `admin.scim_token.create`
- [ ] SCIM user create → `scim.user.create`

## 14. Multi-harness Traces in Enterprise

- [ ] As SSO User A, configure Observal hooks for at least 2 harnesses
- [ ] Run a multi-step prompt in each harness
- [ ] Verify traces appear in the session list with correct platform labels
- [ ] Verify agent attribution shows in traces (agent_name, agent_type, skill_name)
- [ ] Verify trace privacy setting applies (admin vs user visibility)

## 15. CLI in Enterprise Mode

- [ ] `observal auth login`; verify it opens browser for SSO (not password prompt)
- [ ] After SSO login, verify CLI is authenticated
- [ ] `observal self doctor`; verify diagnostics pass
- [ ] `observal scan` -- verify harness discovery works (read-only)
- [ ] `observal doctor patch --all --all-harnesses` -- verify instrumentation works
- [ ] `observal agent pull <agent>`; verify agent pull works with SSO auth token
- [ ] `observal admin review list`; verify review list works (admin only)

## 16. Non-Enterprise Zero Overhead

- [ ] Remove or replace `OBSERVAL_LICENSE_KEY` and restart if testing community mode
- [ ] Verify SSO/SCIM endpoints return 404
- [ ] Verify audit log writes don't happen (no ee handlers registered)
- [ ] Verify no enterprise config warnings in diagnostics
- [ ] Verify login page shows password form (not SSO button)
