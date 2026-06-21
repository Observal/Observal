# harness registry audit + cleanup plan

## Context

The current IDE-named registry mixes product-facing terms (`rules`, `feature matrix`, model-selection booleans) with implementation paths. The model picker was tied to `models.dev`; that source is unreliable/removed for our use case, and each harness needs an explicit supported-models collection instead of a boolean-only model field.

Early scan found the current IDE-named registry duplicated in:

- `observal-server/schemas/harness_registry.py`
- `observal_cli/harness_registry.py`

These should be hard-renamed to harness registries. No compatibility import shims.

The server exposes a reduced harness payload from `observal-server/api/routes/config.py`; the web client consumes it via `web/src/lib/api.ts` and `web/src/components/builder/model-picker.tsx`.

Registered harnesses today: Cursor, Kiro, Claude Code, Codex, Copilot, Copilot CLI, OpenCode, Antigravity, Pi.

## Approach

Do the smallest durable fix:

1. Audit each registered harness against official docs / public examples for:
   - agent/instruction file paths and formats
   - hooks support, hook scope, and event naming
   - skills location/format, including Agent Skills conventions
   - sandbox integration expectations
   - MCP config paths, scope, and object shape
   - supported model selection semantics
2. Rename registry/docs vocabulary where it removes confusion:
   - Product term: **harness**. These are not all IDEs: some are CLIs, browser/cloud agents, app integrations, or editor plugins. Pi and Antigravity explicitly use “agent harness” language, and Copilot/Codex/Claude docs describe CLI/cloud/editor surfaces around the same agent runtime. Use “harness registry” in docs/UI.
   - Code/API migration: hard rename to `HARNESS_REGISTRY` / `harness_registry`; remove `HARNESS_REGISTRY`, `/api/config/harnesses`, and `--harness`. Add `/api/config/harnesses` and require `--harness`.
   - `features` / “feature matrix” → `capabilities` / “Harness capabilities”
   - `agent_profile` → split into `agent_profile` for selectable/custom agents and `guidance_files` for always/conditionally loaded context guidance (`AGENTS.md`, `CLAUDE.md`, Cursor rules, Kiro steering, Copilot instructions)
   - Observal should **manage/write `agent_profile` files**, not `guidance_files`, except Pi where `AGENTS.md` is the harness-level agent prompt/config we intentionally write.
   - For all other harnesses, `guidance_files` are read-only layer inputs: scan/capture/attribute them as user/project layer context, but do not create or overwrite them during agent pull.
   - Hard migrate persisted/API names (`ide`, `harness_capability`, `models_by_harness`) to harness names with a data migration and smoke test, not read aliases.
3. Add registry-owned supported model metadata and stop treating `models.dev` as the source of truth for IDE support.
4. Hide `models.dev` from user-facing flows. `observal registry models` should read the new registry-backed model data instead.
5. Update server, CLI, web, tests, and docs from the registry shape rather than adding one-off harness conditionals.

## Files to modify

Code paths:

- `packages/observal-shared/observal_shared/harness_models/*.json` (new shared model data; packaged for CLI and server)
- `packages/observal-shared/observal_shared/harness_models.py` (new tiny loader/validator)
- `observal-server/schemas/harness_registry.py` (rename from `harness_registry.py`; remove old module)
- `observal_cli/harness_registry.py` (rename from `harness_registry.py`; remove old module)
- `observal-server/api/routes/config.py`
- `observal-server/services/model_resolver.py`
- `observal-server/services/model_catalog.py` (keep only if needed for non-user-facing compatibility; remove `models.dev` wording)
- `observal_cli/model_catalog.py` / `observal_cli/cmd_models.py` (repurpose to registry-backed data, add `--harness` filtering)
- `observal_cli/cmd_pull.py`
- `scripts/refresh_harness_models.py` (new script to refresh vendored harness model JSON from official/static upstream sources)
- `web/src/lib/api.ts`
- `web/src/components/builder/model-picker.tsx`
- `tests/test_constants_sync.py`
- `tests/test_harness_registry.py` (rename from `tests/test_harness_registry.py`)
- `tests/test_model_registry.py`

Docs:

- `docs/adding-a-harness.md` (rename from `docs/adding-a-harness.md` and update all references)
- `docs/reference/config-files.md`
- `docs/cli/models.md`
- `docs/cli/pull.md`
- `observal_cli/skills/observal-agents/SKILL.md`
- `observal_cli/skills/observal/references/commands.md`

## Reuse

Existing reusable pieces found so far:

- Registry-derived helpers in the current `observal-server/schemas/harness_registry.py` and `observal_cli/harness_registry.py` (`get_valid_harnesses`, `get_home_mcp_configs`, model-selection helpers) should move to harness-named helpers.
- Server config endpoint already centralizes the web harness list through the current IDE-named route: `observal-server/api/routes/config.py#get_ides`.
- Web model picker already accepts free-form exact model values: `web/src/components/builder/model-picker.tsx`.
- Constants-sync test already enforces CLI/server registry parity: `tests/test_constants_sync.py`.
- Existing docs already contain a registry entry template: `docs/adding-a-harness.md`; rename it to `docs/adding-a-harness.md`.
- Server adapters are the real generation behavior and expose registry drift. Example: `observal-server/services/harness/cursor.py` writes `agent_file` to `.cursor/agents/{name}.md`, but the registry still says `agent_profile` is `.cursor/rules/{name}.mdc`.
- `observal-server/services/harness/codex.py` already writes an agent profile to `~/.codex/agents/{name}.toml`, not `AGENTS.md`; the registry entry `agent_profile: AGENTS.md` is stale and should become read-only `guidance_files` metadata.
- `observal-server/services/harness/antigravity.py` also writes `agent_file`, not `AGENTS.md`; its registry `agent_profile` is stale guidance metadata.
- Docs drift exists too. Example: `docs/reference/config-files.md` says Claude Code agents are JSON, while `observal-server/services/harness/claude_code.py` generates Markdown with YAML frontmatter under `.claude/agents/{name}.md`.

## Research matrix

