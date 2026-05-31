<!-- SPDX-FileCopyrightText: 2026 Nithin Bhargav <gaddamnithinbhargav@gmail.com> -->
<!-- SPDX-License-Identifier: AGPL-3.0-only -->

# observal reconcile

Crash recovery scanner that finds stale session JSONL files whose `Stop` hook never fired and pushes their unsynced tail to the server so no turns are lost.

---

## What it does

Every live session is tracked in `~/.observal/sync_state.json`. Each entry records:

| Field | Description |
| --- | --- |
| `offset` | Byte position up to which lines have already been pushed |
| `line_count` | Number of lines sent so far |
| `finalized` | Set to `true` only when the `Stop` hook fires cleanly |

When the `Stop` hook is missed — because the IDE was force-quit, the machine shut down mid-session, or a crash interrupted the normal shutdown — `finalized` stays `false` and the JSONL file on disk grows beyond `offset`. The reconciler finds exactly these sessions, pushes the remaining bytes, then marks them `finalized` so they are never recovered again.

### Staleness criteria

A session is considered stale and eligible for recovery when **all** of the following are true:

| Condition | Detail |
| --- | --- |
| `finalized` is absent or `false` | The `Stop` hook never completed |
| File size > cursor offset | There are unsynced bytes on disk |
| File mtime is ≥ 2 minutes old | Avoids touching an actively running session |
| File mtime is ≤ 7 days old | Ignores ancient orphaned files |

### Session locations scanned

| IDE | Path |
| --- | --- |
| Claude Code (top-level) | `~/.claude/projects/<project>/<session_id>.jsonl` |
| Claude Code (subagent) | `~/.claude/projects/<project>/<session_id>/subagents/<agent_id>.jsonl` |
| Kiro | `~/.kiro/sessions/cli/<session_id>.jsonl` |

---

## When it runs automatically

`session_push.py` spawns the reconciler as a detached background subprocess after every non-`Stop` hook event (for example, `UserPromptSubmit`):

1. You submit a new prompt in your IDE.
2. The `UserPromptSubmit` hook fires.
3. `session_push.py` handles the current event, then immediately spawns the reconciler in the background — it does **not** block the hook.
4. The reconciler silently scans for stale sessions and pushes any it finds.

You do not need to do anything to enable this. It runs automatically as part of normal Observal operation.

---

## Manual invocation

Run the reconciler at any time from your terminal:

```bash
python -m observal_cli.cmd_reconcile
```

The command exits silently on success. All activity is written to `~/.observal/sync.log`.

**When to run manually:**

- After a system crash or hard reboot, before starting your IDE again.
- If you suspect a session was not synced after an unexpected IDE close.
- During troubleshooting, to force a recovery pass and observe its log output.

**Example — trigger a recovery pass and inspect the results:**

```bash
python -m observal_cli.cmd_reconcile
tail -n 20 ~/.observal/sync.log
```

---

## Logs

All diagnostic output goes to:

```
~/.observal/sync.log
```

Example log output:

```
2026-05-10 14:03:21 | DEBUG | find_stale_sessions: home=/Users/alice
2026-05-10 14:03:21 | INFO  | Recovering stale session abc123 (2048 unsynced bytes)
2026-05-10 14:03:22 | INFO  | Session abc123 recovered and finalized
```

| Message | Meaning |
| --- | --- |
| `find_stale_sessions: home=…` | Scan started |
| `Recovering stale session <id>` | A stale session was found; push is being attempted |
| `Session <id> recovered and finalized` | Push succeeded; session is now marked `finalized` |
| No output | No stale sessions found, or all sessions already finalized |

---

## State file reference

`~/.observal/sync_state.json` is the source of truth for cursor positions. Inspect it directly to understand what the reconciler sees:

```bash
cat ~/.observal/sync_state.json | python -m json.tool
```

Example:

```json
{
  "abc123": {
    "offset": 40960,
    "line_count": 87,
    "finalized": true
  },
  "def456": {
    "offset": 8192,
    "line_count": 12,
    "finalized": false
  }
}
```

`def456` above is a candidate for recovery on the next reconciler run, assuming its JSONL file has grown beyond byte `8192` and meets the age criteria.

---

## Troubleshooting

| Symptom | What to check |
| --- | --- |
| Sessions missing from the server after a crash | Run `python -m observal_cli.cmd_reconcile` manually and inspect `~/.observal/sync.log` |
| Log shows repeated failures for the same session | Verify server URL and API key; check network connectivity |
| `sync_state.json` does not exist | Observal has not run a push yet; no sessions to recover |
| Reconciler exits with no log output | No stale sessions found — normal if all sessions finished cleanly |

---

## Related

- [`observal ops`](ops.md) — view traces and session data on the server
- [Environment variables](../reference/environment-variables.md) — `OBSERVAL_SERVER_URL`, `OBSERVAL_API_KEY`
- [Hooks specification](../reference/hooks-spec.md) — how `Stop` and `UserPromptSubmit` hooks work
