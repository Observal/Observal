# SPDX-FileCopyrightText: 2026 Aryan Iyappan <aryaniyappan2006@gmail.com>
# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-FileCopyrightText: 2026 Kaushik Kumar <kaushikrjpm10@gmail.com>
# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Centralized IDE registry -- single source of truth for per-IDE data.

Config generators, CLI commands, and the frontend TypeScript mirror
all derive from this registry.  Behavioral logic (prompt wrapping,
frontmatter generation, MCP transforms) stays in service modules.

When adding a new IDE, add its entry here and everything else
(``VALID_IDES``, ``IDE_FEATURE_MATRIX``, scope helpers, shim targets)
is derived automatically.
"""

from __future__ import annotations

IDE_REGISTRY: dict[str, dict] = {
    "cursor": {
        "display_name": "Cursor",
        "features": {"hooks", "mcp_servers"},
        "session_parser": "cursor",
        "scopes": ["project", "user"],
        "default_scope": "project",
        "scope_labels": ("project (.cursor/rules/)", "user (~/.cursor/rules/)"),
        "rules_file": {
            "project": ".cursor/rules/{name}.mdc",
            "user": "~/.cursor/rules/{name}.mdc",
        },
        "rules_format": "markdown_frontmatter",
        "mcp_config_path": {
            "project": ".cursor/mcp.json",
            "user": "~/.cursor/mcp.json",
        },
        "mcp_servers_key": "mcpServers",
        "skill_file": {
            "project": ".cursor/skills/{name}/SKILL.md",
            "user": "~/.cursor/skills/{name}/SKILL.md",
        },
        "skill_format": "yaml_frontmatter",
        "home_mcp_config": "~/.cursor/mcp.json",
        "hook_type": "command",
        "hook_config_path": {
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
        "accepts_model_choice": False,
        "auto_sentinel": None,
    },
    "kiro": {
        "display_name": "Kiro",
        "features": {"hooks", "mcp_servers"},
        "session_parser": "kiro",
        "scopes": ["project", "user"],
        "default_scope": "user",
        "scope_labels": ("project (.kiro/agents/)", "user (~/.kiro/agents/)"),
        "rules_file": {
            "project": ".kiro/agents/{name}.json",
            "user": "~/.kiro/agents/{name}.json",
        },
        "rules_format": "json",
        "mcp_config_path": {
            "project": ".kiro/settings/mcp.json",
            "user": "~/.kiro/settings/mcp.json",
        },
        "mcp_servers_key": "mcpServers",
        "skill_file": {
            "project": ".kiro/skills/{name}/SKILL.md",
            "user": "~/.kiro/skills/{name}/SKILL.md",
        },
        "skill_format": "yaml_frontmatter",
        "home_mcp_config": "~/.kiro/settings/mcp.json",
        "hook_type": "command",
        "hook_config_path": {
            "user": "~/.kiro/agents/{name}.json",
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
        "accepts_model_choice": True,
        "auto_sentinel": {"json_value": None},
    },
    "claude-code": {
        "display_name": "Claude Code",
        "features": {"skills", "hooks", "mcp_servers"},
        "session_parser": "claude-code",
        "scopes": ["project", "user"],
        "default_scope": "project",
        "scope_labels": ("project (.claude/agents/)", "user (~/.claude/agents/)"),
        "rules_file": {
            "project": ".claude/agents/{name}.md",
            "user": "~/.claude/agents/{name}.md",
        },
        "rules_format": "yaml_frontmatter",
        "mcp_config_path": {
            "project": None,
            "user": None,
        },
        "mcp_servers_key": "mcpServers",
        "skill_file": {
            "project": ".claude/skills/{name}/SKILL.md",
            "user": "~/.claude/skills/{name}/SKILL.md",
        },
        "skill_format": "yaml_frontmatter",
        "home_mcp_config": "~/.claude.json",
        "hook_type": "command",
        "hook_config_path": {
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
        "accepts_model_choice": True,
        "auto_sentinel": {"omit_frontmatter_field": True},
    },
    "codex": {
        "display_name": "Codex",
        "features": {"mcp_servers", "hooks", "skills"},
        "session_parser": "codex",
        "scopes": ["user"],
        "default_scope": "user",
        "scope_labels": None,
        "rules_file": {
            "user": "AGENTS.md",
        },
        "rules_format": "markdown",
        "mcp_config_path": {
            "user": "~/.codex/config.toml",
        },
        "mcp_servers_key": "mcp.servers",
        "skill_file": {
            "user": "~/.codex/skills/{name}/SKILL.md",
        },
        "skill_format": "yaml_frontmatter",
        "home_mcp_config": "~/.codex/config.toml",
        "hook_type": "command",
        "hook_config_path": {
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
        "accepts_model_choice": True,
        "auto_sentinel": {"omit_toml_field": True},
    },
    "copilot": {
        "display_name": "Copilot",
        "features": {"mcp_servers", "hooks", "skills"},
        "session_parser": "copilot-cli",
        "scopes": ["project"],
        "default_scope": "project",
        "scope_labels": None,
        "rules_file": {
            "project": ".github/copilot-instructions.md",
        },
        "rules_format": "markdown",
        "mcp_config_path": {
            "project": ".vscode/mcp.json",
        },
        "mcp_servers_key": "servers",
        "skill_file": {
            "project": ".github/skills/{name}/SKILL.md",
            "user": "~/.copilot/skills/{name}/SKILL.md",
        },
        "skill_format": "yaml_frontmatter",
        "home_mcp_config": "~/.vscode/mcp.json",
        "hook_type": "command",
        "hook_config_path": {
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
        "accepts_model_choice": False,
        "auto_sentinel": None,
    },
    "copilot-cli": {
        "display_name": "Copilot CLI",
        "features": {"mcp_servers", "hooks", "skills"},
        "session_parser": "copilot-cli",
        "scopes": ["project"],
        "default_scope": "project",
        "scope_labels": None,
        "rules_file": {
            "project": ".github/copilot-instructions.md",
        },
        "rules_format": "markdown",
        "mcp_config_path": {
            "project": ".mcp.json",
        },
        "mcp_servers_key": "mcpServers",
        "skill_file": {
            "project": ".agents/skills/{name}/SKILL.md",
            "user": "~/.copilot/skills/{name}/SKILL.md",
        },
        "skill_format": "yaml_frontmatter",
        "home_mcp_config": "~/.copilot/mcp-config.json",
        "hook_type": "command",
        "hook_config_path": {
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
        "accepts_model_choice": False,
        "auto_sentinel": None,
    },
    "opencode": {
        "display_name": "OpenCode",
        "session_parser": "opencode",
        "features": {"skills", "hooks", "mcp_servers"},
        "scopes": ["project", "user"],
        "default_scope": "user",
        "scope_labels": ("project (.opencode/agents/<name>.md)", "user (~/.config/opencode/agents/<name>.md)"),
        "rules_file": {
            "project": ".opencode/agents/{name}.md",
            "user": "~/.config/opencode/agents/{name}.md",
        },
        "rules_format": "markdown",
        "mcp_config_path": {
            "project": "opencode.json",
            "user": "~/.config/opencode/opencode.json",
        },
        "mcp_servers_key": "mcp",
        "skill_file": {
            "project": ".opencode/skills/{name}/SKILL.md",
            "user": "~/.config/opencode/skills/{name}/SKILL.md",
        },
        "skill_format": "yaml_frontmatter",
        "home_mcp_config": "~/.config/opencode/opencode.json",
        "hook_type": "plugin",
        "hook_config_path": {
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
        "accepts_model_choice": True,
        "auto_sentinel": {"omit_field": True},
    },
    "antigravity": {
        "display_name": "Antigravity",
        "features": {"hooks", "mcp_servers", "skills"},
        "session_parser": "antigravity",
        "scopes": ["project", "user"],
        "default_scope": "project",
        "scope_labels": ("project (.agents/)", "user (~/.gemini/antigravity-cli/)"),
        "rules_file": {
            "project": "AGENTS.md",
            "user": "~/.gemini/GEMINI.md",
        },
        "rules_format": "markdown",
        "mcp_config_path": {
            "project": ".agents/mcp_config.json",
            "user": "~/.gemini/antigravity-cli/mcp_config.json",
        },
        "mcp_servers_key": "mcpServers",
        "skill_file": {
            "project": ".agents/skills/{name}/SKILL.md",
            "user": "~/.gemini/config/skills/{name}/SKILL.md",
        },
        "skill_format": "yaml_frontmatter",
        "home_mcp_config": "~/.gemini/antigravity-cli/mcp_config.json",
        "hook_type": "command",
        "hook_config_path": {
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
        "accepts_model_choice": True,
        "auto_sentinel": {"omit_setting": True},
    },
    "pi": {
        "display_name": "Pi",
        "features": {"skills", "hooks", "mcp_servers"},
        "session_parser": "pi",
        "scopes": ["project", "user"],
        "default_scope": "user",
        "scope_labels": ("project (.pi/)", "user (~/.pi/agent/)"),
        "rules_file": {
            "project": "AGENTS.md",
            "user": "~/.pi/agent/AGENTS.md",
        },
        "rules_format": "markdown",
        "mcp_config_path": {
            "project": ".pi/mcp.json",
            "user": "~/.pi/agent/mcp.json",
        },
        "mcp_servers_key": "mcpServers",
        "skill_file": {
            "project": ".pi/skills/{name}/SKILL.md",
            "user": "~/.pi/agent/skills/{name}/SKILL.md",
        },
        "skill_format": "yaml_frontmatter",
        "home_mcp_config": "~/.pi/agent/mcp.json",
        "hook_type": "extension",
        "hook_config_path": {
            "user": "~/.pi/agent/settings.json",
        },
        "hook_scripts_dir": None,
        "hook_events_map": {},
        "config_dir": ".pi",
        "accepts_model_choice": True,
        "auto_sentinel": {"omit_field": True},
    },
}


# ── Derived helpers ──────────────────────────────────────────


def get_valid_ides() -> list[str]:
    """Return the canonical list of valid IDE names."""
    return list(IDE_REGISTRY.keys())


def get_ide_feature_matrix() -> dict[str, set[str]]:
    """Return {ide: feature_set} mapping for all registered IDEs."""
    return {ide: spec["features"] for ide, spec in IDE_REGISTRY.items()}


def get_ide_display_names() -> dict[str, str]:
    """Return {ide: display_name} mapping for all registered IDEs."""
    return {ide: spec["display_name"] for ide, spec in IDE_REGISTRY.items()}


def get_scope_aware_ides() -> dict[str, tuple[str, str]]:
    """Return IDEs that support project/user scope selection, with labels."""
    return {ide: spec["scope_labels"] for ide, spec in IDE_REGISTRY.items() if spec.get("scope_labels")}


def get_home_mcp_configs() -> dict[str, str]:
    """Return {ide: home_mcp_config_path} for IDEs with home-level MCP config."""
    return {ide: spec["home_mcp_config"] for ide, spec in IDE_REGISTRY.items() if spec.get("home_mcp_config")}


def get_mcp_servers_key(ide: str) -> str:
    """Return the JSON key used for MCP servers in this IDE's config."""
    return IDE_REGISTRY.get(ide, {}).get("mcp_servers_key", "mcpServers")


def get_default_scope(ide: str) -> str:
    """Return the default install scope for an IDE."""
    return IDE_REGISTRY.get(ide, {}).get("default_scope", "project")


def get_model_choice_ides() -> list[str]:
    """Return IDEs that accept a per-agent model selection."""
    return [ide for ide, spec in IDE_REGISTRY.items() if spec.get("accepts_model_choice")]


def accepts_model_choice(ide: str) -> bool:
    """Return True if this IDE supports a per-agent model field."""
    return bool(IDE_REGISTRY.get(ide, {}).get("accepts_model_choice"))


def get_auto_sentinel(ide: str) -> dict | None:
    """Return the codegen sentinel describing how to express ``auto`` for this IDE."""
    return IDE_REGISTRY.get(ide, {}).get("auto_sentinel")
