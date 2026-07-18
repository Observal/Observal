# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Base adapter with feature-flag gating from harness_Registry.

Methods automatically raise NotSupportedError when the harness lacks
the required feature in its harness_Registry entry. Subclasses override
methods they support; the feature gate runs before the override.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from observal_cli.harness.protocol import (
    METHOD_FEATURE_MAP,
    DiscoveredMcp,
    HookSpec,
    NotSupportedError,
    ScanResult,
    SessionSource,
)


def _get_features(harness_name: str) -> set[str]:
    """Look up the feature set for an harness from the registry."""
    from observal_cli.harness_registry import HARNESS_REGISTRY

    spec = HARNESS_REGISTRY.get(harness_name, {})
    return spec.get("capabilities", set())


def _check_feature(harness_name: str, method_name: str) -> None:
    """Raise NotSupportedError if the harness lacks the required feature for a method."""
    required_feature = METHOD_FEATURE_MAP.get(method_name)
    if required_feature is None:
        return  # No feature gate for this method
    features = _get_features(harness_name)
    if required_feature not in features:
        raise NotSupportedError(harness_name, method_name)


class BaseAdapter:
    """Base class providing feature-gated defaults for all protocol methods.

    On each call, checks the harness_Registry feature set. If the harness lacks
    the required feature, raises NotSupportedError before reaching the
    method body. Subclasses override methods they support.
    """

    home_markers: tuple[str, ...] = ()
    managed_agent_profiles: tuple[str, ...] = ()
    managed_skills: tuple[str, ...] = ()
    managed_mcp_files: tuple[str, ...] = ()

    @property
    def harness_name(self) -> str:
        raise NotImplementedError("Subclasses must define harness_name")

    def scan_home(self, home: Path | None = None) -> ScanResult:
        _check_feature(self.harness_name, "scan_home")
        return ScanResult()

    def scan_project(self, project_dir: Path) -> ScanResult:
        _check_feature(self.harness_name, "scan_project")
        return ScanResult()

    def get_hook_spec(self) -> HookSpec:
        _check_feature(self.harness_name, "get_hook_spec")
        return HookSpec()

    def generate_hook_config(
        self,
        observal_url: str,
        api_key: str,
        agent_id: str | None = None,
    ) -> dict[str, Any]:
        _check_feature(self.harness_name, "generate_hook_config")
        raise NotSupportedError(self.harness_name, "generate_hook_config")

    def detect_hooks(self, config_dir: Path) -> str:
        _check_feature(self.harness_name, "detect_hooks")
        return "none"

    def shim_status(self, mcps: list[DiscoveredMcp]) -> str:
        _check_feature(self.harness_name, "shim_status")
        if not mcps:
            return "none"
        from observal_cli.shared.utils import is_already_shimmed

        shimmed = sum(1 for m in mcps if m.command and is_already_shimmed({"command": m.command, "args": m.args}))
        if shimmed == 0:
            return "none"
        if shimmed == len(mcps):
            return "all"
        return "partial"

    def is_installed(self, home: Path | None = None) -> bool:
        """Return whether this harness has a detectable home config marker."""
        if not self.home_markers:
            return False
        home = home or Path.home()
        for marker in self.home_markers:
            if any(char in marker for char in "*?["):
                if any(path.exists() for path in home.glob(marker)):
                    return True
            elif (home / marker).exists():
                return True
        return False

    def resolve_session_source(self, event: dict[str, Any], home: Path | None = None) -> SessionSource | None:
        """Resolve a hook payload to a session source when the harness supports it."""
        return None

    def discover_session_sources(
        self,
        home: Path | None = None,
        since_hours: int = 168,
    ) -> list[SessionSource]:
        """Return recent session sources; harness adapters opt in as they are migrated."""
        return []

    def related_session_sources(self, source: SessionSource, home: Path | None = None) -> list[SessionSource]:
        """Return child sources when a harness stores them separately."""
        return []

    def session_extra_fields(
        self,
        source: SessionSource,
        event: dict[str, Any],
        final: bool,
        home: Path | None = None,
    ) -> dict[str, Any]:
        """Return optional harness-specific ingest fields."""
        return {}

    def is_session_final(self, event: dict[str, Any]) -> bool:
        """Recognize common final lifecycle event names."""
        event_name = str(
            event.get("hook_event_name")
            or event.get("hookEventName")
            or event.get("event")
            or event.get("type")
            or ""
        )
        return event_name.lower() in {"stop", "sessionend", "session_end", "sessionshutdown"}

    def get_observal_managed_files(self, lockfile_data: dict, project_dir: str | None = None) -> set[str]:
        """Return layer snapshot display paths managed by Observal for this harness."""
        managed: set[str] = set()
        harness_section = lockfile_data.get("harnesses", {}).get(self.harness_name)
        if harness_section is None:
            harness_section = lockfile_data.get("ides", {}).get(self.harness_name, {})

        for agent in harness_section.get("agents", []):
            agent_name = agent.get("name", "")
            if agent_name:
                managed.update(self._format_managed_paths(self.managed_agent_profiles, agent_name))

            for component in agent.get("components", []):
                managed.update(self._managed_component_files(component.get("type", ""), component.get("name", "")))

        for item in harness_section.get("standalone", []):
            managed.update(self._managed_component_files(item.get("type", ""), item.get("name", "")))

        return managed

    def _managed_component_files(self, component_type: str, component_name: str) -> set[str]:
        if not component_name:
            return set()
        if component_type == "skill":
            return self._format_managed_paths(self.managed_skills, component_name)
        if component_type == "mcp":
            return self._format_managed_paths(self.managed_mcp_files, component_name)
        return set()

    @staticmethod
    def _format_managed_paths(patterns: tuple[str, ...], name: str) -> set[str]:
        return {pattern.format(name=name) for pattern in patterns}
