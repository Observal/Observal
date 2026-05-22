# SPDX-FileCopyrightText: 2026 Apoorv Garg <apoorvgarg.21@gmail.com>
# SPDX-FileCopyrightText: 2026 Aryan Iyappan <aryaniyappan2006@gmail.com>
# SPDX-FileCopyrightText: 2026 Subramania Raja <dhanpraja231@gmail.com>
# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-FileCopyrightText: 2026 Kaushik Kumar <kaushikrjpm10@gmail.com>
# SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
# SPDX-FileCopyrightText: 2026 Naraen Rammoorthi <naraen13@gmail.com>
# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-FileCopyrightText: 2026 Shreem Seth <shreemseth26@gmail.com>
# SPDX-FileCopyrightText: 2026 Vishnu Muthiah <vishnu.muthiah04@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

from __future__ import annotations

from typing import TYPE_CHECKING

from schemas.constants import IDE_FEATURE_MATRIX
from schemas.ide_registry import IDE_REGISTRY
from services.shared.utils import sanitize_name as _sanitize_name

if TYPE_CHECKING:
    from models.agent import Agent, AgentVersion
from services.config_generator import (
    _build_run_command,
    _claude_otlp_env,
    _gemini_otlp_env,
    _gemini_settings,
    generate_config,
)

# Map from internal PascalCase event names to Kiro camelCase event names.
_KIRO_EVENT_MAP = {
    "SessionStart": "agentSpawn",
    "UserPromptSubmit": "userPromptSubmit",
    "PreToolUse": "preToolUse",
    "PostToolUse": "postToolUse",
    "Stop": "stop",
}

# Session push hook command — reads JSONL incrementally, only needs 2 events.
_SESSION_PUSH_CMD = "python3 -m observal_cli.hooks.session_push"
_CURSOR_SESSION_PUSH_CMD = "python3 -m observal_cli.hooks.cursor_session_push"


# The two events that drive JSONL-based telemetry collection.
# UserPromptSubmit: push new lines accumulated since last push.
# Stop: push final lines and mark session complete.
_SESSION_PUSH_EVENTS = ("UserPromptSubmit", "Stop")


def _claude_code_hooks_frontmatter_lines(
    custom_hooks: list[dict] | None = None,
) -> list[str]:
    """Build the YAML lines for a hooks: section in Claude Code frontmatter.

    Returns a list of indented strings (no trailing newlines) ready to be
    appended to the frontmatter_lines list before the closing '---'.

    Only two events are needed (UserPromptSubmit + Stop) because the hook
    reads the session JSONL file incrementally — no per-event shell scripts.

    custom_hooks: list of dicts with event, handler_type, handler_config
    from hook components attached to the agent.
    """
    custom_hooks = custom_hooks or []
    custom_by_event: dict[str, list[dict]] = {}
    for h in custom_hooks:
        ev = h.get("event")
        if ev:
            custom_by_event.setdefault(ev, []).append(h)

    cmd = _SESSION_PUSH_CMD

    lines = ["hooks:"]

    for event in _SESSION_PUSH_EVENTS:
        lines += [
            f"  {event}:",
            "    - hooks:",
            "        - type: command",
            f'          command: "{cmd}"',
        ]
        for ch in custom_by_event.get(event, []):
            lines += _custom_hook_matcher_lines(ch)

    # Append any custom hooks on events we don't natively use
    for event, hooks in custom_by_event.items():
        if event in _SESSION_PUSH_EVENTS:
            continue
        lines.append(f"  {event}:")
        for ch in hooks:
            lines += _custom_hook_matcher_lines(ch)

    return lines


def _custom_hook_matcher_lines(hook: dict) -> list[str]:
    """Build YAML lines for a single custom hook matcher group."""
    handler_type = hook.get("handler_type", "command")
    handler_config = hook.get("handler_config", {})

    if handler_type == "http":
        url = handler_config.get("url", "")
        timeout = handler_config.get("timeout", 10)
        lines = [
            "    - hooks:",
            "        - type: http",
            f'          url: "{url}"',
            f"          timeout: {timeout}",
        ]
    else:
        command = handler_config.get("command", "")
        # Rewrite bare script filenames to the IDE hooks directory path
        script_filename = hook.get("script_filename")
        if script_filename and command == script_filename:
            command = f".claude/hooks/{script_filename}"
        lines = ["    - hooks:", "        - type: command", f'          command: "{command}"'] if command else []
    return lines


