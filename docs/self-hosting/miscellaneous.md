<!--
SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
SPDX-License-Identifier: AGPL-3.0-only
-->

# Miscellaneous Settings

Settings that control platform-wide behavior, IDE restrictions, and display preferences.

## IDE Allowlist {#ide-allowlist}

Restrict which IDEs are available in the platform. When set, only the listed IDEs appear in install dropdowns, agent compatibility tags, and the `observal pull` target selection.

**Affects:** The IDE dropdown on agent detail pages, component install commands, agent builder IDE selection, and `observal pull --ide` validation. IDEs not in the allowlist are hidden from all users.

| Value | Effect |
|-------|--------|
| _(empty)_ (default) | All supported IDEs are available |
| `cursor,claude_code,pi` | Only Cursor, Claude Code, and Pi appear in dropdowns |
| `kiro,cursor` | Only Kiro and Cursor are available |

**Format:** Comma-separated IDE identifiers. Valid identifiers: `cursor`, `claude_code`, `kiro`, `pi`, `copilot`, `copilot_cli`, `codex`, `opencode`, `gemini_cli`, `antigravity`

**When to set:** Your organization standardizes on specific IDEs and you don't want users confused by irrelevant options. Also useful for reducing noise in the registry when agents only need to support a subset of IDEs.

**CLI behavior:** When set, `observal pull <agent>` without `--ide` defaults to the first IDE in the allowlist (the "default IDE"). Users can still specify any allowed IDE explicitly.

## Default IDE {#default-ide}

The IDE pre-selected in install dropdowns and used as the default for `observal pull` when no `--ide` flag is provided.

| Value | Effect |
|-------|--------|
| _(empty)_ (default) | First IDE in the allowlist, or `cursor` if no allowlist is set |
| `claude_code` | Claude Code is pre-selected in all IDE dropdowns |
| `pi` | Pi is the default target |

**Affects:** UI dropdown default selection, CLI default when `--ide` is omitted, and the install command shown on agent detail pages.

## Git Mirror Path {#git-mirror-path}

Directory used for cloned repository mirrors during component analysis and source discovery.

| Value | Effect |
|-------|--------|
| _(empty)_ (default) | Use the system temporary directory |
| `/data/git-mirrors` | Store mirrors on a persistent volume |

**When to set:** Multi-instance deployments where repeated clone work should be shared, or production deployments where temporary storage is small.

## Registered Agents Only {#registered-agents-only}

When enabled, telemetry ingestion only accepts traces from agents that are registered in the Observal registry. Traces from unknown agents are rejected with a 403.

| Value | Effect |
|-------|--------|
| `false` (default) | Accept telemetry from any agent, registered or not |
| `true` | Only registered agents can submit telemetry; unknown agents are rejected |

**When to enable:** Organizations that want strict control over which agents produce telemetry, for compliance or cost control. Ensure all team agents are registered before enabling.

## Trace Privacy {#trace-privacy}

Redact user message content from stored traces, keeping only metadata (timing, tool usage, token counts).

| Value | Effect |
|-------|--------|
| `false` (default) | Full trace content is stored and visible in the trace viewer |
| `true` | User messages are redacted; only structural metadata is retained |

**When to enable:** Organizations with strict data privacy requirements where storing LLM conversation content is not permitted. Note: redaction is irreversible for new traces.
