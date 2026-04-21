# Kiro Compatibility Matrix

Comparison of Observal's Claude Code integration vs Kiro CLI support.

**Research date:** 2026-04-11
**Kiro CLI version tested:** 1.28.1

## Telemetry & Observability

| Feature | Claude Code | Kiro CLI | Gap | Severity |
|---------|------------|----------|-----|----------|
| Native OTEL traces via /v1/traces | Yes | **No** — feature requested ([#6319](https://github.com/kirodotdev/Kiro/issues/6319)) | Kiro has no native OTLP export. Telemetry must be collected via hooks. | Critical |
| Native OTEL logs via /v1/logs | Yes | **No** | Same as above — no OTLP log export | Critical |
| OTEL endpoint redirection (`OTEL_EXPORTER_OTLP_ENDPOINT`) | Yes | **No** — requested ([#7226](https://github.com/kirodotdev/Kiro/issues/7226)) | No env var or config to redirect telemetry | Critical |
| Token counts (input/output/cache) | Yes (in OTLP attributes) | **Internal only** — visible in UI/credits, not exportable ([#7347](https://github.com/kirodotdev/Kiro/issues/7347)) | Hook payloads don't include token data | Major |
| Session IDs | Yes (resource attribute) | **Partial** — sessions exist but ID not in hook STDIN | Need to generate/track session IDs via hooks | Major |
| Model name | Yes (`model` attribute) | **Internal only** — visible in UI, not in hook payloads | Not available in hook context | Major |
| Cost data | Yes (computed) | **Internal only** — credit display in UI, `/usage` CLI command | Not accessible programmatically via hooks | Major |
| IDE detection in OTLP | Yes (`_IDE_HINTS` dict) | Yes — `"kiro": "kiro"` already in code | None | None |

## Hook System

| Feature | Claude Code | Kiro CLI | Gap | Severity |
|---------|------------|----------|-----|----------|
| HTTP hooks (webhook-style) | Yes (`type: "http"`) | **No** — hooks are shell commands only (`runCommand`) | Observal must use `curl` in a shell hook, not native HTTP | Major |
| Hook config location | `~/.claude/settings.json` | Agent config JSON (`.kiro/agents/*.json`) or `.kiro/hooks/` | Different config injection point for `observal scan --home` | Major |
| PreToolUse / PostToolUse | Yes | Yes (`preToolUse` / `postToolUse`) | Event names differ (camelCase vs PascalCase) | Minor |
| SessionStart | Yes | **`agentSpawn`** | Different event name, needs mapping | Minor |
| SessionEnd / Stop | Yes (`Stop`) | **`stop`** | Different event name (lowercase) | Minor |
| UserPromptSubmit | Yes | **`userPromptSubmit`** (CLI) / `promptSubmit` (IDE) | Different naming | Minor |
| SubagentStart / SubagentStop | Yes | **No equivalent** | Kiro doesn't expose subagent lifecycle hooks | Minor |
| PreCompact / PostCompact | Yes | **No equivalent** | Kiro doesn't expose compaction hooks | Minor |
| Hook STDIN format | `hook_event_name`, `tool_name`, `tool_input`, `tool_response`, `session_id` | `hook_event_name`, `tool_name`, `tool_input`, `tool_response`, `cwd` | Missing `session_id`, has `cwd` instead | Minor |
| Tool matchers | Glob patterns | Canonical names + aliases + MCP refs (`@git`, `fs_read`, `*`) | Different matcher syntax | Minor |
| Hook blocking (exit code) | Return `{"decision": "block"}` | Exit code 2 blocks | Different blocking mechanism | Minor |

## MCP & Agent Configuration

| Feature | Claude Code | Kiro CLI | Gap | Severity |
|---------|------------|----------|-----|----------|
| MCP config file | `.mcp.json` or `~/.claude/settings.json` | `.kiro/settings/mcp.json` | Already supported in Observal | None |
| MCP format (`mcpServers` key) | Yes | Yes | Compatible | None |
| Stdio transport | Yes | Yes | Compatible | None |
| HTTP/SSE transport | Yes | Yes (streamable-HTTP) | Compatible | None |
| Agent rules files | `CLAUDE.md` / `AGENTS.md` | **Steering files** (`.kiro/steering/*.md`) + AGENTS.md compat | Observal generates AGENTS.md (works), but no Steering file support | Major |
| Agent config format | N/A | `.kiro/agents/<name>.json` with rich schema | Already implemented in Observal | None |
| Skills/plugins | Claude Code skills | `.kiro/skills/` with SKILL.md | No Observal skill installation for Kiro format | Major |
| Specs system | N/A | `.kiro/specs/` (requirements/design/tasks) | No equivalent in Observal — Kiro-only feature | Minor |
| Powers (bundled extensions) | N/A | 50+ Powers (MCP + steering + hooks bundles) | No equivalent in Observal | Minor |
| Inclusion modes | Hierarchical (root/subdirs) | Always / FileMatch / Manual / Auto (YAML frontmatter) | Steering files more expressive than AGENTS.md | Minor |

## CLI Commands

| Feature | Claude Code | Kiro CLI | Gap | Severity |
|---------|------------|----------|-----|----------|
| `observal scan --ide kiro` | N/A | Yes — discovers `.kiro/settings/mcp.json` | Works but no agent/plugin discovery, no hook injection | Major |
| `observal pull --ide kiro` | N/A | Yes — generates `.kiro/agents/<name>.json` | Works but no Steering file generation | Minor |
| `observal doctor --ide kiro` | N/A | Yes — checks settings files | Works but limited diagnostics | Minor |
| Agent discovery (`scan --home`) | Finds `~/.claude/agents/` | **No** — doesn't scan `~/.kiro/agents/` | Missing Kiro agent discovery | Major |
| Plugin discovery (`scan --home`) | Finds `~/.claude/plugins/` | **No** — doesn't scan Kiro skills/powers | Missing Kiro plugin discovery | Minor |
| Hook injection (`scan --home`) | Injects into `~/.claude/settings.json` | **No** — doesn't inject into Kiro hook config | Missing hook auto-injection for Kiro | Major |

## Frontend Display

| Feature | Claude Code | Kiro CLI | Gap | Severity |
|---------|------------|----------|-----|----------|
| IDE filter in trace list | Yes | Yes — `kiro` and `kiro-cli` in filter | None | None |
| IDE badge color | Yellow | **No distinct badge color** in web UI | trace-list.tsx filters but doesn't show colored badge | Minor |
| Install dialog IDE option | Yes | Yes — "Kiro IDE" and "Kiro CLI" | None | None |
| Pull command IDE option | Yes | Yes — "Kiro" | None | None |
| CLI render color | Yellow | Magenta | None | None |

## Summary

| Category | Complete | Gaps |
|----------|----------|------|
| OTLP Telemetry | 1 | 7 (all blocked by Kiro lacking native OTEL) |
| Hook System | 0 | 11 |
| MCP & Agents | 4 | 5 |
| CLI Commands | 3 | 4 |
| Frontend | 4 | 1 |
| **Total** | **12** | **28** |

### Critical Gaps (block basic functionality)
1. Kiro has no native OTEL export — all telemetry must flow through hooks
2. Hook-based telemetry bridge needed (shell command hooks → Observal API)
3. No token/cost/model data accessible via hooks

### Major Gaps (missing important features)
4. Hook config format differs — can't inject HTTP hooks directly
5. Hook event name mapping needed (camelCase ↔ PascalCase)
6. No Steering file generation (only AGENTS.md)
7. No Kiro agent/plugin discovery in `scan --home`
8. No hook auto-injection for Kiro
9. No Skills installation support for Kiro format

### Minor Gaps (nice-to-have)
10. Missing subagent/compaction hook events
11. Different hook blocking mechanism
12. No Specs/Powers support
13. Frontend IDE badge color
14. Limited doctor diagnostics
