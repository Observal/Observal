<!-- SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com> -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Plan: Shareable links — components, teamspaces, and Observal invites

Status: draft for review · Written: 2026-08-08 · Base: `main` @ `e4fb739e`

## Goal

Anyone with a link should be able to reach the thing the link points to, with at most one
sign-in in between:

1. **Component / agent share links** — every agent and component has a stable, copyable URL.
   A signed-in recipient lands directly on the detail page; a signed-out recipient signs in
   and is returned to that exact page.
2. **Teamspace share-to-join links** — a Share button copies the canonical
   `/teamspaces/{handle}` page. A signed-out recipient is sent to sign-in and returned to the
   teamspace page, where they explicitly click **Request to join**. Owners approve or reject;
   the link itself never grants membership.
3. **Invite to Observal** — a link that lets someone who has no account yet get one (even when
   self-registration is off), then continue to the page the invite came from.

## Roadmap mapping

| Roadmap initiative | Priority | Covered here |
|---|---|---|
| Canonical shareable product URLs | P1 | Phases 1 |
| Teamspace share-to-join | P0 | Phases 0–2 |
| Teamspace creation and membership approvals (membership half) | P0 | Phase 2 |
| Cross-product actionable Inbox (teamspace request events) | P1 | Phase 2 wires the reserved kinds |

Roadmap boundaries this plan preserves:

- The shared link **never grants access directly** — membership always goes through an explicit
  request and owner approval.
- Anonymous access to protected routes gets a sign-in challenge carrying the return URL; a
  signed-in non-member requesting team-private content gets **401 with no resource payload**
  (no existence leak).
- No email delivery. Invites are link-channel only; notifications go to terminal + Inbox.
- Marketplace/authorship semantics untouched.

The "invite to Observal" phase is an extension beyond the written roadmap. It is scoped so it
doesn't violate any boundary: an invite token authorizes **account creation only**, never
membership or content access.

## Current state (verified on main, 2026-08-08)

**The sign-in return path exists but is never fed.**
- `web/src/pages/login.tsx` honors a `next` search param in all five completion paths (SAML
  token exchange :121-123, OIDC code exchange :148-150, password login :191-192, register link
  :643) and forwards it to every SSO kickoff (:239-271). `web/src/pages/register.tsx:74-75`
  honors it too. Server round-trips it: `_is_safe_next` at
  `observal-server/api/routes/auth.py:211-212`, stashed in session :215-225, re-appended at
  :520-526 (OIDC) and :867-870 (Google/GitHub); SAML uses RelayState
  (`observal-server/api/routes/sso_saml.py:330-358`, :837-839).
- But the auth guard drops the requested URL at all three redirect sites —
  `web/src/hooks/use-auth.ts:57`, `:64-67`, `:78` — and the 401-refresh failure path
  hard-navigates to `/login?reason=session_expired` (`web/src/lib/api.ts:272-275`,
  `web/src/lib/graphql-ws.ts:32-35`). Today every deep link dies at the login page.
- The only producer of `next` today is the device-auth page (`web/src/pages/device.tsx:34-45`).
- An already-signed-in visitor to `/login` or `/register` is bounced to `/` and `next` is
  ignored (`login.tsx:90-99`, `register.tsx:42-46`); must-change-password also drops it
  (`login.tsx:227`).

**Canonical identity exists in the data model and API, not in web URLs.**
- Agents and all five component types carry `namespace` + `slug` with a uniqueness constraint
  and a `qualified_name` property (`observal-server/models/agent.py:87-118`, mirrored in
  `mcp.py`, `skill.py`, `hook.py`, `prompt.py`, `sandbox.py`).
- The API already resolves UUID **or** `namespace/slug` on the same param:
  `resolve_listing` (`observal-server/api/deps.py:318-374`), `_load_agent`
  (`observal-server/api/routes/agent/helpers.py:33-95`), and
  `GET /api/v1/registry/resolve` (`observal-server/api/routes/registry.py:95-136`) which
  returns `{id, type, namespace, slug, qualified_name}`.
- The web app links everything by UUID (`components/registry/agent-card.tsx:53`,
  `component-card.tsx:48`, etc.), and `/components/$componentId` needs a `?type=` query param
  that silently defaults to `mcps` (`web/src/routes/_authed/components/$componentId.tsx:15`) —
  a copied URL without it queries the wrong collection.
