# observal use / observal profile

Snapshot-style profile management for IDE configs. Swap between configs from a single command without manually copying files.

## Commands

| Command | Description |
| --- | --- |
| [`observal use`](#observal-use) | Switch to a git-hosted or local profile |
| [`observal profile`](#observal-profile) | Show the active profile and backup info |

Unlike `observal pull` (installs one agent), these work at **config-level** — your whole IDE setup.

---

## `observal use`

Switch the current IDE configs to a profile.

### Synopsis

```bash
observal use <git-url|path>
```

Accepts either:

* A git URL — `observal use https://github.com/your-org/your-profile.git`
* A local path — `observal use ./profiles/work`

### What it does

1. Backs up your current IDE configs to a timestamped location.
2. Pulls the profile contents (clones or copies).
3. Writes the profile's files to the appropriate IDE paths.
4. Records what it did in `~/.observal/profile.json`.

A profile is a directory with IDE-flavored subdirectories:

```
your-profile/
├── claude-code/
│   ├── settings.json
│   └── agents/*.json
├── kiro/
│   ├── settings/mcp.json
│   └── steering/*.md
└── cursor/
    └── mcp.json
```

Only the IDEs present in the profile are touched. Others are left alone.

### Example

```bash
observal use https://github.com/acme-team/shared-profile.git
```

Output:

```
Cloning acme-team/shared-profile...
Backing up current configs:
  ~/.claude/settings.json → .observal/backups/profile-before-20260421_143000/claude-code/settings.json
  .kiro/settings/mcp.json → .observal/backups/profile-before-20260421_143000/kiro/settings/mcp.json

Applying profile:
  ✓ Claude Code: 4 file(s)
  ✓ Kiro: 2 file(s)

Profile active: acme-team/shared-profile@main (commit a1b2c3d)
```

---

## `observal profile`

Print the active profile and where your pre-switch backup lives.

```bash
observal profile
# Active profile: acme-team/shared-profile@main (a1b2c3d)
# Applied:        2026-04-21 14:30:00
# Backup:         ~/.observal/backups/profile-before-20260421_143000/
```

## Rollback

Every `use` leaves a timestamped backup. Restore manually:

```bash
cp -r ~/.observal/backups/profile-before-20260421_143000/claude-code/* ~/.claude/
cp -r ~/.observal/backups/profile-before-20260421_143000/kiro/* .kiro/
```

## When to use this vs `pull`

| Situation | Use |
| --- | --- |
| Install one published agent into my current setup | [`observal pull`](pull.md) |
| Switch my whole setup to a known-good team config | `observal use` |
| Onboard a new machine to match your team's baseline | `observal use` |
| Swap between "work setup" and "personal setup" | `observal use` |

## Related

* [`observal pull`](pull.md) — the single-agent equivalent
* [Use Cases → Share agent configs](../use-cases/share-agent-configs.md)
