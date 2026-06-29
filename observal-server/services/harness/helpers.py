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
# SPDX-FileCopyrightText: 2026 tsitu0 <tomsitu0102@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger as optic

from schemas.constants import HARNESS_CAPABILITIES
from schemas.harness_registry import HARNESS_REGISTRY
from services.shared.utils import sanitize_name as _sanitize_name

if TYPE_CHECKING:
    from models.agent import Agent
from services.config_generator import (
    _build_run_command,
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

# Session push hook command - reads JSONL incrementally, only needs 2 events.
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
    reads the session JSONL file incrementally - no per-event shell scripts.

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
        # Rewrite bare script filenames to the harness hooks directory path
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

    Uses the official Copilot hooks format:
    - "version": 1 (required)
    - "bash" key for Unix, "powershell" key for Windows
    - "timeoutSec" for timeout (not "timeout")
    - PascalCase event names for VS Code compatible payloads
    """
    cmd = _SESSION_PUSH_CMD
    ps_cmd = "python -m observal_cli.hooks.copilot_cli_session_push"
    return {
        "version": 1,
        "hooks": {
            "UserPromptSubmit": [{"type": "command", "bash": cmd, "powershell": ps_cmd, "timeoutSec": 5}],
            "Stop": [{"type": "command", "bash": cmd, "powershell": ps_cmd, "timeoutSec": 5}],
        },
    }


def _vscode_copilot_hooks_frontmatter_lines() -> list[str]:
    """Build YAML lines for hooks in a VS Code Copilot .agent.md frontmatter.

    Uses the official Copilot hooks format with bash/powershell keys.
    """
    cmd = _SESSION_PUSH_CMD
    ps_cmd = "python -m observal_cli.hooks.copilot_cli_session_push"
    return [
        "hooks:",
        "  UserPromptSubmit:",
        "    - type: command",
        f'      bash: "{cmd}"',
        f'      powershell: "{ps_cmd}"',
        "      timeoutSec: 5",
        "  Stop:",
        "    - type: command",
        f'      bash: "{cmd}"',
        f'      powershell: "{ps_cmd}"',
        "      timeoutSec: 5",
    ]


def _opencode_plugin_js() -> str:
    """Return TypeScript plugin source for OpenCode telemetry."""
    from observal_shared.opencode_plugin_source import OPENCODE_PLUGIN_SOURCE

    return OPENCODE_PLUGIN_SOURCE


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
    "hooks": "hook bridge",
    "mcp_servers": "MCP servers",
}


def _check_harness_compatibility(agent: Agent, harness: str) -> list[str]:
    """Return warning strings when *ide* lacks features the agent requires."""
    required = getattr(agent, "required_capabilities", None) or []
    ide_caps = HARNESS_CAPABILITIES.get(harness, set())
    warnings: list[str] = []
    for feature in required:
        if feature not in ide_caps:
            label = _FEATURE_LABELS.get(feature, feature)
            warnings.append(
                f"This agent requires '{label}' but {harness} does not support it. Some functionality may not work."
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
        f"# {agent_name} - Agent Specialization\n\n"
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


def _sandbox_str(value, default: str = "") -> str:
    return value if isinstance(value, str) else default


def _build_sandbox_mcp_entry(sandbox_listings: dict, harness: str) -> dict:
    """Build an MCP server entry for sandbox components.

    Returns a dict like {"observal-sandbox": {"command": ..., "args": [...]}}
    that exposes sandboxes as callable tools via the sandbox MCP server.
    """
    if not sandbox_listings:
        return {}

    sandboxes_json = []
    for _lid, listing in sandbox_listings.items():
        resource_limits = getattr(listing, "resource_limits", {}) or {}
        if not isinstance(resource_limits, dict):
            resource_limits = {}
        runtime_config = getattr(listing, "runtime_config", {}) or {}
        if not isinstance(runtime_config, dict):
            runtime_config = {}
        sandboxes_json.append(
            {
                "id": str(_lid),
                "name": _sandbox_str(getattr(listing, "name", "")),
                "runtime_type": _sandbox_str(getattr(listing, "runtime_type", "docker"), "docker") or "docker",
                "image": _sandbox_str(getattr(listing, "image", "")),
                "resource_limits": resource_limits,
                "timeout": resource_limits.get("timeout", 300),
                "entrypoint": _sandbox_str(getattr(listing, "entrypoint", None), "bash") or "bash",
                "network_policy": _sandbox_str(getattr(listing, "network_policy", "none"), "none"),
                "runtime_config": runtime_config,
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
    harness: str,
    observal_url: str,
    mcp_listings: dict | None = None,
    env_values: dict | None = None,
    header_values: dict | None = None,
) -> dict:
    """Build MCP server configs from registry components + external MCPs.

    Args:
        mcp_listings: optional {component_id: McpListing} map. When provided,
            used to look up MCP listings for each component. The install route
            pre-loads these to avoid N+1 queries in a sync context.
        env_values: optional {mcp_listing_id_str: {VAR: value}} map of user-supplied
            environment variable values for each MCP.
        header_values: optional {mcp_listing_id_str: {Header-Name: value}} map of
            user-supplied header values for each MCP (e.g. Authorization tokens).
    """
    mcp_configs = {}
    mcp_listings = mcp_listings or {}
    env_values = env_values or {}
    header_values = header_values or {}

    optic.debug(
        "building MCP configs for agent '{}' (ide={}, {} components)",
        agent.name,
        harness,
        sum(1 for c in agent.components if c.component_type == "mcp"),
    )

    for comp in agent.components:
        if comp.component_type != "mcp":
            continue
        listing = mcp_listings.get(comp.component_id)
        if not listing:
            continue
        mcp_env = env_values.get(str(listing.id), {})
        mcp_headers = header_values.get(str(listing.id), {})
        cfg = generate_config(
            listing, harness, observal_url=observal_url, env_values=mcp_env, header_values=mcp_headers
        )
        if "mcpServers" in cfg:
            mcp_configs.update(cfg["mcpServers"])
        elif "mcp" in cfg:
            # OpenCode returns {"mcp": {name: entry}} — merge directly
            mcp_configs.update(cfg["mcp"])
        elif harness in ("claude-code", "claude_code"):
            # generate_config returns shell commands for Claude Code, not
            # an mcpServers dict. Build the shim entry directly so the
            # agent file gets proper mcpServers frontmatter.
            safe = _sanitize_name(listing.name)
            if listing.url:
                # SSE/streamable-http listing - no shim needed
                entry: dict = {"type": (listing.transport or "sse").lower(), "url": listing.url}
                if mcp_headers:
                    entry["headers"] = mcp_headers
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
    that harness-specific generators turn into skill files.
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
                "script_content": getattr(listing, "script_content", None),
                "script_filename": getattr(listing, "script_filename", None),
            }
        )

    return skills


def _generate_skill(skill: dict, harness: str, scope: str = "project") -> dict:
    """Generate an harness-specific skill file entry.

    Returns a dict with 'path' and 'content' keys, or None for
    monolithic harnesses (Gemini, Codex, Copilot) that inline skills into rules.
    """
    from services.config.skill_builder import generate_skill

    return generate_skill(skill, harness, scope)


def _build_hook_configs(
    agent: Agent,
    hook_listings: dict | None = None,
) -> list[dict]:
    """Extract hook component metadata from agent's hook components.

    Returns a list of dicts with event, handler_type, handler_config
    that harness-specific generators merge into the agent's hook frontmatter.
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


def _get_hook_events_map(harness: str) -> dict[str, str]:
    """Get canonical event → harness event mapping from the harness registry."""
    return HARNESS_REGISTRY.get(harness, {}).get("hook_events_map", {})


def _get_hook_scripts_dir(harness: str) -> str:
    """Get the hook scripts directory for an harness from the registry."""
    return HARNESS_REGISTRY.get(harness, {}).get("hook_scripts_dir", "")


_HOOK_SCRIPTS_DIR: dict[str, str] = {
    "cursor": ".cursor/hooks",
    "codex": ".codex/hooks",
    "copilot": ".github/hooks/scripts",
    "copilot-cli": ".github/hooks/scripts",
    "claude-code": ".claude/hooks",
    "kiro": ".kiro/hooks",
    "opencode": ".opencode/hooks",
}


def _merge_hook_components_into_config(hooks_content: dict, hook_configs: list[dict], harness: str) -> None:
    """Merge user-submitted hook components into the harness hooks config dict (in-place)."""
    events_map = _get_hook_events_map(harness)
    scripts_dir = _HOOK_SCRIPTS_DIR.get(harness, "")
    hooks_dict = hooks_content.setdefault("hooks", {})

    for hc in hook_configs:
        event = hc.get("event")
        if not event:
            continue
        ide_event = events_map.get(event, event)
        handler_config = hc.get("handler_config", {})
        command = handler_config.get("command", "")
        script_filename = hc.get("script_filename")
        if not command and script_filename and scripts_dir:
            command = f"{scripts_dir}/{script_filename}"
        elif not command:
            continue
        elif script_filename and scripts_dir:
            command = f"{scripts_dir}/{script_filename}"

        if harness == "cursor":
            hooks_dict.setdefault(ide_event, []).append({"command": command})
        elif harness in ("copilot", "copilot-cli"):
            hooks_dict.setdefault(ide_event, []).append({"type": "command", "command": command})
        else:
            hooks_dict.setdefault(ide_event, []).append({"command": command})


def _collect_hook_script_files(hook_configs: list[dict], hook_listings: dict | None, harness: str) -> list[dict]:
    """Collect script files from hook components that need to be written on install."""
    scripts_dir = _HOOK_SCRIPTS_DIR.get(harness, "")
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


def _collect_opencode_hook_plugins(hook_configs: list[dict]) -> list[dict]:
    """Generate OpenCode plugin files for custom hook components.

    OpenCode uses plugins (JS/TS files) instead of JSON hook configs.
    Each custom hook component becomes a plugin file that subscribes
    to the mapped OpenCode event and runs the hook command via execSync.
    """
    events_map = _get_hook_events_map("opencode")
    plugins: list[dict] = []

    for hc in hook_configs:
        event = hc.get("event")
        if not event:
            continue
        handler_config = hc.get("handler_config", {})
        handler_type = hc.get("handler_type", "command")
        command = handler_config.get("command", "")
        name = hc.get("name", "") or f"hook-{event.lower()}"
        safe_name = _sanitize_name(name)
        ide_event = events_map.get(event, event)

        # Script-based hooks: write the script to .opencode/hooks/ and reference it
        script_filename = hc.get("script_filename")
        script_content = hc.get("script_content")
        if script_filename and script_content:
            command = f".opencode/hooks/{script_filename}"

        if not command and handler_type != "http":
            continue

        if handler_type == "http":
            url = handler_config.get("url", "")
            timeout = handler_config.get("timeout", 10)
            plugin_source = _opencode_http_hook_plugin(safe_name, ide_event, url, timeout)
        else:
            plugin_source = _opencode_command_hook_plugin(safe_name, ide_event, command)

        plugins.append(
            {
                "path": f".opencode/plugins/hook-{safe_name}.ts",
                "content": plugin_source,
            }
        )

    return plugins


def _opencode_command_hook_plugin(name: str, event: str, command: str) -> str:
    """Generate a plugin file that runs a shell command on an OpenCode event."""
    import json as _json

    cmd_json = _json.dumps(command)
    return f"""// Observal hook plugin: {name}
// Event: {event}
// Auto-generated by `observal pull`

import {{ execSync }} from "child_process";

const HOOK_COMMAND = {cmd_json};

export const Hook_{name.replace("-", "_")} = async (ctx) => {{
  return {{
    event: async ({{ event }}) => {{
      if (event?.type === "{event}") {{
        try {{
          execSync(HOOK_COMMAND, {{
            cwd: ctx.directory,
            timeout: 10000,
            stdio: ["pipe", "pipe", "pipe"],
            shell: true,
          }});
        }} catch {{
          // Non-blocking: don't break the session
        }}
      }}
    }},
  }};
}};
"""


def _opencode_http_hook_plugin(name: str, event: str, url: str, timeout: int = 10) -> str:
    """Generate a plugin file that makes an HTTP request on an OpenCode event."""
    from urllib.parse import urlparse

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return f"// Observal hook plugin: {name} — SKIPPED (invalid URL)\nexport {{}};\n"
    import json as _json

    url_json = _json.dumps(url)
    is_https = url.startswith("https")
    req_module = "https" if is_https else "http"
    return f"""// Observal hook plugin: {name}
// Event: {event}
// Auto-generated by `observal pull`

import {{ request }} from "{req_module}";

const HOOK_URL = {url_json};

export const Hook_{name.replace("-", "_")} = async (ctx) => {{
  return {{
    event: async ({{ event }}) => {{
      if (event?.type === "{event}") {{
        try {{
          const body = JSON.stringify({{ event: event?.type, properties: event?.properties || {{}} }});
          const req = request(HOOK_URL, {{
            method: "POST",
            headers: {{ "Content-Type": "application/json", "Content-Length": Buffer.byteLength(body) }},
            timeout: {timeout * 1000},
          }});
          req.on("error", () => {{}});
          req.on("timeout", () => {{ req.destroy(); }});
          req.write(body);
          req.end();
        }} catch {{
          // Non-blocking
        }}
      }}
    }},
  }};
}};
"""


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

    optic.debug(
        "building rules content for agent '{}' ({} components, prompt={})",
        agent.name,
        len(agent.components),
        bool(agent.prompt),
    )
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