| Harness | Agent / context files | Hooks | Skills | Sandbox | MCP | Models |
| --- | --- | --- | --- | --- | --- | --- |
| Cursor | Rules: `.cursor/rules/*.mdc`. Subagents: `.cursor/agents/*.md` project, `~/.cursor/agents/*.md` user. Also loads `.claude/agents` / `.codex/agents` for compatibility. Current registry is stale because it only has `agent_profile`; adapter already writes `agent_file` to `.cursor/agents/{name}.md`. | `.cursor/hooks.json` project and `~/.cursor/hooks.json` user. Events include `sessionStart`, `sessionEnd`, `preToolUse`, `postToolUse`, `beforeSubmitPrompt`, `subagentStart`, `subagentStop`, etc. | Agent Skills standard. Project: `.agents/skills/`, `.cursor/skills/`; user: `~/.agents/skills/`, `~/.cursor/skills/`; also Claude/Codex skill dirs. | Cursor Cloud agents use cloud VMs; local agent uses local workspace. Observal sandbox can remain MCP/tool-level where applicable. | Project `.cursor/mcp.json`, user `~/.cursor/mcp.json`, key `mcpServers`; stdio/HTTP/SSE; variable interpolation. | Cursor docs expose a model table and subagent `model` field. List known Cursor IDs plus `auto`/`inherit`; no `models.dev` dependency. |
| Kiro | Persistent guidance is steering: workspace `.kiro/steering/`, global `~/.kiro/steering/`; also supports `AGENTS.md` in workspace root and `~/.kiro/steering/`. Kiro CLI v3 agent profiles are Markdown with YAML frontmatter in `.kiro/agents/` workspace and `~/.kiro/agents/` user; JSON is only an equivalent generated format. Current registry `.kiro/agents/{name}.json` should move to `.md`. | Kiro CLI v3 uses standalone `.kiro/hooks/<name>.json` files, workspace-wide across agents. Existing embedded hooks in agent configs still work during migration, but new writes should target `.kiro/hooks/`. Triggers include `SessionStart`, `Stop`, `UserPromptSubmit`, `PreToolUse`, `PostToolUse`, `PostFileCreate`, `PostFileSave`, `PostFileDelete`, `PreTaskExec`, `PostTaskExec`, `Manual`. Actions are command or agent prompt. | Agent Skills standard. Workspace `.kiro/skills/`; global `~/.kiro/skills/`; folder with `SKILL.md`. | Local IDE; no separate Observal-specific path needed beyond MCP/tool sandbox wording. | Workspace `.kiro/settings/mcp.json`, user `~/.kiro/settings/mcp.json`, key `mcpServers`; JSON; workspace overrides/merges user. Agent profiles can also embed `mcpServers`. | Kiro docs list Auto, Sonnet 4.0/4.5/4.6, Haiku 4.5, Opus 4.6/4.7/4.8, MiniMax M2.5/M2.1, GLM-5, DeepSeek 3.2, Qwen models. Use curated IDs. |
| Claude Code | Subagents: `.claude/agents/*.md`, `~/.claude/agents/*.md`, Markdown + YAML frontmatter. Context: `CLAUDE.md`, `.claude/CLAUDE.md`, `~/.claude/CLAUDE.md`, local `CLAUDE.local.md`; `AGENTS.md` is not read directly, but can be imported from `CLAUDE.md`. Registry path is OK; docs page saying `.json` is stale. | `hooks` block in `.claude/settings.json`, `~/.claude/settings.json`, `.claude/settings.local.json`; command hooks. Events: `PreToolUse`, `PostToolUse`, `UserPromptSubmit`, `Notification`, `Stop`, `SessionStart`, `SubagentStop`, etc. Subagents also support frontmatter `hooks` scoped to that subagent. | Agent Skills standard plus Claude extensions. Project `.claude/skills/<name>/SKILL.md`; user `~/.claude/skills/<name>/SKILL.md`; plugin/enterprise scopes too. | Claude Code has `isolation: worktree` for subagents and local permission modes; Observal sandbox remains separate MCP/tooling layer if used. | User/local in `~/.claude.json`; project `.mcp.json`; CLI `claude mcp add`; subagents can reference `mcpServers` in frontmatter. Current registry has `mcp_config: None` but `home_mcp_config: ~/.claude.json`; needs explicit project `.mcp.json` behavior if we write files instead of commands. | Accepts `model` in subagent frontmatter. Supports aliases like `sonnet`, `opus`, `haiku`, `inherit`, plus concrete Claude IDs. |
| Codex | `AGENTS.md` layering: global `$CODEX_HOME/AGENTS.md` or `AGENTS.override.md` (default `~/.codex`), project `AGENTS.md` / `AGENTS.override.md` from repo root to cwd. | Lifecycle hooks from `~/.codex/hooks.json`, `~/.codex/config.toml`, `<repo>/.codex/hooks.json`, `<repo>/.codex/config.toml`; project hooks require trusted project. Events configured as `[hooks.<Event>]` or JSON. | Agent Skills standard. Repo `.agents/skills` discovered up tree; user `$HOME/.agents/skills`; admin `/etc/codex/skills`; `SKILL.md` requires `name` and `description`. Current registry `~/.codex/skills` is wrong for official Codex skills. | Built-in OS sandbox/approval system. Config in `config.toml`: `sandbox_mode`, `approval_policy`, `sandbox_workspace_write.network_access`; `.codex` protected paths. | `~/.codex/config.toml` user and `.codex/config.toml` project; `[mcp_servers.<name>]` tables. Current registry TOML key `mcp.servers` is wrong; replace with `[mcp_servers.<name>]` tables. | Default `model = "gpt-5.5"`; supports OpenAI models and custom providers/base URLs. Supported collection should include OpenAI Codex/GPT IDs plus `provider:*`/custom-provider marker. |
| Copilot cloud agent | Repo custom instructions: `.github/copilot-instructions.md`, `.github/instructions/*.instructions.md`, `AGENTS.md` anywhere, root `CLAUDE.md`/`GEMINI.md`. Custom agents: repo `.github/agents/<name>.agent.md`; org/enterprise `.github` or `.github-private` root `agents/`. | `.github/hooks/*.json` repo hooks. Events include `sessionStart`, `sessionEnd`, `userPromptSubmitted`, `preToolUse`, `postToolUse`, `agentStop`, `subagentStop`, `errorOccurred`. Current registry `.github/hooks/{name}.json` is plausible but should glob, not single named file only. | Project skills: `.github/skills/`, `.claude/skills/`, or `.agents/skills/`; personal skills are CLI-local (`~/.copilot/skills` / `~/.agents/skills`). Registry `.github/skills/{name}/SKILL.md` is valid for project. | Cloud agent runs in GitHub Actions-powered ephemeral environment; 59-minute max; local IDE agent mode is local. Observal sandbox docs should not pretend to own Copilot cloud isolation. | GitHub.com repository MCP settings are JSON with `mcpServers` typed into repo settings; VS Code local Copilot uses `.vscode/mcp.json` with `servers`. Registry currently mixes Copilot cloud and VS Code paths; needs split or explicit `ide_variant`. | Users may select model depending on entry point/admin policy; no per-agent persisted model file except custom agent `model` for IDEs. Supported set should mirror GitHub model availability/admin restrictions at a high level, with `auto` fallback. |
| Copilot CLI | Custom agents are Markdown `.agent.md` files. Project: `.github/agents/`; user: `~/.copilot/agents/`. If names conflict, user wins. Custom instructions: `.github/copilot-instructions.md`, `.github/instructions/**/*.instructions.md`, `AGENTS.md`, root `CLAUDE.md`/`GEMINI.md`, local `$HOME/.copilot/copilot-instructions.md`, plus `COPILOT_CUSTOM_INSTRUCTIONS_DIRS`. | Repo `.github/hooks/*.json`; user `~/.copilot/hooks/*.json` or `$COPILOT_HOME/hooks/*.json`; command hooks. | Project skills: `.github/skills`, `.claude/skills`, `.agents/skills`. Personal: `~/.copilot/skills`, `~/.agents/skills`. `SKILL.md` with YAML frontmatter. | Local CLI; BYOK/offline options exist. Cloud/local sandbox docs should be linked but registry does not need sandbox paths. | User config `~/.copilot/mcp-config.json`, key `mcpServers`; `copilot mcp add` writes there. Docs also list user/workspace/plugin sources; project path still not clearly documented for direct file writes. Current registry `.mcp.json` is wrong for CLI user config. | Supports BYOK providers via env: `COPILOT_PROVIDER_TYPE=openai|azure|anthropic`, `COPILOT_PROVIDER_BASE_URL`, `COPILOT_PROVIDER_API_KEY`, `COPILOT_MODEL`; model must support tool calling and streaming. Current boolean-only model selection metadata is wrong for CLI. |
| OpenCode | Config JSON `agent` map in `opencode.json`, or Markdown agents in `.opencode/agents/` project and `~/.config/opencode/agents/` user. Markdown frontmatter + body. Registry matches. | Plugins: `.opencode/plugins/` project, `~/.config/opencode/plugins/` global. Events include `tool.execute.before`, `tool.execute.after`, `session.idle`, message/session/etc. Registry plugin hook direction is right. | Agent Skills are first-class. Project `.opencode/skills/<name>/SKILL.md`; global `~/.config/opencode/skills/<name>/SKILL.md`; also `.agents` and `.claude` compatibility paths. | Local execution/permissions, not a sandbox. | `opencode.json` project and `~/.config/opencode/opencode.json` global; `mcp` object; local `command` is array, env key is `environment`, remote `url`. Registry matches key/path but adapters must normalize env/command. | OpenCode supports AI SDK providers, OpenCode Zen/Go, custom provider/models; model IDs are `provider/model-id`. Use wildcard `provider:*` plus curated Zen examples. |
| Antigravity | Editor/CLI uses `AGENTS.md`; API managed agent can mount `AGENTS.md` and `.agents/skills/`. Current registry project `AGENTS.md`, user `~/.gemini/GEMINI.md` needs CLI/editor distinction; CLI docs reference global `~/.gemini/antigravity-cli`. | CLI plugins can include `hooks.json`; primary settings hooks also supported. Existing Observal spec uses `.agents/hooks.json` / `~/.gemini/config/hooks.json` with flat `PreInvocation`/`Stop` handlers; keep that schema unless upstream docs expose a better primary-settings schema. | CLI workspace `.agents/skills/*.md`; global `~/.gemini/antigravity-cli/skills/*.md`; plugin `skills/`. API also mounts `.agents/skills/`. Current registry user `~/.gemini/config/skills` is stale. | Editor has Local Mode and New Worktree Mode; API managed agent provisions secure Linux sandbox. CLI sandbox docs exist; use product-native sandbox wording. | Editor: `~/.gemini/config/mcp_config.json`. CLI: global `~/.gemini/antigravity-cli/mcp_config.json`, workspace `.agents/mcp_config.json`; key `mcpServers`; remote uses `serverUrl`. Current registry partly matches workspace; user path must split by target variant. | API agent ID `antigravity-preview-05-2026`; editor/CLI reasoning model IDs come from Antigravity model docs plus the observed `/model` menu. |
| Pi | Context: `AGENTS.md` from `~/.pi/agent/`, parent dirs, current dir; `.pi/SYSTEM.md` / `.pi/APPEND_SYSTEM.md` for system prompt. Registry project/user AGENTS paths are OK. | Extensions, not JSON hooks: global `~/.pi/agent/extensions/*.ts`; project `.pi/extensions/*.ts`; event API includes `session_start`, `tool_call`, `session_shutdown`, etc. Current registry `hook_type: extension` is right; replace `hooks` with extension routes. | Agent Skills standard. Global `~/.pi/agent/skills/` and `~/.agents/skills/`; project `.pi/skills/` and `.agents/skills/`; settings `skills` array; folders with `SKILL.md`. Registry project/user `.pi` paths OK but should add `.agents` compatibility. | No built-in sandbox. Docs explicitly say run Pi inside container/VM/OpenShell/Gondolin for isolation. Observal sandbox should be described as optional external containment, not universal. | Via `pi-mcp-extension`: global `~/.pi/agent/mcp.json`, project `.pi/mcp.json`, key `mcpServers`, project overrides global. Registry matches. | Built-in providers plus `~/.pi/agent/models.json` custom providers/models; LiteLLM extension discovers `/model/info` or `/v1/models`. Supported collection should include `litellm:*`, `openai-compatible:*`, built-in provider wildcards, and custom models. |

