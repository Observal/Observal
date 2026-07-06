# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Infer harness feature requirements and compatible harnesses from agent components."""

from __future__ import annotations

from loguru import logger as optic

from schemas.constants import HARNESS_CAPABILITIES


def infer_required_features(
    agent,
    skill_listings: dict | None = None,
) -> list[str]:
    """Determine which harness features an agent requires based on its components.

    Args:
        agent: Agent model instance with `components` and `external_mcps`.
        skill_listings: optional ``{component_id: SkillListing}`` map used
            to inspect ``slash_command`` and ``is_power`` on skill components.

    Returns:
        Sorted list of required feature strings (e.g. ``["mcp_servers", "rules"]``).
    """
    optic.trace("agent={}, skill_listings={}", agent, skill_listings)
    features: set[str] = set()
    skill_listings = skill_listings or {}

    for comp in getattr(agent, "components", []):
        if comp.component_type == "mcp":
            features.add("mcp_servers")
        elif comp.component_type == "hook":
            features.add("hooks")
        elif comp.component_type == "skill":
            listing = skill_listings.get(comp.component_id)
            if listing and getattr(listing, "slash_command", None):
                features.add("skills")

    if getattr(agent, "external_mcps", None):
        features.add("mcp_servers")

    return sorted(features)


def compute_supported_harnesses(required_features: list[str]) -> list[str]:
    """Return sorted harness names that support all *required_features*."""
    optic.trace("required_features={}", required_features)
    required = set(required_features)
    return sorted(harness for harness, capabilities in HARNESS_CAPABILITIES.items() if required.issubset(capabilities))
