# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""CLI-side IDE adapter protocol, registry, and orchestrator.

Each IDE has a self-contained adapter module implementing the IdeAdapter
protocol. Adapters auto-register via module-level register_adapter() calls
when their module is imported (triggered by load_all).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from pathlib import Path

# ── Data Types ────────────────────────────────────────────────────


class DiscoveredMcp:
    """An MCP server discovered during scanning."""

    def __init__(
        self,
        name: str,
        command: str | None,
        args: list[str],
        url: str | None,
        description: str,
        source: str,
    ):
        self.name = name
        self.command = command
        self.args = args
        self.url = url
        self.description = description
        self.source = source

    def display_cmd(self) -> str:
        if self.url:
            return self.url[:60]
        cmd = f"{self.command or '?'} {' '.join(self.args[:3])}"
        return cmd[:60] + "..." if len(cmd) > 60 else cmd


class DiscoveredSkill:
    """A skill discovered during scanning."""

    def __init__(self, name: str, description: str, source: str, task_type: str = "general"):
        self.name = name
        self.description = description
        self.source = source
        self.task_type = task_type


class DiscoveredHook:
    """A hook discovered during scanning."""

    def __init__(
        self,
        name: str,
        event: str,
        handler_type: str,
        handler_config: dict,
        description: str,
        source: str,
    ):
        self.name = name
        self.event = event
        self.handler_type = handler_type
        self.handler_config = handler_config
        self.description = description
        self.source = source


class DiscoveredAgent:
    """An agent discovered during scanning."""

    def __init__(self, name: str, description: str, model_name: str, prompt: str, source_file: str):
        self.name = name
        self.description = description
        self.model_name = model_name
        self.prompt = prompt
        self.source_file = source_file


@dataclass
class ScanResult:
    """Aggregated scan output from an IDE adapter."""

    mcps: list[DiscoveredMcp] = field(default_factory=list)
    skills: list[DiscoveredSkill] = field(default_factory=list)
    hooks: list[DiscoveredHook] = field(default_factory=list)
    agents: list[DiscoveredAgent] = field(default_factory=list)


@dataclass
class HookSpec:
    """Hook specification for an IDE."""

    events: list[str] = field(default_factory=list)
    format: str = ""  # "command", "http", "plugin"
    markers: list[str] = field(default_factory=list)
    env_vars: dict[str, str] = field(default_factory=dict)


class NotSupportedError(Exception):
    """Raised when an IDE does not support a requested operation."""

    def __init__(self, ide_name: str, method_name: str):
        self.ide_name = ide_name
        self.method_name = method_name
        super().__init__(f"{ide_name} does not support {method_name}")


# Keep backward compat alias
NotSupported = NotSupportedError


# ── Protocol ──────────────────────────────────────────────────────


@runtime_checkable
class IdeAdapter(Protocol):
    """Protocol defining the interface for CLI-side IDE adapters.

    Each IDE adapter implements this protocol to handle scanning,
    hook specs, and config file operations specific to that IDE.
    """

    @property
    def ide_name(self) -> str:
        """Canonical IDE name (e.g. 'claude-code', 'cursor')."""
        ...

    def scan_home(self, home: Path | None = None) -> ScanResult:
        """Scan the user's home directory for this IDE's configuration.

        Args:
            home: Override home directory (defaults to Path.home()).

        Returns:
            ScanResult with discovered MCPs, skills, hooks, and agents.
        """
        ...

    def scan_project(self, project_dir: Path) -> ScanResult:
        """Scan a project directory for this IDE's configuration.

        Args:
            project_dir: The project root to scan.

        Returns:
            ScanResult with discovered MCPs, skills, hooks, and agents.
        """
        ...

    def get_hook_spec(self) -> HookSpec:
        """Return the hook specification for this IDE.

        Returns:
            HookSpec describing available hooks, or empty HookSpec
            if this IDE does not support hook_bridge.
        """
        ...

    def generate_hook_config(
        self,
        observal_url: str,
        api_key: str,
        agent_id: str | None = None,
    ) -> dict[str, Any]:
        """Generate hook configuration for telemetry collection.

        Args:
            observal_url: The Observal server URL.
            api_key: User's API key.
            agent_id: Optional agent ID to tag telemetry.

        Returns:
            Dict representing the hook config to write.

        Raises:
            NotSupported: If this IDE does not support hooks.
        """
        ...

    def detect_hooks(self, config_dir: Path) -> str:
        """Detect whether Observal hooks are already installed.

        Args:
            config_dir: IDE-specific config directory to check.

        Returns:
            Status string: "installed", "partial", or "none".
        """
        ...

    def shim_status(self, mcps: list[DiscoveredMcp]) -> str:
        """Check whether MCP servers are wrapped with observal-shim.

        Args:
            mcps: List of discovered MCP servers.

        Returns:
            Status string: "all", "partial", "none".
        """
        ...


# ── Adapter Registry ──────────────────────────────────────────────

_ADAPTER_REGISTRY: dict[str, IdeAdapter] = {}

_IDE_ALIASES: dict[str, str] = {
    "claude_code": "claude-code",
    "gemini_cli": "gemini-cli",
    "copilot_cli": "copilot-cli",
}


def register_adapter(adapter: IdeAdapter) -> None:
    """Register an IDE adapter instance.

    Raises RuntimeError if the adapter is missing required protocol methods.
    """
    required = (
        "ide_name",
        "scan_home",
        "scan_project",
        "get_hook_spec",
        "generate_hook_config",
        "detect_hooks",
        "shim_status",
    )
    for method in required:
        if not hasattr(adapter, method) or not callable(getattr(adapter, method, None)):
            if method == "ide_name":
                continue  # property, not callable
            raise RuntimeError(f"Adapter {type(adapter).__name__} missing required method: {method}")
    _ADAPTER_REGISTRY[adapter.ide_name] = adapter


def get_adapter(ide: str) -> IdeAdapter:
    """Look up an adapter by IDE name or alias.

    Raises KeyError if no adapter is registered for the given IDE.
    """
    adapter = _ADAPTER_REGISTRY.get(ide) or _ADAPTER_REGISTRY.get(_IDE_ALIASES.get(ide, ""))
    if adapter is None:
        registered = sorted(_ADAPTER_REGISTRY.keys())
        raise KeyError(f"No adapter registered for IDE '{ide}'. Available: {', '.join(registered)}")
    return adapter


def get_all_adapters() -> dict[str, IdeAdapter]:
    """Return all registered adapters."""
    return dict(_ADAPTER_REGISTRY)


def ensure_loaded() -> None:
    """Ensure all adapter modules have been imported and registered."""
    if not _ADAPTER_REGISTRY:
        import observal_cli.ide.load_all  # noqa: F401
