import re

from models.agent import Agent
from schemas.constants import IDE_FEATURE_MATRIX
from services.config_generator import (
    _build_run_command,
    _claude_otlp_env,
    _gemini_otlp_env,
    _gemini_settings,
    generate_config,
)

_SAFE_NAME = re.compile(r"^[a-zA-Z0-9_-]+$")

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


def _sanitize_name(name: str) -> str:
    if _SAFE_NAME.match(name):
        return name
    return re.sub(r"[^a-zA-Z0-9_-]", "-", name)


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
                "activation_keywords": getattr(listing, "activation_keywords", None),
            }
        )

    return skills


def _generate_skill_file(skill: dict, ide: str, scope: str = "project") -> dict:
    """Generate an IDE-specific skill file entry.

    Returns a dict with 'path' and 'content' keys, or None for
    monolithic IDEs (Gemini, Codex, Copilot) that inline skills into rules.
    """
    name = skill["name"]
    desc = skill.get("description", "")
    slash_cmd = skill.get("slash_command")

    if ide in ("claude-code", "claude_code"):
        content = f"---\nname: {name}\n"
        if desc:
            content += f'description: "{desc}"\n'
        if slash_cmd:
            content += f"command: /{slash_cmd}\n"
        content += f"---\n\n{desc}\n"
        prefix = "~/.claude" if scope == "user" else ".claude"
        return {"path": f"{prefix}/skills/{name}/SKILL.md", "content": content}

    if ide == "kiro":
        content = f"---\nname: {name}\n"
        if desc:
            content += f'description: "{desc}"\n'
        content += f"---\n\n{desc}\n"
        return {"path": f".kiro/skills/{name}/SKILL.md", "content": content}

    if ide == "cursor":
        prefix = "~/.cursor" if scope == "user" else ".cursor"
        content = f"---\ndescription: {desc}\nalwaysApply: false\n---\n\n# {name}\n\n{desc}\n"
        return {"path": f"{prefix}/rules/{name}.md", "content": content}

    if ide == "vscode":
        content = f"---\ndescription: {desc}\nalwaysApply: false\n---\n\n# {name}\n\n{desc}\n"
        return {"path": f".vscode/rules/{name}.md", "content": content}

    # Monolithic IDEs (gemini, codex, copilot) — no separate file
    return None


