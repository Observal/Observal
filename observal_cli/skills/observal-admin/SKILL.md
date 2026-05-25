---
# SPDX-FileCopyrightText: 2026 Hemalatha Madeswaran <hemalathamadeswaran@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only
name: observal-admin
command: observal
description: Observal admin operations including user management, enterprise settings, submission review queue, eval scoring, security events, audit logs, and SSO configuration. Use when the user needs to manage users, approve or reject submissions, run evals, view security events, or configure SAML/SCIM.
version: 2.0.0
owner: observal
---

# Observal Admin Operations

All commands require the `admin` role. Enterprise-only commands (SAML, SCIM, audit-log) require enterprise mode.

## Critical Rules

1. **EXECUTE commands**: run them in your shell. Set timeout to 60 seconds.
2. **Pass `--output json`** on list/show commands.
3. **Pass `--yes` or `--force`** on destructive commands.
4. **If 403 is returned**, confirm role with `observal auth whoami --output json`.

---

## Procedure: Settings & Diagnostics

```bash
observal admin settings --output json
observal admin set KEY VALUE
observal admin diagnostics --output json
observal admin trace-privacy
observal admin trace-privacy-set true
observal admin cache-clear
```

---

## Procedure: User Management

```bash
observal admin users --output json
observal admin create-user EMAIL NAME --role user --output json
observal admin reset-password EMAIL --generate
observal admin set-role EMAIL admin
observal admin delete-user EMAIL --force
```

---

## Procedure: Review Queue

```bash
observal admin review list --output json
observal admin review list --type mcp --output json
observal admin review show REVIEW_ID --output json
observal admin review approve REVIEW_ID
observal admin review approve REVIEW_ID --agent
observal admin review reject REVIEW_ID --reason 'Not reproducible'
```

`--agent` and `--bundle` disambiguate when an ID could refer to multiple entity types.

---

## Procedure: Eval

```bash
observal admin eval run TRACE_ID
observal admin eval scorecards --output json
observal admin eval show SCORECARD_ID --output json
observal admin eval compare CARD_A CARD_B --output json
observal admin eval aggregate --output json
```

---

## Procedure: Security & Audit

```bash
observal admin security-events --limit 50 --output json
observal admin audit-log --limit 100 --output json
observal admin audit-log-export --file audit.csv
```

---

## Procedure: Enterprise SSO

```bash
observal admin saml-config --output json
observal admin saml-config-set \
  --idp-entity-id ID \
  --idp-sso-url URL \
  --idp-x509-cert /path/to/cert.pem \
  --active
observal admin saml-config-delete --force
observal admin scim-tokens --output json
observal admin scim-token-create --description 'Okta'
observal admin scim-token-revoke TOKEN_ID --force
```

---

## Output Contract

1. One sentence stating intent.
2. The exact command in a fenced code block.
3. The result: success / specific error.
4. The next action, or "done".
