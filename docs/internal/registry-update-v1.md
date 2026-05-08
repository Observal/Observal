# Registry Update v1.0

Date: 2026-04-28
Status: Design complete, git layer removed, phased implementation plan added

## Overview

Transform Observal's registry from single-row-per-item into a full package-registry-style system with version history, lock files, review workflows, notifications, and auto-update policies.

This covers two tightly coupled subsystems:
1. **Component version history** — all 5 component types (MCP, skill, hook, prompt, sandbox) get version tables, enabling semver range resolution for agent lock files
2. **Agent lifecycle management** — agents get version history, generated IDE configs, lock files, release workflows, consumer notifications

Follows established patterns from npm, Cargo, Terraform, GitHub Actions, and Hugging Face Hub.

## Design Decisions (Agreed)

| Decision | Choice | Rationale |
|---|---|---|
| Source of truth (agents) | Registry DB (version rows) | Same as components; registry API is the single source of truth and distribution layer |
| Source of truth (components) | DB version rows | Components don't need their own git repos; Observal version-tracks them |
| IDE configs | Generated at publish time, stored in version row, served by API at pull time | No git repo; configs are derived data stored alongside the version |
| Lock file model | `package.json` / `package-lock.json` style | YAML has version constraints, lock file has resolved UUIDs + exact versions |
| Lock file resolution | Lazy (Cargo-style) | Lock file stable by default; re-resolves only on explicit `agent update` |
| Version in traces | OTel resource attribute at install time | Baked into config at agent pull; enables red/green version comparison |
| DB migration | Clean break, no backwards compat | Product is alpha; no tech debt |
| Review flow | Author releases → platform review → consumer notification | Reviewers see canonical YAML diff between previous and new version |
| Auto-update check | Opportunistic on CLI invocation | No daemon, no webhook; updates checked/applied when CLI runs |
| Web UI editing | Form-based editor | Structured fields prevent YAML syntax errors |
| Component references | Names in YAML, UUIDs only in lock file | Human-readable manifest, machine-managed lock |
| Version range syntax | `"1.2.0"` (exact), `"^1.2.0"` (compatible), `"latest"` | Three options only; simple resolver, expand later |
| Component content storage | Unified versioning model, split storage | DB inline for small (skills, hooks, prompts); source_url/source_ref pointer for large (MCPs, sandboxes) whose code lives in their own repos |
| Evals visibility | Org setting | Some orgs don't want eval scores public; controlled per-org |
| Ownership model | Owner + co-maintainers list | No ReBAC needed; simple list of user UUIDs with same permissions as owner |
| Ownership transfer | CLI/API command | Current owner or admin can transfer to another user |
| Beta releases | Skip review by default (org-configurable) | Beta testers opted into risk; review protects the general consumer base, not bleeding edge |
| A/B testing | Semver pre-release versions (`1.3.0-beta.1`) | Free component swaps in beta; traces tagged with version for comparison |
| Beta component resolution | Includes pre-release component versions | Beta agents resolve to beta components; stable agents resolve only to approved components |

---

## Part 1: Component Version History

### Problem

Today, all component types (MCP, skill, hook, prompt, sandbox) are single-row in the DB. When a component is updated, the row is overwritten and the old version is gone. This makes semver range resolution impossible — the lock file can't query "all versions of X matching ^1.2.0" because only the latest exists.

### Solution

Every component type gets an identity table (existing) + a versions table (new). Same pattern applied uniformly to all 5 types.

### Data Model

#### Pattern: `{type}_listings` (identity) + `{type}_versions` (new)

Applied to: `mcp_listings`, `skill_listings`, `hook_listings`, `prompt_listings`, `sandbox_listings`

**Identity table keeps:** `id`, `name`, `owner`, `category`, `submitted_by`, `owner_org_id`, `is_private`, `created_at`, `updated_at`

**Identity table adds:**
- `latest_version_id` — FK to `{type}_versions.id`, points to current approved version

**Identity table removes (moved to versions):** `version`, `description`, type-specific content fields, `status`, `rejection_reason`, `download_count`, `changelog`

#### `{type}_versions` table (new)

Each component type gets its own versions table. Columns vary slightly by type, but the common structure is:

| Column | Type | Notes |
|---|---|---|
| `id` | UUID | PK |
| `listing_id` | UUID | FK to `{type}_listings.id` |
| `version` | String(50) | Semver string |
| `description` | Text | Version-specific description |
| `content` | Text/JSON | Inline content (skills, hooks, prompts) OR null for large types |
| `source_url` | String(500) | Optional — external source URL (git repo, package registry). Used for MCP servers and sandboxes whose code lives externally. |
| `source_ref` | String(255) | Optional — git tag/SHA/branch at the external source |
| `status` | Enum | `draft`, `pending`, `approved`, `rejected` |
| `rejection_reason` | Text | Nullable |
| `download_count` | Integer | Per-version downloads |
| `changelog` | Text | What changed in this version |
| `released_by` | UUID | FK to `users.id` |
| `released_at` | DateTime | |
| `reviewed_by` | UUID | FK to `users.id`, nullable |
| `reviewed_at` | DateTime | Nullable |
| `created_at` | DateTime | |

**Unique constraint:** `(listing_id, version)`

**Type-specific columns:**

| Type | Extra columns on version row |
|---|---|
| MCP | `transport`, `framework`, `docker_image`, `command`, `args`, `url`, `headers`, `auto_approve`, `mcp_validated`, `tools_schema`, `environment_variables`, `supported_ides`, `setup_instructions` |
| Skill | `supported_ides`, `skill_type`, `trigger_pattern` |
| Hook | `supported_ides`, `hook_type`, `trigger_event` |
| Prompt | `supported_ides` |
| Sandbox | `docker_image`, `supported_ides` |

### Content Storage Model

Unified versioning (DB rows + semver), split storage by artifact size:

| Type | Typical size | Content storage | What the version row holds |
|---|---|---|---|
| MCP servers | Full application | External git repo / npm / PyPI | Metadata (transport, command, args, env vars, tools schema) + `source_url`/`source_ref` pointing at the MCP's own repo@tag. The actual server code lives externally — Observal tracks the version, not the source. |
| Sandboxes | Docker configs + scripts | External git repo / registry | Metadata (docker image, setup instructions) + `source_url`/`source_ref`. Same as MCP — code lives externally. |
| Skills | Markdown / small script | DB inline | Full content in `content` column |
| Hooks | Few lines of config | DB inline | Full content in `content` column |
| Prompts | Text string | DB inline | Full content in `content` column |

**Key distinction:** MCP servers and sandboxes are real software — they live in their own repos and are installed via `npx`, `pip`, `docker pull`, etc. Observal doesn't store or serve their source code. It version-tracks the *reference* (which repo, which tag) so the lock file can pin a specific version and consumers get reproducible installs.

For inline types (skills, hooks, prompts), Observal stores the full content. These are small text artifacts — a skill is a markdown file, a hook is a few lines of config, a prompt is a text string. The version row is fully self-contained for these types.

### Version Range Resolver Service

New service: `services/version_resolver.py`

```python
async def resolve_version(
    component_type: str,
    component_name: str,
    version_constraint: str,  # "^1.2.0", "1.2.0", "latest"
    db: AsyncSession,
) -> ResolvedComponent | None:
    """Resolve a version constraint to the best matching approved version."""
```

Queries the `{type}_versions` table for all approved versions of the named component, applies the constraint, returns the highest matching version.

Used by:
- `observal agent update` — lock file resolution
- `observal agent release` — final lock file resolution before publishing
- API endpoint for lock file validation

### Component Update Notification to Agent Authors

When a component gets a new approved version:
1. Query all agents whose YAML snapshot references that component name
2. Check if the new version falls within the agent's declared constraint
3. If yes → notify agent author: "filesystem-server 1.2.4 is available (you're locked at 1.2.3)"
4. Author can run `observal agent update` to re-resolve

This is informational only — no automatic lock file changes, no cascading reviews.

### API Endpoints (Components)

New endpoints, applied uniformly to all 5 types (`{type}` = mcps, skills, hooks, prompts, sandboxes):

| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/{type}/{id}/versions` | List all versions |
| GET | `/api/v1/{type}/{id}/versions/{version}` | Get specific version |
| POST | `/api/v1/{type}/{id}/versions` | Publish new version |
| POST | `/api/v1/{type}/{id}/versions/{version}/review` | Approve/reject |
| GET | `/api/v1/resolve/{type}/{name}?match={constraint}` | Resolve version constraint |

Existing endpoints modified:
| Method | Path | Changes |
|---|---|---|
| GET | `/api/v1/{type}/{id}` | Returns identity + latest approved version |
| POST | `/api/v1/{type}` | Creates identity + initial version |

---

## Part 2: Agent Lifecycle Management

### Data Model

#### PostgreSQL: `agents` table (identity only)

The `agents` table becomes the package identity record. Version-specific fields move to `agent_versions`.

**Keeps:** `id`, `name`, `owner`, `created_by`, `owner_org_id`, `is_private`, `created_at`, `updated_at`

**Adds:**
- `latest_version_id` — FK to `agent_versions.id`, points to current approved release
- `co_maintainers` — JSON list of user UUIDs who share ownership permissions

**Removes (moved to `agent_versions`):** `version`, `description`, `prompt`, `model_name`, `model_config_json`, `external_mcps`, `supported_ides`, `required_ide_features`, `inferred_supported_ides`, `status`, `rejection_reason`, `download_count`, `unique_users`

#### PostgreSQL: `agent_versions` table (new)

One row per release of an agent.

| Column | Type | Notes |
|---|---|---|
| `id` | UUID | PK |
| `agent_id` | UUID | FK to `agents.id` |
| `version` | String(50) | Semver string, e.g., `1.2.0` |
| `description` | Text | Version-specific description |
| `prompt` | Text | System prompt |
| `model_name` | String(100) | Model identifier |
| `model_config_json` | JSON | Model parameters |
| `external_mcps` | JSON | External MCP configs |
| `supported_ides` | JSON | List of IDE identifiers |
| `required_ide_features` | JSON | Inferred features |
| `inferred_supported_ides` | JSON | Computed from features |
| `yaml_snapshot` | Text | Complete agent definition YAML at this version (canonical source of truth) |
| `ide_configs` | JSON | Generated IDE config files per IDE, keyed by IDE identifier |
| `lock_snapshot` | Text | Resolved lock file content at this version |
| `status` | Enum | `draft`, `pending`, `active`, `rejected` |
| `is_prerelease` | Boolean | True for beta releases (`1.3.0-beta.1`). Beta versions may skip review (org setting). |
| `promoted_from` | UUID | Nullable FK to `agent_versions.id` — set when this stable version was promoted from a beta |
| `rejection_reason` | Text | Nullable |
| `download_count` | Integer | Per-version downloads |
| `released_by` | UUID | FK to `users.id` |
| `released_at` | DateTime | When the release was created |
| `reviewed_by` | UUID | FK to `users.id`, nullable |
| `reviewed_at` | DateTime | Nullable |
| `created_at` | DateTime | |

**Unique constraint:** `(agent_id, version)`

#### PostgreSQL: `agent_components` table (modified)

FK changes from `agent_id` to `agent_version_id`. Stores resolved values only; constraints live in the YAML snapshot.

| Column | Type | Notes |
|---|---|---|
| `id` | UUID | PK |
| `agent_version_id` | UUID | FK to `agent_versions.id` (was `agent_id`) |
| `component_type` | String | `mcp`, `skill`, `hook`, `prompt`, `sandbox` |
| `component_name` | String | Human-readable name |
| `component_id` | UUID | Resolved registry UUID |
| `resolved_version` | String(50) | Resolved exact version |
| `order_index` | Integer | |
| `config_override` | JSON | Nullable |

#### PostgreSQL: `agent_subscriptions` table (new)

Tracks consumer installations for notifications and auto-update.

| Column | Type | Notes |
|---|---|---|
| `id` | UUID | PK |
| `agent_id` | UUID | FK to `agents.id` |
| `user_id` | UUID | FK to `users.id` |
| `installed_version` | String(50) | Currently installed version |
| `ide` | String(50) | Which IDE config they pulled |
| `update_policy` | Enum | `pin`, `auto_patch`, `auto_minor`, `auto_all` |
| `created_at` | DateTime | |
| `updated_at` | DateTime | |

**Unique constraint:** `(agent_id, user_id, ide)`

#### PostgreSQL: `agent_notifications` table (new)

In-app notification queue for consumers.

| Column | Type | Notes |
|---|---|---|
| `id` | UUID | PK |
| `user_id` | UUID | FK to `users.id` |
| `agent_id` | UUID | FK to `agents.id` |
| `agent_version_id` | UUID | FK to `agent_versions.id` |
| `type` | Enum | `new_version`, `update_applied`, `update_available` |
| `read` | Boolean | Default false |
| `created_at` | DateTime | |

#### PostgreSQL: `agent_goal_templates` and `agent_goal_sections`

FK changes from `agent_id` to `agent_version_id` — goal templates are per-version.

#### ClickHouse: Schema changes

Add `agent_version` column to traces, spans, and events tables. Clean break — drop and recreate tables (alpha product, no data migration).

**Traces:**
```sql
agent_version Nullable(String)
INDEX idx_agent_version agent_version TYPE bloom_filter(0.01) GRANULARITY 1
```

**Spans and Events:** Same addition.

The `observal.agent.version` OTel resource attribute is extracted at ingest time and written to this column.

### File Formats

#### `observal-agent.yaml` (authoring format)

The CLI-side file authors use to define agents locally before publishing.

```yaml
name: my-agent
version: 1.2.0
description: "Code review agent with security focus"
owner: acme-team
model_name: claude-sonnet-4
model_config:
  max_tokens: 4096
  temperature: 0.2
prompt: |
  You are a code review agent focused on security...

supported_ides:
  - claude-code
  - cursor
  - kiro
  - copilot
  - copilot-cli
  - gemini-cli
  - codex
  - opencode
  - vscode

components:
  - type: mcp
    name: filesystem-server
    version: "^1.2.0"
  - type: skill
    name: code-review
    version: "~2.0.0"

external_mcps:
  - name: custom-server
    command: npx
    args: ["my-custom-mcp"]

goal_template:
  description: "Review code for security issues"
  sections:
    - name: scan
      description: "Scan codebase for vulnerabilities"
    - name: report
      description: "Generate findings report"
      grounding_required: true
```

Platform-only metadata NOT in YAML: `is_private`, `status`, `created_by`, `org_id`, access control.

#### `observal-agent.lock` (generated)

```yaml
# Auto-generated by observal agent update — do not edit manually
lock_version: 1
resolved_at: "2026-04-26T18:00:00Z"
components:
  - type: mcp
    name: filesystem-server
    resolved: 1.2.3
    id: abc123-def4-5678-9012-abcdef012345
  - type: skill
    name: code-review
    resolved: 2.0.7
    id: def456-abcd-1234-5678-abcdef678901
```

#### Version range syntax

| Syntax | Meaning |
|---|---|
| `"1.2.0"` | Exact pin |
| `"^1.2.0"` | Compatible: `>=1.2.0, <2.0.0` |
| `"latest"` | Resolve to newest approved version |

### Consumer-Side Files

#### Per-project tracker

```yaml
# .observal/installed-agents.yaml (in consumer's project root)
agents:
  - name: my-agent
    version: 1.2.0
    ide: claude-code
    update_policy: auto-patch
```

Managed by `observal agent pull`. Tracks what's installed in this project.

#### Global installation index

```json
// ~/.config/observal/installations.json
{
  "my-agent": {
    "projects": ["/home/user/project-a", "/home/user/project-b"],
    "global": false
  },
  "code-review-agent": {
    "projects": [],
    "global": true
  }
}
```

Enables `observal agent outdated --all` and cross-project auto-update.

---

## Workflows

### Author: Create Agent

```
$ observal agent create
→ Interactive wizard (name, description, model, components, etc.)
→ Agent definition saved to registry DB
→ Initial version submitted for review
→ ✓ Created my-agent v1.0.0 (pending review)
```

Or via web UI:
1. Form-based editor creates agent definition in registry DB
2. Submit for review from the web UI

### Author: Edit Agent

**Via CLI:**
```
$ observal agent update my-agent
→ Reads local observal-agent.yaml
→ Pushes changes to registry DB
→ Re-resolves lock file (lazy — only if explicitly requested or first time)
→ ✓ Updated my-agent in registry
```

**Via Web UI:**
1. Form-based editor modifies definition
2. Saved to registry DB directly

No sync, no bidirectional merge. CLI pushes to API. Web UI saves to DB. Both write to the same place.

### Author: Release

```
$ observal agent release my-agent --bump minor
→ Bumps version (1.2.0 → 1.3.0)
→ Re-resolves lock file
→ Generates IDE configs for all supported IDEs
→ Publishes version to registry (YAML snapshot + lock + IDE configs stored)
→ Submits v1.3.0 to review queue
→ ⚠ v1.2.1 is still pending review (if applicable)
```

### Reviewer: Review Release

1. New version appears in review queue (web UI)
2. Reviewer sees side-by-side YAML diff (previous approved version vs new)
3. Reviewer approves or rejects with reason
4. On approval:
   - Version status → `active`
   - `agents.latest_version_id` updated
   - Notifications fired to all subscribers
5. On rejection:
   - Author notified with reason
   - Author can edit and re-release

### Consumer: Pull Agent

```
$ observal agent pull my-agent --ide claude-code
→ (First time) Install location:
    1. This project (/home/user/my-project)
    2. Global (~/.config/observal/agents/)
