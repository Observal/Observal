# SPDX-FileCopyrightText: 2026 Kaushik Kumar <kaushikrjpm10@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Validate HARNESS_REGISTRY structural invariants.

Catches misconfigurations early: missing keys, invalid scopes, features
that don't exist in the canonical HARNESS_CAPABILITY_NAMES list, etc.
"""

from __future__ import annotations

import pytest

from observal_shared.harness_registry import HARNESS_REGISTRY
from schemas.constants import HARNESS_CAPABILITY_NAMES

REQUIRED_KEYS = {
    "display_name",
    "capabilities",
    "scopes",
    "default_scope",
    "scope_labels",
    "agent_profile",
    "agent_profile_format",
    "mcp_config",
    "mcp_servers_key",
    "skills",
    "skill_format",
    "home_mcp_config",
    "hook_type",
    "config_dir",
}


@pytest.mark.parametrize("harness", list(HARNESS_REGISTRY.keys()))
def test_registry_has_required_keys(harness):
    spec = HARNESS_REGISTRY[harness]
    missing = REQUIRED_KEYS - set(spec.keys())
    assert not missing, f"harness {harness!r} missing keys: {missing}"


@pytest.mark.parametrize("harness", list(HARNESS_REGISTRY.keys()))
def test_default_scope_is_valid(harness):
    spec = HARNESS_REGISTRY[harness]
    assert spec["default_scope"] in spec["scopes"], (
        f"harness {harness!r}: default_scope {spec['default_scope']!r} not in scopes {spec['scopes']!r}"
    )


@pytest.mark.parametrize("harness", list(HARNESS_REGISTRY.keys()))
def test_features_are_valid(harness):
    spec = HARNESS_REGISTRY[harness]
    invalid = spec["capabilities"] - set(HARNESS_CAPABILITY_NAMES)
    assert not invalid, f"harness {harness!r} has invalid capabilities: {invalid}"


@pytest.mark.parametrize("harness", list(HARNESS_REGISTRY.keys()))
def test_agent_profile_has_scope_entries(harness):
    spec = HARNESS_REGISTRY[harness]
    for scope in spec["scopes"]:
        assert scope in spec["agent_profile"], (
            f"harness {harness!r}: scope {scope!r} not in agent_profile keys {list(spec['agent_profile'].keys())!r}"
        )


@pytest.mark.parametrize("harness", list(HARNESS_REGISTRY.keys()))
def test_scope_labels_consistency(harness):
    spec = HARNESS_REGISTRY[harness]
    if len(spec["scopes"]) > 1 and spec["scope_labels"] is not None:
        assert isinstance(spec["scope_labels"], tuple), (
            f"harness {harness!r}: scope_labels should be a tuple, got {type(spec['scope_labels'])}"
        )
        assert len(spec["scope_labels"]) == 2, (
            f"harness {harness!r}: scope_labels should have 2 entries (project, user)"
        )


@pytest.mark.parametrize("harness", list(HARNESS_REGISTRY.keys()))
def test_display_name_is_nonempty(harness):
    assert HARNESS_REGISTRY[harness]["display_name"], f"harness {harness!r} has empty display_name"


def test_no_duplicate_display_names():
    names = [spec["display_name"] for spec in HARNESS_REGISTRY.values()]
    assert len(names) == len(set(names)), f"Duplicate display names: {names}"


def test_all_harnesses_have_features():
    for harness, spec in HARNESS_REGISTRY.items():
        assert len(spec["capabilities"]) > 0, f"harness {harness!r} has no capabilities"
