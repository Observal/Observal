# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""CLI-side IDE adapter protocol, registry, and orchestrator.

Each IDE has a self-contained adapter module implementing the IdeAdapter
protocol. Adapters auto-register via module-level register_adapter() calls
when their module is imported (triggered by load_all).
"""

from __future__ import annotations

from observal_cli.ide.protocol import (
    METHOD_FEATURE_MAP,
    DiscoveredAgent,
    DiscoveredHook,
    DiscoveredMcp,
    DiscoveredSkill,
    HookSpec,
    IdeAdapter,
    NotSupported,
    NotSupportedError,
    ScanResult,
)
from observal_cli.ide_registry import IDE_REGISTRY

__all__ = [
    "METHOD_FEATURE_MAP",
    "DiscoveredAgent",
    "DiscoveredHook",
    "DiscoveredMcp",
    "DiscoveredSkill",
    "HookSpec",
    "IdeAdapter",
    "NotSupported",
    "NotSupportedError",
    "ScanResult",
    "ensure_loaded",
    "get_adapter",
    "get_all_adapters",
    "register_adapter",
]


# ── Adapter Registry ──────────────────────────────────────────────

_ADAPTER_REGISTRY: dict[str, IdeAdapter] = {}

_IDE_ALIASES: dict[str, str] = {
    "claude_code": "claude-code",
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
        "get_observal_managed_files",
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
    if len(_ADAPTER_REGISTRY) < len(IDE_REGISTRY):
        import observal_cli.ide.load_all  # noqa: F401