## Install/write route policy

Observal should route generated files by artifact type, not the old overloaded `agent_profile` key.

| Harness | Observal writes on pull/install | Observal scans only |
| --- | --- | --- |
| Cursor | `agent_profile`: `.cursor/agents/{name}.md` (project), `~/.cursor/agents/{name}.md` only if user-scope is confirmed supported; `mcp`: `.cursor/mcp.json` / `~/.cursor/mcp.json`; `hooks`: `.cursor/hooks.json` / `~/.cursor/hooks.json`; `skills`: `.cursor/skills/{name}/SKILL.md` plus `.agents/skills` compatibility if we choose. | `.cursor/rules/*.mdc`, `AGENTS.md`, `.agents/skills`, Claude/Codex compatibility dirs. |
| Kiro | `agent_profile`: `.kiro/agents/{name}.md` / `~/.kiro/agents/{name}.md`; `mcp`: `.kiro/settings/mcp.json` / `~/.kiro/settings/mcp.json`; `hooks`: `.kiro/hooks/{name}.json`; `skills`: `.kiro/skills/{name}/SKILL.md` / `~/.kiro/skills/{name}/SKILL.md`. | `.kiro/steering/*.md`, `~/.kiro/steering/*.md`, `AGENTS.md`. |
| Claude Code | `agent_profile`: `.claude/agents/{name}.md` / `~/.claude/agents/{name}.md`; `mcp`: prefer setup commands or `.mcp.json` project / `~/.claude.json` user depending install mode; `hooks`: `.claude/settings.json` / `~/.claude/settings.json`; `skills`: `.claude/skills/{name}/SKILL.md` / `~/.claude/skills/{name}/SKILL.md`. | `CLAUDE.md`, `.claude/CLAUDE.md`, `~/.claude/CLAUDE.md`, `CLAUDE.local.md`, `.claude/rules/**`, imported `AGENTS.md`. |
| Codex | `agent_profile`: keep existing generated `~/.codex/agents/{name}.toml` unless docs prove a project route; `mcp`: `~/.codex/config.toml` and trusted `.codex/config.toml` using `[mcp_servers.<name>]`; `hooks`: `~/.codex/hooks.json` / `.codex/hooks.json`; `skills`: `.agents/skills/{name}/SKILL.md` or `$HOME/.agents/skills/{name}/SKILL.md` if we install skills for Codex. | `AGENTS.md`, `AGENTS.override.md`, fallback instruction files configured in Codex config. |
| Copilot cloud | `agent_profile`: `.github/agents/{name}.agent.md`; `hooks`: `.github/hooks/{name}.json`; `skills`: `.github/skills/{name}/SKILL.md` unless user picks `.agents/skills`; `mcp`: no local file for GitHub.com repo settings, so docs/API should say manual repo setting unless we add GitHub API integration. | `.github/copilot-instructions.md`, `.github/instructions/*.instructions.md`, `AGENTS.md`, root `CLAUDE.md`/`GEMINI.md`. |
| Copilot CLI | `agent_profile`: `.github/agents/{name}.agent.md` project or `~/.copilot/agents/{name}.agent.md` user; `mcp`: `~/.copilot/mcp-config.json`; `hooks`: `.github/hooks/{name}.json` / `~/.copilot/hooks/{name}.json`; `skills`: `.github/skills/{name}/SKILL.md`, `.agents/skills/{name}/SKILL.md`, or `~/.copilot/skills/{name}/SKILL.md`. | `.github/copilot-instructions.md`, `.github/instructions/**/*.instructions.md`, `AGENTS.md`, `$HOME/.copilot/copilot-instructions.md`, `COPILOT_CUSTOM_INSTRUCTIONS_DIRS`. |
| OpenCode | `agent_profile`: `.opencode/agents/{name}.md` / `~/.config/opencode/agents/{name}.md`; `mcp`: `opencode.json` / `~/.config/opencode/opencode.json` under `mcp`; `hooks`: `.opencode/plugins/{name}.ts` / `~/.config/opencode/plugins/{name}.ts`; `skills`: `.opencode/skills/{name}/SKILL.md` / `~/.config/opencode/skills/{name}/SKILL.md` plus `.agents`/`.claude` compatibility. | Project/global `opencode.json` guidance and plugin-provided assets not owned by Observal. |
| Antigravity | `agent_profile`: do not write standalone `agent.json`; docs only confirm plugin-packaged `agents/` templates, so Observal should use a plugin route if it generates Antigravity subagents. `mcp`: CLI `.agents/mcp_config.json` project / `~/.gemini/antigravity-cli/mcp_config.json` user, while editor/global migration docs also mention `~/.gemini/config/mcp_config.json` (scan both, write CLI path for CLI installs). `skills`: `.agents/skills/{name}.md` / `~/.gemini/antigravity-cli/skills/{name}.md`; `hooks`: current Observal spec `~/.gemini/config/hooks.json` global or `.agents/hooks.json` workspace. | `AGENTS.md`, `GEMINI.md`, editor project settings. |
| Pi | `guidance_as_config`: `AGENTS.md` project / `~/.pi/agent/AGENTS.md` user; `mcp`: `.pi/mcp.json` / `~/.pi/agent/mcp.json`; `skills`: `.pi/skills/{name}/SKILL.md` / `~/.pi/agent/skills/{name}/SKILL.md`; `hooks/extensions`: `.pi/extensions/{name}.ts` / `~/.pi/agent/extensions/{name}.ts` if we generate extensions. | Additional context files (`CLAUDE.md`, parent `AGENTS.md`), `.agents/skills`, settings-provided paths. |

