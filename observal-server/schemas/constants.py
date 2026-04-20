"""Canonical valid-option lists for all registry submit fields.

This module is the single source of truth for constrained field values.
The CLI mirrors these in ``observal_cli/constants.py`` -- a sync test
(``tests/test_constants_sync.py``) ensures they stay in lockstep.
"""

from __future__ import annotations

import re

# ── Name validation ───────────────────────────────────────────

AGENT_NAME_REGEX = re.compile(r"^[a-z0-9][a-z0-9_-]*$")

# ── IDE / client names (hyphen-canonical) ───────────────────
VALID_IDES: list[str] = [
    "cursor",
    "kiro",
    "claude-code",
    "gemini-cli",
    "vscode",
    "codex",
    "copilot",
]

# ── IDE feature capabilities ──────────────────────────────────
# Each IDE supports a subset of agent features. This matrix is the
# single source of truth used by the inference engine, config
# generator, and frontend.  Mirrored in observal_cli/constants.py
# and web/src/lib/ide-features.ts.

IDE_FEATURES: list[str] = [
    "skills",
    "superpowers",
    "hook_bridge",
    "mcp_servers",
    "rules",
    "steering_files",
    "otlp_telemetry",
]

IDE_FEATURE_MATRIX: dict[str, set[str]] = {
    "claude-code": {"skills", "hook_bridge", "mcp_servers", "rules", "otlp_telemetry"},
    "kiro": {"superpowers", "hook_bridge", "mcp_servers", "rules", "steering_files", "otlp_telemetry"},
    "cursor": {"mcp_servers", "rules"},
    "gemini-cli": {"mcp_servers", "rules"},
    "codex": {"rules"},
    "copilot": {"rules"},
    "vscode": {"mcp_servers", "rules"},
}

# ── MCP servers ─────────────────────────────────────────────
VALID_MCP_CATEGORIES: list[str] = [
    "browser-automation",
    "cloud-platforms",
    "code-execution",
    "communication",
    "databases",
    "developer-tools",
    "devops",
    "file-systems",
    "finance",
    "knowledge-memory",
    "monitoring",
    "multimedia",
    "productivity",
    "search",
    "security",
    "version-control",
    "ai-ml",
    "data-analytics",
    "general",
]

VALID_MCP_TRANSPORTS: list[str] = [
    "stdio",
    "sse",
    "streamable-http",
]

VALID_MCP_FRAMEWORKS: list[str] = [
    "python",
    "docker",
    "typescript",
    "go",
]

# ── Skills ──────────────────────────────────────────────────
VALID_SKILL_TASK_TYPES: list[str] = [
    "code-review",
    "code-generation",
    "testing",
    "documentation",
    "debugging",
    "refactoring",
    "deployment",
    "security-audit",
    "performance",
    "general",
]

# ── Hooks ───────────────────────────────────────────────────
VALID_HOOK_EVENTS: list[str] = [
    "PreToolUse",
    "PostToolUse",
    "Notification",
    "Stop",
    "SubagentStop",
    "SessionStart",
    "UserPromptSubmit",
]

VALID_HOOK_HANDLER_TYPES: list[str] = [
    "command",
    "http",
]

VALID_HOOK_EXECUTION_MODES: list[str] = [
    "async",
    "sync",
    "blocking",
]

VALID_HOOK_SCOPES: list[str] = [
    "agent",
    "session",
    "global",
]

# ── Prompts ─────────────────────────────────────────────────
VALID_PROMPT_CATEGORIES: list[str] = [
    "system-prompt",
    "code-review",
    "code-generation",
    "testing",
    "documentation",
    "debugging",
    "general",
]

# ── Sandboxes ───────────────────────────────────────────────
VALID_SANDBOX_RUNTIME_TYPES: list[str] = [
    "docker",
    "lxc",
    "firecracker",
    "wasm",
]

VALID_SANDBOX_NETWORK_POLICIES: list[str] = [
    "none",
    "host",
    "bridge",
    "restricted",
]


# ── Pydantic validator helpers ──────────────────────────────


def _normalize_ide(value: str) -> str:
    """Normalize underscore IDE names to hyphens (e.g. claude_code -> claude-code)."""
    return value.replace("_", "-")


def make_option_validator(field_name: str, valid_options: list[str]):
    """Return a classmethod suitable for ``@field_validator``."""

    def _check(cls, v: str) -> str:
        if v not in valid_options:
            raise ValueError(f"Invalid {field_name} '{v}'. Valid options: {', '.join(valid_options)}")
        return v

    return classmethod(_check)


def make_name_validator(field_name: str = "name", max_length: int = 64):
    """Return a classmethod that validates slug-style names (no spaces)."""

    def _check(cls, v: str) -> str:
        if not v:
            raise ValueError(f"{field_name} is required")
        if len(v) > max_length:
            raise ValueError(f"{field_name} must be at most {max_length} characters")
        if not AGENT_NAME_REGEX.match(v):
            raise ValueError(
                f"Invalid {field_name} '{v}'. "
                "Must start with a letter or digit and contain only lowercase letters, digits, hyphens, and underscores."
            )
        return v

    return classmethod(_check)


def make_ide_list_validator():
    """Return a classmethod that validates and normalizes each IDE in a list."""

    def _check(cls, v: list[str]) -> list[str]:
        normalized = [_normalize_ide(ide) for ide in v]
        invalid = [ide for ide in normalized if ide not in VALID_IDES]
        if invalid:
            raise ValueError(f"Invalid IDE(s): {', '.join(invalid)}. Valid options: {', '.join(VALID_IDES)}")
        return normalized

    return classmethod(_check)
