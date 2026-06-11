<!-- SPDX-FileCopyrightText: 2026 Aryan Iyappan <aryaniyappan2006@gmail.com> -->
<!-- SPDX-License-Identifier: AGPL-3.0-only -->

# Product analytics telemetry (PostHog)

Observal can send a small set of product-usage events to [PostHog](https://posthog.com)
(PostHog Cloud US). This is **off by default** and intended **only for the public
observal.io instance**.

> **Enterprise / private deployments: leave this off.**
> Enabling product analytics sends the events documented below to PostHog Cloud
> US, which makes PostHog a data subprocessor for your deployment. If your
> organization has data-residency, SOC 2, or customer-VPC requirements, do not
> set `PRODUCT_ANALYTICS_ENABLED=true`.

This is separate from the [telemetry pipeline](telemetry-pipeline.md), which is
your own trace/observability data and never leaves your deployment.

## How to keep it off

Do nothing. The default is off:

```bash
PRODUCT_ANALYTICS_ENABLED=false   # default
```

With the flag unset or false (or with no `POSTHOG_API_KEY`), the server makes
zero requests to PostHog and the web app never loads or initializes
`posthog-js`.

## Configuration

| Variable | Default | Description |
|---|---|---|
| `PRODUCT_ANALYTICS_ENABLED` | `false` | Master switch. Must be explicitly set to `true` to send anything. |
| `POSTHOG_API_KEY` | empty | PostHog **project** API key (`phc_...`, write-only). Analytics stays off while empty. |
| `POSTHOG_HOST` | `https://us.i.posthog.com` | PostHog ingestion host. |

## The gate

An event is sent only when **all** of the following are true:

1. `PRODUCT_ANALYTICS_ENABLED=true`
2. `POSTHOG_API_KEY` is non-empty
3. The acting user's organization has **not** enabled trace privacy
   (`organizations.trace_privacy`). Orgs that opted into trace privacy emit no
   usage telemetry of any kind.

The same gate controls the web app: the public config endpoint
(`/api/v1/config/public`) only exposes the PostHog key and host when the gate
passes, and `posthog-js` is only initialized when it does.

## Exactly what is sent

### Events

| Event | Source | Fired when | Properties |
|---|---|---|---|
| `user_signed_up` | server | A real (non-demo) user account is created via `/auth/init`, `/auth/bootstrap`, OIDC signup, SAML JIT provisioning, or SCIM provisioning | `utm_source`, `utm_medium`, `utm_campaign` (all nullable), `auth_provider` (`local` / `oidc` / `saml` / `scim`), `org_id` (UUID, nullable) |
| `agent_registered` | server | An agent is created in the registry | `workspace_id` (org UUID), `agent_id` (agent UUID), `agent_type` (agent category, nullable) |
| `invite_sent` | server | An admin creates a teammate invite | `workspace_id` (org UUID), `invite_channel` (`email` / `link`) |
| `invite_accepted` | server | An invited user completes signup via an invite link | `workspace_id` (org UUID) |
| `insights_viewed` | web app | A user opens an insights report page | `workspace_id` (org UUID) |

Notes:

- **Demo accounts emit nothing.**
- SSO/SCIM-provisioned users are counted as signups with null UTMs (bucketed
  as organic by downstream consumers).
- `utm_*` values come from first-touch attribution: the web app stores
  `utm_source` / `utm_medium` / `utm_campaign` from the first URL that carried
  them (in `localStorage`, 90-day expiry, first touch wins) and forwards them
  with the signup request. They are used only for the `user_signed_up` event
  and are never persisted to the database.
- Invite acceptances also emit `user_signed_up` with `utm_source` forced to
  `"invite"` (server-side), so invite-loop signups are attributed correctly
  regardless of stored first-touch UTMs. The invitee's email address is never
  sent — only org and invite UUIDs.

### Identity

- The PostHog distinct ID is always the **user UUID** (`users.id`).
- The web app calls `posthog.identify(<user UUID>)` only — no email, name, or
  any other person properties are set.

### What is never sent

- Email addresses, names, usernames, password hashes, avatars
- Organization names or slugs (UUIDs only)
- Prompts, agent YAML, trace content, session data
- IP addresses — server-side captures explicitly null `$ip` so PostHog stores
  no IP and performs no geolocation

### Web app posture

When enabled, `posthog-js` is initialized with:

- `autocapture: false`
- `capture_pageview: false`
- `disable_session_recording: true`
- `person_profiles: 'identified_only'`

The only frontend event is `insights_viewed`. There is no autocapture, no
pageview tracking, and no session replay. This is a deliberate privacy
posture.

## Reliability

Captures are fire-and-forget: events are queued in memory and flushed by a
background thread, and any PostHog failure (bad key, network down) is logged
and swallowed. Analytics can never fail or slow down an API request. Queued
events are flushed on graceful shutdown.

## Support bundles

`observal support bundle` includes `PRODUCT_ANALYTICS_ENABLED` and
`POSTHOG_HOST` so support can confirm the analytics posture of a deployment.
The `POSTHOG_API_KEY` value is always redacted by the CLI redaction layer
(only its presence is visible).
