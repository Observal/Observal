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


def generate_agent_config(
    agent: Agent,
    ide: str,
    observal_url: str = "http://localhost:8000",
    mcp_listings: dict | None = None,
) -> dict:
    """Generate IDE-specific config for an agent.

    Args:
        mcp_listings: optional {component_id: McpListing} map pre-loaded by caller.
    """
    safe_name = _sanitize_name(agent.name)
    mcp_configs = _build_mcp_configs(agent, ide, observal_url, mcp_listings=mcp_listings)

    if ide == "kiro":
        # Kiro agent JSON: drop into ~/.kiro/agents/<name>.json
        # Telemetry collected via observal-shim, no native OTel
        return {
            "agent_file": {
                "path": f"~/.kiro/agents/{safe_name}.json",
                "content": {
                    "name": safe_name,
                    "description": agent.description[:200] if agent.description else "",
                    "prompt": agent.prompt,
                    "mcpServers": mcp_configs,
                    "tools": [f"@{n}" for n in mcp_configs] + ["read", "write", "shell"],
                    "hooks": {},
                    "includeMcpJson": True,
                    "model": agent.model_name,
                },
            },
        }

    if ide in ("claude-code", "claude_code"):
        otlp = _claude_otlp_env(observal_url)
        setup_commands = []
        claude_mcps = {}
        for name, cfg in mcp_configs.items():
            cmd = cfg.get("command", "observal-shim")
            args = cfg.get("args", [])
            setup_commands.append(["claude", "mcp", "add", name, "--", cmd, *args])
            claude_mcps[name] = {"command": cmd, "args": args, "env": cfg.get("env", {})}
        return {
            "rules_file": {"path": f".claude/rules/{safe_name}.md", "content": agent.prompt},
            "mcp_config": claude_mcps,
            "mcp_setup_commands": setup_commands,
            "otlp_env": otlp,
            "claude_settings_snippet": {"env": otlp},
        }

    if ide in ("gemini-cli", "gemini_cli"):
        return {
            "rules_file": {"path": "GEMINI.md", "content": agent.prompt},
            "mcp_config": {"path": ".gemini/mcp.json", "content": {"mcpServers": mcp_configs}},
            "otlp_env": _gemini_otlp_env(observal_url),
            "gemini_settings_snippet": _gemini_settings(observal_url),
        }

    if ide == "codex":
        return {
            "rules_file": {"path": "AGENTS.md", "content": agent.prompt},
        }

    if ide == "copilot":
        return {
            "rules_file": {"path": ".github/copilot-instructions.md", "content": agent.prompt},
        }

    # cursor, vscode: rules file + mcp.json — telemetry via observal-shim
    ide_paths = {
        "cursor": (".cursor/rules/{name}.md", ".cursor/mcp.json"),
        "vscode": (".vscode/rules/{name}.md", ".vscode/mcp.json"),
    }
    rules_path, mcp_path = ide_paths.get(ide, (f".rules/{safe_name}.md", ".mcp.json"))
    return {
        "rules_file": {"path": rules_path.format(name=safe_name), "content": agent.prompt},
        "mcp_config": {"path": mcp_path, "content": {"mcpServers": mcp_configs}},
    }
