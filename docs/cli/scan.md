<!-- SPDX-FileCopyrightText: 2026 Apoorv Garg <apoorvgarg.21@gmail.com> -->
<!-- SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com> -->
<!-- SPDX-FileCopyrightText: 2026 tsitu0 <tomsitu0102@gmail.com> -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# observal scan

Inspect agents, MCP servers, skills, hooks, and telemetry configuration across local harnesses. The default scan is read-only. Add `--discover` to correlate richer harness evidence with bounded package-manager metadata, local installation tracking, and exact Registry identities.

An interactive `--discover` run can offer to create portable Registry **drafts**. It never publishes or submits those drafts for review. Scanning never modifies harness files or the installation lockfile.

To install session telemetry hooks, use [`observal doctor patch`](doctor.md). MCP commands and URLs are never rewritten by `scan`.

## Synopsis

```bash
observal scan [--harness <harness>] [--discover] [--output table|json]
```

## Options

| Option | Description |
| --- | --- |
| `--harness <harness>`, `-i` | Scope harness evidence to one registered harness. Package evidence may enrich matching harness candidates, but unrelated package-only candidates are suppressed. |
| `--discover` | Enable bounded rich discovery, package evidence, local tracking, exact Registry classification, and—only in an interactive table session—optional draft registration. |
| `--output table|json`, `-o` | Select human-readable table output or versioned JSON. JSON never prompts or creates drafts. |

With no flags, `observal scan` auto-detects registered harnesses and preserves the established read-only inventory output.

## Default inventory

The default command scans harness home directories and the current project independently. It reports discovered agents, MCP servers, skills, hooks, and installed session telemetry hooks.

```bash
observal scan
observal scan --harness claude-code
observal scan --output json
```

Default JSON preserves these top-level keys:

```json
{
  "harnesses": [],
  "mcps": [],
  "skills": [],
  "hooks": [],
  "agents": []
}
```

The default scan does not inspect npm, pipx, or uv metadata, does not perform the authenticated exact-matching workflow, and never prompts.

Compatibility fixes intentionally included in this implementation are:

- the current project is scanned even when no matching harness home marker exists;
- every component type found in secondary scopes is retained; and
- same-name MCPs with behaviorally different launches remain distinct.

The default JSON keys and component record shapes remain unchanged.

## Rich discovery

```bash
# Interactive table workflow; eligible candidates may be offered for registration
observal scan --discover

# Machine-readable and always non-mutating
observal scan --discover --output json

# Restrict harness evidence while allowing relevant package enrichment
observal scan --harness kiro --discover --output json
```

Discovery adds:

- bounded rich evidence from Claude Code, Cursor, Pi, and Kiro adapters;
- bounded top-level npm, pipx, and installed uv tool metadata;
- optional local lockfile identity and launch-fingerprint matching;
- authenticated owned-state and exact canonical Registry resolution;
- typed candidate provenance, confidence, tracking, support, Registry, and registration states; and
- non-fatal, redacted diagnostics for partial provider or adapter failures.

Package discovery does not install, import, or execute discovered packages. uv cache metadata can only enrich an already-known package and never creates a cache-only registration candidate.

Discovery JSON uses `discovery_schema_version: 1` and retains the default component arrays while adding `candidates` and `diagnostics`. Paths and launch data are normalized and secret values are removed before output or fingerprinting.

## Interactive draft registration

Draft registration is available only when all of the following are true:

1. `--discover` is enabled;
2. output is the default table format;
3. standard input is an interactive terminal;
4. authentication, owned-state loading, and exact canonical Registry lookup succeed; and
5. the candidate is locally untracked, unambiguous, supported, complete, and portable.

For each eligible candidate, Observal shows sanitized evidence and its proposed `namespace/slug` target. Creation requires three explicit, default-no confirmations:

1. create this draft;
2. confirm ownership or authorization for the component and included content; and
3. approve the final sanitized draft summary.

The workflow creates drafts through the same validated MCP, skill, hook, and agent draft endpoints used by their dedicated commands. It does not publish, submit for review, install, or add drafts to the installation lockfile.

Existing owned drafts—including pending or rejected items—suppress duplicate creation. If a POST has an uncertain outcome or races with another creator, Observal performs bounded GET-only reconciliation and never automatically repeats the POST. An unreconciled requested mutation is reported as `failed` or `uncertain`; rerun discovery before attempting it again.

### Guaranteed non-mutating modes

These forms never prompt and never create Registry drafts:

```bash
observal scan
observal scan --discover --output json
observal scan --discover </dev/null
```

Piped or otherwise non-interactive invocations are treated the same as `</dev/null`.

## Discovery result states

Candidate state is deliberately split rather than represented by one status:

- **Tracking**: whether an exact or compatible local installation-lock identity exists.
- **Registry**: owned exact match, accessible exact match, exact miss, ambiguous, unavailable, or not checked.
- **Support/readiness**: whether the evidence has a supported, complete portable representation.
- **Registration**: already exists, eligible, incomplete, not applicable, or otherwise blocked.

A package name is correlation evidence only. It cannot collapse behaviorally different launches or independently prove local or Registry identity.

Canonical launch fingerprints are recorded only when an install path has the exact structured launch that discovery will later observe. Agent pulls can record fingerprints for portable nested MCP definitions emitted in the installed configuration. Agent, skill, and hook entries have no compatible MCP launch identity and therefore omit this field. The standalone `registry mcp install` command currently generates a configuration snippet for the user to apply rather than writing it itself, so it also does not claim an installed lockfile identity. Unsupported, local-path, ambiguous, or otherwise non-canonical launches omit the fingerprint and continue to use stronger Registry identities or legacy matching tiers.

## Security boundaries

- Environment-variable and header names may be retained; their values are removed.
- URL credentials and sensitive query values are removed.
- Nested hook configuration and diagnostic messages are redacted.
- Local paths are represented as project-relative, home-relative, or opaque external paths.
- Filesystem traversal, metadata files, command output, item counts, and provider runtimes are bounded.
- Symlinks escaping approved roots are rejected.
- Registration accepts portable Registry content, not arbitrary local executable or file paths.

## Exit codes

| Code | Meaning |
| --- | --- |
| 0 | Scan completed with findings, or JSON emitted a valid result (including an empty result). Declined and skipped candidates are not failures. |
| 1 | Invalid harness, no table-mode findings, or a requested interactive registration failed or remained uncertain. |

Provider and adapter diagnostics do not fail an otherwise successful local scan. Registry or authentication uncertainty blocks registration rather than being treated as proof that a Registry item is absent.

## What to do next

To instrument detected harnesses:

```bash
# Preview changes without writing anything
observal doctor patch --all-harnesses --dry-run

# Install session telemetry hooks across all harnesses
observal doctor patch --all-harnesses

# Or target a specific harness
observal doctor patch --harness kiro
```

To inspect or edit a draft created by discovery, use the matching Registry or agent commands before submitting it for review.

## Related

- [`observal doctor patch`](doctor.md): instrument harnesses with Observal-managed telemetry
- [`observal agent pull`](pull.md): install a published agent and its components
- [`observal registry`](registry.md): inspect, edit, and submit component drafts
- [`observal agent`](agent.md): inspect, edit, and publish agent definitions
- [Use Cases — Observe MCP traffic](../use-cases/observe-mcp-traffic.md): narrative walkthrough
