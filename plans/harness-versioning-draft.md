<!-- SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com> -->
<!-- SPDX-License-Identifier: AGPL-3.0-only -->

# Harness Versioning — Spec

## Context

Derived from [issue #615](https://github.com/BlazeUp-AI/Observal/issues/615), translated into the harness platform context established in [harness-pivot.md](./harness-pivot.md). The platform pivots from agent-centric versioning to harness-centric versioning. Most of the versioning infrastructure built for agents carries forward — the migration is primarily a rename + addition of missing pieces.

This document specifies the complete versioning model for harnesses and their components. It supersedes the agent lifecycle management design in issue #615.

---

## What's Already Built

These exist in the codebase and carry forward with renames:

| Existing                                                       | Becomes                             | Status                                      |
| -------------------------------------------------------------- | ----------------------------------- | ------------------------------------------- |
| `Agent` / `AgentVersion` tables                                | `Harness` / `HarnessVersion`        | **Rename + migrate**                        |
| `AgentComponent` table                                         | `HarnessComponent`                  | **Rename + add `version_constraint` field** |
| `SkillVersion`, `McpVersion`, `HookVersion`, `SandboxVersion`  | Same tables, same names             | **Keep as-is**                              |
| `lock_snapshot` on `AgentVersion`                              | `lock_snapshot` on `HarnessVersion` | **Already correct shape**                   |
| `agent_lock_file.py`                                           | `harness_lock_file.py`              | **Rename + minor update**                   |
| `versioning.py` (parse_semver, bump_version, suggest_versions) | Same                                | **Keep as-is**                              |
| `agent release` CLI                                            | `observal harness publish`          | **Rename**                                  |
| `agent versions` CLI                                           | `observal harness versions`         | **Rename**                                  |
| `is_prerelease` / `promoted_from` on version                   | Same on `HarnessVersion`            | **Carries forward**                         |
| `resolved_sha` on `McpVersion`                                 | Same                                | **Carries forward**                         |
| Review queue with YAML diff                                    | Updated for harness YAML shape      | **Adapt**                                   |

**What's stubbed but incomplete:**

- `lock_snapshot` exists server-side but `observal-harness.lock` is never written to disk
- `resolved_version` on `AgentComponent` is a stored string — no actual semver range resolution happens

**What doesn't exist yet:**

- `Harness` / `HarnessVersion` / `HarnessComponent` tables (currently `Agent`/`AgentVersion`/`AgentComponent`)
- `version_constraint` field on `HarnessComponent`
- Semver range resolver service
- `UserLayer` table
- `layer_events` ClickHouse table
- `SubagentVersion` table (component type added in harness pivot)
- All `observal harness` CLI commands
- `.observal/harness` marker file (currently `.observal/agent`)
- Subscriptions / consumer update policies

---

## Versioning Model

### Harness Versioning

Harnesses use semver (`MAJOR.MINOR.PATCH`). The author controls bumps — the registry doesn't auto-increment.

```
observal harness publish --bump patch   # 1.2.0 → 1.2.1
observal harness publish --bump minor   # 1.2.0 → 1.3.0
observal harness publish --bump major   # 1.2.0 → 2.0.0
```

On publish:

1. Author bumps version in `observal-harness.yaml`
2. Component version constraints are resolved to exact versions (lock file generated)
3. Harness YAML snapshot stored in `HarnessVersion.yaml_snapshot`
4. Lock file stored in `HarnessVersion.lock_snapshot`
5. Version submitted for admin review (unless author is trusted)
6. On approval, `Harness.latest_version_id` updated, consumers notified (phase 2)

### Component Versioning

All 5 component types (`skill`, `mcp`, `hook`, `sandbox`, `subagent`) follow the same versioning model. Authors publish new versions via `observal component publish --type <type> --bump <patch|minor|major>` (or type-specific commands). Each version is independently reviewable.

Component versioning is already implemented for 4 types (skill, mcp, hook, sandbox). `SubagentVersion` table needs to be added as the 5th — inline markdown only, no git ref (see Subagent Versioning below).

### Stale Locks (Author-Side Only)

Users always install from the exact versions in the lock file — reproducible, no drift. Stale locks are an **author concern only**: after publishing, a component the harness depends on may release a newer approved version. The author's lock is now behind.

Detection is opportunistic and author-facing:

- `observal harness outdated` — explicit command, checks all pinned components against latest approved versions, reports what has updates available
- Web UI — harness detail page shows an "updates available" indicator when any pinned component has a newer approved version
- No warning at user install time — users get exactly what the lock says, always

---

## Version Constraints

## Version Constraints

Exact pins only. The version field in the harness manifest is a precise version — no floor, no ranges. What the author specifies is exactly what gets installed.

```yaml
components:
    - type: skill
      name: "@observal/tdd"
      version: "2.1.4" # exactly this version

    - type: mcp
      name: "@mcp/postgres"
      version: "1.2.0" # exactly this version
```

If a new component version is published and the author wants it, they update the version string in the manifest and publish a new harness version. This is deliberate — insights depend on knowing the exact version running in every session. Floor or range versioning would make it impossible to reliably attribute session behaviour to a specific component version.

**User-side version changes** go through the layer. If a user runs `observal harness add skill @observal/tdd@2.1.7`, they get `2.1.7` instead of the harness-specified `2.1.4`. `layer_events` captures both versions in the diff: `{modified: [{type: "skill", name: "@observal/tdd", harness_version: "2.1.4", layer_version: "2.1.7"}]}`. Insights can then surface: "this session ran tdd@2.1.7 instead of the harness-specified 2.1.4."

**Current state:** `version_constraint` field doesn't exist on `AgentComponent`. `resolved_version` is stored as a plain string. Both are straightforward to add.

---

## Lock File

At publish time, exact versions from the manifest are compiled into the lock file with integrity hashes. No resolution step — the lock's job is reproducibility: UUIDs and hashes, not version resolution.

```yaml
# observal-harness.lock — auto-generated at publish time
lock_version: 1
generated_at: "2026-05-14T11:25:17+00:00"
harness: "@acme/fullstack-reviewer"
harness_version: "1.3.0"

components:
    - type: skill
      name: "@observal/tdd"
      resolved: "2.1.4"
      id: "a1b2c3d4-..."
      integrity: "sha256-abc123..."

    - type: mcp
      name: "@mcp/postgres"
      resolved: "1.2.0"
      id: "e5f6g7h8-..."
      source_sha: "d4e5f6..." # external MCPs only

    - type: subagent
      name: "@acme/reviewer"
      resolved: "1.1.2"
      id: "m3n4o5p6-..."
      integrity: "sha256-ghi789..."
```

**Current state:** `agent_lock_file.py` generates this format and stores it as `lock_snapshot` in the DB. Gap: never written to disk as `observal-harness.lock`, and `observal harness pull` doesn't read from it yet.

`observal harness pull` installs the exact versions in the published lock. No re-resolution at install time.

---

## Data Model

### New / Renamed Tables (PostgreSQL)

```
Harness (was: Agent)
├── id, name, owner, namespace
├── latest_version_id → HarnessVersion
├── visibility (public/private)
├── co_maintainers (JSON → join table in phase 2)
└── created_by, created_at, updated_at

HarnessVersion (was: AgentVersion)
├── id, harness_id → Harness
├── version (semver string)
├── system_prompt (inline — the harness's identity)
├── yaml_snapshot (full YAML at publish time)
├── lock_snapshot (generated lock file content)
├── status (pending/approved/rejected)
├── is_prerelease, promoted_from
├── rejection_reason
└── created_at

HarnessComponent (was: AgentComponent)
├── id, harness_version_id → HarnessVersion
├── component_type (skill/mcp/hook/sandbox/subagent)
├── component_id (UUID → respective listing table)
├── component_name (human-readable)
├── version_constraint (NEW: "^2.1.0" | "1.2.0" | "latest")
├── resolved_version (exact version pinned in lock)
├── order_index
└── config_override (JSON)

UserLayer
├── id, user_id → User, harness_id → Harness
├── additions (JSON: list of component refs)
├── disabled (JSON: list of component_ids)
└── updated_at
```

**Component version tables** (already exist for skill/mcp/hook/sandbox — add `subagent_versions`):

```
SubagentVersion (new — inline markdown, no git ref)
├── id, listing_id → SubagentListing
├── version (semver)
├── content (Text — the subagent markdown, stored inline in DB)
├── requires (JSON — [{type, name}] component hints, not enforced at install)
├── status (pending/approved/rejected)
└── created_at
```

Subagents are a single markdown file — no scripts, no directory tree. Content stored inline in the DB. No git_url or git_ref needed. The `requires` field lists components the subagent expects to be present (e.g. it calls mcp:postgres tools) — shown in the UI and builder as a hint, not validated at install time to avoid complexity.

### ClickHouse

```
layer_events (new)
├── session_id, user_id, harness_id, harness_version
├── layer_hash, event_time
└── diff (JSON: {added: [...], removed: [...], modified: [...]})
```

---

## CLI Command Tree

```
observal harness init                    # read CLAUDE.md → scaffold draft observal-harness.yaml
observal harness publish [--bump patch|minor|major]  # compile exact versions into lock, submit for review
observal harness pull <@name/harness[@version]>      # install or update harness (preserves user layer)
observal harness pull --force            # install clean, wipe entire layer (additive + disabled)
observal harness update [--component <type:name>]    # interactively bump pinned component versions (author)
observal harness outdated                # show which pinned components have newer approved versions
observal harness versions                # list version history
observal harness add <type> <name>       # add a registry component to your layer

observal harness layer                   # show current layer state (additions + disabled)
observal harness layer disable <type> <name>  # add to disabled list, remove files from disk
observal harness layer enable <type> <name>   # remove from disabled list, re-install files
observal harness layer remove <type> <name>   # remove an added component from your layer
observal harness layer reset             # clear entire layer
```

`observal harness pull` does both: fresh install if not present, updates harness core to latest approved version if already installed. Preserves user layer either way.

`observal harness pull --force` clears the entire layer — both additive (removes added components) and subtractive (re-enables disabled components). Full reset to clean harness state.

**Current state:** `agent release` and `agent versions` exist and carry forward. Everything else is new.

---

## Marker File

`observal harness install` writes `.observal/harness` into the project directory:

```json
{
    "harness_id": "uuid",
    "harness_version": "1.3.0",
    "layer_hash": null,
    "baseline_hash": "sha256-...",
    "pulled_at": "2026-05-14T11:25:17+00:00"
}
```

`session_push` reads this at each session start to attribute telemetry and detect modification. Replaces `.observal/agent`.

---

## Harness YAML Format

```yaml
# observal-harness.yaml
name: fullstack-reviewer
namespace: "@acme"
version: "1.3.0"
description: "Full-stack code review harness for TypeScript/Python projects"

system_prompt: |
    You are a meticulous code reviewer specialised in full-stack TypeScript
    and Python projects. You prioritise correctness, test coverage, and
    readable diffs over thoroughness for its own sake.

components:
    - type: skill
      name: "@observal/tdd"
      version: "^2.1.0"

    - type: mcp
      name: "@mcp/postgres"
      version: "1.2.0"

    - type: hook
      name: "@acme/pre-commit"
      version: "latest"

    - type: subagent
      name: "@acme/reviewer"
      version: "1.1.0" # exactly this version

env:
    - DATABASE_URL
    - GITHUB_TOKEN
```

---

## Implementation Phases

Follows the additive phase principle from issue #615 — each phase builds on the previous, nothing is rewritten.

### Phase 1 — Demo-Ready (rename + fill gaps)

**Goal:** Visible harness version history, publish flow, install from registry. Enough to demo "publish v1.3, see diff vs v1.2, install v1.3."

**Scope:**

- DB: Rename `Agent` → `Harness`, `AgentVersion` → `HarnessVersion`, `AgentComponent` → `HarnessComponent`. Add `version_constraint` to `HarnessComponent`. Add `SubagentVersion` table. Add `UserLayer` table.
- API: Harness CRUD + version endpoints. Adapt existing agent endpoints (mostly renames).
- CLI: `observal harness publish`, `observal harness pull` (install + update harness core), `observal harness versions`, `observal harness init` (basic CLAUDE.md scaffold). Write `observal-harness.lock` to disk on pull.
- Web: Harness detail with version dropdown. Update builder (agent builder → harness builder, strip prompts).
- ClickHouse: Rename `agent_version` → `harness_version` column.
- `.observal/harness` marker file replaces `.observal/agent`.

## Layer Model

The user layer has two capabilities: **additive** (adding components not in the harness core) and **subtractive** (disabling core components). Both are tracked in `UserLayer` and survive `pull`.

### Additive Layer

`observal harness add <type> <name>` fetches a component from the registry, writes its files to disk, and records it in `UserLayer.additions`. On `pull`, additions are re-applied after the core is updated.

### Subtractive Layer

`observal harness layer disable <type> <name>` adds the component to `UserLayer.disabled` and removes its files from disk. On every subsequent `pull`, disabled components are skipped when writing files — the disable survives harness version updates.

**Disabling an MCP is more complex than disabling a skill.** Disabling a skill = delete its files. Disabling an MCP = find and remove its entry from `.claude/settings.json`'s `mcpServers` block. To do this reliably, at install time the CLI records which config keys each component wrote, stored in `.observal/harness` under `component_config_keys`. Without this, the CLI has no reliable way to know which key to remove.

**System prompt cannot be disabled.** It's inline on the harness and is its identity. Users can only append to it via `UserLayer.prompt_append`.

### Disable Survives Pull

- Normal `pull` — disabled components are skipped. No conflict prompt needed — disable always wins.
- `pull --force` — clears the entire layer. Re-enables all disabled components, removes all added components. Full reset to clean harness state.

### Detecting Manual Deletes

If a user deletes component files manually without running `layer disable`, `session_push` detects the hash divergence but `UserLayer.disabled` is not updated. On the next `pull`, the harness re-installs the files. Manual file deletion is not a tracked disable — the CLI command is required to make it stick.

---

## Pull Conflict Resolution

When a user runs `observal harness pull` and a new harness version is available, the core is replaced and the user layer is preserved. Disabled components stay disabled. Added components stay added.

If the new harness version changes a component the user has a different version of in their additive layer, there is a version conflict:

**Example:**

- User has harness `2.0.1` with skill:tdd @ `2.1.4`
- User ran `observal harness add skill @observal/tdd@2.1.7` — layer has tdd @ `2.1.7`
- Author publishes `2.1.0` with skill:tdd bumped to `2.1.5`
- User runs `observal harness pull` — conflict on skill:tdd

**Behaviour:** Prompt per conflict:

```
Conflict: skill:@observal/tdd
  Harness 2.1.0 specifies: 2.1.5
  Your layer has:          2.1.7

  [K] Keep yours (recommended)  [O] Overwrite with harness version
```

Default is **keep yours**. The conflict and resolution are logged in the layer manifest so insights can track the divergence. Non-conflicting components update silently.

For the **system prompt / CLAUDE.md**: if the new harness version changes the system prompt and the user has direct edits to CLAUDE.md (not via `prompt_append`), the flow is:

1. Diff the user's CLAUDE.md against the original harness prompt stored at install time in `.observal/harness`
2. Stash the additions
3. Write the new harness system prompt
4. Append the stash to the bottom
5. Warn: "If you modified the harness's own prompt text rather than just adding content, review the result."

If the user used `prompt_append` via the layer CLI, no diffing is needed — new harness prompt is written, stored `prompt_append` is re-applied cleanly.

`pull --force` skips all prompts, takes the new harness version clean, wipes the layer.

---

**NOT in Phase 1:** `observal harness add`, `observal harness layer disable/enable/remove/reset`, `observal harness outdated`, `UserLayer` syncing, `layer_events`, subscriptions.

### Phase 2 — Full Registry

**Scope:**

- `observal harness update` — interactive: shows available newer approved versions for each pinned component, author picks which to bump. Updates manifest + lock.
- `observal harness update [--component <type:name>]` — target a single component.
- `observal harness add <type> <name>` — fetches from registry, writes files, updates layer manifest.
- `observal harness layer` subcommand tree — `disable`, `enable`, `remove`, `reset`
- `observal harness layer disable` — adds to `UserLayer.disabled`, removes files from disk. Records component config keys at install time so MCP entries can be cleanly removed from settings.json.
- `UserLayer` sync — layer state persisted to server on session push.
- `layer_events` ClickHouse table — written by `session_push` on hash divergence.
- `.observal/harness` baseline_hash comparison in `session_push`.
- Subscriptions — consumers can subscribe to a harness; notified on new approved versions.
- Component author notifications — when a component publishes a new version, harness authors using it are notified.
- `observal harness versions` enhanced — show which versions consumers are on.

---

### Phase 3 — Advanced

**Scope:**

- Beta channels — `observal harness publish --beta`, pre-release versions, promote beta → stable.
- Consumer update policies — pin / auto-patch / auto-minor / auto-all per harness subscription.
- Auto-update check — opportunistic check on CLI invocation, applies patch updates per policy.
- `observal harness diff <v1> <v2>` — semantic YAML diff between versions.
- Notifications UI — bell icon + notifications page in web UI.
- Org settings UI — beta review policy, orphaned harnesses management.

---

## Key Decisions

| Decision                   | Choice                                                      | Rationale                                                                                                |
| -------------------------- | ----------------------------------------------------------- | -------------------------------------------------------------------------------------------------------- |
| Source of truth            | Registry DB                                                 | Server is artifact store; no git dependency at runtime                                                   |
| Version constraints        | Exact pins only                                             | Insights require precise version attribution per session. User overrides tracked as layer version diffs. |
| Lock file                  | Exact manifest versions + integrity hashes                  | No resolution step. UUIDs + hashes for security.                                                         |
| Lock file location         | `observal-harness.lock` on disk + `lock_snapshot` in DB     | On disk for reproducibility; DB copy for diff view in review queue                                       |
| Component integrity        | SHA256 of inline content; `source_sha` for external MCPs    | Prevents tag-mutability on external components                                                           |
| Stale lock detection       | Author-facing only via `outdated` + web UI                  | Users get exact lock versions always. Authors see newer versions available.                              |
| Subagent versioning        | Inline markdown, no git ref                                 | Single markdown file — no scripts or directory tree. Content stored in DB.                               |
| Pull `--force`             | Wipes entire layer (additive + disabled), full reset        | User explicitly opts into clean state.                                                                   |
| Disable mechanic           | `layer disable` command required                            | Manual file deletes not tracked — `pull` re-installs them.                                               |
| MCP disable                | Records config keys at install time                         | CLI needs to know which `mcpServers` key to remove from settings.json.                                   |
| System prompt              | Cannot be disabled, only appended via `prompt_append`       | It is the harness identity.                                                                              |
| CLAUDE.md conflict on pull | Diff-stash-append + warn if modifications detected          | Clean for additive-only edits; user must review if they modified harness content.                        |
| Pull conflict resolution   | Prompt per version conflict, default keep user version      | User explicitly chose that version. Conflict logged in layer for insights.                               |
| UserLayer storage          | PostgreSQL for current state, ClickHouse for change history | ClickHouse append-only for layer_events; too hot for Postgres                                            |
| Marker file                | `.observal/harness` replaces `.observal/agent`              | Same mechanism, new entity                                                                               |
| Migration                  | Hard replace — no coexistence                               | Product is alpha; no tech debt                                                                           |

---

## What Carries Forward From Issue #615 Unchanged

- Lock file compiled directly from exact manifest versions (no resolution step)
- Integrity hash format (`sha256-<hex>`)
- `resolved_sha` for external component source pinning
- `is_prerelease` / `promoted_from` for beta channels (phase 3)
- Review flow: author publishes → admin reviews YAML diff → approves/rejects
- `co_maintainers` JSON (phase 1) → join table (phase 2)
- Trust ladder for review queue (trusted authors skip review)
- The three-form version syntax removed — exact pins only

## What Changed From Issue #615

- "Agent" lifecycle → "Harness" lifecycle throughout
- "Agents" component type → "Subagents" (one of 5 component types)
- Prompts component type dropped entirely
- `observal-agent.lock` → `observal-harness.lock`
- `observal-agent.yaml` → `observal-harness.yaml`
- Evals removed — version comparison is YAML diff only (review queue) + session metric delta via insights service
- Version constraints: exact pins only — insights require precise version attribution
- User-side version overrides tracked as layer diffs with `harness_version` vs `layer_version`
- Pull conflict resolution added: prompt on conflict, default keep user version
- Floor versioning removed entirely
- `observal harness update` reframed as interactive author tool for bumping pinned versions
- `layer_events` ClickHouse table is new (not in issue #615) — tracks modification history for insights
- `UserLayer` table is new — explicit model for user layer state
