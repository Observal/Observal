# SPDX-FileCopyrightText: 2026 Kaushik Kumar <kaushikrjpm10@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Validate IDE_REGISTRY structural invariants.

Catches misconfigurations early: missing keys, invalid scopes, features
that don't exist in the canonical IDE_FEATURES list, etc.
"""

from __future__ import annotations

import pytest

from schemas.constants import IDE_FEATURES
from schemas.ide_registry import IDE_REGISTRY

REQUIRED_KEYS = {
    "display_name",
    "features",
    "scopes",
    "default_scope",
    "scope_labels",
    "rules_file",
    "rules_format",
    "mcp_config_path",
    "mcp_servers_key",
    "skill_file",
    "skill_format",
    "home_mcp_config",
    "hook_type",
    "config_dir",
}


@pytest.mark.parametrize("ide", list(IDE_REGISTRY.keys()))
def test_registry_has_required_keys(ide):
    spec = IDE_REGISTRY[ide]
    missing = REQUIRED_KEYS - set(spec.keys())
    assert not missing, f"IDE {ide!r} missing keys: {missing}"


@pytest.mark.parametrize("ide", list(IDE_REGISTRY.keys()))
def test_default_scope_is_valid(ide):
    spec = IDE_REGISTRY[ide]
    assert spec["default_scope"] in spec["scopes"], (
        f"IDE {ide!r}: default_scope {spec['default_scope']!r} not in scopes {spec['scopes']!r}"
    )


@pytest.mark.parametrize("ide", list(IDE_REGISTRY.keys()))
def test_features_are_valid(ide):
    spec = IDE_REGISTRY[ide]
    invalid = spec["features"] - set(IDE_FEATURES)
    assert not invalid, f"IDE {ide!r} has invalid features: {invalid}"


@pytest.mark.parametrize("ide", list(IDE_REGISTRY.keys()))
def test_rules_file_has_scope_entries(ide):
    spec = IDE_REGISTRY[ide]
    for scope in spec["scopes"]:
        assert scope in spec["rules_file"], (
            f"IDE {ide!r}: scope {scope!r} not in rules_file keys {list(spec['rules_file'].keys())!r}"
        )


@pytest.mark.parametrize("ide", list(IDE_REGISTRY.keys()))
def test_scope_labels_consistency(ide):
    spec = IDE_REGISTRY[ide]
    if len(spec["scopes"]) > 1 and spec["scope_labels"] is not None:
        assert isinstance(spec["scope_labels"], tuple), (
            f"IDE {ide!r}: scope_labels should be a tuple, got {type(spec['scope_labels'])}"
        )
        assert len(spec["scope_labels"]) == 2, f"IDE {ide!r}: scope_labels should have 2 entries (project, user)"


@pytest.mark.parametrize("ide", list(IDE_REGISTRY.keys()))
def test_display_name_is_nonempty(ide):
    assert IDE_REGISTRY[ide]["display_name"], f"IDE {ide!r} has empty display_name"


def test_no_duplicate_display_names():
    names = [spec["display_name"] for spec in IDE_REGISTRY.values()]
    assert len(names) == len(set(names)), f"Duplicate display names: {names}"


def test_all_ides_have_features():
    for ide, spec in IDE_REGISTRY.items():
        assert len(spec["features"]) > 0, f"IDE {ide!r} has no features"
