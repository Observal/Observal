<!-- SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com> -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Registry Publish Loop — Single Feature Plan

## Context

Select and implement one independently reviewable registry publish-loop feature from the proposed sequence. The checkout is currently clean on `main` (one commit behind `upstream/main`), and the referenced registry analysis documents and large implementation branch are not present in this worktree.

**Recommendation:** start with **Feature 1: Canonical user namespaces**. Feature 0 has nothing to clean in this worktree, while canonical identity is the first real dependency for team publishing, forks/provenance, and qualified install resolution. Feature 7 (required changelogs) would be a smaller isolated win, but it would not advance the dependency chain.

The current schema still uses globally unique `name` values (`010_global_unique_names`), agents/components carry free-form `owner` strings, and users already have a unique but nullable 32-character `username`. Registration/SSO normally fills usernames via `generate_unique_username()`, but the profile API allows later renames. No namespace columns or namespace service exist yet.

Repository tracing also found three non-obvious constraints:

- Qualified identifiers contain `/`, while current FastAPI routes capture one path segment. A shared resolver can understand `namespace/slug`, but commands cannot safely interpolate it into existing URLs without either route duplication/reordering or a small resolver endpoint that returns the UUID first.
- Components have no `deleted_at`; archived versions remain fetchable/installable. Their canonical identity therefore must stay unique even when archived. Only agents can use a partial unique index excluding soft-deleted rows.
- Listing creation also happens in agent drafts, bulk agent creation, and insight self-learn component generation; these must call the same namespace assignment logic or the new non-null columns will be bypassed.

## Approach

### Identity and migration

- Add `namespace` (user handle), stable `slug`, and computed `qualified_name` (`namespace/slug`) to agents and all five component listings. Keep `name` as display text; changing it does not change the slug.
- Backfill null usernames deterministically, make usernames non-null, derive listing namespaces from their creator/submitter, and slugify existing names. Abort with the affected table/ID if an orphaned creator is detected rather than inventing ownership. Preserve existing usernames during upgrade; reject reserved handles only for new registrations/renames, and deterministically number legacy item slugs that collide within a namespace or with reserved route words (`search`, `search-1`, `search-2`).
- Replace global name uniqueness with `(namespace, slug)`: a partial active index for soft-deleted agents and full uniqueness for components because archived components remain addressable.

### Runtime ownership and resolution

- Centralize handle/slug validation, reserved words, slug generation, identifier parsing, and qualified formatting in `services/registry_namespace.py`.
- Assign the authenticated user's namespace in every creation path; requests cannot spoof it. Block username changes once the user has any listing, including restorable deleted agents.
- Move an item to the target user's namespace during ownership transfer, reject target slug collisions, and return the new qualified identity.
- Resolve UUIDs first, exact `namespace/slug` second, and legacy bare name/slug last. Bare lookup succeeds only for one visible match; ambiguity returns a clear error requiring qualification.
- Add one authenticated `/api/v1/registry/resolve` query endpoint so slash-qualified CLI input can become a UUID without converting every existing FastAPI route to a greedy path parameter. Apply the same approval/owner/private visibility rules as detail routes.

### Clients and generated names

- Have CLI show/install/pull and component lookup commands resolve qualified arguments once, then continue through existing UUID routes. Display canonical names in list/detail output and docs.
- Return identity fields in API detail and summary responses. Keep web navigation UUID-based, but show qualified names and use them in copied install/pull commands.
- Feed stable slugs—not display names or namespace-prefixed names—to harness config generators. Reuse the existing lockfile to detect a second installed item of the same type/slug and pass a deterministic `namespace-slug` local override only for that collision.

## Files to modify

Critical paths (grouped where the same mechanical change applies):