- `/teamspaces/$handle` already exists (`web/src/routes/_authed/teamspaces.$handle.tsx`), but
  handle→team resolution is client-side filtering of `GET /teams/all`
  (`web/src/hooks/use-teams-api.ts:36-47`); there is no server-side by-handle lookup
  (`observal-server/api/routes/teams.py:125` takes UUID only).
- No `notFoundComponent` on the router (`web/src/main.tsx:9-12`) — a bad shared link renders an
  unmatched shell.
- Redirect precedent for legacy→canonical: `web/src/routes/_authed/insights/$reportId.tsx:15-22`
  resolves then `navigate({ replace: true })`.

**No share UI, no join requests, no invites.**
- No share/permalink button anywhere; clipboard helper exists (`web/src/lib/utils.ts:28-61`)
  and `PageHeader` has empty action-button slots (`web/src/components/layouts/page-header.tsx:31-39`).
- `TeamMembership` has no request/pending state (`observal-server/models/team.py:43-58`); the
  only add path is owner-initiated upsert (`teams.py:316`). Non-members see "Membership
  required" (`web/src/pages/registry/teamspace-detail.tsx:247-255`) and the teamspaces empty
  state literally says "Ask an owner to add you to one." (`teamspaces.tsx:314`).
- An `invites` table existed and was removed (`observal-server/alembic/versions/007_invites.py`
  → dropped in `008_remove_invites.py`); the only vestige is
  `EventType.INVITE_CREATED` (`observal-server/services/security_events.py:60`).
- Registration is gated by dynamic setting `auth.self_registration_enabled` (default `"false"`,
  `observal-server/services/dynamic_settings.py:243`; gate at `auth.py:329`). SSO deployments
  JIT-provision users (`auth.py:433-474`).

**Inbox (PR #1669, open, branch `feat/cross-product-inbox`) already reserves the hooks this
feature needs.**
- `InboxKind` declares `team_join_requested`, `team_join_decided`, `team_created_pending` as
  "declared ahead of time, wait on the teamspace request flow"
  (branch: `observal-server/models/inbox.py:32-53`).
- `recipients.team_owners(db, team_id)` exists with the comment "join requests and transfer
  offers land here" (branch: `services/inbox/recipients.py:70-78`).
- `_registry_url` builds id-form URLs today and explicitly says it will switch to
  `/agents/{namespace}/{slug}` and `/components/{type}/{namespace}/{slug}` "when those routes
  land" (branch: `services/inbox/registry.py:57-77`).
- Delivery is transactional in the caller's transaction with savepoint-recovered idempotency on
  `(user_id, dedupe_key)` — join-request delivery must use the same `services/inbox/deliver()`.

---

## Phase 0 — Sign-in return path (`next`) everywhere

Small, self-contained, unblocks everything else. Web-only except for one shared constant.

1. **One sanitizer, both sides.** Add `web/src/lib/safe-next.ts` matching the server's
   `_is_safe_next` exactly: must start with a single `/`, reject `//`, reject `\`. Replace the
   four bare `startsWith("/")` checks (`login.tsx:122,149,192`, `register.tsx:75`).
2. **Feed `next` from the guard.** In `useAuthGuard` (`web/src/hooks/use-auth.ts`), all three
   `router.navigate({ to: "/login" })` sites pass
   `search: { next: location.pathname + location.search }` (skip when already `/login` or `/`).
3. **Preserve location on session expiry.** `web/src/lib/api.ts:274` and
   `web/src/lib/graphql-ws.ts:34` become
   `/login?reason=session_expired&next=<encoded current path>`.
4. **Honor `next` when already authenticated.** The signed-in bounce in `login.tsx:90-99` and
   `register.tsx:42-46` navigates to sanitized `next` instead of `/`; must-change-password
   completion (`login.tsx:227`) carries it through.
5. No server changes needed — OIDC/Google/GitHub/SAML round-trips already work. Optional
   cleanup: deduplicate the inline `next` guard at `auth.py:867-870` into `_is_safe_next`.

**Tests:** Vitest for the sanitizer (open-redirect corpus: `//evil.com`, `/\evil.com`,
`https://…`, empty); e2e: deep link → login → land on target for password and OIDC paths;
expired-session mid-navigation returns to the same page.

**Done when:** any protected URL pasted into a signed-out browser ends on that URL after
sign-in, on every auth method, and nothing off-origin can ever be a redirect target.

---