def _build_rules_content(agent: Agent, component_names: dict | None = None) -> str:
    """Build markdown rules content from the agent and its components.

    Assembles the agent prompt (if any), description, and a summary of
    all bundled components so the rules file is never empty.
    """
    sections: list[str] = []

    if agent.prompt:
        sections.append(agent.prompt)
    elif agent.description:
        sections.append(agent.description)

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
        lines = [f"## {heading}", ""]
        for n in comp_names:
            lines.append(f"- **{n}**")
        sections.append("\n".join(lines))

    return "\n\n".join(sections) if sections else f"# {agent.name}\n\n{agent.description or ''}"


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
    otlp_http_url: str = "",
) -> dict:
    """Generate IDE-specific config for an agent.

    Args:
        mcp_listings: optional {component_id: McpListing} map pre-loaded by caller.
        component_names: optional {component_id_str: name} map for all component types.
        env_values: optional {mcp_listing_id_str: {VAR: value}} map of user-supplied env var values.
        platform: client platform string (e.g. "win32", "darwin", "linux"). Empty = Unix default.
        skill_listings: optional {component_id: SkillListing} map pre-loaded by caller.
    """
    safe_name = _sanitize_name(agent.name)
    effective_otlp_http = otlp_http_url or observal_url
    mcp_configs = _build_mcp_configs(agent, ide, effective_otlp_http, mcp_listings=mcp_listings, env_values=env_values)
    rules_content = _build_rules_content(agent, component_names)
    skill_configs = _build_skill_configs(agent, skill_listings)
    options = options or {}
    compatibility_warnings = _check_ide_compatibility(agent, ide)

    if ide == "kiro":
        # Kiro agent JSON: drop into ~/.kiro/agents/<name>.json
        # Telemetry collected via observal-shim + hook bridge
        if platform == "win32":
            # PowerShell-compatible: pipe stdin through the Python hook script.
            # No cat/sed/curl/$PPID/$TERM/$SHELL — those don't exist in PowerShell.
            hook_cmd = (
                f"python -m observal_cli.hooks.kiro_hook "
                f"--url {observal_url}/api/v1/otel/hooks "
                f"--agent-name {safe_name}"
            )
            stop_cmd = (
                f"python -m observal_cli.hooks.kiro_stop_hook "
                f"--url {observal_url}/api/v1/otel/hooks "
                f"--agent-name {safe_name}"
            )
            spawn_cmd = hook_cmd  # Windows: Python script handles session IDs
        else:
            # Unix: use the same Python hook scripts as Windows.
            hook_cmd = (
                f"python3 -m observal_cli.hooks.kiro_hook "
                f"--url {observal_url}/api/v1/otel/hooks "
                f"--agent-name {safe_name}"
            )
            stop_cmd = (
                f"python3 -m observal_cli.hooks.kiro_stop_hook "
                f"--url {observal_url}/api/v1/otel/hooks "
                f"--agent-name {safe_name}"
            )
            spawn_cmd = hook_cmd  # Python script handles session IDs
        hooks = {
            "agentSpawn": [{"command": spawn_cmd}],
            "userPromptSubmit": [{"command": hook_cmd}],
            "preToolUse": [{"matcher": "*", "command": hook_cmd}],
            "postToolUse": [{"matcher": "*", "command": hook_cmd}],
            "stop": [{"command": stop_cmd}],
        }
        kiro_scope = options.get("scope", "user")  # Kiro historically defaults to user-level
        agent_path = f"~/.kiro/agents/{safe_name}.json" if kiro_scope == "user" else f".kiro/agents/{safe_name}.json"
        result: dict = {
            "agent_file": {
                "path": agent_path,
                "content": {
                    "name": safe_name,
                    "description": agent.description[:200] if agent.description else "",
                    "prompt": _wrap_kiro_prompt(agent.prompt, safe_name),
                    "mcpServers": mcp_configs,
                    "tools": ["*"],
                    "toolAliases": {},
                    "allowedTools": [],
                    "resources": [
                        "file://AGENTS.md",
                        "file://README.md",
                        "skill://.kiro/skills/*/SKILL.md",
                        "skill://~/.kiro/skills/*/SKILL.md",
                    ],
                    "hooks": hooks,
                    "toolsSettings": {},
                    "includeMcpJson": True,
                    "model": None,  # Kiro uses "auto" model selection; actual model captured via SQLite in hooks
                },
            },
            "scope": kiro_scope,
        }
        skill_files = [_generate_skill_file(s, "kiro") for s in skill_configs]
        skill_files = [f for f in skill_files if f]
        if skill_files:
            result["skill_files"] = skill_files
        if compatibility_warnings:
            result["_warnings"] = compatibility_warnings
        return result

    if ide in ("claude-code", "claude_code"):
        otlp = _claude_otlp_env(effective_otlp_http)
        setup_commands = []
        claude_mcps = {}
        for name, cfg in mcp_configs.items():
            cmd = cfg.get("command", "observal-shim")
            args = cfg.get("args", [])
            setup_commands.append(["claude", "mcp", "add", name, "--", cmd, *args])
            claude_mcps[name] = {"command": cmd, "args": args, "env": cfg.get("env", {})}

        # IDE-specific options
        scope = options.get("scope", "project")  # "project" or "user"
        model_choice = options.get("model", "")  # "", "inherit", "sonnet", "opus", "haiku"
        tools = options.get("tools", "")  # comma-separated whitelist
        color = options.get("color", "")

        # Build Claude Code agent file with YAML frontmatter
        desc_line = (agent.description or safe_name).replace("\n", " ").strip()
        frontmatter_lines = [
            "---",
            f"name: {safe_name}",
            f'description: "{desc_line}"',
        ]
        if model_choice and model_choice != "inherit":
            frontmatter_lines.append(f"model: {model_choice}")
        if tools:
            frontmatter_lines.append(f"tools: {tools}")
        if color:
            frontmatter_lines.append(f"color: {color}")
        if claude_mcps:
            frontmatter_lines.append("mcpServers:")
            for mcp_name in claude_mcps:
                frontmatter_lines.append(f"  - {mcp_name}")
        frontmatter_lines.append("---")
        agent_content = "\n".join(frontmatter_lines) + "\n\n" + rules_content

        # Path: project-level (.claude/agents/) or user-level (~/.claude/agents/)
        agent_path = f"~/.claude/agents/{safe_name}.md" if scope == "user" else f".claude/agents/{safe_name}.md"

        skill_files = [_generate_skill_file(s, ide, scope) for s in skill_configs]
        skill_files = [f for f in skill_files if f]

        result = {
            "rules_file": {"path": agent_path, "content": agent_content},
            "mcp_config": claude_mcps,
            "mcp_setup_commands": setup_commands,
            "otlp_env": otlp,
            "claude_settings_snippet": {"env": otlp},
            "scope": scope,
        }
        if skill_files:
            result["skill_files"] = skill_files
        if compatibility_warnings:
            result["_warnings"] = compatibility_warnings
        return result

    if ide in ("gemini-cli", "gemini_cli"):
        gemini_scope = options.get("scope", "project")
        rules_path = "~/.gemini/GEMINI.md" if gemini_scope == "user" else "GEMINI.md"
        mcp_path = "~/.gemini/settings.json" if gemini_scope == "user" else ".gemini/settings.json"
        result = {
            "rules_file": {"path": rules_path, "content": rules_content},
            "mcp_config": {"path": mcp_path, "content": {"mcpServers": mcp_configs}},
            "otlp_env": _gemini_otlp_env(effective_otlp_http),
            "gemini_settings_snippet": _gemini_settings(effective_otlp_http),
            "scope": gemini_scope,
        }
        if compatibility_warnings:
            result["_warnings"] = compatibility_warnings
        return result

    if ide == "codex":
        result = {
            "rules_file": {"path": "AGENTS.md", "content": rules_content},
            "mcp_config": {"path": "~/.codex/config.toml", "content": {"mcp.servers": mcp_configs}},
            "scope": "user",
        }
        if compatibility_warnings:
            result["_warnings"] = compatibility_warnings
        return result

    if ide == "copilot":
        copilot_configs = {}
        for k, v in mcp_configs.items():
            if v.get("url"):
                transport_type = v.get("type", "sse")
                copilot_configs[k] = {"type": transport_type, "url": v["url"]}
                if "env" in v:
                    copilot_configs[k]["env"] = v["env"]
            else:
                copilot_configs[k] = {"type": "stdio", "command": v["command"], "args": v.get("args", [])}
                if "env" in v:
                    copilot_configs[k]["env"] = v["env"]
        result = {
            "rules_file": {"path": ".github/copilot-instructions.md", "content": rules_content},
            "mcp_config": {"path": ".vscode/mcp.json", "content": {"servers": copilot_configs}},
            "scope": "project",
        }
        if compatibility_warnings:
            result["_warnings"] = compatibility_warnings
        return result

    if ide == "copilot-cli":
        copilot_cli_configs = {}
        for k, v in mcp_configs.items():
            if v.get("url"):
                transport_type = v.get("type", "sse")
                copilot_cli_configs[k] = {"type": transport_type, "url": v["url"], "tools": ["*"]}
                if "env" in v:
                    copilot_cli_configs[k]["env"] = v["env"]
            else:
                copilot_cli_configs[k] = {
                    "type": "stdio",
                    "command": v["command"],
                    "args": v.get("args", []),
                    "tools": ["*"],
                }
                if "env" in v:
                    copilot_cli_configs[k]["env"] = v["env"]
        result = {
            "rules_file": {"path": ".github/copilot-instructions.md", "content": rules_content},
            "mcp_config": {"path": ".mcp.json", "content": {"mcpServers": copilot_cli_configs}},
            "scope": "project",
        }
        if compatibility_warnings:
            result["_warnings"] = compatibility_warnings
        return result

    if ide == "opencode":
        opencode_configs = {}
        for k, v in mcp_configs.items():
            cmd_array = [v["command"], *v.get("args", [])]
            opencode_configs[k] = {"type": "local", "command": cmd_array}
            if "env" in v:
                opencode_configs[k]["env"] = v["env"]
        result = {
            "rules_file": {"path": "AGENTS.md", "content": rules_content},
            "mcp_config": {"path": "~/.config/opencode/opencode.json", "content": {"mcp": opencode_configs}},
            "scope": "user",
        }
        if compatibility_warnings:
            result["_warnings"] = compatibility_warnings
        return result

    # cursor, vscode: rules file + mcp.json — telemetry via observal-shim
    ide_scope = options.get("scope", "project")
    ide_paths = {
        "cursor": (
            "~/.cursor/rules/{name}.md" if ide_scope == "user" else ".cursor/rules/{name}.md",
            "~/.cursor/mcp.json" if ide_scope == "user" else ".cursor/mcp.json",
        ),
        "vscode": (".vscode/rules/{name}.md", ".vscode/mcp.json"),
    }
    rules_path, mcp_path = ide_paths.get(ide, (f".rules/{safe_name}.md", ".mcp.json"))
    skill_files = [_generate_skill_file(s, ide, ide_scope) for s in skill_configs]
    skill_files = [f for f in skill_files if f]
    result = {
        "rules_file": {"path": rules_path.format(name=safe_name), "content": rules_content},
        "mcp_config": {"path": mcp_path, "content": {"mcpServers": mcp_configs}},
        "scope": ide_scope,
    }
    if skill_files:
        result["skill_files"] = skill_files
    if compatibility_warnings:
        result["_warnings"] = compatibility_warnings
    return result
