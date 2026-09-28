<!-- SPDX-FileCopyrightText: 2026 Observal contributors -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# DeepSeek Harness

Use `deepseek` as the Observal harness name. This integration targets the `dsh` profile launcher and session format v4.

## Components

- **MCP servers and sandboxes:** native `@deepseek-ai/dsh-mcp-client` plugin entries in the user-level `cordis.patch.yml`. Supported transports are stdio and Streamable HTTP, not legacy SSE.
- **Skills:** `.dsh/skills/<name>/SKILL.md` in a project, or `$DSH_HOME/skills/<name>/SKILL.md` for the user. DeepSeek also discovers `.agents/skills` roots and flat Markdown skills. Skill frontmatter requires `name` and `description`.
- **Agent instructions:** a native skill named `observal-<agent-name>`, not a replacement for the project's `AGENTS.md` or a made-up agent file format. Ask DeepSeek to use this skill explicitly; pulling does not select an agent or model.
- **Hooks:** a JSON command-hook configuration activated by `@deepseek-ai/dsh-hooks-claude-code` in the user patch file. The bridge supports `PreToolUse`, `PostToolUse`, `Stop`, `SessionStart`, `UserPromptSubmit`, and `SubagentStop`.

`DSH_HOME` defaults to `~/.dsh`. MCP and hook activation are user-level even when skills are project-local. DeepSeek does not automatically load a project MCP file: its project overlays require an explicit `dsh --patch <file>`. Observal does not modify profile launch commands or enable headless delegation for this integration.

## Usage

```sh
observal agent pull <namespace/agent> --harness deepseek --scope user
observal scan --harness deepseek
observal doctor patch --harness deepseek
observal reconcile --harness deepseek --dry-run
```

Restart the DeepSeek profile after installing configuration if hot reload is not enabled. Keep the MCP client and Claude hook bridge packages available to the profile's plugin resolver; they are dependencies of the shipped `dsh` CLI.

Pull and doctor preserve foreign patch text, comments, and `!!js` expressions. Ambiguous patch structures fail rather than being overwritten. Standalone MCP installation returns a patch snippet to merge; do not redirect it onto an existing `cordis.patch.yml`. Hook component scripts live under `$DSH_HOME/observal/scripts`, beside the user-level hook configuration.

## Sessions

Default logs are stored at:

```text
$DSH_HOME/sessions/--<normalized-cwd>--/<encoded-session-id>/session.v4.jsonl.zstd
```

Uncompressed `session.v4.jsonl` logs are also supported. The CLI transports raw records through Observal's existing outbox and checkpoint protocol; the server interprets DeepSeek messages, reasoning, tools, usage, and lifecycle events. No MCP telemetry wrappers or OTLP configuration are installed.

The hook bridge supplies a session ID but leaves `transcript_path` empty, so source discovery must locate the corresponding log. A `Stop` hook is a turn boundary, not proof that the session cannot receive more input. Reconciliation covers records missed by hooks.

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

The home-level patch is `$DSH_HOME/cordis.patch.yml`; per-profile patches are `$DSH_HOME/profiles/<profile>/cordis.patch.yml`. Scanning is read-only and must not execute configuration expressions such as `!!js`.