## Phase 1 — Canonical shareable URLs + Share buttons

### Server

1. **Team by-handle lookup.** `GET /api/v1/teams/by-handle/{handle}` → same shape as
   `GET /teams/{team_id}` plus the caller's `role` (null for non-members). All teams are
   already enumerable to every signed-in user via `GET /teams/all` (`teams.py:90`), so
   returning name/handle/description/member_count to a signed-in non-member leaks nothing new.
   Anonymous → 401 (standard `require_role(user)`).
2. **401-no-payload contract for team-private detail.** Roadmap: signed-in non-members
   requesting team-private agents/components get HTTP 401 with no resource payload. Today
   component detail returns 404 (`mcp.py:292-311`) and agent detail 404s via visibility check.
   Add this as an explicit, tested contract decision in this epic — either keep 404 everywhere
   (also non-leaking, current behavior) or move to the roadmap's 401. **Recommendation: follow
   the roadmap's 401-with-empty-body**, because the web app uses 401 as its sign-in-challenge
   trigger and this keeps "not signed in" and "not a member" indistinguishable to a link
   recipient. Whichever way, agents and components must agree (today `GET /agents/{id}`
   requires auth while component detail is optional-auth — `agent/crud.py:560` vs
   `mcp.py:296`).

### Web

3. **Canonical routes** (TanStack file routes; `$agentId`/`$componentId` match one segment, so
   these are new files, not param changes):
   - `/agents/$namespace/$slug` → fetches via existing `GET /agents/{id}` with
     `namespace%2Fslug` (already supported by `_load_agent`).
   - `/components/$type/$namespace/$slug` — `$type` validated against the plural set
     `mcps|skills|hooks|prompts|sandboxes` (mirrors `_COMPONENT_TYPE_PARAM` on the inbox
     branch). Kills the `?type=` defaulting trap.
   - `/teamspaces/$handle` already exists; switch it from client-side `/teams/all` filtering to
     the new by-handle endpoint (keeps the explicit `notFound` state).
4. **Legacy → canonical redirects.** Keep `/agents/$agentId` and `/components/$componentId`
   as resolve-then-redirect routes (precedent: `insights/$reportId.tsx:15-22`): fetch, then
   `navigate({ to: canonical, replace: true })` once namespace/slug are known. UUID links in
   old inbox items, bookmarks, and chat history keep working forever.
5. **Flip link producers to canonical params:** `agent-card.tsx:53`, `component-card.tsx:48`,
   `pages/registry/{home,agents/index,components/index,leaderboard}.tsx`,
   `recommended-for-you.tsx:124`, `pages/admin/insights/detail.tsx:637`. Fall back to the UUID
   route when a payload predates namespace/slug (use `registryIdentity()` from
   `web/src/lib/registry-name.ts`).
6. **Share button.** A small `ShareLinkButton` (copies
   `window.location.origin + canonicalPath` via `copyToClipboard`, toast "Link copied") placed
   in `PageHeader.actionButtonsRight` on agent detail, component detail, and teamspace detail.
7. **`notFoundComponent`** on the router (`main.tsx`) so a dead shared link gets a real
   "not found or not visible to you" page with a sign-in hint when signed out.
