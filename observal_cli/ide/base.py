# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Base adapter with feature-flag gating from IDE_Registry.

Methods automatically raise NotSupportedError when the IDE lacks
the required feature in its IDE_Registry entry. Subclasses override
methods they support; the feature gate runs before the override.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

from observal_cli.ide.protocol import (
    METHOD_FEATURE_MAP,
    DiscoveredMcp,
    HookSpec,
    NotSupportedError,
    ScanResult,
)


def _get_features(ide_name: str) -> set[str]:
    """Look up the feature set for an IDE from the registry."""
    from observal_cli.ide_registry import IDE_REGISTRY

    spec = IDE_REGISTRY.get(ide_name, {})
    return spec.get("features", set())


def _check_feature(ide_name: str, method_name: str) -> None:
    """Raise NotSupportedError if the IDE lacks the required feature for a method."""
    required_feature = METHOD_FEATURE_MAP.get(method_name)
    if required_feature is None:
        return  # No feature gate for this method
    features = _get_features(ide_name)
    if required_feature not in features:
        raise NotSupportedError(ide_name, method_name)


class BaseAdapter:
    """Base class providing feature-gated defaults for all protocol methods.

    On each call, checks the IDE_Registry feature set. If the IDE lacks
    the required feature, raises NotSupportedError before reaching the
    method body. Subclasses override methods they support.
    """

    managed_agent_files: tuple[str, ...] = ()
    managed_skill_files: tuple[str, ...] = ()
    managed_mcp_files: tuple[str, ...] = ()

    @property
    def ide_name(self) -> str:
        raise NotImplementedError("Subclasses must define ide_name")

    def scan_home(self, home: Path | None = None) -> ScanResult:
        _check_feature(self.ide_name, "scan_home")
        return ScanResult()

    def scan_project(self, project_dir: Path) -> ScanResult:
        _check_feature(self.ide_name, "scan_project")
        return ScanResult()

    def get_hook_spec(self) -> HookSpec:
        _check_feature(self.ide_name, "get_hook_spec")
        return HookSpec()

    def generate_hook_config(
        self,
        observal_url: str,
        api_key: str,
        agent_id: str | None = None,
    ) -> dict[str, Any]:
        _check_feature(self.ide_name, "generate_hook_config")
        raise NotSupportedError(self.ide_name, "generate_hook_config")

    def detect_hooks(self, config_dir: Path) -> str:
        _check_feature(self.ide_name, "detect_hooks")
        return "none"

    def shim_status(self, mcps: list[DiscoveredMcp]) -> str:
        _check_feature(self.ide_name, "shim_status")
        if not mcps:
            return "none"
        from observal_cli.shared.utils import is_already_shimmed

        shimmed = sum(1 for m in mcps if m.command and is_already_shimmed({"command": m.command, "args": m.args}))
        if shimmed == 0:
            return "none"
        if shimmed == len(mcps):
            return "all"
        return "partial"

    def get_observal_managed_files(self, lockfile_data: dict, project_dir: str | None = None) -> set[str]:
        """Return layer snapshot display paths managed by Observal for this IDE."""
        managed: set[str] = set()
        ide_section = lockfile_data.get("ides", {}).get(self.ide_name, {})

        for agent in ide_section.get("agents", []):
            agent_name = agent.get("name", "")
            if agent_name:
                managed.update(self._format_managed_paths(self.managed_agent_files, agent_name))

            for component in agent.get("components", []):
                managed.update(self._managed_component_files(component.get("type", ""), component.get("name", "")))

        for item in ide_section.get("standalone", []):
            managed.update(self._managed_component_files(item.get("type", ""), item.get("name", "")))

        return managed

    def _managed_component_files(self, component_type: str, component_name: str) -> set[str]:
        if not component_name:
            return set()
        if component_type == "skill":
            return self._format_managed_paths(self.managed_skill_files, component_name)
        if component_type == "mcp":
            return self._format_managed_paths(self.managed_mcp_files, component_name)
        return set()

    @staticmethod
    def _format_managed_paths(patterns: tuple[str, ...], name: str) -> set[str]:
        return {pattern.format(name=name) for pattern in patterns}