def _cursor_hooks_config(platform: str = "") -> dict:
    """Build .cursor/hooks.json content with Observal telemetry hooks.

    Cursor uses beforeSubmitPrompt (fires after user hits send) and stop
    (fires when the agent loop ends).
    """
    cmd = "python -m observal_cli.hooks.cursor_session_push" if platform == "win32" else _CURSOR_SESSION_PUSH_CMD
    return {
        "version": 1,
        "hooks": {
            "beforeSubmitPrompt": [{"command": cmd, "type": "command"}],
            "stop": [{"command": cmd, "type": "command"}],
        },
    }


def _vscode_copilot_hooks_config() -> dict:
    """Build .github/hooks/observal.json content for VS Code Copilot hooks.

    TODO: No JSONL session push implementation for VS Code / Copilot yet.
    Stub — session_push.py will no-op gracefully when it can't find a
    matching session file.
    """
    cmd = _SESSION_PUSH_CMD
    return {
        "hooks": {
            "UserPromptSubmit": [{"type": "command", "command": cmd}],
            "Stop": [{"type": "command", "command": cmd}],
        },
    }


def _vscode_copilot_hooks_frontmatter_lines() -> list[str]:
    """Build YAML lines for hooks in a VS Code Copilot .agent.md frontmatter.

    TODO: No JSONL session push for Copilot yet — stub (no-ops gracefully).
    """
    cmd = _SESSION_PUSH_CMD
    return [
        "hooks:",
        "  UserPromptSubmit:",
        "    - type: command",
        f'      command: "{cmd}"',
        "  Stop:",
        "    - type: command",
        f'      command: "{cmd}"',
    ]


def _gemini_hooks_config() -> dict:
    """Build the hooks block for Gemini CLI settings.json.

    Gemini uses SessionStart/SessionEnd.  We hook SessionStart (first turn)
    and SessionEnd (final flush) which maps to our UserPromptSubmit + Stop pattern.

    TODO: No JSONL session push for Gemini CLI yet.  session_push.py will
    no-op when it can't locate a matching session JSONL file.
    """
    cmd = _SESSION_PUSH_CMD
    return {
        "hooks": {
            "SessionStart": [{"hooks": [{"type": "command", "command": cmd}]}],
            "SessionEnd": [{"hooks": [{"type": "command", "command": cmd}]}],
        },
    }


def _opencode_plugin_js() -> str:
    """Build JS plugin source for OpenCode telemetry.

    Only fires on session.created (start) and session.idle (stop).

    TODO: No JSONL session push for OpenCode yet.  The plugin invokes
    session_push.py which will no-op gracefully until an OpenCode-specific
    pusher is written.
    """
    cmd = _SESSION_PUSH_CMD.replace("\\", "\\\\").replace('"', '\\"')
    return f"""// Observal telemetry plugin for OpenCode
// Auto-generated by `observal pull`
import {{ execSync }} from "child_process";

const SESSION_PUSH = "{cmd}";

function fireHook(event, input) {{
  try {{
    execSync(SESSION_PUSH, {{
      input: JSON.stringify({{ hook_event_name: event, ...input }}),
      timeout: 10000,
      stdio: ["pipe", "pipe", "pipe"],
    }});
  }} catch (e) {{
    // Non-blocking: don't break the session
  }}
}}

export const ObservalPlugin = async ({{ project, client }}) => {{
  return {{
    "session.created": () => fireHook("session.created", {{}}),
    "session.idle": () => fireHook("session.idle", {{}}),
  }};
}};
"""


_MODEL_SHORT_NAMES: dict[str, str] = {
    "sonnet": "sonnet",
    "opus": "opus",
    "haiku": "haiku",
}


def _model_name_to_frontmatter(model_name: str) -> str:
    """Convert a stored model_name to a Claude Code frontmatter short name.

    Claude Code frontmatter accepts short names (sonnet, opus, haiku)
    or full API model IDs (claude-sonnet-4-6-20250725). The intermediate
    form (claude-sonnet-4-6) is NOT valid and causes API errors.

    e.g. 'claude-sonnet-4-6-20250725' -> 'sonnet'
         'claude-opus-4-6-20250725'   -> 'opus'
         'gpt-4o'                     -> 'gpt-4o'  (passthrough)
    """
    if not model_name:
        return ""
    lower = model_name.lower()
    for keyword, short in _MODEL_SHORT_NAMES.items():
        if keyword in lower:
            return short
    return model_name