Route checks resolved from docs:

- Cursor user-scope agents are real: docs list `~/.cursor/agents/`; remove the stale CLI comment that forces Cursor agents to project-only.
- Codex custom agents are real TOML files under `~/.codex/agents/` and `.codex/agents/`; current adapter should add project-scope support and keep TOML.
- Antigravity standalone agent profile route is **not** documented. Do not write current stale `~/.gemini/antigravity-cli/agents/{name}/agent.json`. For Antigravity, package Observal behavior through documented plugin assets only: `plugins/<plugin>/agents/` for subagent templates, `hooks.json`, `skills/`, and `mcp_config.json`.
- OpenCode skills are documented: `.opencode/skills/<name>/SKILL.md`, `~/.config/opencode/skills/<name>/SKILL.md`, plus `.agents` and `.claude` compatibility paths.

## Harness terminology blast radius

Decision: yes, this should be a **harness registry**, not an harness registry. “IDE” is wrong for Codex CLI, Copilot CLI, Claude Code web/desktop, Copilot cloud agent, Antigravity CLI, and Pi. Docs also back the term: Pi calls itself an “agent harness” and Antigravity CLI says plugins augment the “shared agent harness”.

Root grep blast radius found these buckets to rename:

- Registry modules/constants:
  - `observal-server/schemas/harness_registry.py` → `harness_registry.py`
  - `observal_cli/harness_registry.py` → `harness_registry.py`
  - `HARNESS_REGISTRY` → `HARNESS_REGISTRY`
  - `VALID_HARNESSES` / `valid_harnesses` → `VALID_HARNESSES` / `valid_harnesses`
  - `HARNESS_CAPABILITIES` / `harness_capability_*` → `HARNESS_CAPABILITIES` / `harness_capability_*`
