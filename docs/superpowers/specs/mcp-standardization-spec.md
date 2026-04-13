# MCP Server Standardization Spec

**Date:** 2026-04-13
**Status:** Draft

## Overview

This document defines the standardized metadata format for MCP servers in the Observal registry. It is a **superset of the official MCP Registry `server.json` format** (`registry.modelcontextprotocol.io`), adding fields for categorization, tool discovery, and client compatibility that the official registry deliberately omits.

MCP servers submitted via `observal registry mcp submit` are validated against this spec. Servers that pass are eligible for the registry. Servers that fail are flagged for conversion by an external standardizer agent.

Observal is **framework-agnostic**. Any MCP-compatible server is accepted regardless of implementation framework (FastMCP, MCP SDK, TypeScript SDK, Go SDK, or custom implementations). The registry detects and records the framework for informational purposes but does not enforce a specific one.

## Alignment with Official MCP Registry

The official MCP Registry (backed by Anthropic, GitHub, Microsoft) defines a `server.json` validated against:
```
https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json
```

Observal preserves all official fields and adds registry-specific extensions. A valid Observal entry is a valid `server.json` with additional metadata.

## Required Fields

| Field | Type | Constraints | Source |
|-------|------|-------------|--------|
| `name` | string | 3-100 chars, unique in registry | Publisher |
| `version` | string | Semver recommended, no ranges | Publisher |
| `description` | string | 100+ chars | Publisher |
| `category` | string | One of the valid categories (see taxonomy below) | Publisher |
| `git_url` | string | Valid HTTPS URL. Internal/private IPs allowed for self-hosted instances (configure via `ALLOW_INTERNAL_URLS`). Blocked by default in public registry mode. | Publisher |
| `owner` | string | Non-empty | Publisher |
| `supported_ides` | list[string] | Each one of: `cursor`, `kiro`, `claude-code`, `gemini-cli`, `vscode`, `codex`, `copilot` | Publisher |

## Optional Fields

| Field | Type | Constraints | Source |
|-------|------|-------------|--------|
| `transport` | string | One of: `stdio`, `sse`, `streamable-http` | Auto-detected or publisher |
| `environment_variables` | list[object] | Each: `name` (string), `description` (string), `required` (bool) | Auto-detected + publisher |
| `setup_instructions` | string | Free text | Publisher |
| `changelog` | string | Free text | Publisher |
| `tools_schema` | list[object] | Extracted tool definitions | Auto-detected |
| `packages` | list[object] | Official `server.json` format: `registryType`, `identifier`, `version`, `transport`, `environmentVariables` | Publisher |
| `remotes` | list[object] | Official `server.json` format: `type`, `url`, `variables`, `headers` | Publisher |

## Registry-Managed Fields

Set by the system, not the publisher:

| Field | Type | Description |
|-------|------|-------------|
| `status` | enum | `pending`, `approved`, `rejected` |
| `mcp_validated` | boolean | Whether automated validation passed |
| `validation_results` | list | Per-stage validation output |
| `submitted_by` | UUID | Submitting user |
| `created_at` | datetime | Submission timestamp |
| `updated_at` | datetime | Last modification |
| `download_count` | integer | Install count |

## Validation Levels

### Level 0: Metadata Validation

Performed at submission time (CLI + API).

- All required fields present
- Constrained fields match valid options (category, supported_ides, transport)
- `description` is 100+ characters
- `version` is non-empty, no range operators

**git_url validation:** By default, internal IPs (`localhost`, `10.*`, `192.168.*`, `172.*`) are blocked to prevent SSRF on public instances. Self-hosted deployments set `ALLOW_INTERNAL_URLS=true` to permit corporate GitLab/GitHub Enterprise URLs. This is the expected deployment mode for companies hosting their own MCP server repos.

**Result:** 422 rejection with valid options listed if any field is invalid.

### Level 1: Repository Inspection

Performed asynchronously as a background task after submission. The clone runs in a thread pool (`asyncio.to_thread`) to avoid blocking the server event loop, with a configurable timeout (`GIT_CLONE_TIMEOUT`, default 120s).

