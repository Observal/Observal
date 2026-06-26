<!-- SPDX-FileCopyrightText: 2026 Apoorv Garg <apoorvgarg.21@gmail.com> -->
<!-- SPDX-License-Identifier: AGPL-3.0-only -->

# Authentication and SSO

How Observal authenticates users and signs tokens, and how to wire up SSO.

## Authentication modes

Observal supports password auth, API keys, OAuth / OIDC, and SAML. The public login page shows only the methods enabled for the deployment.

| Method | How it is enabled | Notes |
| --- | --- | --- |
| Email + password | Default password auth | Used by bootstrap admins and locally managed users |
| Self registration | `auth.self_registration_enabled=true` | Creates standard `user` accounts only |
| OAuth / OIDC | SSO tab settings: `oauth.client_id`, `oauth.client_secret`, `oauth.server_metadata_url` | Uses IdP discovery metadata. API restart required after changes. |
| SAML | SSO tab settings: `saml.*` | Enterprise SAML setup |
| API keys | User generated after login | Inherits the user's role |

Use `deployment.sso_only=true` when password login should be hidden and only SSO should be available.

## SSO-only mode {#sso-only-mode}

`deployment.sso_only` controls whether password-based authentication is available.

| Value | Effect |
| --- | --- |
| `false` (default) | Email and password login stays available alongside SSO. |
| `true` | Password login, password reset, and local user bootstrap are blocked. Users must sign in with OIDC or SAML. |

Set it in **Admin → SSO → Access policy**. Confirm OIDC or SAML works with a real test user before enabling it.

## Self registration {#self-registration}

Controls whether visitors can create their own Observal account from the login page.

| Value | Effect |
|-------|--------|
| `true` | Shows a **Register** button on the login page and allows public account creation |
| `false` (default) | Hides registration and blocks `POST /api/v1/auth/register` |

You can set this in the web UI at **Admin → Settings → Authentication → Self Registration Enabled**. If you prefer the CLI, set the same dynamic setting directly:

```bash
observal admin set auth.self_registration_enabled true
```

New accounts are created with the built-in `user` role. They cannot review submissions, manage users, or change server settings unless an admin promotes them later.

Disable it again with:

```bash
observal admin set auth.self_registration_enabled false
```

## The bootstrap flow

On a fresh server with no users, the `/api/v1/auth/bootstrap` endpoint is available **to localhost only**. When you run `observal auth login`, the CLI detects the empty user table and bootstraps an admin account interactively.

This is how you create the first admin without any pre-existing credential.

Once the first admin exists, bootstrap is disabled.

## JWT signing keys

Tokens are signed with asymmetric keys (ES256 by default, RS256 also supported). Keys are generated on first startup and stored in the `apidata` volume at `$JWT_KEY_DIR` (default `/data/keys`).

```
JWT_SIGNING_ALGORITHM=ES256          # ES256 (default) or RS256
JWT_KEY_DIR=/data/keys
```

### Critical: back up `$JWT_KEY_DIR`

Losing these keys invalidates **every** access and refresh token. All users must log in again. Tokens rotate, but only the private key can issue new ones, and there is no recovery path without the keys.

Back up the `apidata` volume every time you back up Postgres. See [Backup and restore](backup-and-restore.md).

### Key rotation

To rotate keys, stop the API, delete the files under `$JWT_KEY_DIR`, and restart. New keys are generated. All existing sessions are invalidated. Plan for the outage.

## OAuth / OIDC SSO

Set these three in **Admin → SSO → SSO settings**, then restart the API so the OIDC client is rebuilt:

| Setting | Value |
| --- | --- |
| `oauth.client_id` {#oauth-client-id} | Client ID from your IdP |
| `oauth.client_secret` {#oauth-client-secret} | Client secret from your IdP |
| `oauth.server_metadata_url` {#oauth-server-metadata-url} | OIDC discovery URL, for example `https://accounts.example.com/.well-known/openid-configuration` |

Observal uses [Authlib](https://docs.authlib.org/) and reads the IdP discovery document, so any OIDC-compliant provider works (Auth0, Okta, Azure AD, Google Workspace, Keycloak, Authentik, Dex, etc.).

### OIDC Client ID {#oauth-client-id}

The public client identifier from your IdP application registration.

### OIDC Client Secret {#oauth-client-secret}

The private client secret from your IdP application registration. It is stored encrypted and is never shown again after saving.

### OIDC Discovery URL {#oauth-server-metadata-url}

The `.well-known/openid-configuration` URL for your IdP tenant or authorization server.

### Redirect URI

Configure your IdP to allow:

```
{FRONTEND_URL}/api/v1/auth/oauth/callback
```

With `FRONTEND_URL=https://observal.your-company.internal`, that's:

```
https://observal.your-company.internal/api/v1/auth/oauth/callback
```

### First OAuth login

The first user who logs in via OAuth is **not** automatically an admin. Bootstrap a local admin first (via `observal auth login` before enabling OAuth, or via the demo super admin), then use that admin to promote the OAuth user.

### Scope / claims

Observal requests standard `openid profile email` scope. The IdP's `email` claim is the canonical user identifier.

## Role-based access control (RBAC)

Four built-in roles enforced on every endpoint:

| Role | Typical abilities |
| --- | --- |
| `user` | Publish components, install agents, view their own data |
| `reviewer` | + approve/reject registry submissions |
| `admin` | + manage users, change server settings |
| `super_admin` | + sensitive super-admin-only operations |

Change a user's role:

```bash
observal admin users
# GET /api/v1/admin/users/{id}/role   to inspect
# PUT /api/v1/admin/users/{id}/role   to change
```

Or in the web UI at `/settings/users`.

## API keys

Users can generate API keys for scripts and CI. The key inherits the user's role.

```bash
# Get a key - flow depends on your setup (web UI usually)
# Then in CI:
export OBSERVAL_API_KEY=<key>
export OBSERVAL_SERVER_URL=https://observal.your-company.internal

observal ops traces --limit 100 --output json | jq
```

Keys can be revoked via `POST /api/v1/auth/token/revoke`.

## Rate limits

Auth endpoints are rate-limited to slow brute-force attempts:

| Setting | Default | Scope |
| --- | --- | --- |
| `RATE_LIMIT_AUTH` | `10/minute` | General auth endpoints |
| `RATE_LIMIT_AUTH_STRICT` | `5/minute` | Login, registration, and password reset |

Tighten for public-facing deployments.

## Password reset

Users who forget their password request a reset code via `observal auth reset-password --email <email>` or the web UI **Forgot password?** link. The server logs a 6-character code to its console:

```
WARNING - PASSWORD RESET CODE for alice@example.com: A7X9B2 (expires in 15 minutes)
```

An operator reads the log and passes the code to the user out-of-band (Slack, phone). This is deliberate: no email infrastructure needed for the default flow. If you want emailed reset codes, implement an email transport in the server.

## Enterprise extras

Enterprise edition adds:

* **Audit logging**: every privileged action lands in ClickHouse's `audit_log`
* **SSO-only mode** (`deployment.sso_only=true`)

See `/ee/docs/cli.md` in the repo for enterprise-specific CLI commands.

## Next

→ [Telemetry pipeline](telemetry-pipeline.md)
