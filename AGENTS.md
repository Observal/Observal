<!-- SPDX-FileCopyrightText: 2026 Aryan Iyappan <aryaniyappan2006@gmail.com> -->
<!-- SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com> -->
<!-- SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com> -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# AGENTS.md

Internal context for contributors and AI coding agents. Use `README.md` for the public API reference, `SETUP.md` for environment setup, and `docs/adding-a-harness.md` for harness integration.

## What Observal is

Observal is an agent-centric registry and observability platform for AI coding agents. Users interact with it three ways:

1. **CLI** (`observal`): pull agents, sca harnesses, submit components, manage the server
2. **Web UI** (`web/`): browse the registry, view traces, manage users, admin dashboard
3. **Observal skill** (bundled, auto-installed on login): lets the LLM inside any harness drive Observal commands directly (e.g. "create an agent that uses the github MCP")

Agents are the primary entity. Each agent bundles 5 component types: MCP servers, skills, hooks, prompts, and sandboxes. When a user runs `observal pull <agent>`, the platform resolves all components and writes harness-specific config files.

## harness support tiers

**First-class** (full session parsing, hooks, scanning, config gen, tested e2e):
- Claude Code
- Kiro
- Cursor
- Pi

**Functional** (config gen and scanning work, but no session parser or hook spec):
- Codex CLI, Copilot, Copilot CLI, OpenCode

See `docs/adding-a-harness.md` for the complete guide to adding or promoting a harness.

## Architecture at a glance

```
observal_cli/          Python CLI (Typer)
  harness/             CLI-side harness adapters (protocol.py, base.py, 9 adapters)
  harness_specs/           Hook specs (claude_code, kiro, pi only)
  skills/              Bundled skills installed on login (observal, observal-admin, etc.)

observal-server/       FastAPI server
  api/routes/          REST endpoints (agent/, admin/ are sub-packages)
  api/middleware/      Audit, request-id, content-type
  models/              SQLAlchemy models (PostgreSQL)
  schemas/             Pydantic request/response schemas
  services/            Business logic
    clickhouse/        ClickHouse subpackage (client, schema, insert, query)
    harness/           Server-side harness adapters (config generation)
    session_parsers/   Per-harness JSONL parsers (claude_code, kiro, cursor, pi)
    audit/             Compliance audit system (loguru-based)
    config/            Config generation helpers (mcp_builder, skill_builder)
    insights/          Insight engine (report generation, facets, sections, HTML export)
    shared/            Cross-service utilities
  jobs/                Background job definitions (catalog, maintenance)


web/                   Next.js 16 / React 19 frontend
packages/pi-extension/ Pi telemetry extension (npm: observal-pi)
docker/                Docker Compose stack (10 services)
tests/                 pytest (123 files)
tests/e2e/             Playwright (19 specs)
```

## How the modularisation works

The codebase follows a strict adapter pattern for harness-specific logic. This is the most important architectural decision:

**One adapter per harness, on both sides.** CLI adapters handle scanning and hook detection (`observal_cli/harness/<name>.py`). Server adapters handle config file generation (`observal-server/services/harness/<name>.py`). The shared harness registry (`packages/observal-shared/observal_shared/harness_registry.py`) defines paths, keys, features, and event maps for both sides.

**No if/elif chains for harness logic.** If you need harness-specific behavior, it goes in the adapter. The orchestrators (`cmd_scan.py`, `agent_builder.py`, `cmd_doctor.py`) call adapters via the registry, never with conditionals.

**Feature-flag gating.** Each adapter method maps to a feature (`hooks`, `mcp_servers`, `skills`). The `BaseAdapter` raises `NotSupportedError` if the harness's registry entry lacks the required feature. This means stubs are safe: they exist but can't be called for unsupported operations.

**Session parsers are separate from adapters.** They live in `services/session_parsers/` (server-side) and handle converting raw JSONL into normalized trace events. Only first-class harnesses have parsers.

### What "first-class" means concretely