→ Selected: 1
→ Fetching v1.2.0 from registry API...
→ Writing IDE config to .claude/agents/my-agent/
→ Created .observal/installed-agents.yaml
→ Updated ~/.config/observal/installations.json
→ ✓ Pulled my-agent v1.2.0 (claude-code)
```

Subsequent pulls:
```
$ observal agent pull my-agent
→ Updating my-agent: 1.2.0 → 1.3.0
→ ✓ Updated .claude/agents/my-agent/
```

### Consumer: Check for Updates

```
$ observal agent outdated
→ Reads .observal/installed-agents.yaml
→ Checks registry for newer approved versions
  my-agent       1.2.0 → 1.3.0 (minor)
  code-reviewer  2.0.0 → 2.0.1 (patch, auto-update eligible)

$ observal agent outdated --all
→ Reads global installations.json
→ Checks across all projects
```

### Consumer: Auto-Update

On any `observal` CLI invocation:
1. Background check against registry for installed agents
2. For each agent with a newer approved version:
   - If update policy allows (e.g., `auto-patch` and it's a patch bump): pull new IDE config automatically, update tracker files, show notice
   - If update policy blocks: show notification ("my-agent v1.3.0 available, run `observal agent pull my-agent` to update")

### Consumer: Update Policies

| Policy | Auto-adopts | Requires manual pull |
|---|---|---|
| `pin` | Nothing | Everything |
| `auto-patch` | Patch releases | Minor, major |
| `auto-minor` | Patch + minor | Major |
| `auto-all` | All stable releases | Nothing |
| `beta` | All versions including pre-release | Nothing |

Default: `auto-patch`

Beta subscribers also receive pre-release component versions — the lock file resolver includes `beta`/`rc` component versions when the consumer is on the `beta` policy.

---

## Registry Updates (Component → Agent Flow)

Observal indexes and tracks components from external sources. The update flow is lazy (Cargo-style).

### Lock File Re-Resolution

- The lock file is **stable by default**. New component versions do NOT auto-update an agent's lock file.
- Author runs `observal agent update` → lock file re-resolves within declared constraints.
- No cascading reviews. Component updates do not trigger re-review of agents.
- The author controls when to adopt component updates.

### Author Notification

When a component gets a new approved version:
1. Query all agents whose YAML snapshot references that component name
2. Check if the new version falls within the agent's declared constraint
3. If yes → notify agent author: "filesystem-server 1.2.4 available (locked at 1.2.3)"
4. Informational only — no automatic changes

### Flow

1. Component `filesystem-server` gets new version in registry: `1.2.3` → `1.2.4`
2. Agent's lock file still says `resolved: 1.2.3` — unchanged
3. Agent author notified: "new version available within your constraint"
4. Author runs `observal agent update my-agent` → lock file re-resolves to `1.2.4`
5. Author tests, then runs `observal agent release my-agent --bump patch`
6. New agent version submitted for review with updated lock file

---

## Ownership & Co-Maintainers

### Ownership Model

Each agent has one **owner** (`created_by`) and zero or more **co-maintainers** (`co_maintainers` JSON list on `agents` table). Co-maintainers have the same permissions as the owner:

- `agent update` — push changes to registry
- `agent release` — publish new versions
- Edit via web UI
- View eval results
- Manage beta releases

Auth check everywhere:
```python
is_maintainer = (user.id == agent.created_by or user.id in agent.co_maintainers)
```

### Co-Maintainer Management

```
$ observal agent maintainers add my-agent --user <email-or-username>
$ observal agent maintainers remove my-agent --user <email-or-username>
$ observal agent maintainers list my-agent
```

Only the owner can add/remove co-maintainers. Co-maintainers cannot add other co-maintainers.

Web UI: "Maintainers" section on the agent settings page. Owner can add/remove.

### Ownership Transfer

```
$ observal agent transfer my-agent --to <email-or-username>
→ Are you sure? This makes <user> the owner of my-agent. You will become a co-maintainer. (y/n)
```

- Current owner or an admin can initiate
- Previous owner is automatically added as a co-maintainer (can be removed by new owner)
- Transfers the `created_by` field

API: `POST /api/v1/agents/{id}/transfer` with `{ "new_owner_id": "..." }`

### When a Developer Leaves the Org

If the owner's account is deactivated:
1. Admins can transfer ownership via `POST /api/v1/agents/{id}/transfer`
2. Co-maintainers retain access and can continue to update/release
3. If no co-maintainers exist, the agent is orphaned — admins can transfer or archive it

---

## Evals Visibility

### Org Setting

Eval visibility is controlled per-organization:

| Setting | Behavior |
|---|---|
| `evals_public: true` | Eval summary scores (grade, overall score, dimension breakdown) visible to anyone who can see the agent |
| `evals_public: false` (default) | Eval scores visible only to agent owner, co-maintainers, and org admins |

Regardless of the setting, **detailed trace-level eval data** (individual scorecard raw output, penalties, recommendations) is always restricted to owner/co-maintainers/admins.

### Org Settings Table Addition

Add to `organizations` table (or a separate `org_settings` table):

| Column | Type | Default | Notes |
|---|---|---|---|
| `evals_public` | Boolean | `false` | Whether eval summaries are public on agent cards |
| `beta_requires_review` | Boolean | `false` | Whether beta releases require reviewer approval |

### API

- `GET /api/v1/org/settings` — get org settings
- `PATCH /api/v1/org/settings` — update org settings (admin only)

Web UI: Org settings page with toggles.

---

## Beta Releases & A/B Testing

### Release Channels

Agents have two release channels:

| Channel | Version format | Review required | Who receives |
|---|---|---|---|
| **Stable** | `1.3.0` | Yes (always) | All consumers based on update policy |
| **Beta** | `1.3.0-beta.1` | No (org-configurable) | Only `beta` policy subscribers |

### Beta Release Flow

```
$ observal agent release my-agent --bump minor --beta
→ Version: 1.3.0-beta.1
→ Resolving lock file (including pre-release components)...
→ Generating IDE configs...
→ Published to registry
→ ✓ Beta released (no review required)
→ Beta subscribers notified
```

Subsequent beta iterations:
```
$ observal agent release my-agent --beta
→ Version: 1.3.0-beta.2
→ ...
```

### A/B Testing with Component Swaps

Beta releases allow free component editing — the author can swap any component version, including using pre-release component versions:

```yaml
# observal-agent.yaml during beta
components:
  - type: skill
    name: code-review
    version: "3.0.0-beta.1"    # pre-release component version
  - type: mcp
    name: filesystem-server
    version: "^2.0.0"           # can also bump to new major
