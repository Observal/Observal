# SPDX-FileCopyrightText: 2026 Aryan Iyappan <aryaniyappan2006@gmail.com>
# SPDX-FileCopyrightText: 2026 Subramania Raja <dhanpraja231@gmail.com>
# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-License-Identifier: Apache-2.0

import re

from loguru import logger as optic

from models.mcp import McpListing
from services.shared.utils import sanitize_name as _sanitize_name

_SHELL_META_RE = re.compile(r"[|;&`><\n\r]|\$\(|\$\{")
_DANGEROUS_CMD_RE = re.compile(
    r"^(?:curl|wget|bash|sh|zsh|fish|dash|python|perl|ruby|nc|ncat|netcat|powershell|cmd\.exe)$",
    re.IGNORECASE,
)


def validate_mcp_command(command: str, args: list[str] | None = None) -> None:
    """Raise ValueError if command contains shell metacharacters or uses a dangerous program."""
    optic.trace("validating MCP command: {} {}", command, args)
    if not command:
        return
    full = " ".join([command, *list(args or [])])
    if _SHELL_META_RE.search(full):
        raise ValueError("MCP command contains shell metacharacters")
    cmd_base = command.strip().split()[0] if command.strip() else ""
    if _DANGEROUS_CMD_RE.match(cmd_base):
        raise ValueError(f"MCP command uses a disallowed program: {cmd_base!r}")


_DOLLAR_VAR = re.compile(r"\$\{([A-Z][A-Z0-9_]+)\}|\$([A-Z][A-Z0-9_]+)")


def _substitute_dollar_vars(args: list[str], env: dict[str, str] | None) -> list[str]:
    """Replace $VAR and ${VAR} patterns in args with values from env dict."""
    optic.trace("substituting dollar vars in {} args", len(args))
    if not env:
        return list(args)

    def _replacer(m: re.Match) -> str:
        optic.trace("replacing variable: {}", m.group(0))
        var_name = m.group(1) or m.group(2)
        return env.get(var_name, m.group(0))  # keep original if no value

    return [_DOLLAR_VAR.sub(_replacer, arg) for arg in args]


def _build_run_command(
    name: str,
    framework: str | None,
    docker_image: str | None = None,
    server_env: dict[str, str] | None = None,
    stored_command: str | None = None,
    stored_args: list[str] | None = None,
) -> list[str]:
    """Return the appropriate run command based on the MCP framework.

    - Stored command/args: use as-is (set during analysis or by publisher)
    - Docker: docker run -i --rm [-e KEY=VAL ...] <image>
    - TypeScript: npx -y <name>
    - Go: <name> (assumes binary on PATH)
    - Python / unknown: python -m <name>
    """
    optic.trace("building run command for {} (framework={}, docker={})", name, framework, docker_image)
    # Use stored command/args if available, substituting $VAR placeholders
    if stored_command is not None:
        cmd = [stored_command]
        if stored_args:
            cmd.extend(_substitute_dollar_vars(stored_args, server_env))
        return cmd

    # Legacy path: infer from framework/docker_image
    fw = (framework or "").lower()
    if docker_image:
        cmd = ["docker", "run", "-i", "--rm"]
        for k, v in (server_env or {}).items():
            cmd.extend(["-e", f"{k}={v}"])
        cmd.append(docker_image)
        return cmd
    if "typescript" in fw or "ts" in fw:
        return ["npx", "-y", name]
    if "go" in fw:
        return [name]
    return ["python", "-m", name]


def _build_server_env(listing: McpListing, env_values: dict[str, str] | None = None) -> dict[str, str]:
    """Build env dict from the listing's declared environment_variables and user-supplied values."""
    optic.trace("building server env for MCP listing")
    env: dict[str, str] = {}
    for var in listing.environment_variables or []:
        name = var["name"] if isinstance(var, dict) else var.name
        env[name] = (env_values or {}).get(name, "")
    return env