- Adapter packages:
  - Rename `observal-server/services/harness/` → `observal-server/services/harness/` and `observal_cli/harness/` → `observal_cli/harness/` in the same change.
  - Update all imports; do not leave wrapper packages.
- API/web:
  - Add `GET /api/config/harnesses`.
  - Replace `GET /api/config/harnesses` with `GET /api/config/harnesses`; remove the old route.
  - Rename web types `IdeEntry`, `IdesResponse`, selected IDE labels/copy to harness equivalents.
- CLI:
  - Replace `--harness` with `--harness` everywhere.
  - Rename user-facing output from “IDE” to “harness”.
- DB/schema fields:
  - Fields like `ide`, `harness_capability`, `models_by_harness` are persisted/API-facing. Hard rename them to `harness`, `harness_capability`, `models_by_harness` with an explicit DB/data migration and fixture updates.
- Docs:
  - `docs/adding-a-harness.md` → `docs/adding-a-harness.md`.
  - Update all references to that file, including `AGENTS.md`.
  - Update “harness registry”, “feature matrix”, “valid harnesss”, “per-harness” wording across docs to “harness registry”, “capabilities”, “valid harnesses”, “per-harness”.
  - Keep product names that are literally IDEs (Cursor IDE, Kiro IDE) when talking about the vendor product, but not as Observal’s abstraction.
- Tests:
  - Rename `tests/test_harness_registry.py`, `tests/test_ide_config_e2e.py`, `observal-server/tests/test_harness_capability_inference.py`, and constants-sync assertions to harness names.
  - Add smoke tests proving the new harness names work and root grep has no Observal-owned `HARNESS_REGISTRY`, `VALID_HARNESSES`, `/harnesses`, or `--harness` references left.

Grep evidence from the repo root: `HARNESS_REGISTRY` appears across server services/adapters/registry/tests/CLI; `harness_registry` imports appear in server, CLI, tests; `VALID_HARNESSES`, `IDE_FEATURE*`, `/harnesses`, and `--harness` appear in CLI commands, API routes, web API types, docs, and tests. Ignore generated/cache/vendor paths like `.pi-lens`, `.venv`, and `node_modules`.

## Registry shape decisions

Use separate top-level route keys in each harness registry entry:

- `capabilities`: replaces `features` / “feature matrix”.
- `agent_profile`: selectable custom/sub-agent definition route(s). Observal writes these.
- `guidance_files`: prompt/context files. Observal scans/layers these, but only writes them for Pi.
- `mcp_config`: MCP config route(s), key shape, and transform mode.
- `hooks`: hook config route(s), hook type, event map, and generated hook support.
- `skills`: Agent Skills route(s), format, and compatibility paths.
- `model_catalog_file`: shared JSON file that defines supported model IDs/patterns for this harness.

Hard remove old names (`IDE_REGISTRY`, `/api/config/ides`, `--ide`, `features`, `rules_file`, `mcp_config_path`, `hook_config_path`, `skill_file`, `supports_model_selection`) from Observal-owned code/docs/tests. The smoke test should grep for these after migration and fail on matches outside changelog/historical notes.

Model data location: small registry-owned JSON files in `packages/observal-shared/observal_shared/harness_models/`, one file per harness, referenced by the registry. This avoids bloating Python files while still packaging data for CLI and server.

Model collection shape: finite exact rows for static harnesses; dynamic provider-source rows for harnesses that truly support provider catalogs (Pi, OpenCode, Copilot CLI BYOK, Codex custom providers). Dynamic rows must describe the actual provider namespace accepted by the harness, not a random sample.

## Proposed model JSON shape

Keep this boring and static:

```json
{
  "harness": "claude-code",
  "updated_at": "2026-06-21",
  "models": [
    {"id": "sonnet", "label": "Latest Sonnet alias", "provider": "anthropic", "kind": "alias"},
    {"id": "claude-sonnet-4-6", "label": "Claude Sonnet 4.6", "provider": "anthropic", "kind": "exact"},
    {"id": "claude-opus-4-8", "label": "Claude Opus 4.8", "provider": "anthropic", "kind": "exact"}
  ]
}
```

Rules:

- `id` is the exact value we write to the harness when selected.
- `kind` is `exact`, `alias`, or `provider_source`.
- `provider_source` rows are allowed only when the harness docs say the harness discovers or accepts provider/model IDs dynamically. They must name the actual namespace/pattern the harness accepts (`opencode/*`, `<provider>/<model-id>`, `litellm:<model-id>`, `COPILOT_MODEL`, etc.).
- `effort` is optional for harnesses that split model and reasoning effort (Antigravity, Kiro, Claude Code, Codex).
- `label` is display-only.
- `provider` is display/filter metadata; no external provider routing logic.
- No `models.dev` fields, no live refresh.

## Initial supported model catalogs

Create one shared JSON file for **every** registered harness:

- `harness_models/cursor.json`
- `harness_models/kiro.json`
- `harness_models/claude-code.json`
- `harness_models/codex.json`
- `harness_models/copilot.json`
- `harness_models/copilot-cli.json`
- `harness_models/opencode.json`
- `harness_models/antigravity.json`
- `harness_models/pi.json`

These are the initial complete catalogs from current public docs. Static harnesses get exact model IDs. Dynamic harnesses get documented `provider_source` rows that reflect their actual model discovery/selection mechanism.