```

Beta lock file resolution includes pre-release versions:
- Stable resolution: `^1.2.0` matches `1.2.0`, `1.2.3`, `1.9.0` — NOT `2.0.0-beta.1`
- Beta resolution: `^1.2.0` matches all of the above PLUS `1.3.0-beta.1`, `1.9.0-rc.1`

### Promote Beta to Stable

When the author is satisfied with beta results:

```
$ observal agent release my-agent --promote
→ Promoting 1.3.0-beta.2 to stable release
→ Any final tweaks? (opens editor / prompts for changes)
→ (author makes minor adjustments or confirms as-is)
→ Version: 1.3.0
→ Re-resolving lock file (stable components only)...
→ Generating IDE configs...
→ Published to registry
→ Submitted for review
```

Key behaviors:
- `--promote` takes the current beta and publishes as stable
- Prompts author for optional minor tweaks before promotion
- Lock file re-resolves with **stable-only** component versions (beta component versions get replaced with their nearest stable match)
- The stable release goes through the normal review queue
- `promoted_from` field on the version record links to the beta version for audit trail

### Trace Tagging for A/B Comparison

Beta versions get their own trace tags:
- Stable consumers: `observal.agent.version = 1.2.0`
- Beta consumers: `observal.agent.version = 1.3.0-beta.1`

The version comparison view (stub) can filter by `agent_version` to compare:
- Stable vs stable (red/green deployment)
- Stable vs beta (A/B test)
- Beta vs beta (iterating on beta)

### Org Setting: Beta Review Requirement

| Setting | Behavior |
|---|---|
| `beta_requires_review: false` (default) | Beta releases go directly to beta subscribers |
| `beta_requires_review: true` | Beta releases enter review queue, same as stable |

For regulated orgs that need all releases reviewed, regardless of channel.

---

## Version Comparison (Stub)

The version comparison view enables red/green deployment analysis. Placeholder for the full implementation, which integrates with the incoming DAG profiling system.

### Data Foundation

- `agent_version` on every trace/span/event in ClickHouse
- Filterable by `(agent_id, agent_version)` with bloom filter index
- Eval scorecards already have a `version` field

### Planned Comparison View (Web UI)

Pick two versions → side-by-side:

| Metric | v1.2.0 | v1.3.0 | Delta |
|---|---|---|---|
| Avg latency | - | - | - |
| Avg eval score | - | - | - |
| Tool call count | - | - | - |
| Error rate | - | - | - |

Plus: eval scorecard dimension breakdown, DAG profiling comparison (pending DAG system).

### Implementation Note

The data model (`agent_version` in ClickHouse, version-aware eval queries) is built as part of this project. The comparison UI is a stub — query endpoints return version-filtered data, but the full side-by-side view ships with the DAG profiling feature.

---

## Sidebar Navigation Structure

The current sidebar has 4 groups with 16 items. We're adding new pages but must avoid overcrowding. The principle: **new pages are nested inside existing items or accessed via tabs on detail pages, not added as top-level sidebar entries.**

### Current Sidebar → Updated Sidebar

```
REGISTRY (public)
  Home                          ← unchanged
  Agents                        ← unchanged (browse page)
  Leaderboard                   ← unchanged
  Components                    ← unchanged
  Builder                       ← unchanged (authed)

MY STUFF (authed, new group)
  My Agents                     ← NEW: author dashboard (own + co-maintained)
  Installed Agents              ← NEW: consumer dashboard
  Notifications                 ← NEW: bell also in top nav, page here

REVIEW (reviewer+)
  Review                        ← updated with diff view

TRACES (user+)
  My Traces                     ← unchanged

ADMIN (admin+)
  Dashboard                     ← unchanged
  Errors                        ← unchanged
  Evals                         ← unchanged
  Users                         ← unchanged
  Audit Log                     ← unchanged
  Security                      ← unchanged
  SSO & SCIM                    ← unchanged
  Diagnostics                   ← unchanged
  Settings                      ← updated with org registry settings + orphaned agents
