<!-- SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com> -->
<!-- SPDX-License-Identifier: AGPL-3.0-only -->

# observal registry models list

Display the model catalog. Lists known AI models with their provider, display name, supported IDEs, and release date.

## Synopsis

```bash
observal registry models list [--ide <ide>] [--output <format>] [--refresh]
```

## Options

| Option | Description |
| --- | --- |
| `--ide <ide>` | Filter to models supported by a specific IDE (e.g. `claude-code`, `cursor`, `kiro`). |
| `--output, -o <format>` | Output format: `table` (default), `json`, or `plain`. |
| `--refresh` | Bypass the local 1-hour file cache and re-fetch from the server. |

## Data sources

The command resolves model data using a layered fallback strategy:

1. **File cache** (1-hour TTL): fastest, used when fresh.
2. **Server API** (`GET /api/v1/models`): fetched when cache is stale or `--refresh` is passed.
3. **Stale file cache**: used when the server is unreachable.
4. **Vendored offline mirror**: built-in snapshot used as a last resort.

The output footer shows which source was used and whether the data is degraded (i.e. served from a snapshot rather than live data).

## What it shows

Each row in the table includes:

| Column | Description |
| --- | --- |
| `model_id` | Canonical model identifier. Deprecated models are tagged. |
| `provider` | Model provider (e.g. Anthropic, OpenAI, Google). |
| `display` | Human-readable model name. |
| `ides` | Comma-separated list of IDEs that support this model. |
| `released` | Release date of the model. |

## Examples

```bash
# List all models in a table
observal registry models list

# Filter to models available in Claude Code
observal registry models list --ide claude-code

# JSON output for scripting
observal registry models list --output json

# Force a fresh fetch from the server
observal registry models list --refresh

# Plain tab-separated output filtered by IDE
observal registry models list --ide cursor -o plain
```