- Migration/models: `observal-server/alembic/versions/016_registry_publish_loop.py`, `models/user.py`, `models/agent.py`, and `models/{mcp,skill,hook,prompt,sandbox}.py`
- Shared identity/resolution: new `observal-server/services/registry_namespace.py`, `api/deps.py`, new `api/routes/registry.py`, and `routes.py`
- Create/load/transfer flows: `api/routes/agent/{crud,draft,helpers,install}.py`, `api/routes/{mcp,skill,hook,prompt,sandbox,bulk,auth,co_authors}.py`, `services/{ownership,username_generator}.py`, and `services/insights/self_learn.py`
- API contracts/config generation: `schemas/{auth,agent,mcp,skill,hook,prompt,sandbox}.py`, `services/harness/__init__.py`, `services/harness/helpers.py`, and component config/install helpers
- CLI/local collision handling: `observal_cli/{client,config,lockfile,cmd_agent,cmd_pull,cmd_component,cmd_mcp,cmd_skill,cmd_hook,cmd_prompt,cmd_sandbox,cmd_transfer}.py`
- Web: `web/src/lib/types/registry.ts`, registry agent/component list and detail pages, `components/registry/{pull-command,component-install-command}.tsx`
- Tests/docs: focused files under `tests/` and `observal_cli/tests/`, `docs/cli/{agent,registry,pull}.md`, and the UUID-or-name guidance in `AGENTS.md`

## Reuse

- Extend `resolve_listing()` in `observal-server/api/deps.py`; all five component route families already call it for UUID-or-name resolution.
- Extend `_load_agent()` / `_agent_to_response()` in `observal-server/api/routes/agent/helpers.py`; agent routes use this separate UUID/prefix/name path.
- Preserve the rules already expressed by `schemas.constants.make_name_validator` and the CLI `_slugify()` / `_validate_name()` helpers, moving the canonical server-side behavior into the shared namespace service rather than creating divergent rules.
- Follow the partial active-name index pattern on `Agent`; replace global component `UniqueConstraint("name")` constraints with namespace-qualified uniqueness.
- Build on the user `username` in `observal-server/models/user.py` as the user namespace source, with an explicit migration fallback for null usernames.
- Reuse `generate_unique_username()` rules for runtime handles and mirror them deterministically in the migration rather than deriving namespaces from free-form `owner` strings.
- Use the existing harness `_sanitize_name()` pipeline, but feed it the stable item `slug` rather than display `name`; do not create namespace-prefixed harness names.
- Keep existing UUID-based web detail links. Add namespace/slug to centralized registry types and visible item labels rather than converting internal web navigation to slash-bearing routes.

## Steps

- [x] Confirm that this clean `main` checkout—not the absent large implementation branch—is the intended source, and select Feature 1.
- [x] Reject username changes after the user owns any listing; allow them beforehand.
- [x] Reject ambiguous bare names and require `namespace/slug`.
- [x] Move canonical identity to the recipient namespace on ownership transfer.
- [x] Add and verify the Alembic backfill, null handling, constraints, indexes, and downgrade for all six listing tables and users.
- [x] Add the minimal shared namespace service and wire every normal, draft, bulk, and self-learn creation path through it.
- [x] Update username registration/generation/change checks, transfer collision handling, and deleted-agent restore behavior.
- [x] Extend component and agent resolvers plus the visibility-safe registry resolver endpoint.
- [x] Add identity fields to schemas/responses and switch harness config naming to stable slugs.
- [x] Resolve qualified CLI references to UUIDs, display canonical names, and use lockfile-backed local disambiguation only on an actual same-slug collision.
- [x] Update web canonical labels/copy commands while retaining UUID routes.
- [x] Update focused tests and documentation; make no team, fork, recommendation, or unrelated dashboard changes.

## Verification

- Run focused Python tests covering slug/handle validation, all six create paths, duplicate slugs across namespaces, same-namespace conflicts, UUID/canonical/unique-bare resolution, ambiguous bare errors, private/draft visibility, username lockout, ownership transfer collisions, restore collisions, and local-name disambiguation.
- Run `python3 scripts/check_migrations.py`; apply `upgrade head` to both a clean PostgreSQL database and a database seeded at revision 015 with null usernames, legacy names, deleted agents, and archived components; inspect backfilled identities and exercise downgrade/upgrade.
- Run focused CLI tests proving `show`, `install`, and agent `pull` resolve `namespace/slug` once and continue by UUID; verify UUID, aliases, row numbers, and unique bare names remain unchanged.
- Run `make lint`, the focused/full pytest commands as appropriate, `pnpm --filter web lint`, `pnpm --filter web typecheck`, and `make check`.
- Smoke test two users publishing the same slug, canonical web copy commands, ambiguous bare rejection, transfer into a free/conflicting namespace, username-change rejection, direct UUID access, and two same-slug local installs. Capture the required frontend screenshot showing canonical identity/install text.
