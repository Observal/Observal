# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Consolidated MCP config builder.

Provides a single source of truth for building MCP server configurations,
used by both the agent_builder (manifest-based) and the harness config generator
(registry-based with live DB listings).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from models.agent import Agent
    from services.agent_builder_types import AgentManifest


def build_mcp_entries(manifest: AgentManifest) -> dict:
    """Build MCP server config entries from an agent manifest.

    This is the manifest-based path used by the agent builder when
    composing portable agent packages without DB access.

    Returns a dict of {server_name: {command, args, env}} entries.
    """
    entries = {}
    for mcp in manifest.components.mcps:
        shim_args = ["--mcp-id", mcp.name, "--", "python", "-m", mcp.name]
        entries[mcp.name] = {
            "command": "observal-shim",
            "args": shim_args,
            "env": {},
        }
    return entries


def build_mcp_configs(
    agent: Agent,
    harness: str,
    observal_url: str,
    mcp_listings: dict | None = None,
    env_values: dict | None = None,
) -> dict:
    """Build MCP server configs from registry components + external MCPs.

    This is the registry-based path used by the install route when
    generating harness configs from live DB listings.

    Args:
        agent: The Agent model with components and external_mcps.
        harness: Target harness name.
        mcp_listings: optional {component_id: McpListing} map.
        env_values: optional {mcp_listing_id_str: {VAR: value}} map.

    Returns a dict of MCP server configs keyed by sanitized name.
    """
    # Delegate to the existing implementation in helpers to avoid duplication
    # during the transition. This will be inlined once helpers is cleaned up.
    from services.harness.helpers import _build_mcp_configs

    return _build_mcp_configs(agent, harness, observal_url, mcp_listings, env_values)