| Harness | Seed supported model IDs / patterns | Proof |
| --- | --- | --- |
| Cursor | `auto`, `composer-2.5`, `composer-2`, `gpt-5.5`, `gpt-5.5-fast`, `gpt-5.4`, `gpt-5.4-mini`, `gpt-5.4-nano`, `gpt-5.3-codex`, `gpt-5.3-codex-high`, `claude-fable-5`, `claude-opus-4-8`, `claude-opus-4-8-fast`, `claude-sonnet-4-6`, `gemini-3.5-flash`, `gemini-3.1-pro`, `gemini-3-flash`, `grok-build-0.1`. Also allow `inherit` only inside subagent `model` frontmatter. | Cursor models page + subagent model docs. |
| Kiro | `auto`, `claude-sonnet-4`, `claude-sonnet-4-5`, `claude-sonnet-4-6`, `claude-haiku-4-5`, `claude-opus-4-5`, `claude-opus-4-6`, `claude-opus-4-7`, `claude-opus-4-8`, `minimax-m2.5`, `minimax-m2.1`, `glm-5`, `deepseek-3.2`, `qwen3-coder-next`. Effort levels where supported: `low`, `medium`, `high`, `xhigh`, `max` per model. | Kiro models page; Kiro agent config example uses `model: claude-sonnet-4`. |
| Claude Code | Aliases: `default`, `best`, `fable`, `opus`, `sonnet`, `haiku`, `opusplan`, `inherit`; 1M variants: `sonnet[1m]`, `opus[1m]`, `opusplan[1m]`; full IDs: `claude-fable-5`, `claude-opus-4-8`, `claude-opus-4-7`, `claude-opus-4-6`, `claude-sonnet-4-6`, `claude-sonnet-4-5`, `claude-haiku-4-5`. Also allow `anthropic-custom:*` for `ANTHROPIC_CUSTOM_MODEL_OPTION`/gateway deployments. | Claude Code model-config + Anthropic model overview. |
| Codex | Exact OpenAI IDs from docs/examples: `gpt-5.5`, `gpt-5.4`, `gpt-5.4-mini`, `gpt-5.4-nano`, `gpt-5.3-codex`, `gpt-5.3-codex-spark`, `gpt-5.2`, `gpt-5.2-codex`, `gpt-5.1`, `gpt-5.1-codex`, `gpt-5.1-codex-max`, `gpt-5.1-codex-mini`; provider-source rows for documented custom providers: `{id:"model_providers.<id>:<model>", kind:"provider_source"}`, `{id:"amazon-bedrock:<bedrock-model-id>", kind:"provider_source"}`, `{id:"ollama:<model>", kind:"provider_source"}`, `{id:"lmstudio:<model>", kind:"provider_source"}`. | Codex config docs and subagent examples. |
| Copilot cloud | `auto`, `claude-sonnet-4.5`, `claude-opus-4.7`, `claude-haiku-4.5`, `gemini-3.1-pro`, `gemini-3.5-flash`, `gpt-5.4-mini`. Treat these as GitHub model-picker selections, not local config values we write. | GitHub Copilot cloud agent model page. |
| Copilot CLI | Hosted/auto: `auto`; provider-source rows for BYOK env config: `{id:"COPILOT_PROVIDER_TYPE=openai;COPILOT_MODEL=<model>", kind:"provider_source"}`, `{id:"COPILOT_PROVIDER_TYPE=azure;COPILOT_MODEL=<deployment>", kind:"provider_source"}`, `{id:"COPILOT_PROVIDER_TYPE=anthropic;COPILOT_MODEL=<claude-model>", kind:"provider_source"}`. Examples from docs include `gpt-4o`, `claude-opus-4-5`, `llama3.2`. Model must support tool calling and streaming. | GitHub Copilot CLI BYOK docs. |
| OpenCode | Generate `opencode.json` instead of hand-maintaining Zen IDs. Fetch OpenCode Zen `/v1/models` for exact `opencode/<model-id>` entries and include docs-backed provider-source support for `provider_id/model_id` because OpenCode docs say the full ID is `provider_id/model_id`, custom providers use the `provider` config key, and OpenAI-compatible providers use returned `/v1/models` IDs. This mirrors Pi’s generated-catalog approach where possible while avoiding user-facing `models.dev`. | OpenCode Zen `/v1/models`, OpenCode models/providers/agent docs. |
| Antigravity | Do not hand-maintain a short list. `antigravity.json` should have `reasoning_models` and `platform_models`. `reasoning_models` are the actual `/model` picker entries from official Antigravity docs plus observed variants: `gemini-3.5-flash` (`low|medium|high`), `gemini-3.1-pro` (`low|high`), `gemini-3-flash`, `claude-sonnet-4-6` (`thinking`), `claude-opus-4-6` (`thinking`), `gpt-oss-120b-maas` (`medium`), and API agent `antigravity-preview-05-2026`. `platform_models` should be scraped/refreshed from Gemini Enterprise Agent Platform model pages (Gemini, Claude partner models, GPT-OSS/open models, etc.) as provider-source rows so the registry reflects the larger platform model surface when Antigravity exposes it. | Antigravity models docs, user `/model` screenshot, Gemini API model code, Google Cloud gpt-oss model ID, Gemini Enterprise Agent Platform model index. |
| Pi | Generate `pi.json` from Pi’s real bundled catalog, not samples. Fetch/parse `https://github.com/earendil-works/pi/blob/main/packages/ai/src/models.generated.ts` (raw URL in script), using `packages/ai/src/models.ts` as proof that this is Pi’s runtime registry and `scripts/generate-models.ts` as proof of how upstream generates it. The current upstream file has 35 providers and ~979 bundled model entries. Also add provider-source rows for user `~/.pi/agent/models.json` custom providers and LiteLLM discovery (`litellm:<model-id>`). | Pi `models.generated.ts`, `models.ts`, `generate-models.ts`, Pi model/provider docs, LiteLLM extension docs. |

## Hook route details

