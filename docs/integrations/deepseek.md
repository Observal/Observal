<!-- SPDX-FileCopyrightText: 2026 SrihariLegend <sriharilegend23@gmail.com> -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# DeepSeek Harness

Use `deepseek` as the Observal harness name. This integration targets the `dsh` profile launcher and session format v4.

## Components

- **MCP servers and sandboxes:** native `@deepseek-ai/dsh-mcp-client` plugin entries in the user-level `cordis.patch.yml`. Supported transports are stdio and Streamable HTTP, not legacy SSE.
- **Skills:** `.dsh/skills/<name>/SKILL.md` in a project, or `$DSH_HOME/skills/<name>/SKILL.md` for the user. DeepSeek also discovers `.agents/skills` roots and flat Markdown skills. Skill frontmatter requires `name` and `description`.
- **Agent instructions:** a native skill named `observal-<agent-name>`, not a replacement for the project's `AGENTS.md` or a made-up agent file format. Ask DeepSeek to use this skill explicitly; pulling does not select an agent or model.
- **Sessions:** Observal installs its own dependency-free Cordis plugin at `$DSH_HOME/observal/collector.mjs`, activated by the user-level patch. It observes native session events; it does not use command hooks for telemetry.
- **Optional hook components:** a JSON command-hook configuration activated by DeepSeek's `@deepseek-ai/dsh-hooks-claude-code` only when the pulled agent includes command-hook components. The bridge supports `PreToolUse`, `PostToolUse`, `Stop`, `SessionStart`, `UserPromptSubmit`, and `SubagentStop`.

`DSH_HOME` defaults to `~/.dsh`. Plugin, MCP, and optional hook activation are user-level even when skills are project-local. DeepSeek does not automatically load a project MCP file: its project overlays require an explicit `dsh --patch <file>`. Observal does not modify profile launch commands or enable headless delegation for this integration.

## Usage

```sh
observal agent pull <namespace/agent> --harness deepseek --scope user
observal scan --harness deepseek
observal doctor patch --harness deepseek
observal reconcile --harness deepseek --dry-run
```

Restart DeepSeek after installing the plugin. `doctor patch` also removes obsolete Observal telemetry commands from an earlier DeepSeek hook installation while preserving unrelated hook commands. The local plugin is bundled with the Observal CLI: **users do not clone, build, or modify DeepSeek**. MCP and optional command-hook components use DeepSeek's own packages, when needed.

Pull and doctor preserve foreign patch text, comments, and `!!js` expressions. Ambiguous patch structures fail rather than being overwritten. Standalone MCP installation returns a patch snippet to merge; do not redirect it onto an existing `cordis.patch.yml`. Hook component scripts live under `$DSH_HOME/observal/scripts`.

## Sessions

Default logs are stored at:

```text
$DSH_HOME/sessions/--<normalized-cwd>--/<encoded-session-id>/session.v4.jsonl.zstd
```

Uncompressed `session.v4.jsonl` logs are also supported. The CLI transports raw records through Observal's existing outbox and checkpoint protocol; the server interprets DeepSeek messages, reasoning, tools, usage, and lifecycle events. No MCP telemetry wrappers or OTLP configuration are installed.

DeepSeek's `session/event` notification precedes disk persistence. On each `turn/end`, Observal's **in-process** plugin awaits `sessions.flush(session)` before launching its host-side Python collector. The collector locates the physical v4 log by session identity and uses Observal's existing outbox, checkpoint, and ingestion pipeline. It does not run inside DeepSeek's tool-hook sandbox. On startup it also retries sessions older than two minutes; use `observal reconcile --harness deepseek` to recover immediately after a crash or outage. Abrupt process termination before the flush/collector finishes cannot guarantee immediate delivery.

This distinction was measured against a real `dsh headless` process: the host could see the v4 log before `UserPromptSubmit`, while an isolated shell hook could not. After installing the native plugin, a headless session appeared on an authenticated Observal server **without manual reconciliation**. Resuming the session appended records without duplicates, and a second reconciliation was a no-op.

Historical and future session-format generations are not treated as v4. Run a compatible DeepSeek version to migrate historical sessions before reconciling them; retained generations must not be uploaded as duplicate sessions.

## Native configuration reference

DeepSeek uses YAML patch sequences rather than an `mcpServers` object:

```yaml
- insert:
    - id: example-mcp
      name: '@deepseek-ai/dsh-mcp-client'
      config:
        serverName: example
        transport: stdio
        command: example-mcp-server
        args: []
```

The home-level patch is `$DSH_HOME/cordis.patch.yml`; per-profile patches are `$DSH_HOME/profiles/<profile>/cordis.patch.yml`. Observal's collector is inserted by its absolute local file path with the current CLI interpreter and runtime `DSH_HOME` as plugin config. Scanning is read-only and must not execute configuration expressions such as `!!js`.