_FEATURE_LABELS: dict[str, str] = {
    "skills": "slash-command skills",
    "superpowers": "Kiro superpowers",
    "hook_bridge": "hook bridge",
    "mcp_servers": "MCP servers",
    "rules": "rules / system prompt",
    "steering_files": "steering files",
    "otlp_telemetry": "OTLP telemetry",
}


def _check_ide_compatibility(agent: Agent, ide: str) -> list[str]:
    """Return warning strings when *ide* lacks features the agent requires."""
    required = getattr(agent, "required_ide_features", None) or []
    ide_caps = IDE_FEATURE_MATRIX.get(ide, set())
    warnings: list[str] = []
    for feature in required:
        if feature not in ide_caps:
            label = _FEATURE_LABELS.get(feature, feature)
            warnings.append(
                f"This agent requires '{label}' but {ide} does not support it. Some functionality may not work."
            )
    return warnings


def _wrap_kiro_prompt(prompt: str, agent_name: str) -> str:
    """Wrap a user prompt in Kiro-compatible framing.

    Kiro's model guardrails reject prompts that appear to override its
    identity or restrict its behaviour (e.g. "You are X", "Say only Y").
    Wrapping the prompt as *agent specialization* avoids false-positive
    prompt-injection detection while preserving the user's intent.
    """
    if not prompt:
        return prompt
    return (
        f"# {agent_name} — Agent Specialization\n\n"
        f"You are a Kiro agent with the following specialization.\n\n"
        f"## Instructions\n\n"
        f"{prompt}"
    )


def _inject_agent_id(mcp_config: dict, agent_id: str):
    """Add OBSERVAL_AGENT_ID env var to all MCP server entries."""
    for _name, cfg in mcp_config.items():
        if isinstance(cfg, dict):
            cfg.setdefault("env", {})
            cfg["env"]["OBSERVAL_AGENT_ID"] = agent_id


def _build_sandbox_mcp_entry(sandbox_listings: dict, ide: str) -> dict:
    """Build an MCP server entry for sandbox components.

    Returns a dict like {"observal-sandbox": {"command": ..., "args": [...]}}
    that exposes sandboxes as callable tools via the sandbox MCP server.
    """
    if not sandbox_listings:
        return {}

    sandboxes_json = []
    for _lid, listing in sandbox_listings.items():
        sandboxes_json.append(
            {
                "id": str(_lid),
                "name": getattr(listing, "name", ""),
                "image": getattr(listing, "image", ""),
                "timeout": (getattr(listing, "resource_limits", {}) or {}).get("timeout", 300),
                "entrypoint": getattr(listing, "entrypoint", None) or "bash",
                "network_policy": getattr(listing, "network_policy", "none"),
            }
        )

    if not sandboxes_json:
        return {}

    import json as _json

    return {
        "observal-sandbox": {
            "command": "python3",
            "args": ["-m", "observal_cli.sandbox_mcp", "--sandboxes", _json.dumps(sandboxes_json)],
        }
    }


