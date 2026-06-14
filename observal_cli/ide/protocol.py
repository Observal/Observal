# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""IDE adapter protocol definition.

This module defines the IdeAdapter protocol that all IDE adapters must
satisfy, along with the data types used across the adapter interface.

Feature-flag gating: Each protocol method maps to an IDE_Registry feature.
The BaseAdapter enforces that methods raise NotSupportedError when the
IDE lacks the required feature.

Method → Feature mapping:
    generate_hook_config, detect_hooks, get_hook_spec → "hooks"
    scan_home, scan_project, shim_status              → "mcp_servers"
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from pathlib import Path


# ── Feature → Method mapping ──────────────────────────────────────

METHOD_FEATURE_MAP: dict[str, str] = {
    "generate_hook_config": "hooks",
    "detect_hooks": "hooks",
    "get_hook_spec": "hooks",
    "scan_home": "mcp_servers",
    "scan_project": "mcp_servers",
    "shim_status": "mcp_servers",
}


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

        Raises:
            NotSupportedError: If this IDE does not have mcp_servers feature.
        """
        ...

    def scan_project(self, project_dir: Path) -> ScanResult:
        """Scan a project directory for this IDE's configuration.

        Args:
            project_dir: The project root to scan.

        Returns:
            ScanResult with discovered MCPs, skills, hooks, and agents.

        Raises:
            NotSupportedError: If this IDE does not have mcp_servers feature.
        """
        ...

    def get_hook_spec(self) -> HookSpec:
        """Return the hook specification for this IDE.

        Returns:
            HookSpec describing available hooks, or empty HookSpec
            if this IDE does not support hooks.

        Raises:
            NotSupportedError: If this IDE does not have hooks feature.
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
            NotSupportedError: If this IDE does not have hooks feature.
        """
        ...

    def detect_hooks(self, config_dir: Path) -> str:
        """Detect whether Observal hooks are already installed.

        Args:
            config_dir: IDE-specific config directory to check.

        Returns:
            Status string: "installed", "partial", "missing", or "none".

        Raises:
            NotSupportedError: If this IDE does not have hooks feature.
        """
        ...

    def shim_status(self, mcps: list[DiscoveredMcp]) -> str:
        """Check whether MCP servers are wrapped with observal-shim.

        Args:
            mcps: List of discovered MCP servers.

        Returns:
            Status string: "all", "partial", "none".

        Raises:
            NotSupportedError: If this IDE does not have mcp_servers feature.
        """
        ...

    def get_observal_managed_files(self, lockfile_data: dict, project_dir: str | None = None) -> set[str]:
        """Return layer snapshot display paths managed by Observal for this IDE.

        Args:
            lockfile_data: Parsed Observal lockfile content.
            project_dir: Optional project directory for project-scoped installs.

        Returns:
            Display paths that correspond to Observal-installed files.
        """
        ...
