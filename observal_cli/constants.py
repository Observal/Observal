# SPDX-FileCopyrightText: 2026 Apoorv Garg <apoorvgarg.21@gmail.com>
# SPDX-FileCopyrightText: 2026 Aryan Iyappan <aryaniyappan2006@gmail.com>
# SPDX-FileCopyrightText: 2026 Kaushik Kumar <kaushikrjpm10@gmail.com>
# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Canonical valid-option lists for all registry submit fields.

Mirror of ``observal-server/schemas/constants.py``.
A sync test (``tests/test_constants_sync.py``) ensures these stay in lockstep.

harness-specific data is defined in
``observal_shared/harness_registry.py``.
"""

from __future__ import annotations

import re

from observal_shared.harness_registry import get_harness_capability_matrix, get_valid_harnesses

# ── Name validation ───────────────────────────────────────────
AGENT_NAME_REGEX = re.compile(r"^[a-z0-9][a-z0-9_-]*$")

# ── harness / client names (hyphen-canonical) ───────────────────
# Derived from HARNESS_REGISTRY key order.
VALID_HARNESSES: list[str] = get_valid_harnesses()

# ── harness feature capabilities ──────────────────────────────────
# HARNESS_CAPABILITY_NAMES defines the vocabulary of possible features.
# HARNESS_CAPABILITIES is derived from the registry.

HARNESS_CAPABILITY_NAMES: list[str] = [
    "skills",
    "hooks",
    "mcp_servers",
    "prompts",
]

HARNESS_CAPABILITIES: dict[str, set[str]] = get_harness_capability_matrix()

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

# GitHub download redirect allowlist (used by version_check and upgrade_executor)
REDIRECT_ALLOWLIST = frozenset(
    [
        "github.com",
        "objects.githubusercontent.com",
        "github-releases.githubusercontent.com",
    ]
)