def _build_mcp_configs(
    agent: Agent,
    ide: str,
    observal_url: str,
    mcp_listings: dict | None = None,
    env_values: dict | None = None,
) -> dict:
    """Build MCP server configs from registry components + external MCPs.

    Args:
        mcp_listings: optional {component_id: McpListing} map. When provided,
            used to look up MCP listings for each component. The install route
            pre-loads these to avoid N+1 queries in a sync context.
        env_values: optional {mcp_listing_id_str: {VAR: value}} map of user-supplied
            environment variable values for each MCP.
    """
    mcp_configs = {}
    mcp_listings = mcp_listings or {}
    env_values = env_values or {}

    for comp in agent.components:
        if comp.component_type != "mcp":
            continue
        listing = mcp_listings.get(comp.component_id)
        if not listing:
            continue
        mcp_env = env_values.get(str(listing.id), {})
        cfg = generate_config(listing, ide, observal_url=observal_url, env_values=mcp_env)
        if "mcpServers" in cfg:
            mcp_configs.update(cfg["mcpServers"])
        elif ide in ("claude-code", "claude_code"):
            # generate_config returns shell commands for Claude Code, not
            # an mcpServers dict. Build the shim entry directly so the
            # agent file gets proper mcpServers frontmatter.
            safe = _sanitize_name(listing.name)
            if listing.url:
                # SSE/streamable-http listing — no shim needed
                entry: dict = {"type": (listing.transport or "sse").lower(), "url": listing.url}
                if mcp_env:
                    entry["env"] = mcp_env
                if listing.auto_approve:
                    entry["autoApprove"] = listing.auto_approve
                    entry["disabled"] = False
                mcp_configs[safe] = entry
            else:
                mcp_id = str(listing.id)
                run_cmd = _build_run_command(
                    safe,
                    listing.framework,
                    listing.docker_image,
                    mcp_env,
                    stored_command=listing.command,
                    stored_args=listing.args,
                )
                shim_args = ["--mcp-id", mcp_id, "--", *run_cmd]
                mcp_configs[safe] = {"command": "observal-shim", "args": shim_args, "env": mcp_env}

    for ext in agent.external_mcps or []:
        name = _sanitize_name(ext.get("name", ""))
        if not name:
            continue
        cmd = ext.get("command", "npx")
        args = ext.get("args", [])
        if isinstance(args, str):
            args = args.split()
        env = ext.get("env", {})
        ext_mcp_id = ext.get("id", name)
        shim_args = ["--mcp-id", ext_mcp_id, "--", cmd, *args]
        mcp_configs[name] = {"command": "observal-shim", "args": shim_args, "env": env}

    _inject_agent_id(mcp_configs, str(agent.id))
    return mcp_configs


def _build_skill_configs(
    agent: Agent,
    skill_listings: dict | None = None,
) -> list[dict]:
    """Build skill metadata from registry skill components.

    Returns a list of dicts with skill metadata (name, description, etc.)
    that IDE-specific generators turn into skill files.
    """
    skill_listings = skill_listings or {}
    skills: list[dict] = []

    for comp in agent.components:
        if comp.component_type != "skill":
            continue
        listing = skill_listings.get(comp.component_id)
        if not listing:
            continue
        skills.append(
            {
                "name": _sanitize_name(listing.name),
                "description": getattr(listing, "description", "") or "",
                "slash_command": getattr(listing, "slash_command", None),
                "task_type": getattr(listing, "task_type", ""),
                "git_url": getattr(listing, "git_url", None),
                "git_ref": getattr(listing, "git_ref", None) or "main",
                "skill_path": getattr(listing, "skill_path", None) or "/",
                "skill_md_content": getattr(listing, "skill_md_content", None),
            }
        )

    return skills


def _generate_skill_file(skill: dict, ide: str, scope: str = "project") -> dict:
    """Generate an IDE-specific skill file entry.

    Returns a dict with 'path' and 'content' keys, or None for
    monolithic IDEs (Gemini, Codex, Copilot) that inline skills into rules.
    """
    ide_key = ide.replace("_", "-")
    spec = IDE_REGISTRY.get(ide_key, {})
    skill_paths = spec.get("skill_file")
    if not skill_paths:
        return None

    name = skill["name"]
    desc = skill.get("description", "")
    slash_cmd = skill.get("slash_command")
    path = skill_paths.get(scope, next(iter(skill_paths.values()))).format(name=name)

    skill_format = spec.get("skill_format")
    if skill_format == "yaml_frontmatter":
        content = f"---\nname: {name}\n"
        if desc:
            content += f'description: "{desc}"\n'
        if slash_cmd and ide_key == "claude-code":
            content += f"command: /{slash_cmd}\n"
        content += f"---\n\n{desc}\n"
    else:
        content = f"---\ndescription: {desc}\nalwaysApply: false\n---\n\n# {name}\n\n{desc}\n"

    return {"path": path, "content": content}


