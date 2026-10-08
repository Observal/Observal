<!-- SPDX-FileCopyrightText: 2026 Apoorv Garg <apoorvgarg.work@gmail.com> -->
<!-- SPDX-FileCopyrightText: 2026 SrihariLegend <sriharilegend23@gmail.com> -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Authentication and SSO

How Observal authenticates users and signs tokens, and how to wire up SSO.

## Authentication modes

Observal supports password auth, API keys, OAuth / OIDC, and SAML. The public login page shows only the methods enabled for the deployment.

| Method | How it is enabled | Notes |
| --- | --- | --- |
| Email + password | Default password auth | Used by bootstrap admins and locally managed users |
| Self registration | `auth.self_registration_enabled=true` | Creates standard `user` accounts only |
| OAuth / OIDC | SSO tab settings: `oauth.client_id`, `oauth.client_secret`, `oauth.server_metadata_url` | Uses IdP discovery metadata. API restart required after changes. |
| SAML | SSO tab settings: `saml.*` | SAML setup with JIT provisioning |
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

After initialization, a missing, unreadable, or corrupt active key—or a previously validated retired public key that is missing while still within retention, or an unreadable, corrupt, or replaced retired-key file required for a still-retained key ID—is treated as a key-store outage. In writable POSIX-managed mode, an unavailable coordination file or a lock that cannot be acquired within five seconds is also an outage. Read-only mode does not use the coordination lock and requires a restart to adopt an externally provisioned replacement key. Requests requiring unavailable key material return a generic 503, and JWKS requests return 503 rather than omitting a previously validated, still-retained key; request handling never creates a replacement key. With a healthy key store, malformed, tampered, unknown-key, and algorithm-confused JWTs continue to receive normal authentication rejection. Restore the authoritative shared key directory and its permissions before retrying.

### Normal key rotation and algorithm changes

For managed keys, `KeyManager.rotate_key()` performs a **normal** rotation: it archives the actual active public key before publishing a replacement private key. Already-running workers sharing the same key directory discover the new key on their next operation, and eligible old tokens remain verifiable. There is no built-in rotation endpoint or scheduler. Back up the entire directory, including `retired_*.pem`; ordinary rotation does **not** revoke tokens issued by the former key. Configure key retention to cover the longest access, refresh, or hooks-token lifetime issued under the retiring key. The server does not remember past lifetime settings: lowering retention later can invalidate still-unexpired tokens. Retired-key retention is measured from the archived public-key file's modification time, so backdating or restoring that file with an old modification time can expire its tokens early. JWKS responses require HTTP revalidation, but third-party verifier libraries may cache keys independently; the server cannot force those clients to refresh.

Shared managed-key rotation requires compatible workers on one authoritative key directory hosted on a filesystem with POSIX advisory locking and atomic replacement. Use a coordinated rollout: all workers must run a compatible key-manager version and share the same key-store and signing configuration; mixed-version workers or separate directories are outside the guarantee. On Windows, the unlocked fallback is for compatibility only and does not guarantee multi-worker coordination. `JWT_KEY_READ_ONLY=true` is for a pre-provisioned store and does not allow rotation or live external replacement.

To move between ES256 and RS256, change `JWT_SIGNING_ALGORITHM` and perform a coordinated restart. Startup archives the old public key and generates the selected key type; old tokens remain verifiable until retention expires. A worker left running with a conflicting signing algorithm refuses to sign or rotate rather than changing the algorithm back. Unsupported algorithms and token headers that do not match the resolved key type are rejected.

Adding `JWT_KEY_PASSWORD_FILE` to a previously unencrypted key encrypts it at startup. **Changing the password of an already encrypted `signing.pem` requires an offline key-file update**: stop all API and worker processes, back up the key directory, decrypt the existing private key with the old password, and re-encrypt that **same key** with the new password into an owner-only temporary file in `$JWT_KEY_DIR`. Replace `signing.pem` atomically, update `JWT_KEY_PASSWORD_FILE` to supply the matching new password, then restart all workers together. Changing only the password secret causes startup to fail; the server does not automatically migrate an encrypted key to a different password. Keep the retired public keys and verify that the active key ID and previously issued tokens are unchanged. Subsequent normal rotations remain encrypted.

### Emergency key compromise

Normal rotation retains the old public key and **does not revoke compromised tokens**. For an emergency in a **managed** store, stop all workers, back up the key store, remove the compromised `signing.pem` (and any matching `retired_<kid>.pem`), then restart with a newly generated key. In read-only mode, provision a replacement key before restarting; the server will not generate one. Tokens signed by the compromised key will no longer verify; users may need to log in again. This is a disruptive revocation procedure, not a substitute for normal rotation.

### File-backed SAML keys

SAML service-provider keys can remain outside the settings database:

```dotenv
SAML_SP_PRIVATE_KEY_FILE=/run/secrets/saml_sp_private_key
SAML_SP_X509_CERT_FILE=/run/secrets/saml_sp_x509_cert
```

Both files are required together. File-backed material overrides the generated database key, appears as externally managed in admin responses, and cannot be replaced through the admin API. Replace both files atomically and restart the API to rotate them.