| Harness | Hook route to write | Canonical events / notes |
| --- | --- | --- |
| Cursor | `.cursor/hooks.json`, `~/.cursor/hooks.json`; plugin hooks use `hooks/hooks.json`. | Use Cursor event names: `sessionStart`, `sessionEnd`, `preToolUse`, `postToolUse`, `postToolUseFailure`, `subagentStart`, `subagentStop`, `beforeShellExecution`, `afterShellExecution`, `beforeMCPExecution`, `afterMCPExecution`, `beforeReadFile`, `afterFileEdit`, `beforeSubmitPrompt`, `preCompact`, `stop`, `afterAgentResponse`, `afterAgentThought`, plus Tab/app lifecycle events where relevant. |
| Kiro | `.kiro/hooks/{name}.json`; legacy embedded hooks in agent config are read-only/migration only. | Versioned JSON with `hooks` array. Triggers: `SessionStart`, `Stop`, `UserPromptSubmit`, `PreToolUse`, `PostToolUse`, `PostFileCreate`, `PostFileSave`, `PostFileDelete`, `PreTaskExec`, `PostTaskExec`, `Manual`. Actions: `{type: "command"}` or `{type: "agent"}`. |
| Claude Code | `.claude/settings.json`, `~/.claude/settings.json`, `.claude/settings.local.json`; subagent frontmatter `hooks` for agent-scoped hooks. | Events: `PreToolUse`, `PostToolUse`, `UserPromptSubmit`, `Notification`, `Stop`, `SessionStart`, `SubagentStop`. Command hooks are supported; HTTP hooks need allowlist settings. |
| Codex | `~/.codex/hooks.json`, `.codex/hooks.json`, or inline `[hooks]` in adjacent `config.toml`. | Events include `PreToolUse`, `PermissionRequest`, `PostToolUse`, `PreCompact`, `PostCompact`, `SessionStart`, `SubagentStart`, `SubagentStop`, `UserPromptSubmit`, `Stop`; command hooks supported. |
| Copilot cloud / CLI | Repo `.github/hooks/*.json`; CLI user `~/.copilot/hooks/*.json` or `$COPILOT_HOME/hooks/*.json`. | JSON with `version: 1`. Events: `sessionStart`, `sessionEnd`, `userPromptSubmitted`, `preToolUse`, `postToolUse`, `agentStop`, `subagentStop`, `errorOccurred`. Command hooks use `bash`/`powershell`. |
| OpenCode | `.opencode/plugins/{name}.ts`, `~/.config/opencode/plugins/{name}.ts`. | Plugin hooks/events. For Observal telemetry use `tool.execute.before`, `tool.execute.after`, `event` filtered for `session.idle`, and optionally `shell.env`/message events only if needed. |
| Antigravity | Existing Observal hook spec writes `hooks.json` via `resolve_antigravity_config_dir()` (`~/.gemini/config/hooks.json` global or `.agents/hooks.json` workspace); plugin docs also allow plugin `hooks.json`. Keep the existing flat hook schema. | Events used by Observal: `PreInvocation` and `Stop`; flat handler list: `{ "observal-telemetry": { "PreInvocation": [{"type":"command","command":"...","timeout":30}], "Stop": [...] } }`. Do not use Claude/Codex matcher-group schema here. |
| Pi | `.pi/extensions/{name}.ts`, `~/.pi/agent/extensions/{name}.ts`. | Pi has TypeScript extension events, not JSON hooks. Use `session_start`, `tool_call`, `session_shutdown`/other documented event API in generated extension code. |

## Reference proof links

- Cursor rules: https://cursor.com/docs/rules.md
- Cursor subagents and user/project agent paths: https://cursor.com/docs/subagents.md
- Cursor hooks/plugin event list: https://cursor.com/docs/hooks.md and https://cursor.com/docs/reference/plugins.md
- Cursor MCP: https://cursor.com/docs/mcp.md
- Cursor skills: https://cursor.com/docs/skills.md
- Cursor models: https://cursor.com/docs/models-and-pricing.md
- Kiro steering: https://kiro.dev/docs/steering/
- Kiro MCP: https://kiro.dev/docs/mcp/configuration/
- Kiro hooks v3: https://kiro.dev/docs/cli/v3/hooks/
- Kiro agent config: https://kiro.dev/docs/cli/v3/agent-config
- Kiro skills: https://kiro.dev/docs/skills/
- Kiro models: https://kiro.dev/docs/models/
- Claude Code settings/scopes: https://docs.anthropic.com/en/docs/claude-code/settings
- Claude Code subagents: https://docs.anthropic.com/en/docs/claude-code/sub-agents
- Claude Code hooks guide: https://docs.anthropic.com/en/docs/claude-code/hooks-guide
- Claude Code skills: https://docs.anthropic.com/en/docs/claude-code/skills
- Claude Code MCP: https://docs.anthropic.com/en/docs/claude-code/mcp
- Claude Code model config: https://docs.anthropic.com/en/docs/claude-code/model-config
- Anthropic model IDs: https://docs.anthropic.com/en/docs/about-claude/models/overview
- Codex AGENTS.md: https://developers.openai.com/codex/guides/agents-md
- Codex config/MCP/hooks: https://developers.openai.com/codex/config-basic, https://developers.openai.com/codex/config-advanced, https://developers.openai.com/codex/config-reference, https://developers.openai.com/codex/mcp
- Codex subagents/custom agents: https://developers.openai.com/codex/subagents
- Codex models: https://developers.openai.com/codex/models
- GitHub Copilot repo instructions/custom agents: https://docs.github.com/en/copilot/customizing-copilot/adding-repository-custom-instructions-for-github-copilot and https://docs.github.com/en/copilot/how-tos/use-copilot-agents/cloud-agent/create-custom-agents
- GitHub Copilot custom agent config: https://docs.github.com/en/copilot/reference/custom-agents-configuration
- GitHub Copilot hooks: https://docs.github.com/en/copilot/concepts/agents/hooks and https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/use-hooks
- GitHub Copilot skills: https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/add-skills
- GitHub Copilot MCP: https://docs.github.com/en/copilot/customizing-copilot/extending-copilot-chat-with-mcp and https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/add-mcp-servers
- GitHub Copilot cloud models: https://docs.github.com/en/copilot/how-tos/use-copilot-agents/cloud-agent/changing-the-ai-model
- GitHub Copilot CLI BYOK models: https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/use-byok-models
- OpenCode agents/config: https://opencode.ai/docs/agents/ and https://opencode.ai/docs/config/
- OpenCode MCP: https://opencode.ai/docs/mcp-servers/
- OpenCode plugins/hooks: https://opencode.ai/docs/plugins/
- OpenCode skills: https://opencode.ai/docs/skills/
- OpenCode providers/Zen model IDs: https://opencode.ai/docs/providers/, https://opencode.ai/docs/models/, https://opencode.ai/docs/zen/, and https://opencode.ai/zen/v1/models
- Antigravity models: https://antigravity.google/docs/models
- Antigravity CLI plugins/skills/hooks/MCP: https://antigravity.google/docs/cli-plugins
- Antigravity CLI settings/sandbox: https://antigravity.google/docs/cli-using and https://antigravity.google/docs/cli-sandbox
- Antigravity/Gemini migration paths: https://antigravity.google/docs/gcli-migration
- Gemini model code proof: https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash
- Google Cloud GPT-OSS model ID proof: https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/maas/openai/gpt-oss-120b
- Antigravity API agent ID: https://ai.google.dev/gemini-api/docs/antigravity-agent
- Harness terminology proof: Pi calls itself a “minimal agent harness” and says “Change the harness, not your workflow”: https://pi.dev/ ; Antigravity CLI says plugins augment the “shared agent harness”: https://antigravity.google/docs/cli-plugins
- Pi homepage/context model: https://pi.dev/
- Pi settings/skills/extensions/security/sandbox: https://pi.dev/docs/latest/settings, https://pi.dev/docs/latest/skills, https://pi.dev/docs/latest/extensions, https://pi.dev/docs/latest/security, https://pi.dev/docs/latest/containerization
- Pi model/provider IDs: https://pi.dev/models, https://pi.dev/docs/latest/models, https://pi.dev/docs/latest/providers, https://github.com/earendil-works/pi/blob/main/packages/ai/src/models.generated.ts, https://github.com/earendil-works/pi/blob/main/packages/ai/src/models.ts, https://github.com/earendil-works/pi/blob/main/packages/ai/scripts/generate-models.ts
- Pi LiteLLM extension: https://pi.dev/packages/pi-provider-litellm
- Agent Skills spec/integration: https://agentskills.io/llms-full.txt

