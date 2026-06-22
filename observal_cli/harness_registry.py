# SPDX-FileCopyrightText: 2026 Aryan Iyappan <aryaniyappan2006@gmail.com>
# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-FileCopyrightText: 2026 Kaushik Kumar <kaushikrjpm10@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Centralized harness registry -- CLI mirror of schemas/harness_registry.py.

This is kept in sync with ``observal-server/schemas/harness_registry.py``
by ``tests/test_constants_sync.py``.  When adding a new harness, update
the server copy first, then mirror the change here.
"""

from __future__ import annotations

import json
from pathlib import Path


def supported_model_ids(harness: str) -> list[str]:
    try:
        from observal_shared.harness_models import supported_model_ids as _ids

        return _ids(harness)
    except ModuleNotFoundError:
        path = (
            Path(__file__).resolve().parents[1]
            / "packages/observal-shared/observal_shared/harness_models"
            / f"{harness}.json"
        )
        return [row["id"] for row in json.loads(path.read_text()).get("models", [])]


HARNESS_REGISTRY: dict[str, dict] = {
    "cursor": {
        "display_name": "Cursor",
        "session_parser": "cursor",
        "capabilities": {"hooks", "mcp_servers"},
        "scopes": ["project", "user"],
        "default_scope": "project",
        "scope_labels": ("project (.cursor/agents/)", "user (~/.cursor/agents/)"),
        "agent_profile": {
            "project": ".cursor/agents/{name}.md",
            "user": "~/.cursor/agents/{name}.md",
        },
        "agent_profile_format": "markdown_frontmatter",
        "mcp_config": {
            "project": ".cursor/mcp.json",
            "user": "~/.cursor/mcp.json",
        },
        "mcp_servers_key": "mcpServers",
        "skills": {
            "project": ".cursor/skills/{name}/SKILL.md",
            "user": "~/.cursor/skills/{name}/SKILL.md",
        },
        "skill_format": "yaml_frontmatter",
        "home_mcp_config": "~/.cursor/mcp.json",
        "hook_type": "command",
        "hooks": {
            "project": ".cursor/hooks.json",
            "user": "~/.cursor/hooks.json",
        },
        "hook_scripts_dir": ".cursor/hooks",
        "hook_events_map": {
            "PreToolUse": "preToolUse",
            "PostToolUse": "postToolUse",
            "Stop": "sessionEnd",
            "SessionStart": "sessionStart",
            "UserPromptSubmit": "beforeSubmitPrompt",
            "SubagentStop": "subagentStop",
        },
        "config_dir": ".cursor",
    },
    "kiro": {
        "display_name": "Kiro",
        "session_parser": "kiro",
        "capabilities": {"hooks", "mcp_servers"},
        "scopes": ["project", "user"],
        "default_scope": "user",
        "scope_labels": ("project (.kiro/agents/)", "user (~/.kiro/agents/)"),
        "agent_profile": {
            "project": ".kiro/agents/{name}.json",
            "user": "~/.kiro/agents/{name}.json",
        },
        "agent_profile_format": "json",
        "mcp_config": {
            "project": ".kiro/settings/mcp.json",
            "user": "~/.kiro/settings/mcp.json",
        },
        "mcp_servers_key": "mcpServers",
        "skills": {
            "project": ".kiro/skills/{name}/SKILL.md",
            "user": "~/.kiro/skills/{name}/SKILL.md",
        },
        "skill_format": "yaml_frontmatter",
        "home_mcp_config": "~/.kiro/settings/mcp.json",
        "hook_type": "command",
        "hooks": {
            "project": ".kiro/hooks/{name}.json",
            "user": "~/.kiro/hooks/{name}.json",
        },
        "hook_scripts_dir": ".kiro/hooks",
        "hook_events_map": {
            "PreToolUse": "preToolUse",
            "PostToolUse": "postToolUse",
            "Stop": "stop",
            "SessionStart": "agentSpawn",
            "UserPromptSubmit": "userPromptSubmit",
        },
        "config_dir": ".kiro",
    },
    "claude-code": {
        "display_name": "Claude Code",
        "session_parser": "claude-code",
        "capabilities": {"skills", "hooks", "mcp_servers"},
        "scopes": ["project", "user"],
        "default_scope": "project",
        "scope_labels": ("project (.claude/agents/)", "user (~/.claude/agents/)"),
        "agent_profile": {
            "project": ".claude/agents/{name}.md",
            "user": "~/.claude/agents/{name}.md",
        },
        "agent_profile_format": "yaml_frontmatter",
        "mcp_config": {
            "project": None,
            "user": None,
        },
        "mcp_servers_key": "mcpServers",
        "skills": {
            "project": ".claude/skills/{name}/SKILL.md",
            "user": "~/.claude/skills/{name}/SKILL.md",
        },
        "skill_format": "yaml_frontmatter",
        "home_mcp_config": "~/.claude.json",
        "hook_type": "command",
        "hooks": {
            "project": ".claude/settings.json",
            "user": "~/.claude/settings.json",
        },
        "hook_scripts_dir": ".claude/hooks",
        "hook_events_map": {
            "PreToolUse": "PreToolUse",
            "PostToolUse": "PostToolUse",
            "Stop": "Stop",
            "SessionStart": "SessionStart",
            "UserPromptSubmit": "UserPromptSubmit",
            "Notification": "Notification",
            "SubagentStop": "SubagentStop",
        },
        "config_dir": ".claude",
    },
    "codex": {
        "display_name": "Codex",
        "session_parser": "codex",
        "capabilities": {"mcp_servers", "hooks", "skills"},
        "scopes": ["project", "user"],
        "default_scope": "project",
        "scope_labels": ("project (.codex/agents/)", "user (~/.codex/agents/)"),
        "agent_profile": {
            "project": ".codex/agents/{name}.toml",
            "user": "~/.codex/agents/{name}.toml",
        },
        "agent_profile_format": "toml",
        "mcp_config": {
            "project": ".codex/config.toml",
            "user": "~/.codex/config.toml",
        },
        "mcp_servers_key": "mcp_servers",
        "skills": {
            "project": ".agents/skills/{name}/SKILL.md",
            "user": "~/.agents/skills/{name}/SKILL.md",
        },
        "skill_format": "yaml_frontmatter",
        "home_mcp_config": "~/.codex/config.toml",
        "hook_type": "command",
        "hooks": {
            "project": ".codex/hooks.json",
            "user": "~/.codex/hooks.json",
        },
        "hook_scripts_dir": ".codex/hooks",
        "hook_events_map": {
            "UserPromptSubmit": "UserPromptSubmit",
            "PreToolUse": "PreToolUse",
            "PostToolUse": "PostToolUse",
            "Stop": "Stop",
        },
        "config_dir": ".codex",
    },
    "copilot": {
        "display_name": "Copilot",
        "session_parser": "copilot-cli",
        "capabilities": {"mcp_servers", "hooks", "skills"},
        "scopes": ["project"],
        "default_scope": "project",
        "scope_labels": None,
        "agent_profile": {
            "project": ".github/agents/{name}.agent.md",
        },
        "agent_profile_format": "markdown",
        "mcp_config": {
            "project": ".vscode/mcp.json",
        },
        "mcp_servers_key": "servers",
        "skills": {
            "project": ".github/skills/{name}/SKILL.md",
            "user": "~/.copilot/skills/{name}/SKILL.md",
        },
        "skill_format": "yaml_frontmatter",
        "home_mcp_config": "~/.vscode/mcp.json",
        "hook_type": "command",
        "hooks": {
            "project": ".github/hooks/{name}.json",
            "user": "~/.copilot/hooks/{name}.json",
        },
        "hook_scripts_dir": ".github/hooks/scripts",
        "hook_events_map": {
            "SessionStart": "SessionStart",
            "UserPromptSubmit": "UserPromptSubmit",
            "PreToolUse": "PreToolUse",
            "PostToolUse": "PostToolUse",
            "Stop": "Stop",
        },
        "config_dir": ".vscode",
    },
    "copilot-cli": {
        "display_name": "Copilot CLI",
        "session_parser": "copilot-cli",
        "capabilities": {"mcp_servers", "hooks", "skills"},
        "scopes": ["project"],
        "default_scope": "project",
        "scope_labels": None,
        "agent_profile": {
            "project": ".github/agents/{name}.agent.md",
        },
        "agent_profile_format": "markdown",
        "mcp_config": {
            "project": "~/.copilot/mcp-config.json",
        },
        "mcp_servers_key": "mcpServers",
        "skills": {
            "project": ".agents/skills/{name}/SKILL.md",
            "user": "~/.copilot/skills/{name}/SKILL.md",
        },
        "skill_format": "yaml_frontmatter",
        "home_mcp_config": "~/.copilot/mcp-config.json",
        "hook_type": "command",
        "hooks": {
            "project": ".github/hooks/{name}.json",
            "user": "~/.copilot/hooks/{name}.json",
        },
        "hook_scripts_dir": ".github/hooks/scripts",
        "hook_events_map": {
            "SessionStart": "sessionStart",
            "UserPromptSubmit": "userPromptSubmitted",
            "PreToolUse": "preToolUse",
            "PostToolUse": "postToolUse",
            "Stop": "sessionEnd",
        },
        "config_dir": ".copilot",
    },
    "opencode": {
        "display_name": "OpenCode",
        "session_parser": "opencode",
        "capabilities": {"skills", "hooks", "mcp_servers"},
        "scopes": ["project", "user"],
        "default_scope": "user",
        "scope_labels": ("project (.opencode/agents/<name>.md)", "user (~/.config/opencode/agents/<name>.md)"),
        "agent_profile": {
            "project": ".opencode/agents/{name}.md",
            "user": "~/.config/opencode/agents/{name}.md",
        },
        "agent_profile_format": "markdown",
        "mcp_config": {
            "project": "opencode.json",
            "user": "~/.config/opencode/opencode.json",
        },
        "mcp_servers_key": "mcp",
        "skills": {
            "project": ".opencode/skills/{name}/SKILL.md",
            "user": "~/.config/opencode/skills/{name}/SKILL.md",
        },
        "skill_format": "yaml_frontmatter",
        "home_mcp_config": "~/.config/opencode/opencode.json",
        "hook_type": "plugin",
        "hooks": {
            "project": ".opencode/plugins/{name}.ts",
            "user": "~/.config/opencode/plugins/{name}.ts",
        },
        "hook_scripts_dir": ".opencode/hooks",
        "hook_events_map": {
            "PreToolUse": "tool.execute.before",
            "PostToolUse": "tool.execute.after",
            "Stop": "session.idle",
            "SessionStart": "session.created",
            "UserPromptSubmit": "message.updated",
        },
        "config_dir": ".config/opencode",
    },
    "antigravity": {
        "display_name": "Antigravity",
        "capabilities": {"hooks", "mcp_servers", "skills"},
        "session_parser": "antigravity",
        "scopes": ["project", "user"],
        "default_scope": "user",
        "scope_labels": ("project (.agents/)", "user (~/.gemini/antigravity-cli/)"),
        "agent_profile": {
            "project": ".agents/agents/{name}/agent.json",
            "user": "~/.gemini/antigravity-cli/agents/{name}/agent.json",
        },
        "agent_profile_format": "json",
        "mcp_config": {
            "project": ".agents/mcp_config.json",
            "user": "~/.gemini/antigravity-cli/mcp_config.json",
        },
        "mcp_servers_key": "mcpServers",
        "skills": {
            "project": ".agents/skills/{name}.md",
            "user": "~/.gemini/antigravity-cli/skills/{name}.md",
        },
        "skill_format": "yaml_frontmatter",
        "home_mcp_config": "~/.gemini/antigravity-cli/mcp_config.json",
        "hook_type": "command",
        "hooks": {
            "project": ".agents/hooks.json",
            "user": "~/.gemini/config/hooks.json",
        },
        "hook_scripts_dir": ".agents/hooks",
        "hook_events_map": {
            "PreToolUse": "PreToolUse",
            "PostToolUse": "PostToolUse",
            "Stop": "Stop",
            "SessionStart": "SessionStart",
            "UserPromptSubmit": "PreInvocation",
        },
        "config_dir": ".agents",
    },
    "pi": {
        "display_name": "Pi",
        "capabilities": {"skills", "hooks", "mcp_servers"},
        "session_parser": "pi",
        "scopes": ["project", "user"],
        "default_scope": "user",
        "scope_labels": ("project (.pi/)", "user (~/.pi/agent/)"),
        "agent_profile": {
            "project": "AGENTS.md",
            "user": "~/.pi/agent/AGENTS.md",
        },
        "agent_profile_format": "markdown",
        "mcp_config": {
            "project": ".pi/mcp.json",
            "user": "~/.pi/agent/mcp.json",
        },
        "mcp_servers_key": "mcpServers",
        "skills": {
            "project": ".pi/skills/{name}/SKILL.md",
            "user": "~/.pi/agent/skills/{name}/SKILL.md",
        },
        "skill_format": "yaml_frontmatter",
        "home_mcp_config": "~/.pi/agent/mcp.json",
        "hook_type": "extension",
        "hooks": {
            "user": "~/.pi/agent/settings.json",
        },
        "hook_scripts_dir": None,
        "hook_events_map": {},
        "config_dir": ".pi",
    },
}


_GUIDANCE_FILES = {
    "cursor": [".cursor/rules/*.mdc", "AGENTS.md"],
    "kiro": [".kiro/steering/*.md", "~/.kiro/steering/*.md", "AGENTS.md"],
    "claude-code": ["CLAUDE.md", ".claude/CLAUDE.md", "~/.claude/CLAUDE.md", "CLAUDE.local.md"],
    "codex": ["AGENTS.md", "AGENTS.override.md", "~/.codex/AGENTS.md"],
    "copilot": [
        ".github/copilot-instructions.md",
        ".github/instructions/*.instructions.md",
        "AGENTS.md",
        "CLAUDE.md",
        "GEMINI.md",
    ],
    "copilot-cli": [
        ".github/copilot-instructions.md",
        ".github/instructions/**/*.instructions.md",
        "AGENTS.md",
        "~/.copilot/copilot-instructions.md",
    ],
    "opencode": ["opencode.json", "~/.config/opencode/opencode.json"],
    "antigravity": ["AGENTS.md", "GEMINI.md"],
    "pi": ["AGENTS.md", "~/.pi/agent/AGENTS.md", ".pi/SYSTEM.md", ".pi/APPEND_SYSTEM.md"],
}

for _harness, _spec in HARNESS_REGISTRY.items():
    _spec["guidance_files"] = _GUIDANCE_FILES.get(_harness, [])
    _spec["model_catalog_file"] = f"harness_models/{_harness}.json"
    _spec["supported_models"] = supported_model_ids(_harness)


# ── Derived helpers ──────────────────────────────────────────


def get_valid_harnesses() -> list[str]:
    """Return the canonical list of valid harness names."""
    return list(HARNESS_REGISTRY.keys())


def get_harness_capability_matrix() -> dict[str, set[str]]:
    """Return {harness: capability_set} mapping for all registered harnesses."""
    return {ide: spec["capabilities"] for ide, spec in HARNESS_REGISTRY.items()}


def get_harness_display_names() -> dict[str, str]:
    """Return {harness: display_name} mapping for all registered harnesses."""
    return {ide: spec["display_name"] for ide, spec in HARNESS_REGISTRY.items()}


def get_scope_aware_harnesses() -> dict[str, tuple[str, str]]:
    """Return harnesses that support project/user scope selection, with labels."""
    return {ide: spec["scope_labels"] for ide, spec in HARNESS_REGISTRY.items() if spec.get("scope_labels")}


def get_home_mcp_configs() -> dict[str, str]:
    """Return {harness: home_mcp_config} for harnesses with home-level MCP config."""
    return {ide: spec["home_mcp_config"] for ide, spec in HARNESS_REGISTRY.items() if spec.get("home_mcp_config")}


def get_mcp_servers_key(ide: str) -> str:
    """Return the JSON key used for MCP servers in this harness's config."""
    return HARNESS_REGISTRY.get(ide, {}).get("mcp_servers_key", "mcpServers")


def get_default_scope(ide: str) -> str:
    """Return the default install scope for an harness."""
    return HARNESS_REGISTRY.get(ide, {}).get("default_scope", "project")


def get_model_choice_harnesses() -> list[str]:
    """Return harnesses with registry-backed model choices."""
    return [harness for harness, spec in HARNESS_REGISTRY.items() if spec.get("supported_models")]


def has_model_selection(harness: str) -> bool:
    """Return True if this harness has registry-backed model choices."""
    return bool(HARNESS_REGISTRY.get(harness, {}).get("supported_models"))


def get_session_parser_id(ide: str) -> str:
    """Return the session parser ID for an harness.

    Raises KeyError for unknown harnesses -- callers must handle unrecognised harnesses
    explicitly rather than silently falling back to a default parser.
    """
    entry = HARNESS_REGISTRY[ide]  # raises KeyError for unknown harness
    return entry["session_parser"]  # raises KeyError if entry has no parser
