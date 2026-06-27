# Adding a New IDE to Observal

Observal currently supports Cursor, Kiro, VS Code, Windsurf, Claude Code, and Gemini CLI. When you add a new IDE, you need to touch **6 files** in a specific order. This guide walks through each one.

> **Before you start:** Fork the repo, run `make hooks` to install pre-commit hooks, and create a branch:
> ```bash
> git checkout -b feature/add-<ide-name>-support
> ```

---

## The 7 files you need to touch

### 1. `observal_cli/cmd_scan.py` — teach `observal scan` to detect the IDE

`observal scan` auto-detects MCP servers from IDE config files. You need to add your IDE's config file path and the JSON key that holds MCP server definitions.

**What to look for:** Find the section that handles Cursor, Kiro, VS Code, Windsurf, Claude Code, and Gemini CLI. Add a new entry following the same pattern — the config file location on disk, and the key path inside that file where MCP servers are listed.

**Why this matters:** Without this, `observal scan` won't find MCP servers that users have set up in your IDE.

---

### 2. `observal-server/services/config_generator.py` — generate install snippets for the IDE

When a user runs `observal registry mcp install <name> --ide <your-ide>`, this service generates the config snippet they need to paste into their IDE.

**What to look for:** Find where Cursor, Kiro, and Gemini CLI snippets are generated. Each IDE has its own config format (JSON, YAML, TOML, etc.) and its own file path. Add a new branch that:
- Wraps the MCP command with `observal-shim` (for stdio transport) or `observal-proxy` (for HTTP transport)
- Outputs the snippet in the format your IDE expects

**Why this matters:** This is how users actually get telemetry working — it generates the exact config block they need to paste in.

---

### 3. `observal-server/services/agent_config_generator.py` — generate bundled agent configs

When a user runs `observal pull <agent> --ide <your-ide>`, this service generates 
the full bundled agent config (rules file + MCP configs) for the IDE. It injects 
the `OBSERVAL_AGENT_ID` env var into the generated config.

**What to look for:** Find where other IDEs generate their agent config format. 
Add a branch that outputs the rules/config file format your IDE expects.

**If your IDE doesn't support agent bundles:** Add a branch that returns a clear error.

**Why this matters:** Without this, `observal pull` for agents won't work for your IDE.

---

### 4. `observal-server/services/hook_config_generator.py` — generate hook configs for the IDE

Hooks are lifecycle events (pre/post tool call, session start/end). Each IDE registers hooks differently. This file currently supports Claude Code, Kiro, and Cursor.

**What to look for:** Find where IDE-specific hook configs are generated. Add a new branch for your IDE that outputs its hook registration format.

**If your IDE doesn't support hooks:** Add a branch that returns `None` or raises a clear, descriptive error so users get a helpful message instead of a crash.

**Why this matters:** Without this, hook telemetry won't work for users on your IDE.

---

### 5. `observal-server/api/routes/` — add the IDE to any validation lists

Some API routes validate the `--ide` parameter against a fixed list of accepted values. You need to find every place that does this and add your IDE's identifier.

**How to find them — run this from the repo root:**
```bash
grep -r "cursor" observal-server/api/routes/
grep -r "gemini-cli" observal-server/api/routes/
```
Any file that shows up needs your IDE added in the same spot.

**Why this matters:** If the API only accepts a hardcoded list of IDE names, requests with your IDE will be rejected with a validation error even if all the other code is correct.

---

### 6. `observal_cli/cmd_scan.py` *(second pass)* — add the `--ide` flag value

The `--ide` flag in `observal scan` and `observal registry <type> install` accepts a fixed set of valid values. Your IDE's identifier needs to be in that set.

**What to look for:** Find the Typer enum or list that defines valid `--ide` choices. Add your IDE's identifier. Use lowercase with hyphens for multi-word names (e.g. `gemini-cli`, not `GeminiCLI`).

**Why this matters:** Without this, `--ide your-ide` will fail immediately at the CLI level with an invalid option error, before any of your other code even runs.

---

### 7. `README.md` — add the IDE to the supported IDEs list

The README mentions supported IDEs in the intro paragraph. Find the sentence:

> "**Supported tools:** Claude Code, Codex CLI, Gemini CLI, and Kiro CLI are fully supported. Cursor and VS Code have MCP/rules file support."

Add your IDE to this list.

**Why this matters:** This is the first thing users and contributors see. If it's not in the README, people don't know Observal supports it.

---

## Tests

All tests live in `tests/` and run without Docker:

```bash
make test        # quick
make test-v      # verbose
```

Add tests covering:
- `observal scan` correctly detects MCP servers from your IDE's config format
- `config_generator.py` produces a valid snippet for your IDE (wrapping with `observal-shim`)
- `hook_config_generator.py` produces valid output, or correctly returns `None` if unsupported
- The `--ide` flag accepts your IDE's identifier without error

---

## Quick reference

| # | File | What you're doing |
|---|------|-------------------|
| 1 | `observal_cli/cmd_scan.py` | Add config file path + MCP key for auto-detection |
| 2 | `observal-server/services/config_generator.py` | Add install snippet generator |
| 3 | `observal-server/services/agent_config_generator.py` | Add agent configuration generator |
| 4 | `observal-server/services/hook_config_generator.py` | Add hook config generator |
| 5 | `observal-server/api/routes/` | Add IDE name to validation lists |
| 6 | `observal_cli/cmd_scan.py` | Add IDE to `--ide` flag's valid values |
| 7 | `README.md` | Add IDE to supported IDEs list |

---

## Reference examples

**Gemini CLI** — good reference for a CLI-based IDE (non-GUI, different config format)
**Cursor** — good reference for a desktop IDE with full hook support

Search for either to find every location your IDE also needs to appear:

```bash
grep -r "gemini-cli" observal_cli/ observal-server/ README.md
grep -r "cursor" observal_cli/ observal-server/ README.md
```

---

## Before opening a PR

- [ ] All 6 files updated
- [ ] `make test` passes
- [ ] `make lint` passes
- [ ] `observal scan --ide <your-ide>` correctly detects MCP servers
- [ ] `observal registry mcp install <name> --ide <your-ide>` generates a valid config snippet
- [ ] `CHANGELOG.md` updated under `[Unreleased] → Added`
- [ ] PR description includes `Closes #<issue-number>`

---

## Common mistakes

**Inconsistent IDE identifier** — Use the exact same string in every file (CLI flag, config generator, hook generator, route validation, README). A single mismatch causes hard-to-debug silent failures.

**Skipping the hook generator** — Even if your IDE doesn't support hooks, you still need to add a branch in `hook_config_generator.py`. Without it, any code path that touches hooks will throw an unhandled exception instead of a helpful message.

**Missing route validation** — The API may validate IDE names in places that aren't obvious. Always grep for existing IDE names across `observal-server/api/routes/` before assuming you're done.

**Not preserving the config backup** — When `observal scan` rewrites a user's IDE config, it automatically creates a timestamped `.bak` file. Don't remove or bypass this — it's a core safety guarantee users rely on.
