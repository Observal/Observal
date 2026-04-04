def generate_sandbox_config(sandbox_listing, ide: str, server_url: str = "http://localhost:8000") -> dict:
    """Generate config snippet that wraps sandbox execution with observal-sandbox-run."""
    sandbox_id = str(sandbox_listing.id)
    image = str(sandbox_listing.image)
    entrypoint = getattr(sandbox_listing, "entrypoint", None)
    resource_limits = getattr(sandbox_listing, "resource_limits", {}) or {}
    timeout = resource_limits.get("timeout", 300)

    base = {
        "command": "observal-sandbox-run",
        "args": ["--sandbox-id", sandbox_id, "--image", image, "--timeout", str(timeout)],
        "env": {
            "OBSERVAL_KEY": "$OBSERVAL_API_KEY",
            "OBSERVAL_SERVER": server_url,
        },
    }
    if entrypoint:
        base["args"].extend(["--command", entrypoint])

    return {"sandbox": base, "ide": ide, "listing_id": sandbox_id}
