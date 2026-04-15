def generate_skill_config(skill_listing, ide: str, server_url: str = "http://localhost:8000") -> dict:
    """Generate config snippet for skill telemetry via SessionStart/End hooks."""
    skill_id = str(skill_listing.id)
    skill_name = str(skill_listing.name)

    hook_entry = {
        "type": "http",
        "url": f"{server_url}/api/v1/telemetry/hooks",
        "headers": {
            "Authorization": "Bearer $OBSERVAL_ACCESS_TOKEN",
            "X-Observal-Skill-Id": skill_id,
        },
        "timeout": 10,
    }
    if ide == "claude-code":
        hook_entry["allowedEnvVars"] = ["OBSERVAL_ACCESS_TOKEN"]

    config = {
        "hooks": {
            "SessionStart": [{"matcher": "*", "hooks": [hook_entry]}],
            "SessionEnd": [{"matcher": "*", "hooks": [hook_entry]}],
        },
        "skill": {"name": skill_name, "id": skill_id},
        "ide": ide,
        "listing_id": skill_id,
    }

    # For Kiro, also include the skill path for auto-loading
    git_url = getattr(skill_listing, "git_url", None)
    if git_url:
        config["skill"]["git_url"] = git_url
    skill_path = getattr(skill_listing, "skill_path", None)
    if skill_path:
        config["skill"]["skill_path"] = skill_path

    return config
