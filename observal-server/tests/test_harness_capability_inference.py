# SPDX-FileCopyrightText: 2026 snoopuppy582 <mnb0968@naver.com>
# SPDX-License-Identifier: Apache-2.0

"""Tests for harness capability inference helpers."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from observal_shared.harness_registry import HARNESS_REGISTRY
from services.harness_capability_inference import compute_supported_harnesses, infer_required_features


def _agent(*components, external_mcps=None):
    return SimpleNamespace(components=list(components), external_mcps=external_mcps or [])


def _component(component_type: str, component_id=None):
    return SimpleNamespace(component_type=component_type, component_id=component_id or uuid4())


def test_infer_required_features_empty_agent():
    assert infer_required_features(_agent()) == []


def test_infer_required_features_detects_mcp_components():
    assert infer_required_features(_agent(_component("mcp"))) == ["mcp_servers"]


def test_infer_required_features_detects_external_mcps():
    agent = _agent(external_mcps=[{"name": "filesystem", "command": "npx"}])
    assert infer_required_features(agent) == ["mcp_servers"]


def test_infer_required_features_detects_hooks():
    assert infer_required_features(_agent(_component("hook"))) == ["hooks"]


def test_infer_required_features_detects_skill_capabilities():
    slash_skill_id = uuid4()
    plain_skill_id = uuid4()
    agent = _agent(_component("skill", slash_skill_id), _component("skill", plain_skill_id))
    skill_listings = {
        slash_skill_id: SimpleNamespace(slash_command="/review"),
        plain_skill_id: SimpleNamespace(slash_command=None),
    }
    assert infer_required_features(agent, skill_listings) == ["skills"]


def test_infer_required_features_ignores_unknown_skill_listings():
    assert infer_required_features(_agent(_component("skill"))) == []


@pytest.mark.parametrize("harness", list(HARNESS_REGISTRY))
def test_compute_supported_harnesses_includes_each_harness_for_its_features(harness):
    required_features = sorted(HARNESS_REGISTRY[harness]["capabilities"])
    assert harness in compute_supported_harnesses(required_features)


def test_compute_supported_harnesses_requires_every_feature():
    required_features = ["mcp_servers", "hooks", "skills"]
    supported_harnesses = compute_supported_harnesses(required_features)
    expected = {
        harness for harness, spec in HARNESS_REGISTRY.items() if set(required_features).issubset(spec["capabilities"])
    }
    assert set(supported_harnesses) == expected
