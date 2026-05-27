# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Feature version registry: maps features to the minimum version that supports them.

This file is the CANONICAL SOURCE OF TRUTH for feature versioning.
The TypeScript equivalent at `web/src/lib/features.ts` is auto-generated from
this file by `scripts/sync_features.py`. This is enforced by `tests/test_features_sync.py`.

Usage:
    from observal_cli.features import is_available, available_set

    if is_available("agent_insights", effective_version):
        # include insights data in response
"""

from __future__ import annotations

from packaging.version import InvalidVersion, Version

# Feature name → minimum version that introduced it.
# Both CLI and server use this to gate capabilities at the negotiated effective version.
FEATURE_VERSIONS: dict[str, str] = {
    # v0.5.0
    "basic_agents": "0.5.0",
    "mcp_registry": "0.5.0",
    # v0.6.0
    "component_versions": "0.6.0",
    "bulk_agents": "0.6.0",
    "agent_snapshots": "0.6.0",
    # v0.7.0
    "agent_insights": "0.7.0",
    "reconcile": "0.7.0",
    "device_auth": "0.7.0",
    "skills": "0.7.0",
    # v0.8.0
    "agent_builder": "0.8.0",
    # v1.0.0
    "version_check": "1.0.0",
    "version_enforcement": "1.0.0",
    "self_upgrade": "1.0.0",
    "server_upgrade": "1.0.0",
    "auto_update": "1.0.0",
    "version_negotiation": "1.0.0",
}


def is_available(feature: str, effective_version: str) -> bool:
    """Check if a feature is available at the negotiated effective version.

    Args:
        feature: Feature name (key in FEATURE_VERSIONS).
        effective_version: The min(cli_version, server_version) string.

    Returns:
        True if the feature is available, False otherwise.
        Unknown features return True (assume available).
    """
    min_ver = FEATURE_VERSIONS.get(feature)
    if not min_ver:
        return True  # Unknown features assumed available
    try:
        return Version(effective_version) >= Version(min_ver)
    except InvalidVersion:
        return False


def available_set(effective_version: str) -> set[str]:
    """Return all features available at the given effective version."""
    return {f for f in FEATURE_VERSIONS if is_available(f, effective_version)}