```

**What's NOT in the sidebar (accessed via tabs/navigation within pages):**
- Agent edit form → tab/button on agent detail page
- Release history → tab on agent detail page (author only)
- A/B testing → tab on agent detail page (author only)
- Agent settings → tab on agent detail page (owner only)
- Version diff view → opened from review queue
- Component version history → tab on component detail page

**Net sidebar change:** +3 items in a new "My Stuff" group. No existing items removed. Keeps sidebar manageable.

The notification bell icon also lives in the **top nav bar** (header) with an unread count badge, so users see it without navigating to the full page.

---

## Web UI — Full Page Inventory

### 1. Registry Browse Page (`/registry` — existing, updated)

The main public listing of all agents.

**Changes:**
- Agent cards show **latest approved version** badge
- Eval summary score shown on card if org setting `evals_public: true` (grade badge, e.g., "A-")
- Version dropdown on each card (click to see all versions, warnings on older ones)
- Filter/sort by: name, model, IDE support, eval score (if public), component count

**Edge case:** If an agent has no approved versions (all rejected/pending), it doesn't appear in the public browse. Only visible to the author on their "My Agents" page.

### 2. Agent Detail Page (`/registry/agents/{id}` — existing, updated)

The full agent view. Behavior varies by viewer role.

**For everyone:**
- Version dropdown at top (like GitHub releases / npm). Lists all approved versions. Warns on older versions: "⚠ This is not the latest version"
- Per-version info: description, components list, model, supported IDEs, goal template
- Eval summary (grade, dimension radar) — shown only if org setting allows
- Consumer count per version
- "Pull" button with IDE selector → shows `observal agent pull <name> --ide <ide>` command
- Beta badge on pre-release versions (only visible if consumer is on beta policy or is the author)

**Tab bar (author / co-maintainers see all; everyone else sees only "Overview"):**

```
[ Overview ]  [ Edit ]  [ Releases ]  [ A/B Testing ]  [ Settings ]
```

- **Overview** — visible to everyone (the default view described above)
- **Edit** — author/co-maintainers only → form editor (page 3)
- **Releases** — author/co-maintainers + reviewers → version timeline (page 5)
- **A/B Testing** — author/co-maintainers only → beta management + comparison (page 6)
- **Settings** — owner only → maintainers, transfer, danger zone (page 7)

**For reviewers (additional):**
- Pending versions show "Review" button → opens diff view (page 8)

### 3. Agent Edit Form (`/registry/agents/{id}/edit` — new)

Form-based editor for the agent definition. Only visible to owner and co-maintainers.

**Sections:**
1. **Basics** — name (read-only post-release), description, owner
2. **Model** — model selector dropdown, temperature, max_tokens
3. **System Prompt** — large textarea with syntax highlighting
4. **Components** — picker for each type (MCP, skill, hook, prompt, sandbox). Search registry, select, set version constraint (`^1.2.0`, exact, latest). Shows currently resolved version from lock file.
5. **External MCPs** — add/remove external MCP configs (name, command, args, env)
6. **Supported IDEs** — checkbox list of all 9 IDEs
7. **Goal Template** — description + sortable sections list (add/remove/reorder)

**Actions:**
- "Save" → saves to registry DB as a draft. Changes are live in the registry immediately.
- "Discard changes" → reverts to last saved state

**Edge cases:**
- Agent name is read-only after first approved release (no renames)
- If component version constraint matches nothing: inline warning on the component row "⚠ No approved version matches ^3.0.0"

### 4. My Installed Agents (`/my/installed-agents` — new)

Consumer's view of everything they've pulled.

**Table columns:**
- Agent name (link to detail page)
- Installed version
- Latest available version
- Status: "Up to date" / "Update available (minor)" / "Update available (major)" / "Beta available"
- IDE
- Update policy (dropdown: pin / auto-patch / auto-minor / auto-all / beta)
- Last pulled date

**Actions per row:**
- "Update" button → shows `observal agent pull <name> --ide <ide>` command
- Update policy dropdown → saves immediately via API
- "Unsubscribe" → removes subscription, stops notifications

**Top-level actions:**
- "Check for updates" → triggers check against registry
- Filter by: IDE, update status, update policy

**Edge cases:**
- If an agent was archived/deleted since install: row shows "⚠ Agent no longer available" with dimmed styling
- If installed version was rejected after install (should not happen in normal flow, but defensively): show warning

### 5. Release History (`/registry/agents/{id}/releases` — new tab on detail page)

Timeline of all versions for an agent. Only visible to author/co-maintainers and reviewers.

**For each version row:**
- Version number with badge: `active` (green), `pending` (yellow), `rejected` (red), `beta` (purple)
- Release date, released by (username)
- Reviewer + review date (if reviewed)
- Rejection reason (if rejected, expandable)
- Download count
- `promoted_from` link (if this stable version was promoted from a beta)
- Component changes summary: "Updated filesystem-server 1.2.3 → 1.2.4"

**Actions:**
- Click any version → shows that version's detail on the detail page
- "Compare" → select two versions, opens diff view (page 8)

**Edge cases:**
- Rejected versions show with strikethrough styling, are not expandable to full detail
- Version numbers are never reused — rejected `1.3.0` means next release must be `1.3.1+`
- Warning banner if a release is pending while another is already pending: "⚠ v1.3.0 is still pending review"

### 6. A/B Testing Page (`/registry/agents/{id}/ab-testing` — new tab on detail page)

Author's view for managing beta releases and comparing versions. Only visible to owner/co-maintainers.

**Layout: two panels**

**Left panel: Beta Management**
- Current beta version (if any): `1.3.0-beta.2` with status badge
- Beta subscriber count
- "New Beta Release" button → opens dialog:
  - Bump type selector (patch/minor/major — sets the target stable version)
  - Component override section: shows current components with ability to swap versions (including pre-release component versions)
  - "Release Beta" → shows `observal agent release my-agent --bump minor --beta` command
- "Next Beta Iteration" button (if beta exists) → bumps beta counter
- "Promote to Stable" button → shows `observal agent release my-agent --promote` command. Warns: "This will submit for review"

**Right panel: Version Comparison (stub)**
- Version picker: two dropdowns (baseline version vs comparison version)
- Pre-filled: latest stable vs current beta
- Comparison metrics (stub — placeholder cards):
  - Avg latency delta
  - Avg eval score delta
  - Tool call count delta
  - Error rate delta
  - Dimension radar overlay (two versions on same radar)
- "View traces" link for each version → filtered trace list
- Banner: "Full comparison dashboard coming with DAG profiling"

**Edge cases:**
- Only one active beta series per agent. If beta `1.3.0-beta.1` exists, author can't start `1.4.0-beta.1` until they either promote or abandon the current beta.
- "Abandon Beta" button → marks all `1.3.0-beta.*` versions as abandoned (a terminal status, similar to rejected). Frees the author to start a new beta series.
- If no traces exist for a version: comparison panel shows "No trace data yet. Install this version and generate some activity."

### 7. Agent Settings (`/registry/agents/{id}/settings` — new tab on detail page)

Only visible to owner (not co-maintainers, except read-only view of maintainers list).

**Sections:**

**Maintainers**
- List of co-maintainers: username, email, added date
- "Add co-maintainer" → user search/autocomplete → add button
- "Remove" button per co-maintainer (with confirmation)
- Inactive co-maintainers shown with warning: "⚠ Account inactive" (dimmed, still removable)

**Ownership Transfer**
- "Transfer ownership" button → user search → confirmation dialog: "This will make {user} the owner. You will become a co-maintainer."
- Only owner and org admins can see this
- Transfer blocked if target user is in a different org. Error: "Cannot transfer to a user in a different organization."

**Danger Zone**
- "Archive agent" → soft delete, removes from registry browse, consumers keep current install but get no updates
- "Delete agent" → hard delete (admin only), with confirmation: "This will permanently delete all versions and cannot be undone"

### 8. Review Queue — Diff View (`/review` — existing, updated)

Reviewer sees pending versions across all agents (and components).

**Queue table:**
- Type (agent / mcp / skill / etc.)
- Name
- Version (new) → previous version
- Submitted by, submitted date
- "Review" button
- Beta badge if pre-release (only appears if org requires beta review)

**Diff view (opens on "Review" click):**
- Split pane: left = previous approved YAML, right = new YAML
- Syntax-highlighted YAML diff (additions green, removals red, unchanged dimmed)
- For first-ever version: left pane shows "New agent — no previous version"
- Sidebar metadata: author, submission date, component changes summary, version bump type (patch/minor/major)
- Lock file changes summary: "filesystem-server 1.2.3 → 1.2.4" (not the full lock diff, just a human-readable summary)

**Actions:**
- "Approve" button → version goes active, notifications fire
- "Reject" button → opens reason textarea → version goes rejected, author notified
- "Skip" → move to next in queue

**Edge cases:**
- Multiple pending versions for the same agent: shown as separate rows. Reviewer can review in any order.
- If previous approved version was later archived: diff still works (we have the YAML snapshot on the version record)

### 9. Notifications Page (`/notifications` — new)

Bell icon in top nav with unread count badge.

**Notification types:**
- "🆕 my-agent v1.3.0 is now available" (new approved version for installed agent)
- "🔄 my-agent v1.2.1 auto-updated in 3 projects" (auto-update applied)
- "📦 filesystem-server 1.2.4 available (your agent uses ^1.2.0)" (component dependency update, for authors)
- "❌ my-agent v1.3.0 was rejected: {reason}" (rejection notification for authors)
- "✅ my-agent v1.3.0 was approved" (approval notification for authors)
- "🧪 my-agent v1.3.0-beta.1 available" (beta release for beta subscribers)

**Layout:**
- Grouped by date
- Each notification: icon, message, timestamp, "mark as read" button
- "Mark all as read" top action
- Filter by: type, read/unread

### 10. My Agents (`/my/agents` — new)

Author's dashboard of all agents they own or co-maintain.

**Table columns:**
- Agent name (link to detail page)
- Role: "Owner" / "Co-maintainer"
- Latest version + status (active/pending/rejected)
- Active beta version (if any)
- Consumer count (total installs)
- Last updated date

**Actions:**
- "Create Agent" button → opens create wizard (form version of CLI wizard)
- Per-row: "Edit" / "Releases" / "A/B Testing" / "Settings" quick links

**Edge cases:**
- Agents where user is co-maintainer but owner has been deactivated: show "⚠ Owner inactive" badge. Suggest "Contact an admin to transfer ownership."

### 11. Org Settings Page (`/settings/org` — existing, updated)

Admin-only org configuration.

**New sections:**

**Registry Settings**
- `evals_public` toggle: "Show eval summary scores on agent cards" (default: off)
- `beta_requires_review` toggle: "Require review for beta releases" (default: off)

**Orphaned Agents**
- Table of agents whose owner account is deactivated and have no active co-maintainers
- "Transfer" button per row → admin selects new owner

---

## CLI Commands

### Full Command Inventory

Every `observal agent` subcommand after this redesign. Grouped by persona, with full behavioral descriptions.

---

#### Author Commands (authed, owner or co-maintainer)

**`agent create`**
Interactive wizard that walks the author through building a new agent definition. Collects: name, description, version, model, components (search registry + select), supported IDEs, goal template (sections), owner, system prompt, model config.

After the definition is built:
1. Saves to the Observal registry DB
2. Resolves lock file, generates IDE configs
3. Publishes initial version
4. Submits for review

Flags: `--from-file <path>` (skip wizard, create from JSON file), `--beta` (start at version 0.1.0 instead of 1.0.0)

---

**`agent update <name>`**
The author's save command. Pushes local changes to the registry.

What it does:
1. Reads local `observal-agent.yaml` for changes
2. Pushes definition to registry DB via API
3. Re-resolves lock file (lazy by default — only if `--resolve` flag or lock file doesn't exist)

This does NOT create a release or bump a version. It's just "save my work to the registry."

Flags: `--dir <path>` (directory containing `observal-agent.yaml`, default: `.`), `--resolve` (force lock file re-resolution)

Auth: owner or co-maintainer only. Rejects if current user isn't authorized.

---

**`agent release <name>`**
The deliberate "ship it" action. Creates a versioned release and submits for review. This is separate from `agent update` because releasing should be intentional.

**Stable release:**
```
$ observal agent release my-agent --bump minor
→ Bumps version in observal-agent.yaml (1.2.0 → 1.3.0)
→ Generates IDE configs with new version baked in
→ Re-resolves lock file (always, regardless of lazy setting)
→ Publishes to registry
→ Submits v1.3.0 to review queue
→ ⚠ v1.2.1 is still pending review (if applicable)
```

**Beta release:**
```
$ observal agent release my-agent --bump minor --beta
→ Version: 1.3.0-beta.1
→ Resolves lock file including pre-release component versions
→ Generates IDE configs
→ Published to registry
→ ✓ Beta released (no review required, unless org setting overrides)
→ Beta subscribers notified
```

**Next beta iteration (no --bump needed):**
```
$ observal agent release my-agent --beta
→ Version: 1.3.0-beta.2
→ ...
```

**Promote beta to stable:**
```
$ observal agent release my-agent --promote
→ Promoting 1.3.0-beta.2 to stable
→ Any final tweaks? (opens $EDITOR with observal-agent.yaml)
→ (author saves or quits without changes)
→ Re-resolves lock file with stable-only component versions
→ Version: 1.3.0
→ Generates IDE configs
→ Published to registry
→ Submitted for review
```

Flags: `--bump <patch|minor|major>` (required for new stable/beta series), `--beta` (beta release), `--promote` (promote current beta to stable)

---

**`agent edit <name>`**
Quick local editing. Opens the agent's `observal-agent.yaml` in `$EDITOR` (vim, nano, code, etc.). After the editor closes, detects changes and runs the same flow as `agent update` — pushes changes to registry.

For targeted single-field edits without opening a full editor:
```
$ observal agent edit my-agent --field prompt
→ Opens only the prompt field in $EDITOR
→ Saves back into YAML, runs update flow
```

Flags: `--field <field>` (edit a specific field: `prompt`, `description`, `model_name`, `model_config`)

---

**`agent init`**
Scaffolds an `observal-agent.yaml` in the current directory (or `--dir`). Interactive prompts for: name, version, description, owner, model, system prompt. Creates a minimal valid YAML that can be customized and then published via `agent create --from-file` or `agent update`.

This is for authors who prefer editing YAML locally over the interactive wizard.

Flags: `--dir <path>`, `--beta` (start at 0.1.0)

---

**`agent add <type> <name>`**
Quick shortcut to append a component reference to `observal-agent.yaml` without opening an editor. Validates the component exists in the registry before adding.

```
$ observal agent add mcp filesystem-server --version "^1.2.0"
→ ✓ Added mcp:filesystem-server (^1.2.0) to observal-agent.yaml
```

Flags: `--version <constraint>` (default: `latest`), `--dir <path>`

---

**`agent build`**
Dry-run validation. Reads `observal-agent.yaml`, checks every component reference against the registry (exists? approved? version constraint resolvable?), and reports results.

```
$ observal agent build
→ Agent: my-agent v1.2.0
→ Model: claude-sonnet-4
→ Component Validation:
    mcp   filesystem-server  ✓ valid (^1.2.0 → 1.2.3)
    skill code-review        ✓ valid (latest → 2.0.7)
    hook  pre-commit-lint    ✗ not found