def _build_hook_configs(
    agent: Agent,
    hook_listings: dict | None = None,
) -> list[dict]:
    """Extract hook component metadata from agent's hook components.

    Returns a list of dicts with event, handler_type, handler_config
    that IDE-specific generators merge into the agent's hook frontmatter.
    """
    hook_listings = hook_listings or {}
    hooks: list[dict] = []

    for comp in agent.components:
        if comp.component_type != "hook":
            continue
        listing = hook_listings.get(comp.component_id)
        if not listing:
            continue
        entry = {
            "event": getattr(listing, "event", None),
            "handler_type": getattr(listing, "handler_type", "command"),
            "handler_config": getattr(listing, "handler_config", {}) or {},
            "name": getattr(listing, "name", ""),
            "script_filename": getattr(listing, "script_filename", None),
            "script_content": getattr(listing, "script_content", None),
        }
        hooks.append(entry)

    return hooks


def _get_hook_events_map(ide: str) -> dict[str, str]:
    """Get canonical event → IDE event mapping from the IDE registry."""
    return IDE_REGISTRY.get(ide, {}).get("hook_events_map", {})


def _get_hook_scripts_dir(ide: str) -> str:
    """Get the hook scripts directory for an IDE from the registry."""
    return IDE_REGISTRY.get(ide, {}).get("hook_scripts_dir", "")


_HOOK_SCRIPTS_DIR: dict[str, str] = {
    "cursor": ".cursor/hooks",
    "vscode": ".github/hooks/scripts",
    "gemini-cli": ".gemini/hooks",
    "codex": ".codex/hooks",
    "copilot": ".github/hooks/scripts",
    "copilot-cli": ".github/hooks/scripts",
    "claude-code": ".claude/hooks",
    "kiro": ".kiro/hooks",
}


def _merge_hook_components_into_config(hooks_content: dict, hook_configs: list[dict], ide: str) -> None:
    """Merge user-submitted hook components into the IDE hooks config dict (in-place)."""
    events_map = _get_hook_events_map(ide)
    scripts_dir = _HOOK_SCRIPTS_DIR.get(ide, "")
    hooks_dict = hooks_content.setdefault("hooks", {})

    for hc in hook_configs:
        event = hc.get("event")
        if not event:
            continue
        ide_event = events_map.get(event, event)
        handler_config = hc.get("handler_config", {})
        command = handler_config.get("command", "")
        if not command:
            continue

        # If hook has a script_filename, rewrite command to the IDE scripts dir
        script_filename = hc.get("script_filename")
        if script_filename and scripts_dir:
            command = f"{scripts_dir}/{script_filename}"

        if ide == "cursor":
            hooks_dict.setdefault(ide_event, []).append({"command": command})
        elif ide in ("vscode", "copilot", "copilot-cli"):
            hooks_dict.setdefault(ide_event, []).append({"type": "command", "command": command})
        elif ide == "gemini-cli":
            entry: dict = {"matcher": "*", "command": command}
            timeout = handler_config.get("timeout")
            if timeout:
                entry["timeout"] = timeout
            hooks_dict.setdefault(ide_event, []).append(entry)
        else:
            hooks_dict.setdefault(ide_event, []).append({"command": command})


def _collect_hook_script_files(hook_configs: list[dict], hook_listings: dict | None, ide: str) -> list[dict]:
    """Collect script files from hook components that need to be written on install."""
    scripts_dir = _HOOK_SCRIPTS_DIR.get(ide, "")
    if not scripts_dir:
        return []

    files: list[dict] = []
    for hc in hook_configs:
        script_content = hc.get("script_content")
        script_filename = hc.get("script_filename")
        if script_content and script_filename:
            files.append(
                {
                    "path": f"{scripts_dir}/{script_filename}",
                    "content": script_content,
                    "executable": True,
                }
            )

    return files