A first-class harness has all of:
- A hook spec in `harness_specs/` (defines what `doctor patch` installs)
- A session parser in `services/session_parsers/` (enables `observal reconcile`)
- Full scanning implementation in its CLI adapter (discovers MCPs, skills, hooks, agents)
- E2E test coverage in `tests/e2e/`

A stub harness has:
- A registry entry with correct paths
- A CLI adapter that handles basic MCP scanning
- A server adapter that generates config files
- No hook spec, no session parser, no e2e tests

## Coding patterns we prefer

### Python (server + CLI)

- **Ruff** for lint and format. Line length 120. Pre-commit enforces it.
- **Loguru for dev logging** (`from loguru import logger as optic`). Positional args only: `optic.debug("x={}", x)`. Never f-strings in log calls.
- **Typer for CLI.** `B008` suppressed because Typer requires function calls in argument defaults.
- **Skill files track CLI changes.** When any CLI command is added, removed, renamed, or has its flags changed, update the corresponding skill files in `observal_cli/skills/`. These are the agent's source of truth for command syntax.
- **Dynamic settings** for runtime config: `from services.dynamic_settings import get, get_int, get_bool`. Non-boot settings live in the DB, not env vars.
- **ClickHouse migrations** live in `observal-server/clickhouse/migrations/*.sql` and run through `services.clickhouse.migrations`. Keep Alembic for Postgres only. Never add ClickHouse DDL to startup code. The init container runs ClickHouse migrations after Alembic and before API startup.
- **SSRF guard** for all outbound network: `from services.ssrf_guard import check_url`. Used in webhooks, git clone, MCP analysis.
- **Conventional Commits**: `feat`, `fix`, `docs`, `refactor`, `test`, `build`, `ci`, `chore`. Scope in parens. No fixup commits (amend instead).

### TypeScript (web)

- **sessionStorage** for auth state (API key, user role). Never localStorage.
- **TanStack Query hooks** from `use-api.ts` for all data fetching. No raw `fetch` in components.
- **Types centralized** in `src/lib/types.ts`. No inline API response types.
- **harness list from server** (`/api/v1/config/harnesses`), never hardcoded in frontend.
- **OKLCH color tokens** in `globals.css`. No raw hex/rgb in components.

### General

- **No telemetry wrappers or OTLP env vars.** MCP commands and remote URLs remain direct. Telemetry flows through session push hooks and reconciliation. Never generate `OTEL_*` or `CLAUDE_CODE_ENABLE_TELEMETRY` vars.
- **Owner fallback on install.** Submitters can install their own items without admin approval. Approved items are preferred, but pending/rejected items are accessible to the submitter.
- **Canonical registry identity is `namespace/slug`.** UUIDs remain accepted; legacy bare names resolve only when unambiguous. CLI slash-qualified references resolve to UUIDs before using existing action routes.
- **Hard rewrite policy.** No deprecation wrappers. When code moves, callers update in the same PR. Dead code is deleted immediately.
- **Tests mock externals.** No Docker needed to run the test suite. E2E specs in `tests/e2e/` are the exception (require running stack).

## CLI structure

```
observal
├── pull                     # install agent into harness (primary workflow)
├── scan                     # read-only discovery of what's installed
├── reconcile                # push local session JSONL to server for rich traces
├── use / profile            # swap harness configs from git-hosted profiles
├── uninstall                # tear down Docker stack and config
├── auth                     # login, register, reset-password, logout, whoami, status
├── config                   # show, set, path, alias, aliases
├── registry                 # component parent group
│   ├── mcp                  #   submit, list, show, install, edit, delete, co-authors
│   ├── skill                #   submit, list, show, install, edit, delete, co-authors
│   ├── hook                 #   submit, list, show, install, edit, delete, co-authors
│   ├── prompt               #   submit, list, show, edit, render, delete, co-authors
│   ├── sandbox              #   submit, list, show, edit, delete, co-authors
│   └── models               #   list (public model catalog)
├── component                # version commands (list-versions, publish, show-version)
├── agent                    # create, list, show, install, delete, init, add, build, publish, co-authors
├── ops                      # overview, metrics, top, rate, feedback
│   └── telemetry            #   status, test
├── admin                    # settings, set, users, review (list/show/approve/reject)
├── server                   # start, stop, restart, status, logs, install, reset, config
├── self                     # upgrade, downgrade, rollback, status
├── support                  # bundle (diagnostic tarball with redaction)
├── doctor                   # diagnose + patch harness settings for all 9 harnesses
├── migrate                  # ClickHouse migration tools
└── logs                     # live dev log viewer
```