8. **Inbox follow-up (after #1669 merges):** flip `_registry_url` to emit the canonical shapes,
   exactly as its docstring plans.

**Out of scope, noted:** rename/transfer redirects (roadmap: "renamed and transferred objects
redirect safely") need an identity-history table; UUID fallback covers stale links until the
ownership-transfer epic lands. Renames of team handles are impossible today
(`PUT /teams/{id}` has no handle field), which simplifies v1.

**Tests:** route render + redirect tests for the legacy routes; e2e: copy link on each detail
page, open in a fresh signed-out context, sign in, land on the same page (composes with
Phase 0); component canonical URL for a non-MCP type resolves the right collection; 401/404
contract tests for team-private content as signed-out, non-member, member, admin.

**Done when:** every product object has a stable copyable URL, shared links survive sign-in,
and unauthorized responses reveal no metadata.

---

## Phase 2 — Teamspace share-to-join

Depends on: Phase 0 (return path), Phase 1 items 1+6 (by-handle endpoint, Share button), and
**PR #1669 merging first** (the inbox kinds and delivery primitives live there).

### Data model

New table `team_membership_requests` (alembic `024_team_membership_requests.py`, assuming inbox
takes 023):

```
id UUID PK
team_id UUID FK teams.id ON DELETE CASCADE
user_id UUID FK users.id ON DELETE CASCADE
status ENUM(pending, approved, rejected, cancelled)  -- 'cancelled' = requester withdrew
message VARCHAR(500) NULL          -- optional note to owners
decided_by UUID FK users.id NULL
decided_at TIMESTAMP NULL
decision_reason VARCHAR(500) NULL
created_at TIMESTAMP
UNIQUE partial index ON (team_id, user_id) WHERE status = 'pending'
```

The row itself is the audit record the roadmap asks for (requester, reviewer, decision, reason,
timestamps). Decisions additionally emit a security event
(`services/security_events.py` — add `TEAM_JOIN_REQUESTED` / `TEAM_JOIN_DECIDED`).

### API (`observal-server/api/routes/teams.py`)

- `POST /teams/{team_id}/join-requests` — self, `require_role(user)`. Member already → 409.
  Pending duplicate → 409 with `"You already have a pending request"` (the partial unique index
  enforces it; catch `IntegrityError` inside a SAVEPOINT, same pattern as inbox delivery). A
  previously rejected user may request again (new row).
- `GET /teams/{team_id}/join-requests?status=` — owner-or-admin (reuse the guard used at
  `teams.py:323`). Requesters can see their own via `GET /teams/{team_id}/join-requests/mine`.
- `POST /teams/{team_id}/join-requests/{request_id}/approve` — owner-or-admin. In one
  transaction: mark approved, insert `TeamMembership(role=member)` (reuse the upsert logic from
  `_upsert_member`), deliver `team_join_decided` to the requester, and supersede the
  `team_join_requested` inbox items for the owners.
- `POST /.../reject` — owner-or-admin, body `{reason?}`. Same transactional shape, no
  membership insert.
- `DELETE /teams/{team_id}/join-requests/{request_id}` — requester cancels own pending request.
- On request creation: deliver `team_join_requested` to `recipients.team_owners(db, team_id)`
  with the dedupe key already specced on the inbox branch
  (`team_join_requested:{team_id}:{requester_id}`), `action_required=True`,
  `action_url=/teamspaces/{handle}?tab=review-queue`.

Join requests grant **member** role only — role upgrades stay owner-initiated
(`POST /teams/{id}/members`). Approval never bypasses last-owner or role logic because it only
ever inserts `member`.

### Web

- **Teamspace detail, non-member view** (`teamspace-detail.tsx`): replace the "Membership
  required" dead end (:247-255) with a **Request to join** button (+ optional message). After
  requesting: "Request pending" state with Cancel. On rejection the state clears (the decision
  arrives via Inbox).
- **New "Review queue" tab** on the teamspace detail page, alongside Agents / Components /
  Members / Review. Visible only to team owners and global admins (same gate as member
  management, `canManageMembers` at :225); other visitors never see the tab. It shows:
  - **Pending join requests** — requester (avatar, name, username), optional message,
    requested-at, with Approve / Reject (reason dialog), mirroring the roster row styling
    (:320-360). The tab label carries a pending-count badge.
  - **Decision history** — past request rows (requester, decision, decided-by, reason,
    timestamps), rendered straight from `team_membership_requests`; no separate history store.
  - The `tab` search param on `/teamspaces/$handle` (`teamspaces.$handle.tsx:19-22`) gains a
    `review-queue` value so Inbox `action_url`s land directly on the tab.
  - Naming note: the existing **Review** tab (listing/version submissions, owner|reviewer
    visibility) sits next to this one. Product decision: membership requests get their own
    tab rather than a section inside Review or Members — the two queues have different
    audiences (Review includes team reviewers; Review queue is owners/admins only) and
    different objects. Keep the labels distinct ("Review" vs "Review queue") and revisit only
    if users confuse them.
- **Share button** (from Phase 1) on the teamspace header copies `/teamspaces/{handle}`.
- **Teamspaces list empty state** (`teamspaces.tsx:314`): "Ask an owner to add you" becomes
  "Open a teamspace to request to join, or ask an owner for a link."

### CLI

`observal team request-join <handle>`, `observal team requests <handle>`,
`observal team approve|reject <handle> <username> [--reason]` in
`observal_cli/cmd_team.py` (which gains the by-handle endpoint instead of its client-side
`_resolve_team_id` filtering at :20-33). Inbox items surface via the `observal inbox` command
from #1669.

**Tests:** pytest around request/approve/reject/cancel/duplicate/re-request, last-owner
invariants untouched, transactional inbox delivery (assert item exists iff membership exists),
non-member vs member vs owner authorization matrix; e2e extending
`tests/e2e/teamspace-review.spec.ts`: signed-out user opens `/teamspaces/{handle}` → login →
back on the page → request → owner approves from the Review queue tab → roster changes;
tab-visibility checks (member and non-member never see the Review queue tab, owner sees the
pending-count badge).

**Done when (roadmap signal):** the return path survives sign-in, expired sessions don't lose
the destination, duplicate requests are handled clearly, and approval is required before the
roster changes.

---

## Phase 3 — Invite to Observal via link

Solves the dead end: on a password deployment with `auth.self_registration_enabled=false`, a
share-link recipient with no account hits the closed-registration screen ("Ask your admin for
access", `register.tsx:96-111`). On SSO deployments this phase is unnecessary — JIT
provisioning (`auth.py:433-474`) already onboards anyone who can pass the IdP, and the Phase 0
`next` path carries them through.

### Design

Resurrect the removed invites design (`007_invites.py` is the schema reference), link-channel
only — **no email sending**, per the roadmap's notification boundary.

Table `invites` (alembic `025_invites.py`):

```
id UUID PK
token_hash VARCHAR(64) UNIQUE      -- sha256 of a secrets.token_urlsafe(32); plaintext shown once
invited_by UUID FK users.id
role ENUM = 'user'                 -- fixed in v1; invites never mint reviewers/admins
max_uses INT NULL                  -- NULL = unlimited until expiry
use_count INT DEFAULT 0
next_path VARCHAR(500) NULL        -- optional, validated by _is_safe_next; e.g. /teamspaces/acme
expires_at TIMESTAMP               -- default now + 7 days
revoked_at TIMESTAMP NULL
created_at TIMESTAMP
```

Plus `invite_redemptions (invite_id, user_id, created_at)` for the audit trail.

### API

- `POST /api/v1/admin/invites` — `require_role(admin)`, gated by new dynamic setting
  `auth.invite_links_enabled` (default `"false"`; add to `DEFAULTS` in
  `services/dynamic_settings.py` — the `auth.` prefix auto-surfaces it in the admin settings
  UI). Returns the plaintext link once:
  `{frontend_url}/register?invite=<token>[&next=<path>]` built from `deployment.frontend_url`.
- `GET /api/v1/admin/invites`, `POST /api/v1/admin/invites/{id}/revoke`.
- `GET /api/v1/auth/invite/{token}/preview` — anonymous; returns only `{valid: bool}` +
  inviter display name. Invalid/expired/revoked/exhausted all return the same shape
  (`valid: false`) — no oracle for token guessing beyond validity itself; rate-limited.
- `POST /auth/register` accepts optional `invite_token`. A valid token bypasses the
  `self_registration_enabled` gate (`auth.py:329`); redemption increments `use_count` and
  writes an `invite_redemptions` row in the same transaction, checked against `max_uses` under
  a row lock. Security events: reuse `EventType.INVITE_CREATED`
  (`security_events.py:60`), add `INVITE_REDEEMED`, `INVITE_REVOKED`.
- Token handling copies the migration-artifact pattern's hygiene
  (`api/routes/admin/migrate.py:353-392`): constant-time hash compare, explicit expiry check,
  never log the token.

### Web

- Admin: an Invites card under the existing admin users page (`pages/admin/users.tsx`) —
  create (expiry, max uses, optional destination path), list, revoke, copy-once.
- `register.tsx`: `?invite=` bypasses the closed-registration screen when the preview says
  valid; after account creation, continue to sanitized `next` (Phase 0 machinery).
- Teamspace share menu (Phase 2) gains, **for admins only**, "Create invite link" which mints
  an invite with `next_path=/teamspaces/{handle}` — so one link takes a brand-new person
  through account creation → teamspace page → Request to join. Membership still requires owner
  approval; the invite grants an account, nothing else.

**Explicitly not in v1:** email-channel invites, invites that mint elevated roles, invites that
auto-join a teamspace (violates the "link never grants access" boundary), non-admin invite
creation (revisit once there's demand — a dynamic setting can later widen it to reviewers).

**Tests:** expiry/revocation/max-uses races (two concurrent redemptions of a 1-use token),
closed-registration bypass only with a valid token, `sso_only` deployments reject
password-register even with a token (`require_password_auth`, `api/deps.py:303-309`), preview
endpoint leaks nothing, full e2e: mint invite → incognito → register → land on teamspace →
request to join.

---

## Sequencing and PR breakdown

Dependencies: `0 → 1 → 2`, `0 → 3`; Phase 2 additionally waits on PR #1669 (inbox) merging.
Phases 1 and 3 can proceed in parallel once 0 lands.

| PR | Contents | Size |
|---|---|---|
| A | Phase 0: `next` from guard + session-expiry + sanitizer parity | S |
| B | `GET /teams/by-handle/{handle}` + web/CLI switch to it | S |
| C | Canonical agent/component routes, legacy redirects, link producers, Share button, notFound page, 401-contract tests | M |
| D | `team_membership_requests` migration + API + inbox wiring (after #1669) | M |
| E | Join-request web UI (Review queue tab + non-member request flow) + CLI commands + e2e | M |
| F | Invites migration + API + register integration + settings key | M |
| G | Invites admin UI + register flow + teamspace "create invite link" | S/M |
| H | Post-#1669 follow-up: `_registry_url` emits canonical URLs | XS |

Each PR keeps the repo's conventions: SPDX headers (`reuse lint`), `ruff` + `pnpm lint` +
`pnpm typecheck` clean, alembic upgrade/downgrade/re-upgrade verified on Postgres, tests in
`tests/` (server) and `tests/e2e/` (Playwright).

## Security checklist (cross-cutting)

- Open redirect: one shared `next` validator client-side, `_is_safe_next` server-side; both
  reject absolute URLs, `//`, and `\`. Every new consumer goes through them.
- No existence leaks: by-handle and detail endpoints return identical 401 (or 404 — see Phase 1
  item 2 decision) for "hidden" and "absent"; invite preview returns only validity; inbox items
  for revoked-membership subjects stay omitted (matches #1669's visibility model).
- Tokens: generated with `secrets.token_urlsafe(32)`, stored hashed (sha256), compared
  constant-time, shown exactly once, never logged, always expiring, always revocable.
- Every state change (join request, decision, invite create/redeem/revoke) emits a security
  event and is reconstructable from Postgres rows alone.
- Rate limiting on `POST join-requests` and the invite preview endpoint.

## Scope additions (requested 2026-08-08, mid-implementation)

1. **Teamspace visibility, GitHub-style.** Teams gain `is_private`
   (migration 026). A private teamspace is hidden from plain non-member users
   everywhere — `GET /teams/all`, by-handle resolution, detail, and join
   requests all answer 404 exactly like a missing team — while members,
   global reviewers, admins, and super_admins keep seeing it. Visibility is
   changed by team owners and team reviewers (plus deployment admins) via
   `PATCH /teams/{id}/visibility`, surfaced as a Make public/private button on
   the teamspace page, a private badge on cards, and
   `observal team visibility`. Changes emit `team.visibility.changed`
   security events.
2. **Open teamspace creation.** `POST /teams` now takes any signed-in user
   (was global reviewer+); the creator becomes owner. Creation accepts an
   initial `visibility` and the web create panel offers the choice.
3. **No auto-approve in teamspaces; explicit self-approve instead.**
   `resolve_publish_target` and `publish_auto_approves_for_entity` never
   auto-approve: every publish (any role, any visibility) enters review as
   pending and fans out `review_requested` inbox items. Team owners and team
   reviewers may then explicitly approve — including their own submissions —
   so each release records a `reviewed_by` decision instead of silently
   skipping review. Covered by rewritten `test_team_publishing.py`
   expectations and a dedicated self-approval test in `test_team_review.py`.

## Open questions (defaults chosen, flag if you disagree)

1. **401 vs 404 for hidden content** — plan follows the roadmap's 401-no-payload; current code
   404s. (Phase 1, item 2.)
2. **Invite creation audience** — admin-only in v1; the roadmap is silent on invites entirely.
3. **What a signed-in non-member sees on a teamspace page** — name, handle, description, member
   count, and the Request button; no roster, no listings. Consistent with `GET /teams/all`
   already exposing name/handle/member_count to all signed-in users.
4. **`team_created_pending` inbox kind** — reserved by #1669 for the teamspace *creation*
   approval flow, which is a separate roadmap initiative; deliberately not in this plan.