def _build_rules_content(
    agent: Agent,
    component_names: dict | None = None,
    prompt_listings: dict | None = None,
    sandbox_listings: dict | None = None,
) -> str:
    """Build markdown rules content from the agent and its components.

    Assembles the agent prompt (if any) and a summary of all bundled
    components. Description is registry metadata and is never injected.

    Args:
        prompt_listings: optional {component_id: PromptListing} map. When provided,
            prompt components inject their full template content instead of a bullet name.
        sandbox_listings: optional {component_id: SandboxListing} map. When provided,
            sandbox components inject usage instructions with the run command.
    """
    sections: list[str] = []

    if agent.prompt:
        sections.append(agent.prompt)

    # Group components by type and resolve display names
    names = component_names or {}
    by_type: dict[str, list[str]] = {}
    for comp in agent.components:
        cname = names.get(str(comp.component_id), str(comp.component_id)[:8])
        by_type.setdefault(comp.component_type, []).append(cname)

    type_labels = {
        "mcp": ("MCP Servers", "MCP server"),
        "skill": ("Skills", "skill"),
        "hook": ("Hooks", "hook"),
        "prompt": ("Prompts", "prompt"),
        "sandbox": ("Sandboxes", "sandbox"),
    }

    for comp_type, (heading, _singular) in type_labels.items():
        comp_names = by_type.get(comp_type)
        if not comp_names:
            continue
        if comp_type == "prompt" and prompt_listings:
            # Inject full prompt template content instead of bullet names
            lines = [f"## {heading}", ""]
            for comp in agent.components:
                if comp.component_type != "prompt":
                    continue
                listing = prompt_listings.get(comp.component_id)
                if not listing:
                    continue
                pname = names.get(str(comp.component_id), str(comp.component_id)[:8])
                template = getattr(listing, "template", "") or ""
                if template:
                    lines.append(f"### {pname}")
                    lines.append("")
                    lines.append(template)
                    lines.append("")
                else:
                    lines.append(f"- **{pname}**")
            sections.append("\n".join(lines))
        elif comp_type == "sandbox" and sandbox_listings:
            # Inject sandbox usage instructions with run command
            lines = [
                "## Sandboxes",
                "",
                "You have access to isolated execution environments. Use these to run code safely.",
            ]
            for comp in agent.components:
                if comp.component_type != "sandbox":
                    continue
                listing = sandbox_listings.get(comp.component_id)
                if not listing:
                    continue
                sname = names.get(str(comp.component_id), str(comp.component_id)[:8])
                image = getattr(listing, "image", "") or ""
                entrypoint = getattr(listing, "entrypoint", "") or ""
                resource_limits = getattr(listing, "resource_limits", {}) or {}
                timeout = resource_limits.get("timeout", 300)
                memory_mb = resource_limits.get("memory_mb", 512)
                network = getattr(listing, "network_policy", "none") or "none"
                sandbox_id = str(comp.component_id)
                lines.append("")
                lines.append(f"### {sname}")
                lines.append(f"- **Image:** `{image}`")
                lines.append(f"- **Timeout:** {timeout}s | **Memory:** {memory_mb}MB | **Network:** {network}")
                if entrypoint:
                    lines.append(f"- **Default command:** `{entrypoint}`")
                lines.append(
                    f'- **Run:** `observal-sandbox-run --sandbox-id {sandbox_id} --image {image} --timeout {timeout} --command "<your command>"`'
                )
            sections.append("\n".join(lines))
        else:
            lines = [f"## {heading}", ""]
            for n in comp_names:
                lines.append(f"- **{n}**")
            sections.append("\n".join(lines))

    return "\n\n".join(sections) if sections else f"# {agent.name}"


