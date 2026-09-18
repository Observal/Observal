<!-- SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com> -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Discovery

## Contents

- When to search
- Search
- Inspect
- Use
- Save a working session as an Agent
- Interpreting fields

## When to search

Search whenever the task could plausibly be covered by something the organization has already approved: reviews, test generation, documentation, querying a system, running code safely, connecting to a service. Search once, act on the result, and do not search again for the same need in the same session.

Do not search for trivial edits the user described precisely, or when the user explicitly asked for a from-scratch solution.

## Search

```bash
observal discover search 'review a pull request for authentication bugs' --output json
observal discover search 'query postgres' --type mcp --output json
observal discover search 'generate playwright tests' --harness pi --output json
observal discover search 'release notes' --include-unapproved --output json   # your own drafts too
```

Pass the task as one shell-escaped argument (single-quote it and escape any embedded `'` as `'\''`); the words are user text, not shell syntax. `--type` accepts `agent`, `mcp`, `skill`, `hook`, `prompt`, `sandbox`. `--harness` restricts to resources that list that harness. Results are `results[]`, ranked by `score` (relevance only, 0-100), each with `matchedOn` explaining the match. An empty `results` is a successful answer: nothing matched.

Retry once with fewer or different words before concluding nothing exists.

## Inspect

```bash
observal discover inspect urn:air:observal.acme.com:skill:5f2c... --output json
```

Returns the complete entry: `description`, `capabilities`, `representativeQueries` (what it is good for), `obs:supportedHarnesses`, `obs:lifecycle`, `obs:activatable`, `url` (the exact versioned artifact), `obs:artifactDigest`.

## Use

```bash
observal discover use urn:air:observal.acme.com:skill:5f2c... --output json
observal discover use urn:air:observal.acme.com:mcp:9a1b... --harness kiro --output json
```

- Skills and prompts (`obs:availability: now`): the response has `activated: true`, `mode: context`, and `content` holding the exact approved version. Read `content` and follow it for the current task. `truncated: true` means the artifact was cut at `--max-chars`; fetch `artifact_url` only if the remainder is needed.
- MCP servers, agents, sandboxes (`next-session`) and hooks (`explicit-install`): the response has `activated: false` and `next_step`, the existing install command. It confirms before writing harness config and takes effect after a restart. Run it only with the user's agreement, then tell the user a restart is needed.
- `--harness` is detected from `OBSERVAL_HARNESS` or the single installed harness; pass it explicitly when several harnesses are installed.
- Unapproved resources are refused unless `--yes` is given; use that only for the user's own drafts and say so.

Every `use` is recorded in `~/.observal/capability_lock.jsonl` so the session shows which resources it relied on. Nothing secret is written there.

## Save a working session as an Agent

When a combination of resources worked, offer to save it:

```bash
observal agent init --from-capabilities --name pr-review-flow --dir ./pr-review-flow --output json
```

This pre-fills `components` from everything used in the current directory in the last 24 hours (`--since 2h`, `--since 3d` to change). Agents cannot nest other agents; a pulled agent is reported under `skipped_agents`. Continue with the `observal-agents` skill to review, build, and publish.

## Interpreting fields

| Field | Meaning |
| --- | --- |
| `score` | Relevance to the query only. Not approval, not trust. |
| `obs:approval` / `obs:lifecycle` | `approved`, `pending`, `rejected`, `archived`, `draft`. Only `approved` loads without `--yes`. |
| `obs:availability` | `now`, `next-session`, `explicit-install`, `not-approved`, `archived`, `unsupported-in-harness`. |
| `obs:supportedHarnesses` | Harnesses the publisher declared. Empty means unrestricted. |
| `obs:nativeRef` | `namespace/slug@version`, usable with `observal registry ... show` and `observal agent pull`. |
| `obs:artifactDigest` | SHA-256 of the exact artifact bytes; recorded in the capability lock. |
| `matchedOn` | The query words that matched, for explaining the choice to the user. |