→ 1 component(s) failed validation
```

Does not modify any files. Does not push. Just validates.

Flags: `--dir <path>`

---

**`agent versions <name>`**
Lists all versions of an agent with status badges, release dates, and reviewers.

```
$ observal agent versions my-agent
  VERSION    STATUS     DATE         RELEASED BY    REVIEWER
  1.3.0-β2  beta       2026-04-26   alice          —
  1.2.0      active     2026-04-20   alice          bob
  1.1.0      active     2026-04-10   alice          carol
  1.0.0      active     2026-04-01   alice          bob
```

Flags: `--output <table|json>`, `--include-beta` (show beta versions, hidden by default)

---

**`agent diff <name> <v1> <v2>`**
Shows a YAML diff between two versions of an agent. Fetches the `yaml_snapshot` for each version from the registry and diffs them.

```
$ observal agent diff my-agent 1.1.0 1.2.0
--- v1.1.0
+++ v1.2.0
@@ prompt @@
- You are a code review agent.
+ You are a code review agent focused on security vulnerabilities.
@@ components @@
+ - type: skill
+   name: security-scanner
+   version: "^1.0.0"
```

Flags: `--output <text|json>`

---

**`agent abandon-beta <name>`**
Abandons the current beta series. Marks all `x.y.z-beta.*` versions as `abandoned` status. Frees the author to start a new beta series or move on.

```
$ observal agent abandon-beta my-agent
→ This will abandon the 1.3.0-beta series (2 versions). Continue? (y/n)
→ ✓ Beta series 1.3.0 abandoned. Beta subscribers notified.
```

Flags: `--yes` (skip confirmation)

---

#### Consumer Commands (authed)

**`agent pull <name>`**
Pulls the generated IDE config files from the registry API into the consumer's project (or global location). This is the main way consumers install and update agents.

**First pull:**
```
$ observal agent pull my-agent --ide claude-code
→ Install location:
    1. This project (/home/user/my-project)
    2. Global (~/.config/observal/agents/)
→ Selected: 1
→ Fetching v1.2.0 from registry...
→ Writing to .claude/agents/my-agent/
→ Created .observal/installed-agents.yaml
→ Updated ~/.config/observal/installations.json
→ ✓ Pulled my-agent v1.2.0 (claude-code)
```

**Subsequent pulls (IDE and location remembered):**
```
$ observal agent pull my-agent
→ Updating my-agent: 1.2.0 → 1.3.0
→ ✓ Updated .claude/agents/my-agent/
```

Flags: `--ide <ide>` (required first time, saved in tracker), `--version <version>` (pin to specific version, default: latest approved), `--beta` (pull latest beta version), `--global` (install to global location)

---

**`agent outdated`**
Checks installed agents against the registry and shows which have newer versions available.

**In a project:**
```
$ observal agent outdated
  AGENT          INSTALLED  AVAILABLE  BUMP    POLICY
  my-agent       1.2.0      1.3.0      minor   auto-patch
  code-reviewer  2.0.0      2.0.1      patch   auto-patch (eligible)
```

**Across all projects:**
```
$ observal agent outdated --all
  AGENT          PROJECT              INSTALLED  AVAILABLE
  my-agent       /home/user/proj-a    1.2.0      1.3.0
  my-agent       /home/user/proj-b    1.2.0      1.3.0
  code-reviewer  (global)             2.0.0      2.0.1
```

Flags: `--all` (check all projects via global index), `--output <table|json>`

---

**`agent subscribe <name>`**
Subscribe to update notifications for an agent. Creates an `agent_subscription` record. Notifications appear in-app and via `agent outdated`.

```
$ observal agent subscribe my-agent --policy auto-patch
→ ✓ Subscribed to my-agent (policy: auto-patch)
```

Flags: `--policy <pin|auto-patch|auto-minor|auto-all|beta>` (default: `auto-patch`)

---

**`agent unsubscribe <name>`**
Remove subscription. Stops notifications and auto-updates for this agent.

Flags: `--yes` (skip confirmation)

---

**`agent policy <name> <policy>`**
Change the update policy for an installed agent without unsubscribing and resubscribing.

```
$ observal agent policy my-agent beta
→ ✓ Update policy for my-agent changed to: beta
```

---

#### Ownership Commands (owner only)

**`agent maintainers list <name>`**
Shows the current owner and all co-maintainers.

```
$ observal agent maintainers list my-agent
  ROLE            USER          ADDED
  owner           alice         2026-04-01
  co-maintainer   bob           2026-04-15
  co-maintainer   carol (⚠)    2026-04-20    ← account inactive
```

Flags: `--output <table|json>`

---

**`agent maintainers add <name>`**
Adds a co-maintainer. Only the owner can do this. Co-maintainers get the same permissions as the owner (update, release, edit) except they cannot add/remove other co-maintainers or transfer ownership.

```
$ observal agent maintainers add my-agent --user bob@acme.com
→ ✓ bob added as co-maintainer for my-agent
```

Flags: `--user <email-or-username>` (required)

---

**`agent maintainers remove <name>`**
Removes a co-maintainer.

Flags: `--user <email-or-username>`, `--yes`

---

**`agent transfer <name>`**
Transfers ownership to another user in the same org. The previous owner automatically becomes a co-maintainer (removable by the new owner).

```
$ observal agent transfer my-agent --to bob@acme.com
→ This will make bob the owner of my-agent.
→ You will become a co-maintainer. Continue? (y/n)
→ ✓ Ownership transferred to bob
```

Blocked if target user is in a different org: `"Cannot transfer to a user in a different organization."`

Flags: `--to <email-or-username>` (required), `--yes`

---

#### Browse Commands (any user)

**`agent list`**
Lists active agents in the registry. Paginated. Shows latest approved version per agent.

Flags: `--search <query>`, `--limit <n>` (default: 50), `--page <n>`, `--id`, `--full-id`, `--output <table|json|plain>`, `--interactive` (fuzzy select)

---

**`agent show <name>`**
Shows full details for an agent. Displays latest approved version by default.

```
$ observal agent show my-agent
╭─ my-agent v1.2.0 ─────────────────────────╮
│ Status:      active                         │
│ Model:       claude-sonnet-4                │
│ Owner:       alice                          │
│ IDEs:        claude-code, cursor, kiro ...  │
│ Components:  2 mcp, 1 skill                │
│ Created:     3 weeks ago                    │
│ Downloads:   142                            │
╰─────────────────────────────────────────────╯
```

Flags: `--version <version>` (show a specific version instead of latest), `--output <table|json>`

---

**`agent search <query>`**
Full-text search across agent names, descriptions, component names, and model names. Separate from `agent list --search` which only searches name/description.

```
$ observal agent search "security" --ide claude-code
  NAME              VERSION  MODEL            DESCRIPTION
  security-auditor  1.0.0    claude-sonnet-4  Security audit agent...
  code-reviewer     2.0.1    claude-sonnet-4  Code review with security focus...