def generate_agent_config(
    agent: Agent,
    ide: str,
    observal_url: str = "http://localhost:8000",
    mcp_listings: dict | None = None,
    component_names: dict | None = None,
    env_values: dict | None = None,
    options: dict | None = None,
    platform: str = "",
    skill_listings: dict | None = None,
    hook_listings: dict | None = None,
    otlp_http_url: str = "",
    prompt_listings: dict | None = None,
    sandbox_listings: dict | None = None,
) -> dict:
    """Generate IDE-specific config for an agent.

    Args:
        mcp_listings: optional {component_id: McpListing} map pre-loaded by caller.
        component_names: optional {component_id_str: name} map for all component types.
        env_values: optional {mcp_listing_id_str: {VAR: value}} map of user-supplied env var values.
        platform: client platform string (e.g. "win32", "darwin", "linux"). Empty = Unix default.
        skill_listings: optional {component_id: SkillListing} map pre-loaded by caller.
        hook_listings: optional {component_id: HookListing} map pre-loaded by caller.
        prompt_listings: optional {component_id: PromptListing} map pre-loaded by caller.
    """
    safe_name = _sanitize_name(agent.name)
    effective_otlp_http = otlp_http_url or observal_url
    mcp_configs = _build_mcp_configs(agent, ide, effective_otlp_http, mcp_listings=mcp_listings, env_values=env_values)

    # Inject sandbox MCP server when agent has sandbox components
    if sandbox_listings:
        sandbox_mcp = _build_sandbox_mcp_entry(sandbox_listings, ide)
        if sandbox_mcp:
            mcp_configs.update(sandbox_mcp)

    rules_content = _build_rules_content(agent, component_names, prompt_listings, sandbox_listings)
    skill_configs = _build_skill_configs(agent, skill_listings)
    hook_configs = _build_hook_configs(agent, hook_listings)
    options = options or {}
    compatibility_warnings = _check_ide_compatibility(agent, ide)

    # ── Adapter delegation ────────────────────────────────────────────
    # If an adapter is registered for this IDE, delegate to it.
    import services.ide.load_all  # noqa: F401 — ensure all adapters are registered
    from services.ide import ConfigContext, get_adapter

    adapter = get_adapter(ide)
    if adapter is not None:
        ctx = ConfigContext(
            agent=agent,
            safe_name=safe_name,
            ide=ide,
            observal_url=observal_url,
            effective_otlp_http=effective_otlp_http,
            mcp_configs=mcp_configs,
            rules_content=rules_content,
            skill_configs=skill_configs,
            hook_configs=hook_configs,
            options=options,
            platform=platform,
            compatibility_warnings=compatibility_warnings,
            mcp_listings=mcp_listings,
            hook_listings=hook_listings,
            skill_listings=skill_listings,
            sandbox_listings=sandbox_listings,
        )
        return adapter.format_config(ctx)

    # All IDEs handled by adapters above; this is a safeguard.
    raise ValueError(f"No adapter registered for IDE: {ide!r}")


async def generate_all_ide_configs(
    agent_version: AgentVersion,
    agent: Agent,
    target_ides: list[str] | None = None,
    observal_url: str = "http://localhost:8000",
    mcp_listings: dict | None = None,
    skill_listings: dict | None = None,
    hook_listings: dict | None = None,
    component_names: dict | None = None,
    env_values: dict | None = None,
    otlp_http_url: str = "",
) -> dict[str, dict[str, str]]:
    """Generate IDE config files for all target IDEs from an AgentVersion.

    This is the publish-time generation function. Results are stored in
    agent_versions.ide_configs JSONB column and served at pull time.

    Args:
        agent_version: The AgentVersion being published.
        agent: The parent Agent (identity-only, needed for name/owner).
        target_ides: List of IDE names to generate for. None = all from agent_version.supported_ides.
        mcp_listings: Pre-loaded {component_id: McpListing} map.
        skill_listings: Pre-loaded {component_id: SkillListing} map.
        component_names: {component_id_str: display_name} map.
        env_values: {mcp_listing_id_str: {VAR: value}} map.
        otlp_http_url: OTLP collector URL.

    Returns:
        {ide_name: {"files": {file_path: content, ...}}}
        Stored directly in agent_versions.ide_configs.
    """
    import json as _json

    ides = target_ides or agent_version.supported_ides or list(IDE_REGISTRY.keys())
    result = {}

    for ide in ides:
        if ide not in IDE_REGISTRY:
            continue
        config = generate_agent_config(
            agent=agent,
            ide=ide,
            observal_url=observal_url,
            mcp_listings=mcp_listings,
            skill_listings=skill_listings,
            hook_listings=hook_listings,
            component_names=component_names,
            env_values=env_values,
            otlp_http_url=otlp_http_url,
        )

        files = {}
        if "rules_file" in config:
            rf = config["rules_file"]
            files[rf["path"]] = rf["content"]
        if "agent_file" in config:
            af = config["agent_file"]
            content = af["content"]
            files[af["path"]] = _json.dumps(content, indent=2) if isinstance(content, dict) else content
        if "mcp_config" in config:
            mc = config["mcp_config"]
            if isinstance(mc, dict) and "path" in mc:
                content = mc["content"]
                files[mc["path"]] = _json.dumps(content, indent=2) if isinstance(content, dict) else content
        if "skill_files" in config:
            for sf in config["skill_files"]:
                files[sf["path"]] = sf["content"]

        if files:
            result[ide] = {"files": files}

    return result
