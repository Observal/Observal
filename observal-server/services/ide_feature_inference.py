"""Infer IDE feature requirements and compatible IDEs from agent components."""

from __future__ import annotations

from schemas.constants import IDE_FEATURE_MATRIX


def infer_required_features(
    agent,
    skill_listings: dict | None = None,
) -> list[str]:
    """Determine which IDE features an agent requires based on its components.

    Args:
        agent: Agent model instance with `components` and `external_mcps`.
        skill_listings: optional ``{component_id: SkillListing}`` map used
            to inspect ``slash_command`` and ``is_power`` on skill components.

    Returns:
        Sorted list of required feature strings (e.g. ``["mcp_servers", "rules"]``).
    """
    features: set[str] = set()
    skill_listings = skill_listings or {}

    # Every agent has a prompt / rules file
    features.add("rules")

    for comp in getattr(agent, "components", []):
        if comp.component_type == "mcp":
            features.add("mcp_servers")
        elif comp.component_type == "hook":
            features.add("hook_bridge")
        elif comp.component_type == "skill":
            listing = skill_listings.get(comp.component_id)
            if listing:
                if getattr(listing, "slash_command", None):
                    features.add("skills")
                if getattr(listing, "is_power", False):
                    features.add("superpowers")

    if getattr(agent, "external_mcps", None):
        features.add("mcp_servers")

    return sorted(features)


def compute_supported_ides(required_features: list[str]) -> list[str]:
    """Return sorted IDE names that support all *required_features*."""
    required = set(required_features)
    return sorted(ide for ide, capabilities in IDE_FEATURE_MATRIX.items() if required.issubset(capabilities))