OAuth, Google, GitHub, and SAML secret environment imports also accept the `NAME_FILE` form. File-backed values stay in memory rather than being copied into PostgreSQL or Redis. See [Configuration](configuration.md#secret-files).

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

## Google OAuth (first-class provider) {#google-oauth}

Google sign-in runs as its own provider, separate from the generic OIDC slot above. Both can be enabled at the same time, so a deployment can offer Okta *and* Google on the login screen.

Set these in the SSO settings page, or set them as container env vars for one-time import at startup. The **Sign in with Google** button appears after the API restarts:

```
GOOGLE_OAUTH_CLIENT_ID=1234567890-abc...apps.googleusercontent.com
GOOGLE_OAUTH_CLIENT_SECRET=GOCSPX-...
```

The Google OIDC discovery URL is hardcoded server-side, so you don't need to set it.

### Creating the Google OAuth client

1. Open the [Google Cloud Console](https://console.cloud.google.com/apis/credentials) in the project you want to use.
2. Click **Create Credentials → OAuth client ID**.
3. **Application type:** Web application.
4. **Authorized JavaScript origins:** `{FRONTEND_URL}` (e.g. `https://observal.your-company.internal`).
5. **Authorized redirect URI:** `{FRONTEND_URL}/api/v1/auth/oauth/google/callback`.
6. Copy the generated **Client ID** and **Client secret** into SSO settings or your container env.
7. Restart the API container so the Authlib client is rebuilt.

### Restricting to specific email domains {#google-allowed-domains}

Set `GOOGLE_OAUTH_ALLOWED_DOMAINS` to a comma-separated list of domains. Anyone outside the list is rejected with a 403, even if they have a valid Google account.

```
GOOGLE_OAUTH_ALLOWED_DOMAINS=acme.com,acme.io
```

Leave it unset to allow any Google account (including personal `@gmail.com` addresses) to provision themselves as `role=user`.

### Notes

- Observal additionally requires Google's `email_verified` claim to be `true`. Unverified accounts (rare on Google but possible) are rejected with a 400.
- The first Google user is **not** automatically an admin (matches the generic OIDC behavior). Bootstrap a local admin first, then use that account to promote the Google user.
- The auth provider and Google subject ID are recorded on the user row (`auth_provider="google"`, `sso_subject_id=<google-sub>`) for audit purposes.

## GitHub OAuth (first-class provider) {#github-oauth}

GitHub sign-in runs as its own provider, alongside generic OIDC and Google. Unlike those two, GitHub is plain OAuth 2.0 (not OIDC): there is no discovery URL and no ID token. Observal fetches the profile and email list from the GitHub REST API after the code exchange.

Set these in the SSO settings page, or as container env vars for one-time import at startup. The **Sign in with GitHub** button appears after the API restarts:

```
GITHUB_OAUTH_CLIENT_ID=Iv1.abc123...
GITHUB_OAUTH_CLIENT_SECRET=ghp_... / github_pat_... style secret
```

### Creating the GitHub OAuth app

1. Open **Settings → Developer settings → OAuth Apps** (on your personal account or, preferably, your GitHub organization) and click **New OAuth App**.
2. **Homepage URL:** `{FRONTEND_URL}` (e.g. `https://observal.your-company.internal`).
3. **Authorization callback URL:** `{FRONTEND_URL}/api/v1/auth/oauth/github/callback`.
4. Copy the generated **Client ID** and generate a **Client secret**; put both into SSO settings or your container env.
5. Restart the API container so the Authlib client is rebuilt.

### Restricting to GitHub organizations {#github-allowed-orgs}

Set `GITHUB_OAUTH_ALLOWED_ORGS` to a comma-separated list of GitHub organization slugs. Only *active* members of at least one listed org can sign in; everyone else is rejected with a 403. Pending invitations don't count.

```
GITHUB_OAUTH_ALLOWED_ORGS=acme-inc,acme-labs
```

When an org allowlist is configured, Observal requests the `read:org` scope (in addition to `read:user user:email`) so it can see private org memberships. Members may need to grant/request org approval for the OAuth app if the org restricts third-party access.

Leave it unset to allow any GitHub account to provision itself as `role=user`.

### Notes

- Observal only accepts **verified** email addresses from `GET /user/emails` (preferring the primary). The profile-level `email` field is never trusted, and accounts with no verified email are rejected with a 400.
- Departments are not populated automatically from GitHub (there is no groups claim). Assign them in **Admin → Users**, individually or via bulk upload — same as Google users.
- The auth provider and the *numeric* GitHub user ID are recorded on the user row (`auth_provider="github"`, `sso_subject_id=<github-id>`). The numeric ID is used instead of the login handle because handles can be renamed and re-registered.

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

## Operational controls

Observal includes:

* **Audit logging**: every privileged action lands in ClickHouse's `audit_log`
* **SSO-only mode** (`deployment.sso_only=true`)

See `docs/self-hosting/sso-cli.md` for SSO CLI commands.

## Next

→ [Session tracking and reconciliation](../core-concepts/session-tracking.md)