```

Flags: `--ide <ide>` (filter by IDE support), `--output <table|json>`

---

#### Admin Commands (admin+)

**`agent archive <name>`**
Soft-delete. Removes the agent from the public registry browse. Consumers who already pulled it keep their current install but get no further updates. Reversible via `agent unarchive`.

Flags: `--yes`

---

**`agent unarchive <name>`**
Restores an archived agent back to active status.

Flags: `--yes`

---

**`agent delete <name>`**
Hard delete. Permanently removes the agent and all its versions from the registry. Admin only. Cannot be undone.

```
$ observal agent delete my-agent
→ ⚠ This will permanently delete my-agent and all 5 versions. This cannot be undone.
→ Type the agent name to confirm: my-agent
→ ✓ Deleted
```

Flags: `--yes`

---

#### Bulk Commands (authed)

**`agent bulk-create`**
Creates multiple agents from a JSON file. Supports dry-run mode.

Flags: `--from-file <path>` (required), `--dry-run`, `--yes`

---

### Mapping: Old Commands → New

| Old Command | New Command | Notes |
|---|---|---|
| `agent create` | `agent create` | Updated: saves to registry DB |
| `agent create --from-file` | `agent create --from-file` | Unchanged |
| `agent bulk-create` | `agent bulk-create` | Unchanged |
| `agent list` | `agent list` | Updated: shows latest approved version |
| `agent show` | `agent show` | Updated: supports `--version` flag |
| `agent install` | `agent pull` | Renamed: pulls from registry API |
| `agent delete` | `agent archive` / `agent delete` | Split: archive (owner), hard-delete (admin only) |
| `agent unarchive` | `agent unarchive` | Unchanged |
| `agent init` | `agent init` | Unchanged |
| `agent add` | `agent add` | Updated: adds `--version` flag for constraint |
| `agent build` | `agent build` | Unchanged |
| `agent publish` | `agent update` + `agent release` | Split: `update` for syncing, `release` for versioned release |
| `agent publish --update` | `agent update` | Direct mapping |
| `agent publish --draft` | `agent update` | Drafts are implicit before first release |
| `agent publish --submit` | `agent release` | Direct mapping |
| — | `agent edit` | New: open YAML in $EDITOR |
| — | `agent release` | New: deliberate versioned release |
| — | `agent pull` | New: consumer pulls IDE config from registry API |
| — | `agent outdated` | New: check for newer versions |
| — | `agent subscribe` | New: subscribe to update notifications |
| — | `agent unsubscribe` | New: remove subscription |
| — | `agent policy` | New: change update policy |
| — | `agent maintainers` | New: subcommand group (list/add/remove) |
| — | `agent transfer` | New: transfer ownership |
| — | `agent versions` | New: list all versions |
| — | `agent diff` | New: YAML diff between versions |
| — | `agent abandon-beta` | New: abandon beta series |
| — | `agent search` | New: full-text search |

---

## API Endpoints

### New (Agents)

| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/agents/{id}/versions` | List all versions of an agent |
| GET | `/api/v1/agents/{id}/versions/{version}` | Get specific version |
| POST | `/api/v1/agents/{id}/versions` | Create new version (release) |
| POST | `/api/v1/agents/{id}/versions/{version}/review` | Approve/reject a version |
| GET | `/api/v1/agents/{id}/versions/{version}/ide/{ide}` | Get generated IDE config for a specific version and IDE |
| GET | `/api/v1/agents/{id}/versions/{v1}/diff/{v2}` | YAML diff between two versions |
| GET | `/api/v1/agents/{id}/subscribers` | List subscribers (author view) |
| POST | `/api/v1/agents/{id}/subscribe` | Subscribe to updates |
| DELETE | `/api/v1/agents/{id}/subscribe` | Unsubscribe |
| PATCH | `/api/v1/agents/{id}/subscribe` | Update subscription policy |
| GET | `/api/v1/notifications` | Get user's notifications |
| PATCH | `/api/v1/notifications/{id}/read` | Mark notification as read |
| GET | `/api/v1/agents/outdated` | Check for outdated installed agents |
| POST | `/api/v1/agents/{id}/transfer` | Transfer ownership |
| GET | `/api/v1/agents/{id}/maintainers` | List co-maintainers |
| POST | `/api/v1/agents/{id}/maintainers` | Add co-maintainer |
| DELETE | `/api/v1/agents/{id}/maintainers/{user_id}` | Remove co-maintainer |
| GET | `/api/v1/org/settings` | Get org settings (evals visibility, beta review policy) |
| PATCH | `/api/v1/org/settings` | Update org settings (admin only) |

### New (Components — uniform across all 5 types)

| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/{type}/{id}/versions` | List all versions |
| GET | `/api/v1/{type}/{id}/versions/{version}` | Get specific version |
| POST | `/api/v1/{type}/{id}/versions` | Publish new version |
| POST | `/api/v1/{type}/{id}/versions/{version}/review` | Approve/reject |
| GET | `/api/v1/resolve/{type}/{name}?match={constraint}` | Resolve version constraint |

### Modified

| Method | Path | Changes |
|---|---|---|
| GET | `/api/v1/agents/{id}` | Returns agent identity + latest version |
| POST | `/api/v1/agents` | Creates agent identity + initial version |
| PUT | `/api/v1/agents/{id}` | Updates agent identity fields only (name, owner) |
| GET | `/api/v1/{type}/{id}` | Returns component identity + latest version |
| POST | `/api/v1/{type}` | Creates component identity + initial version |

---

## Edge Cases & Resolutions

### 1. Version rejected after release

**Resolution:** The version string is permanently consumed. Rejected `1.3.0` means the next release must be `1.3.1` or higher. No version reuse. The platform status is authoritative.

### 2. Auto-update performance (opportunistic check on every CLI invocation)

**Resolution:** npm's `update-notifier` pattern — background check with 24h cooldown.

- On CLI invocation, spawn a **detached background process** that checks the registry for updates
- Cache result in `~/.config/observal/update-check.json` with `last_checked` timestamp
- **24h cooldown** — if last check was <24h ago, skip entirely
- Next CLI invocation reads the cached result and prints a banner if updates are available
- **Zero latency** added to any command — the network check never blocks the user's command

```json
// ~/.config/observal/update-check.json
{
  "last_checked": "2026-04-27T10:00:00Z",
  "updates": [
    {"agent": "my-agent", "installed": "1.2.0", "available": "1.3.0", "bump": "minor"}
  ]
}
```

### 3. Deleted/archived component that an agent depends on

**Resolution:** Cargo's yank model — soft-delete, existing locks still work.

- Archived component versions stay resolvable for **existing** lock files that already pin them
- New lock file resolution (`agent update`) skips archived versions — won't newly resolve to them
- If the lock file points at an archived version and author runs `agent update`, it re-resolves to the next best match within the constraint
- If no match exists: clear error message — `"filesystem-server ^1.2.0: no approved versions available (1.2.3 was archived)"`
- Consumer pull still works if the agent's lock file was resolved before archival

### 4. Multiple agents writing to same IDE config location

**Resolution:** Namespace by agent name — prevent conflicts by design.

When `agent pull` writes configs to a consumer's project, each agent gets its own subdirectory:

```
.claude/
  agents/
    my-agent/
      settings.json
    code-reviewer/
      settings.json
