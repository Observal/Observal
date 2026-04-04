def generate_tool_config(tool_listing, ide: str, server_url: str = "http://localhost:8000") -> dict:
    """Generate config snippet for standalone tool telemetry.

    HTTP tools: wrap endpoint_url with observal-proxy.
    Non-HTTP tools: emit a PostToolUse hook pointing at our ingest endpoint.
    """
    tool_id = str(tool_listing.id)
    tool_name = str(tool_listing.name)
    endpoint_url = getattr(tool_listing, "endpoint_url", None)

    if endpoint_url:
        # HTTP tool: use observal-proxy
        return {
            "tool": {
                "proxy_url": "http://localhost:0",
                "original_endpoint": endpoint_url,
                "start_command": f"observal-proxy --mcp-id {tool_id} --target {endpoint_url}",
            },
            "env": {"OBSERVAL_KEY": "$OBSERVAL_API_KEY", "OBSERVAL_SERVER": server_url},
            "ide": ide,
            "listing_id": tool_id,
        }

    # Non-HTTP tool: emit PostToolUse hook
    hook_entry = {
        "type": "http",
        "url": f"{server_url}/api/v1/telemetry/hooks",
        "headers": {"X-API-Key": "$OBSERVAL_API_KEY", "X-Observal-Tool-Id": tool_id},
        "timeout": 10,
    }
    if ide == "claude-code":
        hook_entry["allowedEnvVars"] = ["OBSERVAL_API_KEY"]

    return {
        "hooks": {
            "PostToolUse": [{"matcher": tool_name, "hooks": [hook_entry]}],
        },
        "ide": ide,
        "listing_id": tool_id,
    }
