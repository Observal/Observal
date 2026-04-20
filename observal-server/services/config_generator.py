import re

from models.mcp import McpListing
from services.codex_config_generator import generate_codex_config

_SAFE_NAME = re.compile(r"^[a-zA-Z0-9_-]+$")
_DOLLAR_VAR = re.compile(r"\$\{([A-Z][A-Z0-9_]+)\}|\$([A-Z][A-Z0-9_]+)")


def _sanitize_name(name: str) -> str:
    if _SAFE_NAME.match(name):
        return name
    return re.sub(r"[^a-zA-Z0-9_-]", "-", name)


def _otlp_env(observal_url: str) -> dict:
    """OTLP env vars for IDEs with native OpenTelemetry support."""
    return {
        "OTEL_EXPORTER_OTLP_ENDPOINT": observal_url,
        "OTEL_EXPORTER_OTLP_PROTOCOL": "http/json",
        "OTEL_METRICS_EXPORTER": "otlp",
        "OTEL_LOGS_EXPORTER": "otlp",
        "OTEL_TRACES_EXPORTER": "otlp",
    }


def _claude_otlp_env(observal_url: str) -> dict:
    """Claude Code specific OTLP env vars."""
    return {
        "CLAUDE_CODE_ENABLE_TELEMETRY": "1",
        "CLAUDE_CODE_ENHANCED_TELEMETRY_BETA": "1",
        "OTEL_LOG_USER_PROMPTS": "1",
        "OTEL_LOG_TOOL_DETAILS": "1",
        "OTEL_LOG_TOOL_CONTENT": "1",
        "OTEL_EXPORTER_OTLP_ENDPOINT": "http://localhost:4318",
        "OTEL_EXPORTER_OTLP_PROTOCOL": "http/json",
        "OTEL_METRICS_EXPORTER": "otlp",
        "OTEL_LOGS_EXPORTER": "otlp",
        "OTEL_TRACES_EXPORTER": "otlp",
    }


def _gemini_otlp_env(observal_url: str) -> dict:
    """Gemini CLI specific OTLP env vars."""
    return _otlp_env(observal_url)


def _gemini_settings(observal_url: str) -> dict:
    """Gemini CLI .gemini/settings.json telemetry block."""
    return {
        "telemetry": {
            "enabled": True,
            "target": "custom",
            "otlpEndpoint": "http://localhost:4318",
            "logPrompts": True,
        }
    }


def _substitute_dollar_vars(args: list[str], env: dict[str, str] | None) -> list[str]:
    """Replace $VAR and ${VAR} patterns in args with values from env dict."""
    if not env:
        return list(args)

    def _replacer(m: re.Match) -> str:
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
    env: dict[str, str] = {}
    for var in listing.environment_variables or []:
        name = var["name"] if isinstance(var, dict) else var.name
        env[name] = (env_values or {}).get(name, "")
    return env


def generate_config(
    listing: McpListing,
    ide: str,
    proxy_port: int | None = None,
    observal_url: str = "http://localhost:4318",
    env_values: dict[str, str] | None = None,
    header_values: dict[str, str] | None = None,
) -> dict:
    name = _sanitize_name(listing.name)
    mcp_id = str(listing.id)
    server_env = _build_server_env(listing, env_values)

    # SSE / streamable-http transport: point IDE at the remote URL
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

        if ide == "claude-code":
            return {
                "command": ["claude", "mcp", "add", name, "--url", listing.url],
                "type": "shell_command",
                "claude_settings_snippet": {"env": server_env} if server_env else {},
                "mcpServers": {name: config},
            }
        return {"mcpServers": {name: config}}

    # HTTP proxy transport (existing): point IDE at the proxy URL
    if proxy_port is not None:
        proxy_url = f"http://localhost:{proxy_port}"
        if ide == "claude-code":
            return {
                "command": ["claude", "mcp", "add", name, "--url", proxy_url],
                "type": "shell_command",
                "otlp_env": _claude_otlp_env(observal_url),
                "claude_settings_snippet": {"env": {**_claude_otlp_env(observal_url), **server_env}},
            }
        if ide == "gemini-cli":
            return {
                "mcpServers": {name: {"url": proxy_url, "env": server_env}},
                "otlp_env": _gemini_otlp_env(observal_url),
                "gemini_settings_snippet": _gemini_settings(observal_url),
            }
        if ide == "codex":
            return {
                "mcpServers": {name: {"url": proxy_url, "env": server_env}},
                "codex_config": generate_codex_config(observal_url),
            }
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

    if ide == "claude-code":
        otlp = _claude_otlp_env(observal_url)
        combined_env = {**otlp, **server_env}
        env_prefix = " ".join(f"{k}={v}" for k, v in combined_env.items())
        return {
            "command": ["claude", "mcp", "add", name, "--", "observal-shim", *shim_args],
            "type": "shell_command",
            "shell_env_prefix": env_prefix,
            "otlp_env": otlp,
            "claude_settings_snippet": {"env": combined_env},
        }
    if ide == "gemini-cli":
        return {
            "mcpServers": {
                name: {"command": "observal-shim", "args": shim_args, "env": server_env, **auto_approve_fields}
            },
            "otlp_env": _gemini_otlp_env(observal_url),
            "gemini_settings_snippet": _gemini_settings(observal_url),
        }
    if ide == "codex":
        return {
            "mcpServers": {
                name: {"command": "observal-shim", "args": shim_args, "env": server_env, **auto_approve_fields}
            },
            "codex_config": generate_codex_config(observal_url),
        }

    # cursor, vscode, kiro, kiro-cli — no native OTel; telemetry collected via observal-shim
    return {
        "mcpServers": {name: {"command": "observal-shim", "args": shim_args, "env": server_env, **auto_approve_fields}}
    }