def generate_config(
    listing: McpListing,
    harness: str,
    proxy_port: int | None = None,
    observal_url: str = "",
    env_values: dict[str, str] | None = None,
    header_values: dict[str, str] | None = None,
) -> dict:
    optic.debug("generating MCP config for harness={}", harness)
    name = _sanitize_name(listing.name)
    mcp_id = str(listing.id)
    server_env = _build_server_env(listing, env_values)

    # SSE / streamable-http transport: point harness at the remote URL
    if listing.url and (listing.transport or "").lower() in ("sse", "streamable-http", ""):
        transport_type = (listing.transport or "sse").lower()
        config: dict = {"type": transport_type, "url": listing.url}
        if header_values:
            config["headers"] = header_values
        if server_env:
            config["env"] = server_env
        if listing.auto_approve:
            config["autoApprove"] = listing.auto_approve
        config["disabled"] = False

        if harness == "claude-code":
            return {
                "command": ["claude", "mcp", "add", name, "--url", listing.url],
                "type": "shell_command",
                "claude_settings_snippet": {"env": server_env} if server_env else {},
                "mcpServers": {name: config},
            }
        if harness == "copilot":
            return {"mcpServers": {name: {**config, "type": transport_type}}}
        if harness == "copilot-cli":
            return {"mcpServers": {name: {**config, "type": transport_type, "tools": ["*"]}}}
        if harness == "opencode":
            opencode_config: dict = {"type": "remote", "url": listing.url}
            if header_values:
                opencode_config["headers"] = header_values
            if server_env:
                opencode_config["env"] = server_env
            return {"mcp": {name: opencode_config}}
        if harness == "codex":
            codex_entry: dict = {"url": listing.url}
            if header_values:
                codex_entry["headers"] = header_values
            if server_env:
                codex_entry["env"] = server_env
            return {
                "mcp_servers": {name: codex_entry},
            }
        return {"mcpServers": {name: config}}

    # HTTP proxy transport (existing): point harness at the proxy URL
    if proxy_port is not None:
        proxy_url = f"http://localhost:{proxy_port}"
        if harness == "claude-code":
            return {
                "command": ["claude", "mcp", "add", name, "--url", proxy_url],
                "type": "shell_command",
            }
        if harness == "codex":
            return {
                "mcp_servers": {name: {"url": proxy_url, "env": server_env}},
            }
        if harness == "copilot":
            return {"mcpServers": {name: {"type": "sse", "url": proxy_url, "env": server_env}}}
        if harness == "copilot-cli":
            return {"mcpServers": {name: {"type": "sse", "url": proxy_url, "env": server_env, "tools": ["*"]}}}
        if harness == "opencode":
            return {"mcp": {name: {"type": "remote", "url": proxy_url, "env": server_env}}}
        return {"mcpServers": {name: {"url": proxy_url, "env": server_env}}}

    # Stdio transport: shim wraps the original command
    run_cmd = _build_run_command(
        name,
        listing.framework,
        listing.docker_image,
        server_env,
        stored_command=listing.command,
        stored_args=listing.args,
    )
    shim_args = ["--mcp-id", mcp_id, "--", *run_cmd]

    auto_approve_fields: dict = {}
    if listing.auto_approve:
        auto_approve_fields = {"autoApprove": listing.auto_approve, "disabled": False}

    if harness == "claude-code":
        return {
            "command": ["claude", "mcp", "add", name, "--", "observal-shim", *shim_args],
            "type": "shell_command",
        }
    if harness == "codex":
        return {
            "mcp_servers": {
                name: {"command": "observal-shim", "args": shim_args, "env": server_env, **auto_approve_fields}
            },
        }

    if harness == "copilot":
        return {
            "mcpServers": {
                name: {
                    "type": "stdio",
                    "command": "observal-shim",
                    "args": shim_args,
                    "env": server_env,
                    **auto_approve_fields,
                }
            },
        }

    if harness == "copilot-cli":
        return {
            "mcpServers": {
                name: {
                    "type": "stdio",
                    "command": "observal-shim",
                    "args": shim_args,
                    "env": server_env,
                    "tools": ["*"],
                    **auto_approve_fields,
                }
            },
        }

    if harness == "opencode":
        flat_cmd = ["observal-shim", *shim_args]
        entry: dict = {"type": "local", "command": flat_cmd}
        if server_env:
            entry["environment"] = server_env
        return {"mcp": {name: entry}}

    # cursor, kiro: telemetry collected via observal-shim
    return {
        "mcpServers": {name: {"command": "observal-shim", "args": shim_args, "env": server_env, **auto_approve_fields}}
    }
