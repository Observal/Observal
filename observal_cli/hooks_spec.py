"""Declarative hook specification for Claude Code settings.

Defines the desired state of Observal-managed hooks. The reconciler
compares this spec against the user's current ~/.claude/settings.json
and applies non-destructive updates: adding missing hooks, upgrading
stale ones, and preserving any non-Observal hooks the user has added.

Bump HOOKS_SPEC_VERSION whenever the hook definitions change so the
reconciler knows to re-apply.
"""

from __future__ import annotations

# Bump this when hook definitions change (new events, different scripts,
# additional handlers, etc.).  Stored in ~/.observal/config.json so we
# can detect when an upgrade is needed without re-reading all hooks.
HOOKS_SPEC_VERSION = "5"

# Metadata key injected into every Observal matcher group.
# Primary identification method — the reconciler checks this first.
OBSERVAL_METADATA_KEY = "_observal"

# Legacy marker substrings used as a fallback for matcher groups
# created before metadata injection was added (pre-v3 upgrades).
_LEGACY_HOOK_MARKERS = ("observal-hook", "observal-stop-hook", "/api/v1/otel/hooks")


def is_observal_hook_entry(hook_entry: dict) -> bool:
    """Return True if a single hook handler dict belongs to Observal (legacy path check)."""
    cmd = hook_entry.get("command", "")
    url = hook_entry.get("url", "")
    return any(m in cmd or m in url for m in _LEGACY_HOOK_MARKERS)


def is_observal_matcher_group(matcher_group: dict) -> bool:
    """Return True if a matcher group is Observal-managed.

    Checks the _observal metadata key first (preferred), then falls
    back to legacy path-based detection for pre-metadata installations.
    """
    # Primary: metadata marker
    if OBSERVAL_METADATA_KEY in matcher_group:
        return True
    # Fallback: legacy path matching
    return any(is_observal_hook_entry(hook_entry) for hook_entry in matcher_group.get("hooks", []))


def get_desired_hooks(
    hook_script: str | None,
    stop_script: str | None,
    hooks_url: str,
    user_id: str = "",
) -> dict[str, list[dict]]:
    """Return the full desired hooks spec for Claude Code settings.

    Each event maps to a list of matcher groups.  The Stop event gets
    two handlers: the generic hook (for basic hook_stop events) and the
    stop-specific hook (for transcript-based response/thinking capture).
    """
    meta = {OBSERVAL_METADATA_KEY: {"version": HOOKS_SPEC_VERSION}}

    if hook_script:
        generic = {"type": "command", "command": hook_script}
    else:
        # Fallback to HTTP if scripts aren't found
        generic = {"type": "http", "url": hooks_url}
        if user_id:
            generic["headers"] = {"X-Observal-User-Id": user_id}

    generic_group: list[dict] = [{**meta, "hooks": [generic]}]

    # Stop event: generic hook first (always fires), then stop-specific
    # hook for transcript parsing (response + thinking capture).
    # Each must be in its own matcher group so they receive independent
    # copies of stdin (a single group shares one stdin pipe).
    if stop_script:
        stop_group: list[dict] = [
            {**meta, "hooks": [generic]},
            {**meta, "hooks": [{"type": "command", "command": stop_script}]},
        ]
    else:
        stop_group = generic_group

    return {
        "SessionStart": generic_group,
        "UserPromptSubmit": generic_group,
        "PreToolUse": generic_group,
        "PostToolUse": generic_group,
        "PostToolUseFailure": generic_group,
        "SubagentStart": generic_group,
        "SubagentStop": generic_group,
        "Stop": stop_group,
        "StopFailure": generic_group,
        "Notification": generic_group,
        "TaskCreated": generic_group,
        "TaskCompleted": generic_group,
        "PreCompact": generic_group,
        "PostCompact": generic_group,
        "WorktreeCreate": generic_group,
        "WorktreeRemove": generic_group,
        "Elicitation": generic_group,
        "ElicitationResult": generic_group,
    }


def get_desired_env(
    server_url: str,
    hooks_token: str,
    user_id: str = "",
    user_name: str = "",
    otlp_grpc_url: str = "",
) -> dict[str, str]:
    """Return the desired Observal env vars for Claude Code settings."""
    if otlp_grpc_url:
        otel_endpoint = otlp_grpc_url
    else:
        from urllib.parse import urlparse

        parsed = urlparse(server_url)
        scheme = parsed.scheme or ("http" if parsed.hostname in ("localhost", "127.0.0.1") else "https")
        otel_endpoint = f"{scheme}://{parsed.hostname}:4317"

    env: dict[str, str] = {
        "CLAUDE_CODE_ENABLE_TELEMETRY": "1",
        "OTEL_METRICS_EXPORTER": "otlp",
        "OTEL_LOGS_EXPORTER": "otlp",
        "OTEL_EXPORTER_OTLP_PROTOCOL": "grpc",
        "OTEL_EXPORTER_OTLP_HEADERS": f"Authorization=Bearer {hooks_token}",
        "OTEL_EXPORTER_OTLP_ENDPOINT": otel_endpoint,
        "OBSERVAL_HOOKS_URL": f"{server_url.rstrip('/')}/api/v1/otel/hooks",
    }
    env["OBSERVAL_HOOKS_SPEC_VERSION"] = HOOKS_SPEC_VERSION
    if user_id:
        env["OBSERVAL_USER_ID"] = user_id
        env["OTEL_RESOURCE_ATTRIBUTES"] = f"user.id={user_id}"
    if user_name:
        env["OBSERVAL_USERNAME"] = user_name

    return env


# Keys in settings.env that Observal manages.  Used by the reconciler
# to know which env vars it can safely update without touching others.
MANAGED_ENV_KEYS = frozenset(
    {
        "CLAUDE_CODE_ENABLE_TELEMETRY",
        "OTEL_METRICS_EXPORTER",
        "OTEL_LOGS_EXPORTER",
        "OTEL_EXPORTER_OTLP_PROTOCOL",
        "OTEL_EXPORTER_OTLP_HEADERS",
        "OTEL_EXPORTER_OTLP_ENDPOINT",
        "OTEL_RESOURCE_ATTRIBUTES",
        "OBSERVAL_HOOKS_URL",
        "OBSERVAL_HOOKS_SPEC_VERSION",
        "OBSERVAL_USER_ID",
        "OBSERVAL_USERNAME",
    }
)
