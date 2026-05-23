# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-FileCopyrightText: 2026 Naraen Rammoorthi <naraen13@gmail.com>
# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-FileCopyrightText: 2026 Shreem Seth <shreemseth26@gmail.com>
# SPDX-FileCopyrightText: 2026 Vishnu Muthiah <vishnu.muthiah04@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

from loguru import logger as optic


def generate_hook_telemetry_config(
    hook_listing, ide: str, server_url: str = "http://localhost:8000", platform: str = ""
) -> dict:
    optic.debug("generating hook telemetry config: ide={}, event={}", ide, hook_listing.event)
    if ide in ("kiro", "kiro-cli"):
        event = str(hook_listing.event)
        # Map Claude Code PascalCase events to Kiro camelCase
        kiro_event_map = {
            "SessionStart": "agentSpawn",
            "UserPromptSubmit": "userPromptSubmit",
            "PreToolUse": "preToolUse",
            "PostToolUse": "postToolUse",
            "Stop": "stop",
        }
        kiro_event = kiro_event_map.get(event, event)

        if platform == "win32":
            # PowerShell-compatible: pipe stdin through the Python hook script.
            # No cat/sed/curl/$PPID/$TERM/$SHELL — those don't exist in PowerShell.
            if kiro_event == "stop":
                ps_stop_cmd = f"python -m observal_cli.hooks.kiro_stop_hook --url {server_url}/api/v1/telemetry/hooks"
                return {"hooks": {kiro_event: [{"command": ps_stop_cmd}]}}

            ps_cmd = f"python -m observal_cli.hooks.kiro_hook --url {server_url}/api/v1/telemetry/hooks"
            hook_entry = {"command": ps_cmd}
            if kiro_event in ("preToolUse", "postToolUse"):
                hook_entry["matcher"] = "*"
            return {"hooks": {kiro_event: [hook_entry]}}

        # Unix: use the same Python hook scripts as Windows.
        if kiro_event == "stop":
            stop_cmd = f"python3 -m observal_cli.hooks.kiro_stop_hook --url {server_url}/api/v1/telemetry/hooks"
            return {"hooks": {kiro_event: [{"command": stop_cmd}]}}

        cmd = f"python3 -m observal_cli.hooks.kiro_hook --url {server_url}/api/v1/telemetry/hooks"
        hook_entry = {"command": cmd}
        if kiro_event in ("preToolUse", "postToolUse"):
            hook_entry["matcher"] = "*"
        return {"hooks": {kiro_event: [hook_entry]}}

    hook_entry = {
        "type": "http",
        "url": f"{server_url}/api/v1/telemetry/hooks",
        "timeout": 10,
    }

    if ide == "claude-code":
        hook_entry["allowedEnvVars"] = ["OBSERVAL_API_KEY"]
    elif ide != "cursor":
        return {"comment": f"IDE '{ide}' requires manual hook setup. See Observal docs for configuration."}

    event = str(hook_listing.event)
    return {"hooks": {event: [{"matcher": "*", "hooks": [hook_entry]}]}}
