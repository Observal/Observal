# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""IDE adapter protocol, context, and registry.

Defines the interface all IDE adapters must implement, the shared
ConfigContext that holds pre-computed data, and the registry that
maps IDE names to adapter instances.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass
class ConfigContext:
    """Shared pre-computed data passed to each IDE adapter.

    Built once by the orchestrator (generate_agent_config) from the agent
    model and component listings. Adapters use this to format IDE-specific
    output without duplicating the data extraction logic.
    """

    agent: Any  # Agent model instance
    safe_name: str
    ide: str
    observal_url: str
    effective_otlp_http: str
    mcp_configs: dict = field(default_factory=dict)
    rules_content: str = ""
    skill_configs: list = field(default_factory=list)
    hook_configs: list = field(default_factory=list)
    options: dict = field(default_factory=dict)
    platform: str = ""
    compatibility_warnings: list = field(default_factory=list)
    # Optional component listings (passed through for adapters that need them)
    mcp_listings: dict | None = None
    hook_listings: dict | None = None
    skill_listings: dict | None = None
    sandbox_listings: dict | None = None


@runtime_checkable
class IdeAdapter(Protocol):
    """Protocol defining the interface for IDE-specific config generation.

    Each IDE adapter implements this protocol to handle the differences
    in how that IDE expects configuration files to be structured.
    """

    @property
    def ide_name(self) -> str:
        """Canonical IDE name (e.g. 'claude-code', 'cursor')."""
        ...

    def format_config(self, ctx: ConfigContext) -> dict:
        """Format the pre-computed context into IDE-specific config output.

        Returns a dict with IDE-specific keys (rules_file, agent_file,
        mcp_config, steering_files, hooks_config, etc.).
        """
        ...


# ── Adapter Registry ──────────────────────────────────────────────

_ADAPTER_REGISTRY: dict[str, IdeAdapter] = {}


def register_adapter(adapter: IdeAdapter) -> None:
    """Register an IDE adapter instance."""
    _ADAPTER_REGISTRY[adapter.ide_name] = adapter


def get_adapter(ide: str) -> IdeAdapter | None:
    """Look up an adapter by IDE name or alias. Returns None if not registered."""
    return _ADAPTER_REGISTRY.get(ide) or _ADAPTER_REGISTRY.get(_IDE_ALIASES.get(ide, ""))


# Underscore aliases for backward compatibility
_IDE_ALIASES: dict[str, str] = {
    "claude_code": "claude-code",
    "gemini_cli": "gemini-cli",
    "copilot_cli": "copilot-cli",
}


def get_all_adapters() -> dict[str, IdeAdapter]:
    """Return all registered adapters."""
    return dict(_ADAPTER_REGISTRY)
