"""Canonical valid-option lists for all registry submit fields.

Mirror of ``observal-server/schemas/constants.py``.
A sync test (``tests/test_constants_sync.py``) ensures these stay in lockstep.
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
# Mirror of observal-server/schemas/constants.py — kept in sync by
# tests/test_constants_sync.py.

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