```

Not bare `.claude/settings.json`. The IDE config generator already knows the agent name — put it in the path. This follows VS Code's namespacing pattern. No merge logic, no conflict resolution, no "last writer wins."

### 5. Stale entries in global installation index

**Resolution:** Graceful cleanup on access.

When `agent outdated --all` or auto-update reads the global `installations.json` and encounters a project path that no longer exists:
- Skip it
- Show warning: `"⚠ /home/user/old-project no longer exists, removing from index"`
- Auto-prune the stale entry from `installations.json`
- Never fail the overall command — clean up and continue

### 6. Cross-org ownership transfer

**Resolution:** Block it.

Agent's `owner_org_id` is tied to org-scoped visibility and access. Transferring across orgs would break consumers who could see it before (or expose it to people who shouldn't).

- Transfers must be within the same org
- API returns 400: `"Cannot transfer to a user in a different organization"`
- Admin override available for exceptional cases (with explicit `--force` flag and audit log entry)

### 7. Deactivated user in co-maintainers list

**Resolution:** Inert record, auth-level enforcement — GitHub's pattern.

- The UUID stays in `co_maintainers` — no auto-cleanup
- Deactivated users can't log in, so their maintainer access is moot at the auth layer
- Owner or admin can explicitly remove with `agent maintainers remove`
- Web UI shows warning on inactive co-maintainers: `"⚠ Account inactive"` with dimmed styling
- No background job to prune — keep it simple, let humans clean up

### 8. Version constraint matches nothing

**Resolution:** Fail fast at resolution time.

When `agent update` runs lock file resolution and finds no approved version matching a constraint:
- Clear error: `"skill/code-review: no version matching ^3.0.0 (latest approved: 2.1.0)"`
- Do not proceed with partial resolution — all-or-nothing
- Author fixes the constraint in `observal-agent.yaml` and re-runs
- Same behavior at `agent release` time — blocks release if lock file can't fully resolve

### 9. New release submitted while previous version still pending review

**Resolution:** Allow it, warn the author.

Multiple versions can be pending simultaneously — each is reviewed independently.

```
$ observal agent release my-agent --bump minor
⚠ v1.3.0 is still pending review
→ Proceeding with v1.4.0 release...
```

Reviewer sees both in the queue and can review in any order. Approving v1.4.0 before v1.3.0 is fine — `latest_version_id` points to the highest approved version.

### 10. Concurrent `agent update` by two co-maintainers

**Resolution:** Last-write-wins at the API level. The registry stores the latest state pushed. Since `agent update` is a pre-release save (not a versioned release), overwrites are acceptable — it's like two people editing a Google Doc. For versioned releases (`agent release`), the unique constraint on `(agent_id, version)` prevents conflicts.

### 11. Agent name collision across orgs

**Resolution:** Names are unique within `(name, created_by)` today. With org-scoping, uniqueness is `(name, owner_org_id)`. Two different orgs can have an agent named `code-reviewer`. Consumers within an org see only their org's agents. Public registry browse shows org-scoped results.

### 12. Beta abandoned mid-series

**Resolution:** Explicit "Abandon Beta" action.

If the author decides not to promote a beta series (`1.3.0-beta.1`, `1.3.0-beta.2`):
- "Abandon Beta" marks all `1.3.0-beta.*` versions as `abandoned` (terminal status)
- Frees the version space — author can start `1.3.0-beta.1` fresh, or move to `1.4.0-beta.1`
- Beta subscribers notified: "Beta series 1.3.0 was abandoned"
- Exception to "version numbers never reused": abandoned beta version strings CAN be reused since they were never approved/stable. Only approved stable version strings are permanently consumed.

---

## Migration Plan

### PostgreSQL

**Component version tables (all 5 types):**
1. Create `mcp_versions`, `skill_versions`, `hook_versions`, `prompt_versions`, `sandbox_versions` tables
2. For each existing listing row: create one version row with current data
3. Add `latest_version_id` FK to each listing table
4. Drop version-specific columns from listing tables

**Agent version tables:**
5. Create `agent_versions` table
6. For each existing agent row: create one `agent_versions` row with current version-specific data
7. Add `latest_version_id` to `agents`, set to the newly created version row
8. Update `agent_components` FK from `agent_id` to `agent_version_id`
9. Update `agent_goal_templates` FK from `agent_id` to `agent_version_id`
10. Drop version-specific columns from `agents`

**Agent ownership:**
11. Add `co_maintainers` JSON column to `agents` table (default: `[]`)

**New tables:**
12. Create `agent_subscriptions` table (with `beta` in update_policy enum)
13. Create `agent_notifications` table
14. Migrate `AgentDownloadRecord` to reference version

**Org settings:**
15. Add `evals_public` (boolean, default false) and `beta_requires_review` (boolean, default false) to `organizations` table

### ClickHouse

Clean break — drop and recreate traces, spans, events, scores tables with `agent_version` column added. Alpha product, no data preservation needed.

### Existing Code Updates

All code paths that read version-specific fields from listing/agent tables must be updated to join through version tables. Key files:

**Server:**
- `models/agent.py`, `models/mcp.py`, `models/skill.py`, `models/hook.py`, `models/prompt.py`, `models/sandbox.py` — model restructure
- `api/routes/agent.py` — all endpoints
- `api/routes/mcp.py`, `api/routes/skill.py`, `api/routes/hook.py`, `api/routes/prompt.py`, `api/routes/sandbox.py` — all endpoints
- `services/agent_builder.py` — manifest generation
- `services/agent_resolver.py` — component resolution
- `services/agent_config_generator.py` — IDE config generation
- `services/versioning.py` — add range resolver
- `services/clickhouse.py` — telemetry ingest + query
- `schemas/agent.py` — request/response schemas
- `schemas/` for all component types

**CLI:**
- `observal_cli/cmd_agent.py` — all commands
- New: `observal_cli/cmd_agent_pull.py`, `observal_cli/cmd_agent_release.py`

**Web (11 pages/views):**
- Registry browse page — updated with version dropdown, eval badges
- Agent detail page — updated with version dropdown, role-based sections
- Agent edit form — new form-based editor
- My Installed Agents page — new consumer dashboard
- Release History tab — new version timeline
- A/B Testing tab — new beta management + comparison stub
- Agent Settings tab — new maintainers, transfer, danger zone
- Review queue — updated with YAML diff view
- Notifications page — new notification center
- My Agents page — new author dashboard
- Org settings page — updated with registry settings + orphaned agents
- Component detail pages — updated with version dropdown, version history

### Prerequisites

- Issue #594: Centralize IDE registry into single source of truth (needed for IDE config generation loop)

---

## Implementation Phases

### Design Principle: Purely Additive Phases

Each phase builds on top of the previous one — nothing is scrapped or rewritten between phases.

- **Phase 1 tables are the final tables.** They use the full schema from this spec (all columns, all constraints). Phase 2 just starts *using* more of those columns. No "simple version first, real version later."
- **Phase 1 API endpoints are the final endpoints.** Phase 2 adds new endpoints alongside them, never replaces them.
- **Phase 1 CLI commands are the final commands.** `agent release` in Phase 1 skips lock file resolution (components use exact version or `latest`). Phase 2 adds the resolver — the command gains a capability, nothing is rewritten.
- **Phase 1 Web UI views are the final views.** The version dropdown, YAML diff view, etc. are permanent. Phase 2/3 add new pages and tabs, never rebuilds existing ones.

The only behavioral difference: Phase 1 skips `agent update` (authors go straight to `agent release`). Phase 2 adds `agent update` as a new command — additive, not a rewrite of `release`.

---

### Phase 1: Demo-Ready (target: May 4, 2026)

Goal: Visible version history + basic release flow. Enough to demo "publish v1, publish v2, see both, review v2, pull v2."

**Scope:**

**DB:**
- Create `agent_versions` table. Migrate existing agent rows into version rows. Add `latest_version_id` to `agents`. Update `agent_components` FK to `agent_version_id`. Add `co_maintainers` JSON column to `agents`.
- Create `mcp_versions`, `skill_versions`, `hook_versions`, `prompt_versions`, `sandbox_versions` tables. Migrate existing listing rows. Add `latest_version_id` to each listing table.

**API:**
- Version CRUD for agents (`POST /versions`, `GET /versions`, `GET /versions/{v}`). Version CRUD for all 5 component types (same pattern).
- `POST /versions/{v}/review` (approve/reject) for agents and components.
- Update existing `GET /agents/{id}` and `GET /{type}/{id}` to return identity + latest version.

**CLI:**
- `agent release --bump <patch|minor|major>` — publishes a new version to the registry.
- `agent versions <name>` — lists all versions.
- `agent pull <name> --ide <ide>` — pulls from registry API (replaces old `agent install`).

**Web:**
- Agent detail page updated with version dropdown.
- Review queue updated with YAML diff view between versions.
- Component detail pages updated with version dropdown.

**ClickHouse:**
- Add `agent_version` column to traces, spans, events tables (clean break).

**NOT in Phase 1:**
- No lock files or semver range resolution (components referenced by exact version or `latest`)
- No beta channels, A/B testing, or pre-release versions
- No subscriptions, notifications, or auto-update
- No ownership transfer or co-maintainer management CLI commands
- No "My Agents" or "Installed Agents" pages
- No `agent update` (save-without-release) — authors go straight to `agent release`

Estimated effort: 4-5 person-weeks for 2-3 engineers.

---

### Phase 2: Full Registry (target: May–June 2026)

**Scope:**
- Version range resolver service (`^1.2.0`, `latest`, exact pin)
- Lock files — `observal-agent.lock` generation and resolution
- `agent update` command (save without release)
- `agent outdated` command
- `agent pull` with subscription tracking (`agent_subscriptions` table)
- Consumer update policies (pin, auto-patch, auto-minor, auto-all)
- "My Agents" author dashboard page
- "Installed Agents" consumer dashboard page
- Ownership transfer CLI + API
- Co-maintainer management CLI + API
- Component update notifications to agent authors

---

### Phase 3: Advanced Features (target: July+ 2026)

**Scope:**
- Beta release channels + pre-release versions
- A/B testing page (version comparison stub)
- Promote beta to stable flow
- Notifications page + bell icon in nav
- Auto-update (background check with 24h cooldown)
- `agent subscribe` / `agent unsubscribe` / `agent policy` commands
- `agent diff` command
- `agent search` command
- Org settings (evals visibility, beta review requirement)
- Orphaned agents management in admin settings
