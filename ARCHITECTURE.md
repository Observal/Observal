<!-- SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com> -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Architecture

This document describes the high-level architecture of Observal.

## Overview

Observal is an agent-centric registry and observability platform for AI
coding agents. Users interact with it through three interfaces: the CLI
(`observal`), the web UI (`web/`), and the bundled Observal skill that
lets the LLM inside any harness drive Observal commands directly.

Agents are the primary entity. Each agent bundles five component types:
MCP servers, skills, hooks, prompts, and sandboxes. When a user runs
`observal pull <agent>`, the platform resolves all components and writes
harness-specific config files.

## Components

```
observal_cli/          Python CLI (Typer)
  harness/             CLI-side harness adapters (9 adapters)
  harness_specs/       Hook specs (claude_code, kiro, pi)
  skills/              Bundled skills installed on login

observal-server/       FastAPI server
  api/routes/          REST endpoints
  api/middleware/      Audit, request-id, content-type
  models/              SQLAlchemy models (PostgreSQL)
  schemas/             Pydantic request/response schemas
  services/            Business logic
    clickhouse/        ClickHouse subpackage (client, schema, insert, query)
    harness/           Server-side harness adapters (config generation)
    session_parsers/   Per-harness JSONL parsers
    audit/             Compliance audit system
    config/            Config generation helpers
    insights/          Insight engine (reports, facets, HTML export)
    shared/            Cross-service utilities
  jobs/                Background job definitions

web/                   Next.js 16 / React 19 frontend
packages/pi-extension/ Pi telemetry extension (npm: observal-pi)
docker/                Docker Compose stack (10 services)
tests/                 pytest (174 files)
tests/e2e/             Playwright (19 specs)
```

## Data Stores

- **PostgreSQL**: relational data (users, agents, components, feedback,
  settings). SQLAlchemy async ORM with Alembic migrations.
- **ClickHouse**: session events, session aggregates, audit events, security
  events, and webhook deliveries. HTTP interface, MergeTree-family tables
  with bloom filter indexes. Schema changes use versioned SQL migrations.
- **Redis**: pub/sub for GraphQL subscriptions, arq job queue, dynamic
  settings cache, auth token revocation. Redis fail-closed: if Redis is
  down, auth fails to prevent stale token usage.

## Harness Adapter Pattern

The codebase follows a strict adapter pattern for harness-specific logic.
This is the most important architectural decision:

- **One adapter per harness, on both sides.** CLI adapters handle scanning
  and hook detection. Server adapters handle config file generation. The
  shared harness registry defines paths, keys, features, and event maps.
- **No if/elif chains for harness logic.** Harness-specific behavior lives in
  the adapter. Orchestrators call adapters via the registry, never with
  conditionals.
- **Feature-flag gating.** Each adapter method maps to a feature (hooks,
  mcp_servers, skills). The BaseAdapter raises NotSupportedError if the
  harness lacks the required feature.
- **Session parsers are separate from adapters.** They live in
  `services/session_parsers/` and convert raw JSONL into normalized trace
  events.

First-class harnesses (full session parsing, hooks, scanning, config gen,
e2e tests): Claude Code, Kiro, Cursor, Pi.

## Telemetry Pipeline

```
harness -> session push hooks -> POST /api/v1/ingest/session -> ClickHouse
CLI -> observal reconcile -> POST /api/v1/ingest/session -> ClickHouse
```

Session delivery uses a local outbox and resumes after transient network
failures.

## Auth Model

- API key based. Keys are SHA-256 hashed. X-API-Key header on every request.
- JWT signing uses ES256 (not HS256). JWKS endpoint for public key
  distribution.
- Device authorization flow for CLI login via browser confirmation.
- Redis fail-closed for token revocation.

## Coding Standards

- **Python**: Ruff for lint and format (line length 120). Pre-commit
  enforces. Loguru for dev logging. Typer for CLI.
- **TypeScript**: ESLint + TypeScript strict mode. TanStack Query for data
  fetching. Types centralized in `src/lib/types.ts`. OKLCH color tokens.
- **General**: Conventional Commits. No telemetry wrappers or OTLP env vars.
  Hard rewrite policy (no deprecation wrappers). Tests mock externals.

See [CONTRIBUTING.md](CONTRIBUTING.md) and [AGENTS.md](AGENTS.md) for full
details.
