# SPDX-FileCopyrightText: 2026 Observal Contributors
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from typing import TYPE_CHECKING

from observal_cli.discovery.matcher import apply_local_match, match_local_candidate
from observal_cli.discovery.models import (
    ComponentType,
    DiscoveryCandidate,
    DiscoveryEvidence,
    DiscoveryScope,
    ProviderKind,
    ReasonCode,
    TrackingStatus,
)
from observal_cli.harness import DiscoveredMcp

if TYPE_CHECKING:
    from pathlib import Path

FP_ONE = "sha256:" + "1" * 64
FP_TWO = "sha256:" + "2" * 64


def _candidate(
    *,
    name: str = "search",
    harness: str = "kiro",
    scope: DiscoveryScope = DiscoveryScope.PROJECT,
    fingerprint: str | None = FP_ONE,
    component_type: ComponentType | None = ComponentType.MCP,
) -> DiscoveryCandidate:
    component = DiscoveredMcp(name, "npx", ["search"], None, "Search", "project")
    return DiscoveryCandidate(
        component_type=component_type,
        local_name=name,
        correlation_identity="npm:search",
        launch_fingerprint=fingerprint,
        evidence=[
            DiscoveryEvidence(
                component=component,
                provider=ProviderKind.HARNESS,
                scope=scope,
                harness=harness,
            )
        ],
    )


def _registry(*entries: dict, harness: str = "kiro") -> dict:
    return {"harnesses": {harness: {"agents": [], "standalone": list(entries)}}}


def test_matcher_uses_uuid_then_qualified_name_before_launch() -> None:
    candidate = _candidate()
    by_id = {"type": "mcp", "id": "mcp-1", "qualified_name": "other/item", "launch_fingerprint": FP_TWO}
    by_name = {"type": "mcp", "id": "mcp-2", "qualified_name": "alice/search", "launch_fingerprint": FP_TWO}

    assert match_local_candidate(candidate, _registry(by_id, by_name), component_id="mcp-1") == TrackingStatus.TRACKED
    assert match_local_candidate(candidate, _registry(by_name), qualified_name="alice/search") == TrackingStatus.TRACKED


def test_matcher_uses_exact_launch_fingerprint() -> None:
    entries = [
        {"type": "mcp", "name": "search", "launch_fingerprint": FP_TWO},
        {"type": "mcp", "name": "renamed", "launch_fingerprint": FP_ONE},
    ]

    assert match_local_candidate(_candidate(), _registry(*entries)) == TrackingStatus.TRACKED


def test_scope_directory_local_name_fallback_is_normalized(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    entry = {
        "type": "mcp",
        "name": "Registry Name",
        "local_name": "search",
        "scope": "project",
        "directory": str(project / "."),
    }

    assert (
        match_local_candidate(_candidate(fingerprint=None), _registry(entry), project_directory=project)
        == TrackingStatus.TRACKED
    )
    assert (
        match_local_candidate(_candidate(fingerprint=None), _registry(entry), project_directory=tmp_path / "other")
        == TrackingStatus.NOT_TRACKED
    )


def test_scope_tier_disambiguates_before_legacy_name_fallback(tmp_path: Path) -> None:
    project = tmp_path / "project"
    entries = [
        {"type": "mcp", "local_name": "search", "scope": "project", "directory": str(project)},
        {"type": "mcp", "local_name": "search", "scope": "project", "directory": str(tmp_path / "other")},
    ]

    assert (
        match_local_candidate(_candidate(fingerprint=None), _registry(*entries), project_directory=project)
        == TrackingStatus.TRACKED
    )


def test_legacy_name_fallback_requires_a_unique_match() -> None:
    one = {"type": "mcp", "name": "search", "scope": "user"}
    two = {"type": "mcp", "name": "search", "scope": "user"}
    candidate = _candidate(fingerprint=None, scope=DiscoveryScope.USER)

    assert match_local_candidate(candidate, _registry(one)) == TrackingStatus.TRACKED
    assert match_local_candidate(candidate, _registry(one, two)) == TrackingStatus.AMBIGUOUS


def test_differing_fingerprint_never_falls_back_to_bare_name() -> None:
    entry = {"type": "mcp", "name": "search", "scope": "project", "launch_fingerprint": FP_TWO}

    assert (
        match_local_candidate(_candidate(), _registry(entry), project_directory="/repo") == TrackingStatus.NOT_TRACKED
    )
    assert (
        match_local_candidate(_candidate(fingerprint=None), _registry(entry), project_directory="/repo")
        == TrackingStatus.NOT_TRACKED
    )


def test_multiple_matches_at_a_tier_are_ambiguous() -> None:
    entries = [
        {"type": "mcp", "id": "same", "scope": "project", "directory": "/one"},
        {"type": "mcp", "id": "same", "scope": "project", "directory": "/two"},
    ]

    assert match_local_candidate(_candidate(), _registry(*entries), component_id="same") == TrackingStatus.AMBIGUOUS


def test_matching_is_partitioned_by_component_type_and_harness() -> None:
    wrong_type = {"type": "skill", "name": "search"}
    wrong_harness = _registry({"type": "mcp", "name": "search"}, harness="cursor")

    assert match_local_candidate(_candidate(fingerprint=None), _registry(wrong_type)) == TrackingStatus.NOT_TRACKED
    assert match_local_candidate(_candidate(fingerprint=None), wrong_harness) == TrackingStatus.NOT_TRACKED
    assert match_local_candidate(_candidate(component_type=None), _registry()) == TrackingStatus.NOT_TRACKED


def test_nested_agent_components_are_compatible_lock_entries() -> None:
    registry = {
        "harnesses": {
            "kiro": {
                "standalone": [],
                "agents": [
                    {
                        "scope": "project",
                        "directory": "/repo",
                        "components": [
                            {
                                "type": "mcp",
                                "id": "mcp-1",
                                "name": "search",
                                "qualified_name": "alice/search",
                            }
                        ],
                    }
                ],
            }
        }
    }

    assert match_local_candidate(_candidate(), registry, component_id="mcp-1") == TrackingStatus.TRACKED
    assert match_local_candidate(_candidate(), registry, qualified_name="alice/search") == TrackingStatus.TRACKED


def test_apply_local_match_updates_only_tracking_reasons() -> None:
    candidate = _candidate(fingerprint=None, scope=DiscoveryScope.USER)
    candidate.reason_codes = [ReasonCode.UNSAFE_LAUNCH, ReasonCode.TRACKING_AMBIGUOUS]

    returned = apply_local_match(candidate, _registry({"type": "mcp", "name": "search"}))

    assert returned is candidate
    assert candidate.tracking_status == TrackingStatus.TRACKED
    assert candidate.reason_codes == [ReasonCode.UNSAFE_LAUNCH, ReasonCode.ALREADY_TRACKED]
