import re

from models.agent import Agent
from services.config_generator import (
    _claude_otlp_env,
    _gemini_otlp_env,
    _gemini_settings,
    generate_config,
)

_SAFE_NAME = re.compile(r"^[a-zA-Z0-9_-]+$")


def _sanitize_name(name: str) -> str:
    if _SAFE_NAME.match(name):
        return name
    return re.sub(r"[^a-zA-Z0-9_-]", "-", name)


def _inject_agent_id(mcp_config: dict, agent_id: str):
    """Add OBSERVAL_AGENT_ID env var to all MCP server entries."""
    for _name, cfg in mcp_config.items():
        if isinstance(cfg, dict):
            cfg.setdefault("env", {})
            cfg["env"]["OBSERVAL_AGENT_ID"] = agent_id


def _build_mcp_configs(agent: Agent, ide: str, observal_url: str, mcp_listings: dict | None = None) -> dict:
    """Build MCP server configs from registry components + external MCPs.

    Args:
        mcp_listings: optional {component_id: McpListing} map. When provided,
            used to look up MCP listings for each component. The install route
            pre-loads these to avoid N+1 queries in a sync context.
    """
    mcp_configs = {}
    mcp_listings = mcp_listings or {}

    for comp in agent.components:
        if comp.component_type != "mcp":
            continue
        listing = mcp_listings.get(comp.component_id)
        if not listing:
            continue
        cfg = generate_config(listing, ide, observal_url=observal_url)
        if "mcpServers" in cfg:
            mcp_configs.update(cfg["mcpServers"])

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
) -> dict:
    """Generate IDE-specific config for an agent.

    Args:
        mcp_listings: optional {component_id: McpListing} map pre-loaded by caller.
        component_names: optional {component_id_str: name} map for all component types.
    """
    safe_name = _sanitize_name(agent.name)
    mcp_configs = _build_mcp_configs(agent, ide, observal_url, mcp_listings=mcp_listings)
    rules_content = _build_rules_content(agent, component_names)

    if ide == "kiro":
        # Kiro agent JSON: drop into ~/.kiro/agents/<name>.json
        # Telemetry collected via observal-shim + hook bridge
        model_field = f',\\"model\\":\\"{agent.model_name}\\"' if agent.model_name else ""
        curl_cmd = (
            f"cat | sed 's/^{{/{{\"session_id\":\"kiro-'$PPID'\",\"service_name\":\"kiro-cli\","
            f"\"agent_name\":\"{safe_name}\"{model_field},/' "
            f"| curl -sf -X POST {observal_url}/api/v1/otel/hooks "
            f'-H "Content-Type: application/json" '
            f"-d @-"
        )
        # Stop hook: enrich with model/token data from Kiro SQLite DB.
        # Uses the observal CLI's enrichment script if installed, otherwise
        # falls back to the same curl command as other events.
        stop_cmd = (
            f"cat | sed 's/^{{/{{\"session_id\":\"kiro-'$PPID'\",\"service_name\":\"kiro-cli\","
            f"\"agent_name\":\"{safe_name}\"{model_field},/' "
            f"| python3 -m observal_cli.hooks.kiro_stop_hook "
            f"--url {observal_url}/api/v1/otel/hooks"
        )
        hooks = {
            "agentSpawn": [{"command": curl_cmd}],
            "userPromptSubmit": [{"command": curl_cmd}],
            "preToolUse": [{"matcher": "*", "command": curl_cmd}],
            "postToolUse": [{"matcher": "*", "command": curl_cmd}],
            "stop": [{"command": stop_cmd}],
        }
        result: dict = {
            "agent_file": {
                "path": f"~/.kiro/agents/{safe_name}.json",
                "content": {
                    "name": safe_name,
                    "description": agent.description[:200] if agent.description else "",
                    "prompt": agent.prompt,
                    "mcpServers": mcp_configs,
                    "tools": [f"@{n}" for n in mcp_configs] + ["read", "write", "shell"],
                    "hooks": hooks,
                    "includeMcpJson": True,
                    "model": agent.model_name,
                },
            },
        }
        # Also generate a Steering file for richer instruction support
        if agent.prompt:
            result["steering_file"] = {
                "path": f".kiro/steering/{safe_name}.md",
                "content": (
                    f"---\ninclusion: always\nname: {safe_name}\n"
                    f"description: {(agent.description or safe_name)[:100]}\n---\n\n"
                    f"{agent.prompt}"
                ),
            }
        return result

    if ide in ("claude-code", "claude_code"):
        otlp = _claude_otlp_env(observal_url)
        setup_commands = []
        claude_mcps = {}
        for name, cfg in mcp_configs.items():
            cmd = cfg.get("command", "observal-shim")
            args = cfg.get("args", [])
            setup_commands.append(["claude", "mcp", "add", name, "--", cmd, *args])
            claude_mcps[name] = {"command": cmd, "args": args, "env": cfg.get("env", {})}

        # Build Claude Code agent file with YAML frontmatter
        desc_line = (agent.description or safe_name).replace("\n", " ").strip()
        frontmatter_lines = [
            "---",
            f"name: {safe_name}",
            f"description: \"{desc_line}\"",
        ]
        if claude_mcps:
            frontmatter_lines.append("mcpServers:")
            for mcp_name in claude_mcps:
                frontmatter_lines.append(f"  - {mcp_name}")
        frontmatter_lines.append("---")
        agent_content = "\n".join(frontmatter_lines) + "\n\n" + rules_content

        return {
            "rules_file": {"path": f".claude/agents/{safe_name}.md", "content": agent_content},
            "mcp_config": claude_mcps,
            "mcp_setup_commands": setup_commands,
            "otlp_env": otlp,
            "claude_settings_snippet": {"env": otlp},
        }

    if ide in ("gemini-cli", "gemini_cli"):
        return {
            "rules_file": {"path": "GEMINI.md", "content": rules_content},
            "mcp_config": {"path": ".gemini/mcp.json", "content": {"mcpServers": mcp_configs}},
            "otlp_env": _gemini_otlp_env(observal_url),
            "gemini_settings_snippet": _gemini_settings(observal_url),
        }

    if ide == "codex":
        return {
            "rules_file": {"path": "AGENTS.md", "content": rules_content},
        }

    if ide == "copilot":
        return {
            "rules_file": {"path": ".github/copilot-instructions.md", "content": rules_content},
        }

    # cursor, vscode: rules file + mcp.json — telemetry via observal-shim
    ide_paths = {
        "cursor": (".cursor/rules/{name}.md", ".cursor/mcp.json"),
        "vscode": (".vscode/rules/{name}.md", ".vscode/mcp.json"),
    }
    rules_path, mcp_path = ide_paths.get(ide, (f".rules/{safe_name}.md", ".mcp.json"))
    return {
        "rules_file": {"path": rules_path.format(name=safe_name), "content": rules_content},
        "mcp_config": {"path": mcp_path, "content": {"mcpServers": mcp_configs}},
    }