## Steps

- [x] Audit all registry entries against docs and public examples.
- [x] Capture citations and final path/format decisions in this plan.
- [x] Treat server adapters as implementation truth only where docs confirm them; otherwise fix adapter/registry drift together.
- [x] Hard rename Observal’s abstraction from IDE to harness across code, CLI, API, web, docs, tests, and persisted fields; remove old names instead of aliases.
- [x] Run a smoke grep after the hard migration to prove no Observal-owned `IDE_REGISTRY`, `VALID_IDES`, `/config/ides`, `--ide`, `ide_registry`, `ide_feature`, or `models_by_ide` references remain outside changelog/history/migrations.
- [x] Choose registry vocabulary (`agent_profile`, `guidance_files`, `capabilities`) and hard remove old route keys.
- [x] Remove non-Pi writes to guidance files from install/pull paths; keep guidance files in scan/layer attribution only.
- [x] Add model metadata references to both registry copies: `model_catalog_file` plus derived `supported_models` from shared JSON for every harness (`cursor`, `kiro`, `claude-code`, `codex`, `copilot`, `copilot-cli`, `opencode`, `antigravity`, `pi`).
- [x] Add `scripts/refresh_harness_models.py` to refresh vendored model JSON: parse Pi `models.generated.ts`; fetch OpenCode Zen `/v1/models` and docs-backed provider model patterns; refresh Antigravity from Antigravity docs plus Gemini Enterprise Agent Platform model pages; keep other harness JSON curated from official docs.
- [x] Replace user-facing `models.dev` commands/docs with registry-backed model data.
- [x] Update model resolution to validate against registry-supported models or pass through for wildcard-compatible harnesses.
- [x] Update API/web types and model picker copy.
- [x] Update `observal registry models` to read harness model JSON and support `observal registry models --harness <name>` / `list --harness <name>`.
- [x] Update CLI pull/model prompts.
- [x] Update the Observal CLI agent-creation skill (`observal_cli/skills/observal-agents/SKILL.md`) so its Create Agent procedure first runs `observal registry models --harness <name>` for each selected harness, picks an available model, uses `--harness`, and writes `models_by_harness` in YAML examples.
- [x] Update `observal_cli/skills/observal/references/commands.md` so `observal registry models` is described as registry-backed and harness-filterable, not `models.dev`-backed.
- [x] Update docs to use the new vocabulary and current paths.
- [x] Update tests for registry parity, supported models, API payload, and resolver behavior.

## Verification

- Run focused registry/model tests after renames: `pytest tests/test_constants_sync.py tests/test_harness_registry.py tests/test_model_registry.py`.
- Run affected CLI pull tests.
- Type-check/lint affected web files if available.
- Manual check: `/api/config/harnesses` returns model metadata for every harness and `/api/config/ides` is gone.
- Manual check: builder model picker shows supported/free-form behavior per harness.
- Manual check: `scripts/refresh_harness_models.py --check` confirms Pi model count/provider count from upstream, OpenCode Zen entries, and Antigravity platform/reasoning rows are present.
- Manual check: `observal registry models --harness pi` and `--harness opencode` show generated provider-source rows, while static harnesses show exact model IDs.
- Manual check: bundled `observal-agents` skill no longer mentions `--ide`, `models_by_ide`, or `models.dev`.

Completed verification:

- `PYTHONPATH=observal-server:packages/observal-shared pytest -q tests/test_constants_sync.py tests/test_harness_registry.py tests/test_model_registry.py tests/test_cli_harness_adapters.py tests/test_antigravity_adapter.py` → 169 passed.
- `cd web && pnpm typecheck` → passed.
- `python scripts/refresh_harness_models.py --check` → passed.
- `PYTHONPATH=packages/observal-shared python -m observal_cli.main registry models --harness pi --output plain` → returns Pi catalog rows.
- Smoke grep excluding changelog/history/migrations found no `IDE_REGISTRY`, `VALID_IDES`, `/config/ides`, `--ide`, `ide_registry`, `ide_feature`, `models_by_ide`, old route keys, or user-facing `models.dev` references.