- Git repo is cloneable (depth=1)
- MCP implementation detected via pattern matching across supported languages:
  - Python: FastMCP, MCP SDK, `@app.tool`, `@server.tool`, or any recognized MCP pattern
  - TypeScript/JavaScript: `@modelcontextprotocol/sdk` in package.json
  - Go: `mcp-go` imports
  - Other: any implementation that exposes MCP-compatible endpoints
- Framework identified and recorded for informational purposes (not enforced)
- Servers with unrecognized frameworks are still accepted if they pass subsequent validation
- Environment variables detected from:
  - Python source: `os.environ.get()`, `os.environ[]`, `os.getenv()` patterns
  - `.env.example` / `.env.sample` files (`.env` and `.env.local` are skipped to avoid secrets)
  - Dockerfile `ENV` and `ARG` directives
  - Internal/framework env vars (PATH, HOME, NODE_ENV, etc.) are filtered out

**Result:** `mcp_validated` set to true/false. Validation result stored with stage `clone_and_inspect`.

### Level 2: Manifest Validation

Performed if a parseable entry point is found (currently Python only).

- AST parsing of entry point
- Server name extracted from constructor patterns
- `@tool` decorated functions found and catalogued
- Each tool checked for:
  - Docstring present and 20+ characters
  - All parameters have type annotations
- `tools_schema` populated with extracted tool metadata

For non-Python servers, Level 2 validation is skipped. The server passes with Level 1 only.

**Result:** Validation result stored with stage `manifest_validation`. Issues listed.

### Level 3: Standardized (Future)

Not implemented in this repo. Handled by external standardizer agent.

- All tools have full JSON Schema input definitions
- README.md present at repo root
- Config snippet tested for each supported IDE
- `server.json` compatible output generated
- No specific framework required; the server just needs to be MCP-protocol-compliant

Servers that fail Levels 0-2 are flagged and can be sent to the standardizer agent (separate repo) for automated conversion.

## Transport Types

Aligned with the official MCP spec:

| Transport | Description | Use Case |
|-----------|-------------|----------|
| `stdio` | Local subprocess, stdin/stdout JSON-RPC | Installed locally, launched by IDE |
| `sse` | HTTP + Server-Sent Events | Legacy remote transport |
| `streamable-http` | HTTP POST/GET + optional SSE | Recommended remote transport |

## Category Taxonomy

Derived from community patterns (awesome-mcp-servers, Smithery) and the gap in the official registry (which has no categories):

```
browser-automation    cloud-platforms    code-execution
communication         databases          developer-tools
devops                file-systems       finance
knowledge-memory      monitoring         multimedia
productivity          search             security
version-control       ai-ml              data-analytics
general
```

A server has exactly one category. `general` is the fallback.

## Client Compatibility

The `supported_ides` field tracks which AI coding tools can use this server:

```
cursor       kiro          claude-code
gemini-cli   vscode        codex
copilot
```

Names use hyphens as the canonical format. Underscores are normalized to hyphens on submission for backward compatibility.

## Official server.json Compatibility

Observal entries can include the official `packages` and `remotes` fields from the `server.json` spec:

### packages (local installation)

```json
{
  "registryType": "npm | pypi | nuget | oci | mcpb",
  "identifier": "@scope/package-name",
  "version": "1.0.0",
  "transport": { "type": "stdio" },
  "environmentVariables": [
    {
      "name": "API_KEY",
      "description": "Your API key",
      "isRequired": true,
      "isSecret": true
    }
  ]
}
```

### remotes (remote endpoints)

```json
{
  "type": "streamable-http | sse",
  "url": "https://api.example.com/mcp",
  "variables": {
    "tenant_id": {
      "description": "Your tenant ID",
      "isRequired": true,
      "choices": ["us-east-1", "eu-west-1"]
    }
  },
  "headers": [
    {
      "name": "X-API-Key",
      "description": "API key for auth",
      "isRequired": true,
      "isSecret": true
    }
  ]
}
```

These fields are optional in Observal (the `git_url` field is the primary source reference), but when present they enable richer install config generation and interop with the official MCP Registry.

## Relationship to Official Server Card (SEP-2127)

The MCP Server Card working group is defining a discovery document format (target: April 2026). When finalized, Observal will adopt compatible fields. The `packages`, `remotes`, and `_meta` fields in this spec are already aligned with the expected Server Card structure.