## Server routes

REST at `/api/v1/`. GraphQL at `/api/v1/graphql` (read-only telemetry layer with subscriptions).

Key route files: `auth.py`, `mcp.py`, `skill.py`, `hook.py`, `prompt.py`, `sandbox.py`, `review.py`, `feedback.py`, `dashboard.py`, `insights.py`, `reconcile.py`, `ingest.py`, `telemetry.py`, `alert.py`, `config.py`, `sessions.py`, `device_auth.py`, `jwks.py`, `component_source.py`, `component_versions.py`, `agent_versions.py`, `bulk.py`, `support.py`, `preview.py`, `audit.py`, `registry_models.py`.

Sub-packages: `agent/` (crud, install, draft), `admin/` (enterprise_settings, users, org, retention).

## Database architecture

- **PostgreSQL**: relational data (users, agents, components, feedback, settings). SQLAlchemy async.
- **ClickHouse**: session events, session aggregates, audit events, security events, and webhook deliveries. HTTP interface, MergeTree-family tables, bloom filter indexes. Schema changes use versioned SQL migrations in `observal-server/clickhouse/migrations/`. Runtime helpers stay in `services/clickhouse/`.
- **Redis**: pub/sub for GraphQL subscriptions, arq job queue, dynamic settings cache, auth token revocation.

## Telemetry pipeline

```
harness ──→ session push hooks ──→ POST /api/v1/ingest/session ──→ ClickHouse
CLI ──→ observal reconcile ──→ POST /api/v1/ingest/session ──→ ClickHouse
```

Session delivery uses a local outbox and resumes after transient network failures.

## Auth model

- API key based. Keys are SHA-256 hashed. `X-API-Key` header on every request.
- JWT signing uses ES256 (not HS256). JWKS endpoint for public key distribution.
- Device authorization flow for CLI login via browser confirmation.
- Redis fail-closed: if Redis is down, auth fails (prevents stale token usage).
- Fresh servers auto-bootstrap admin on first `observal auth login` (localhost-only).

## Commands

```bash
# Docker stack (10 services: init, api, db, clickhouse, redis, worker, web, lb, prometheus, grafana)
make up                  # start
make down                # stop
make rebuild             # rebuild and restart
make logs                # tail logs

# CLI (installed via uv)
uv tool install --editable .
observal auth login      # auto-creates admin on fresh server, or login
observal auth whoami     # check auth

# Linting
make lint                # ruff check
make format              # ruff format + ruff fix
make check               # pre-commit on all files
make hooks               # install pre-commit hooks

# Tests (all mock externals, no Docker needed)
make test                # 123 files in tests/ + 22 in observal-server/tests/ + 3 in observal_cli/tests/
make test-v              # verbose
# E2E (requires running stack):
cd tests/e2e && pnpm test   # 19 Playwright specs
```

## Optic (dev logging)

Loguru-based. `observal logs` streams `~/.observal/logs/dev.log`.

- Import: `from loguru import logger as optic`
- Format: `optic.debug("msg: x={}", x)` (positional only, never f-strings)
- Never log secrets, tokens, keys, JWT payloads. Log IDs and counts only.
- Log format (console/json) configured via `observability.log_format` dynamic setting.

## AI contribution policy

See `AI_POLICY.md`. Key rules: no autonomous PRs without human authorship, every change must be explainable, label AI tool usage, frontend changes need screenshots, no slop.

## Paths to never commit

`.claude/`, `CLAUDE.md`, `.kiro/`, `.cursor/`, `.gemini/`, `GEMINI.md`, `.opencode/`, `.github/copilot-instructions.md`, `.copilot/`, `.vscode/`, `.worktrees/`
