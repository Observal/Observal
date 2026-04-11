# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

## [0.1.0] - 2026-04-03

### Added

- **Agent registry** with bundled component packaging (MCP servers, skills, hooks, prompts, sandboxes)
- **6 component registries**: Agents, MCP Servers, Skills, Hooks, Prompts, Sandbox Exec
- **CLI** (`observal`) with auth, registry operations, admin commands, and Rich output
  - `observal init` / `login` / `whoami` for authentication
  - `observal scan` for auto-detection and instrumentation of existing IDE configs
  - `observal pull` for one-command agent installation
  - `observal agent init` / `add` / `build` / `publish` for agent composition workflow
  - `observal submit` / `list` / `show` / `install` for all component types
  - `observal review` admin workflow for approving/rejecting submissions
  - `observal eval` for running evaluations, viewing scorecards, and comparing versions
  - `observal rate` / `feedback` for user ratings
  - `observal doctor` for IDE settings diagnostics
  - `observal use` / `profile` for IDE config profiles
- **Backend API** (FastAPI) with REST and GraphQL (Strawberry) endpoints
- **Telemetry pipeline**: `observal-shim` (stdio) and `observal-proxy` (HTTP) transparent proxies that intercept MCP traffic and stream traces to ClickHouse
- **OpenTelemetry Collector** integration with OTLP HTTP receiver endpoints
- **ClickHouse** storage for traces, spans, and scores
- **Eval engine** with pluggable LLM-as-judge scoring and managed templates
- **RAGAS evaluation** for GraphRAG retrieval spans
- **Web dashboard** (Next.js, React, Tailwind CSS, shadcn/ui, Recharts) with admin dashboard, trace viewer, component browser, and role-gated navigation
- **Background jobs** via arq + Redis with pub/sub service
- **Git mirror service** with component discovery and path traversal/symlink protections
- **Download tracking** with bot prevention
- **IDE support** for Claude Code, Codex CLI, Gemini CLI, GitHub Copilot, Kiro, Cursor, and VS Code
- **Universal IDE agent file generation** from Pydantic manifest
- **Admin review workflow** for all registry types
- **Docker Compose deployment** (7 services)
- **526 tests** with full external service mocking
- **Pre-commit hooks**, linting (ruff, hadolint), and formatting
- **Interactive GitHub issue forms** for bugs and features
- **Pull request template**
- Apache 2.0 license
