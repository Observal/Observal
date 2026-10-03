<!-- SPDX-FileCopyrightText: 2026 Naraen Rammoorthi <naraen13@gmail.com> -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# ADR 0003: Provenance-linked registry forks

**Status:** Accepted (design; implementation staged)
**Date:** 2026-10-02
**Deciders:** Observal maintainers

## Context

The registry already gives agents and five component types (MCP servers, skills,
hooks, prompts, sandboxes) separate identities and version histories. A user
needs to adapt another listing without changing its ownership or creating an
untraceable copy. The roadmap calls for independent drafts in personal or team
namespaces; forking an agent must not recursively fork its components. A fork
must follow ordinary review and release policy, not inherit the source's
approval or adoption metrics.

## Decision 1: A fork is a new listing and draft, linked to an approved base

An authenticated user may fork a currently approved listing they can access,
from an **approved** version only. This holds for owners, reviewers and admins:
permission to inspect unapproved content is not permission to fork it. The
base defaults to the highest stable approved release, or the latest approved
prerelease if no stable release exists. A specified non-approved or missing
version is not forkable. Archived sources are not forkable, even when an older
version is still approved.

Create a new agent or component identity and one draft version in a personal or
permitted teamspace namespace. The source and its versions remain untouched;
the fork gets its own owner, review history, releases, downloads, ratings,
recommendations and insights. Keep the base version string by default and
allow an explicit new version string. The draft must be submitted and approved
normally; forking is never an automatic approval.

Agent forks keep the same component **listing references**, not new component
listings. Rebuild the lock and YAML snapshot from the fork's pins. If a source
agent has an unapproved component pin, use an approved component release and
warn, or fail if none exists; never copy unapproved component content. Component
forks copy the selected approved version's content but reset review, validation
and download state. Each component fork is a separate explicit action.

## Decision 2: Target and visibility follow existing publication rules

Use the normal publish-target resolver for namespace, team membership and
visibility. A public source can be forked into an allowed public or team-private
target; unlike GitHub public repository forks, a private fork of a public
source is permitted. A team-private source may be forked only within the same
teamspace with team visibility. A private personal source may be forked only by
its creator into their personal target. Existing audited visibility changes
and transfers still govern forks after creation. Self-forks and forks of forks
are allowed (lineage points to the immediate parent), subject to unique target
identity. Forking a team-private source into another teamspace is deferred.

## Decision 3: Immutable provenance columns on each listing

Add nullable `forked_from_id` (same-table FK), `forked_from_version_id`
(version FK), `forked_from_ref` (internal snapshot) and `forked_at` to each of
the six listing tables. Index `forked_from_id`. The source and version FKs may
be set null if the underlying rows are hard-deleted. The saved reference is
for internal audit/history, **not** a public fallback identity. Resolve the
live source with the *current viewer's* access whenever showing lineage. If it
is no longer accessible, return no identifying source details and show only
"Source unavailable"; never expose the stored ref, source ID or base version
as a fallback. Public discovery must likewise omit inaccessible provenance.

A separate polymorphic `registry_forks` table was considered: it would retain
one independent record across source deletion and record the forker directly,
but has no per-type foreign keys and adds a join to every detail/list lookup.
Existing identity rows already hold ownership, and per-listing columns match
the registry's conventions. The columns win.

## Decision 4: Public counts are derived from current, visible state

`fork_count` and the public Forks list use **the same predicate**: direct forks
that are currently public, active and have a publicly accessible approved
release. Private forks and unpublished drafts do not count, including private
forks of public sources. A newer pending version does not expose pending
content: retain a fork in the count only if an older approved release remains
publicly accessible and is what the list serves. Compute counts from current
rows, not a stored incrementing counter, so visibility and approval changes
are reflected without leaking private forks. Owners find their private drafts
through existing `my` views, not through the public Forks list.

## Decision 5: Scaffolding and command surface

Reserve `fork` and `forks` for new registry slugs on the server and mirror the
restriction in CLI bulk agent creation. Existing listings with those slugs
remain readable. Add registry dynamic-setting defaults: `registry.fork.enabled`
(`true`) and `registry.fork.max_per_user_per_hour` (`30`), exposed in the
existing admin Registry section. Forking does not notify the source owner: a
notice would disclose drafts and team-private forks the owner cannot otherwise
see, so no setting for it exists until a privacy-safe design is agreed. The canonical CLI command will be `agent fork` (and
`registry <type> fork`), not a second `agent create --from` path.

## Consequences and deferred decisions

- Provenance requires access-aware response serialization, including after
  source transfers, visibility changes, lost team membership or deletion.
- The service must independently check current listing and version approval;
  visibility checks and `may_view_unapproved` alone are insufficient.
- An optional source-owner notification stays off pending Inbox feedback.
  Upstream sync, contribute-back, fork networks and recursive component-fork
  workflows are outside the initial scope.
- Phase 0 reserves names and publishes settings but does not enable fork
  endpoints. The roadmap item remains Planned until the Phase 1 API begins.

See `ROADMAP.md` (Independent fork drafts) for the product boundary and
completion criteria.
