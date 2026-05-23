<!-- SPDX-FileCopyrightText: 2026 Apoorv Garg <apoorvgarg.21@gmail.com> -->
<!-- SPDX-License-Identifier: AGPL-3.0-only -->

# observal admin

Admin commands. Requires the `admin` or `super_admin` role.

## Command families

* [Settings and users](#settings-and-users)
* [Review workflow](#review-workflow)
* [Diagnostics and cache](#diagnostics-and-cache)
* [Trace privacy](#trace-privacy)
* [SAML SSO (Enterprise)](#saml-sso-enterprise)
* [SCIM provisioning (Enterprise)](#scim-provisioning-enterprise)
* [Security events](#security-events)
* [Audit log (Enterprise)](#audit-log-enterprise)

---

## Settings and users

| Command | Description |
| --- | --- |
| `admin settings` | List server settings |
| `admin set <key> <value>` | Update a server setting |
| `admin users` | List all users |
| `admin create-user <email> <name>` | Create a new user account |
| `admin set-role <email> <role>` | Change a user's role |
| `admin reset-password <email>` | Reset a user's password (interactive or `--generate`) |
| `admin delete-user <email>` | Permanently delete a user account |

### admin create-user

Create a new user account. If no password is provided, a secure random password is generated and displayed once.

| Option | Description |
| --- | --- |
| `--username`, `-u` | Username (optional, auto-generated if omitted) |
| `--role`, `-r` | Role: `admin`, `reviewer`, or `user` (default: `reviewer`) |
| `--password`, `-p` | Password (auto-generated if omitted) |
| `--output`, `-o` | Output format: `table` or `json` |

```bash
observal admin create-user alice@example.com "Alice Smith"

observal admin create-user bob@example.com "Bob Jones" --role admin

observal admin create-user carol@example.com "Carol Lee" -u carol -r reviewer -p s3cret
```

Output:

```
User created successfully.

  Name:     Alice Smith
  Email:    alice@example.com
  Role:     reviewer
  ID:       a1b2c3d4-...

Password: xK9mP2qR...
Save this, it will not be shown again.
```

### admin set-role

Change a user's role. Valid roles: `super_admin`, `admin`, `reviewer`, `user`.

```bash
observal admin set-role alice@example.com admin

observal admin set-role bob@example.com reviewer
```

### Examples (settings, users, password)

```bash
observal admin settings
observal admin set review.require_approval true

observal admin users
observal admin reset-password alice@example.com
observal admin reset-password alice@example.com --generate   # auto-generate

observal admin delete-user abandoned@example.com
```

---

## Review workflow

| Command | Description |
| --- | --- |
| `admin review list` | List pending submissions |
| `admin review show <id>` | Show submission details |
| `admin review approve <id>` | Approve a submission |
| `admin review reject <id> --reason "..."` | Reject a submission |

### Examples

```bash
observal admin review list
observal admin review show <submission-id>
observal admin review approve <submission-id>
observal admin review reject <submission-id> --reason "env vars undocumented"
```

---


## Diagnostics and cache

| Command | Description |
| --- | --- |
| `admin diagnostics` | Show system diagnostics and health status |
| `admin cache-clear` | Clear all server caches |

### admin diagnostics

Reports overall system health, database connectivity, JWT key status, and enterprise configuration issues. Useful for troubleshooting deployment problems.

| Option | Description |
| --- | --- |
| `--output`, `-o` | Output format: `table` or `json` |

```bash
observal admin diagnostics

observal admin diagnostics --output json
```

Output:

```
  Overall: ok
  Mode:    enterprise

  Database: ok
    Users: 42

  JWT:     ok
    Algorithm: RS256

  Enterprise: ok
```

### admin cache-clear

Flushes all in-memory and Redis caches on the server. Useful after bulk data changes or when stale data is suspected.

```bash
observal admin cache-clear
```

Output:

```
All caches cleared.
```

---

## Trace privacy

| Command | Description |
| --- | --- |
| `admin trace-privacy` | View the current trace privacy setting |
| `admin trace-privacy-set <enabled>` | Enable or disable trace privacy (redacts sensitive data) |

### admin trace-privacy

Shows whether trace privacy (sensitive data redaction) is currently enabled or disabled for the organization.

```bash
observal admin trace-privacy
```

Output:

```
  Trace privacy: enabled
```

### admin trace-privacy-set

Enable or disable trace privacy. When enabled, the server scrubs PII and secrets from stored traces. When disabled, traces are stored verbatim.

```bash
observal admin trace-privacy-set true

observal admin trace-privacy-set false
```

---

## SAML SSO (Enterprise)

These commands require enterprise mode on the server.

| Command | Description |
| --- | --- |
| `admin saml-config` | View current SAML SSO configuration |
| `admin saml-config-set` | Create or update SAML SSO configuration |
| `admin saml-config-delete` | Delete SAML SSO configuration (disables SSO) |

### admin saml-config

Displays the IdP entity ID, SSO/SLO URLs, SP entity ID, and whether SAML and JIT provisioning are active.

| Option | Description |
| --- | --- |
| `--output`, `-o` | Output format: `table` or `json` |

```bash
observal admin saml-config

observal admin saml-config --output json
```

Output:

```
SAML SSO Configuration

  idp_entity_id: https://idp.example.com
  idp_sso_url: https://idp.example.com/sso
  idp_slo_url: https://idp.example.com/slo
  sp_entity_id: https://observal.example.com
  saml_active: Yes
  jit_provisioning: Yes
```

### admin saml-config-set

Create or update the SAML SSO configuration.

| Option | Description |
| --- | --- |
| `--idp-entity-id` | IdP Entity ID |
| `--idp-sso-url` | IdP SSO URL |
| `--idp-slo-url` | IdP SLO URL (optional) |
| `--idp-x509-cert` | IdP X.509 certificate (PEM string) |
| `--sp-entity-id` | SP Entity ID |
| `--jit/--no-jit` | Enable or disable JIT user provisioning (default: enabled) |
| `--active/--inactive` | Enable or disable SAML SSO (default: active) |

```bash
observal admin saml-config-set \
    --idp-entity-id https://idp.example.com \
    --idp-sso-url https://idp.example.com/sso \
    --idp-x509-cert "$(cat idp-cert.pem)"

observal admin saml-config-set --inactive   # disable without deleting
```

### admin saml-config-delete

Removes the entire SAML configuration, disabling SSO for all users. Prompts for confirmation unless `--force` is passed.

| Option | Description |
| --- | --- |
| `--force`, `-f` | Skip confirmation prompt |

```bash
observal admin saml-config-delete

observal admin saml-config-delete --force
```

---

## SCIM provisioning (Enterprise)

These commands require enterprise mode on the server.

| Command | Description |
| --- | --- |
| `admin scim-tokens` | List SCIM provisioning tokens |
| `admin scim-token-create` | Create a new SCIM provisioning token |
| `admin scim-token-revoke <token-id>` | Revoke a SCIM provisioning token |

### admin scim-tokens

Shows all SCIM bearer tokens with their prefix, description, active status, and creation date.

| Option | Description |
| --- | --- |
| `--output`, `-o` | Output format: `table` or `json` |

```bash
observal admin scim-tokens

observal admin scim-tokens --output json
```

Output:

```
SCIM Tokens
  ID         Prefix     Description       Active  Created
  a1b2c3d4.. scim_Xk9.. Okta SCIM sync    Yes     2026-03-15
```

### admin scim-token-create

Create a new SCIM provisioning token. The token is shown once on creation. Save it securely.

| Option | Description |
| --- | --- |
| `--description`, `-d` | Token description (optional) |

```bash
observal admin scim-token-create

observal admin scim-token-create --description "Okta SCIM sync"
```

Output:

```
SCIM token created.

Token: scim_Xk9mP2qR...
Save this, it will not be shown again.
  Description: Okta SCIM sync
```

### admin scim-token-revoke

Permanently disables a SCIM token so it can no longer be used for provisioning. Prompts for confirmation unless `--force` is passed.

| Option | Description |
| --- | --- |
| `--force`, `-f` | Skip confirmation prompt |

```bash
observal admin scim-token-revoke abc12345-uuid

observal admin scim-token-revoke abc12345-uuid --force
```

---

## Security events

| Command | Description |
| --- | --- |
| `admin security-events` | View security events log |

### admin security-events

Lists security-relevant events (login attempts, permission changes, etc.) with optional filters.

| Option | Description |
| --- | --- |
| `--type`, `-t` | Filter by event type (e.g. `auth.login`) |
| `--severity`, `-s` | Filter by severity: `info`, `warning`, `critical` |
| `--actor`, `-a` | Filter by actor email |
| `--limit`, `-n` | Maximum number of events to return (default: 50) |
| `--output`, `-o` | Output format: `table` or `json` |

```bash
observal admin security-events

observal admin security-events --type auth.login --severity critical

observal admin security-events --actor alice@example.com -n 100

observal admin security-events --output json
```

Output:

```
Security Events (3)
  Time                Type          Severity  Actor              Outcome  Detail
  2026-05-23T14:02:01 auth.login    critical  attacker@evil.com  failure  brute force detected
  2026-05-23T13:55:12 role.change   warning   admin@example.com  success  user promoted to admin
  2026-05-23T12:30:44 auth.login    info      alice@example.com  success
```

---

## Audit log (Enterprise)

These commands require enterprise mode on the server.

| Command | Description |
| --- | --- |
| `admin audit-log` | Query the audit log |
| `admin audit-log-export` | Export the audit log as CSV |

### admin audit-log

Shows timestamped entries of admin and user actions with actor, resource, IP address, and detail fields.

| Option | Description |
| --- | --- |
| `--action`, `-a` | Filter by action (e.g. `auth.login`, `review.approve`) |
| `--actor` | Filter by actor email |
| `--resource-type`, `-r` | Filter by resource type (e.g. `agent`, `mcp`) |
| `--limit`, `-n` | Maximum entries to return (default: 50) |
| `--output`, `-o` | Output format: `table` or `json` |

```bash
observal admin audit-log

observal admin audit-log --action auth.login --limit 100

observal admin audit-log --actor alice@example.com -r agent

observal admin audit-log --output json
```

Output:

```
Audit Log (3 entries)
  Time                Actor              Action          Resource       IP             Detail
  2026-05-23T14:00:00 admin@example.com  review.approve  mcp/my-server  192.168.1.10
  2026-05-23T13:50:00 admin@example.com  user.create     user/alice     192.168.1.10   role=reviewer
  2026-05-23T12:00:00 alice@example.com  auth.login                     10.0.0.5
```

### admin audit-log-export

Exports the audit log in CSV format. Prints to stdout by default, or writes to a file with `--file`.

| Option | Description |
| --- | --- |
| `--action`, `-a` | Filter by action |
| `--actor` | Filter by actor email |
| `--file`, `-f` | Write output to file instead of stdout |

```bash
observal admin audit-log-export

observal admin audit-log-export --file audit.csv

observal admin audit-log-export --action auth.login --actor bob@example.com
```

---

## Related

* [Self-Hosting → Authentication and SSO](../self-hosting/authentication.md)
* [Concepts → Evaluation engine](../concepts/evaluation.md)
