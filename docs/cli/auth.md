# observal auth

Authentication and account management.

## Subcommands

| Command | Description |
| --- | --- |
| [`auth login`](#observal-auth-login) | Log in to an Observal server (auto-creates admin on fresh server) |
| [`auth register`](#observal-auth-register) | Self-register a new account with email + password |
| [`auth logout`](#observal-auth-logout) | Clear saved credentials |
| [`auth whoami`](#observal-auth-whoami) | Show the authenticated user |
| [`auth status`](#observal-auth-status) | Check server connectivity, health, and local telemetry buffer |
| [`auth reset-password`](#observal-auth-reset-password) | Reset a forgotten password |

---

## `observal auth login`

Log in to an Observal server. On a fresh server with no users, bootstraps an admin account with your email and password.

### Synopsis

```bash
observal auth login [--server URL] [--key KEY] [--email EMAIL] [--password PASSWORD] [--name NAME]
```

### Options

| Option | Description |
| --- | --- |
| `--server URL` | Override the server URL for this login |
| `--key KEY` | Log in with an API key instead of email/password |
| `--email EMAIL` | Skip the email prompt |
| `--password PASSWORD` | Skip the password prompt (pass via env var in CI) |
| `--name NAME` | Display name used when bootstrapping |

### Example

```bash
observal auth login
# Server URL [http://localhost:8000]: <Enter>
# Method: [E]mail / [K]ey: E
# Email: admin@demo.example
# Password: **************
# Logged in as admin@demo.example (super_admin)
```

Credentials are saved to `~/.observal/config.json` (mode `0600`).

---

## `observal auth register`

Self-register a new user account. Only available when the server is running in `DEPLOYMENT_MODE=local`. Enterprise mode uses SSO/SCIM instead.

### Synopsis

```bash
observal auth register [--server URL] [--email EMAIL] [--password PASSWORD] [--name NAME]
```

### Example

```bash
observal auth register
# Email: alice@example.com
# Display name: Alice
# Password: **************
# Registered as alice@example.com (user)
```

---

## `observal auth logout`

Clears credentials from `~/.observal/config.json`. Does not delete aliases or the telemetry buffer.

```bash
observal auth logout
```

---

## `observal auth whoami`

Print the currently authenticated user.

```bash
observal auth whoami
# alice@example.com (user) — https://observal.your-company.internal
```

Exits non-zero if you're not logged in.

---

## `observal auth status`

Check server connectivity, health, and the local telemetry buffer.

```bash
observal auth status
# Server:   https://observal.your-company.internal — OK (200)
# Auth:     alice@example.com (user)
# Buffer:   0 pending events
# Health:   API ok, Postgres ok, ClickHouse ok, Redis ok
```

Useful as the first step when things aren't working.

---

## `observal auth reset-password`

Reset a forgotten password. The server logs a 6-character reset code to its console — the operator reads it and passes it to you.

### Synopsis

```bash
observal auth reset-password [--email EMAIL]
```

### Flow

```bash
observal auth reset-password --email admin@demo.example
# → server console prints:
#   WARNING - PASSWORD RESET CODE for admin@demo.example: A7X9B2 (expires in 15 minutes)
# Enter reset code: A7X9B2
# New password: **************
# Password reset for admin@demo.example.
```

The same flow is available in the web UI via the **Forgot password?** link.

---

## Environment variables

| Variable | Purpose |
| --- | --- |
| `OBSERVAL_SERVER_URL` | Default server URL for login |
| `OBSERVAL_ACCESS_TOKEN` / `OBSERVAL_API_KEY` | Pre-authenticate without calling `login` (for CI) |
| `OBSERVAL_TIMEOUT` | Request timeout in seconds |

Full list: [Environment variables](../reference/environment-variables.md).

## Related

* [`observal config`](config.md) — where credentials live
* [Self-Hosting → Authentication and SSO](../self-hosting/authentication.md) — server-side auth setup
