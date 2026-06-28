<!--
SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
SPDX-License-Identifier: AGPL-3.0-only
-->

# Miscellaneous Settings

Settings that control platform-wide behavior, harness restrictions, and display preferences.

## Appearance {#appearance}

Controls the product name and images shown in the web UI.

| Field | Effect |
|-------|--------|
| Icon | Small logo used in navigation and compact surfaces |
| Wordmark | Optional full logo image that replaces text branding |
| App name | Text fallback used when no wordmark is configured |

**Image formats:** PNG, SVG, ICO, JPEG, and WEBP. Keep files under 2 MB. Transparent images work best across light and dark themes.

**When to set:** Self-hosted deployments that need company branding in the admin UI.

## harness Allowlist {#harness-allowlist}

Restrict which harnesses are available in the platform. When set, only the listed harnesses appear in install dropdowns, agent compatibility tags, and the `observal pull` target selection.

**Affects:** The harness dropdown on agent detail pages, component install commands, agent builder harness selection, and `observal pull --harness` validation. harnesses not in the allowlist are hidden from all users.

| Value | Effect |
|-------|--------|
| _(empty)_ (default) | All supported harnesses are available |
| `cursor,claude_code,pi` | Only Cursor, Claude Code, and Pi appear in dropdowns |
| `kiro,cursor` | Only Kiro and Cursor are available |

**Format:** Comma-separated harness identifiers. Valid identifiers: `cursor`, `claude_code`, `kiro`, `pi`, `copilot`, `copilot_cli`, `codex`, `opencode`, `gemini_cli`, `antigravity`

**When to set:** Your organization standardizes on specific harnesses and you don't want users confused by irrelevant options. Also useful for reducing noise in the registry when agents only need to support a subset of harnesses.

**CLI behavior:** When set, `observal pull <agent>` without `--harness` defaults to the first harness in the allowlist (the "default harness"). Users can still specify any allowed harness explicitly.

## Default harness {#default-harness}

The harness pre-selected in install dropdowns and used as the default for `observal pull` when no `--harness` flag is provided.

| Value | Effect |
|-------|--------|
| _(empty)_ (default) | First harness in the allowlist, or `cursor` if no allowlist is set |
| `claude_code` | Claude Code is pre-selected in all harness dropdowns |
| `pi` | Pi is the default target |

**Affects:** UI dropdown default selection, CLI default when `--harness` is omitted, and the install command shown on agent detail pages.

## Git Mirror Path {#git-mirror-path}

Directory used for cloned repository mirrors during component analysis and source discovery.

| Value | Effect |
|-------|--------|
| _(empty)_ (default) | Use the system temporary directory |
| `/data/git-mirrors` | Store mirrors on a persistent volume |

**When to set:** Multi-instance deployments where repeated clone work should be shared, or production deployments where temporary storage is small.

## Registered Agents Only {#registered-agents-only}

Limits telemetry to agents that are registered in the Observal registry.

| Value | Effect |
|-------|--------|
| `false` (default) | Accept telemetry from any agent, registered or not |
| `true` | Only registered agents are traced. Unregistered agent activity may be missing from traces |

**Status:** This control is unstable. Enable it only after confirming all team agents are registered and harness patching is current.

**When to enable:** Organizations that want stricter control over which agents produce telemetry, for compliance or cost control.

## Trace Privacy {#trace-privacy}

Restricts trace visibility by user.

| Value | Effect |
|-------|--------|
| `false` (default) | Admins can inspect traces across the organization according to their role |
| `true` | Users and admins see only their own traces. Super admins retain full visibility |

**When to enable:** Organizations that want trace viewers scoped to each user's own activity while preserving super-admin access for incident response.
