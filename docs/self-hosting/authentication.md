# Authentication and SSO

How Observal authenticates users and signs tokens, and how to wire up SSO.

## Authentication modes

`DEPLOYMENT_MODE` controls what auth methods are allowed:

| Mode | Self-registration | Bootstrap admin | Email + password | API key | OAuth / OIDC |
| --- | --- | --- | --- | --- | --- |
| `local` (default) | Yes | Yes | Yes | Yes | Yes (if configured) |
| `enterprise` | No | No | No | No | Yes (required) |

Flip to `enterprise` once you're ready to require SSO for all access.

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

Losing these keys invalidates **every** access and refresh token. All users must log in again. Tokens rotate, but only the private key can issue new ones — there is no recovery path without the keys.

Back up the `apidata` volume every time you back up Postgres. See [Backup and restore](backup-and-restore.md).

### Key rotation

To rotate keys, stop the API, delete the files under `$JWT_KEY_DIR`, and restart. New keys are generated. All existing sessions are invalidated — plan for the outage.

## OAuth / OIDC SSO

Set these three and SSO is enabled:

```
OAUTH_CLIENT_ID=your-client-id
OAUTH_CLIENT_SECRET=your-client-secret
OAUTH_SERVER_METADATA_URL=https://accounts.example.com/.well-known/openid-configuration
```

Observal uses [Authlib](https://docs.authlib.org/) and reads the IdP discovery document, so any OIDC-compliant provider works (Auth0, Okta, Azure AD, Google Workspace, Keycloak, Authentik, Dex, etc.).

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
# Get a key — flow depends on your setup (web UI usually)
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
| `RATE_LIMIT_AUTH_STRICT` | `5/minute` | Login and password reset |

Tighten for public-facing deployments.

## Password reset

Users who forget their password request a reset code via `observal auth reset-password --email <email>` or the web UI **Forgot password?** link. The server logs a 6-character code to its console:

```
WARNING - PASSWORD RESET CODE for alice@example.com: A7X9B2 (expires in 15 minutes)
```

An operator reads the log and passes the code to the user out-of-band (Slack, phone). This is deliberate — no email infrastructure needed for the default flow. If you want emailed reset codes, implement an email transport in the server.

## Enterprise extras

Enterprise edition adds:

* **SCIM 2.0 provisioning** — provision / deprovision users from your IdP
* **Audit logging** — every privileged action lands in ClickHouse's `audit_log`
* **SSO-only mode** (`DEPLOYMENT_MODE=enterprise`)

See `/ee/docs/cli.md` in the repo for enterprise-specific CLI commands.

## Next

→ [Evaluation engine](evaluation-engine.md)
