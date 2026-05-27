<!--
SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
SPDX-License-Identifier: AGPL-3.0-only
-->

# observal-pi

Session telemetry extension for [Pi](https://pi.dev) that pushes conversation traces to your [Observal](https://obs-sync.dev) server.

## Install

```bash
pi install npm:observal-pi
```

## Prerequisites

1. An Observal account - run `observal auth login` to authenticate
2. Pi installed (`>=0.74.0`)

## What it does

- **Incremental push:** After each user prompt (`agent_end`), reads new JSONL lines from the session file and POSTs them to your Observal server
- **Final push:** On session exit, sends remaining lines with integrity metadata
- **Crash recovery:** On startup, detects sessions that weren't cleanly finalized and pushes their remaining data
- **Status indicator:** Shows `● observal` in the footer with line count

## Commands

| Command | Description |
|---------|-------------|
| `/obs-sync` | Show sync status (lines pushed, server URL) |
| `/obs-sync flush` | Force push pending lines now |
| `/obs-sync config` | Show config file path and server URL |

## Design

- **Zero dependencies** - only `node:*` built-ins
- **Fail-open** - never throws, never crashes pi. If the server is unreachable, pi continues normally
- **5s timeout** - all HTTP calls abort after 5 seconds
- **Chunked uploads** - batches of 500 lines max per request
- **Dedup-safe** - server deduplicates by `(session_id, line_offset, line_hash)`

## Configuration

The extension reads credentials from `~/.observal/config.json` (written by `observal auth login`):

```json
{
  "server_url": "https://your-server.observal.dev",
  "access_token": "..."
}
```

Sync state is tracked in `~/.observal/sync_state.json` (per-session byte offsets).

## License

AGPL-3.0-only - see [LICENSE](./LICENSE)
