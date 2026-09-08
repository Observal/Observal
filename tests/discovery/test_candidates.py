# SPDX-FileCopyrightText: 2026 Observal Contributors
# SPDX-License-Identifier: Apache-2.0

from pathlib import Path

from observal_cli.discovery.models import (
    ComponentType,
    DiscoveryEvidence,
    DiscoveryScope,
    LaunchKind,
    PackageEcosystem,
    ProviderKind,
    ReasonCode,
    RegistrationStatus,
    SanitizedLaunch,
    SupportStatus,
)
from observal_cli.discovery.normalize import build_candidates, fingerprint_launch
from observal_cli.harness import DiscoveredAgent, DiscoveredHook, DiscoveredMcp, DiscoveredSkill


def _harness_mcp(name: str, launch: SanitizedLaunch | None, *, harness: str = "kiro") -> DiscoveryEvidence:
    return DiscoveryEvidence(
        component=DiscoveredMcp(name, "npx", ["server"], None, "desc", f"{harness}:project"),
        provider=ProviderKind.HARNESS,
        scope=DiscoveryScope.PROJECT,
        harness=harness,
        source_path=Path("/project/mcp.json"),
        display_path="<project>/mcp.json",
        launch=launch,
    )


def _package(
    package: str,
    launch: SanitizedLaunch | None,
    *,
    provider: ProviderKind = ProviderKind.NPM,
) -> DiscoveryEvidence:
    ecosystem = PackageEcosystem.NPM if provider is ProviderKind.NPM else PackageEcosystem.PYPI
    return DiscoveryEvidence(
        component=None,
        provider=provider,
        scope=DiscoveryScope.GLOBAL,
        display_path=f"{provider.value}:list",
        package_ecosystem=ecosystem,
        package_name=package,
        package_version="1.0.0",
        launch=launch,
    )


def test_exact_harness_launches_merge_and_package_evidence_enriches() -> None:
    launch = SanitizedLaunch(kind=LaunchKind.NPM, package="server", binary="server", arguments=("--read",))
    package_launch = SanitizedLaunch(kind=LaunchKind.NPM, package="server", binary="server", version="1.0.0")

    candidates = build_candidates(
        [
            _harness_mcp("server", launch, harness="kiro"),
            _harness_mcp("server alias", launch, harness="cursor"),
            _package("server", package_launch),
        ]
    )

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.component_type is ComponentType.MCP
    assert candidate.local_name == "server alias"  # stable evidence ordering chooses cursor first
    assert candidate.correlation_identity == "npm:server"
    assert candidate.launch_fingerprint == fingerprint_launch(launch)
    assert {item.provider for item in candidate.evidence} == {ProviderKind.HARNESS, ProviderKind.NPM}
    assert len(candidate.evidence) == 3
    assert candidate.support_status is SupportStatus.SUPPORTED
    assert candidate.registration_status is RegistrationStatus.ELIGIBLE


def test_same_package_with_different_launches_remains_distinct() -> None:
    read = SanitizedLaunch(kind=LaunchKind.NPM, package="server", binary="server", arguments=("--mode", "read"))
    write = SanitizedLaunch(kind=LaunchKind.NPM, package="server", binary="server", arguments=("--mode", "write"))
    metadata = _package("server", SanitizedLaunch(kind=LaunchKind.NPM, package="server", binary="server"))

    candidates = build_candidates([_harness_mcp("server-read", read), _harness_mcp("server-write", write), metadata])

    assert len(candidates) == 2
    assert len({candidate.launch_fingerprint for candidate in candidates}) == 2
    assert all(metadata in candidate.evidence for candidate in candidates)


def test_package_only_candidates_are_unknown_and_can_be_suppressed() -> None:
    package = _package("server", SanitizedLaunch(kind=LaunchKind.NPM, package="server", binary="server"))

    candidates = build_candidates([package])

    assert len(candidates) == 1
    assert candidates[0].component_type is None
    assert candidates[0].support_status is SupportStatus.UNSUPPORTED
    assert candidates[0].registration_status is RegistrationStatus.NOT_APPLICABLE
    assert candidates[0].reason_codes == [ReasonCode.PACKAGE_EVIDENCE_ONLY]
    assert build_candidates([package], suppress_package_only=True) == []


def test_cache_metadata_never_creates_a_candidate_but_can_enrich() -> None:
    cache = _package("tool", None, provider=ProviderKind.UV)

    assert build_candidates([cache]) == []

    harness = _harness_mcp(
        "tool",
        SanitizedLaunch(kind=LaunchKind.UV, package="tool", binary="tool"),
    )
    candidate = build_candidates([harness, cache])[0]
    assert cache in candidate.evidence


def test_unsupported_mcp_launch_is_incomplete() -> None:
    candidate = build_candidates([_harness_mcp("shell-server", None)])[0]

    assert candidate.support_status is SupportStatus.UNSUPPORTED
    assert candidate.registration_status is RegistrationStatus.INCOMPLETE
    assert candidate.missing_fields == ["portable_launch"]
    assert candidate.reason_codes == [ReasonCode.UNSUPPORTED_LAUNCH, ReasonCode.MISSING_REQUIRED_FIELDS]


def test_component_specific_missing_fields_and_unsupported_extension() -> None:
    agent = DiscoveryEvidence(
        component=DiscoveredAgent("helper", "desc", "", "", "/project/AGENT.md"),
        provider=ProviderKind.HARNESS,
        scope=DiscoveryScope.PROJECT,
        harness="pi",
        display_path="<project>/AGENT.md",
    )
    extension = DiscoveryEvidence(
        component=DiscoveredHook("extension", "extension", "extension", {"extension": "safe.ts"}, "desc", "pi"),
        provider=ProviderKind.HARNESS,
        scope=DiscoveryScope.USER,
        harness="pi",
        display_path="~/.pi/agent/settings.json",
    )
    skill = DiscoveryEvidence(
        component=DiscoveredSkill("review", "desc", "kiro", "general"),
        provider=ProviderKind.HARNESS,
        scope=DiscoveryScope.USER,
        harness="kiro",
        display_path="~/.kiro/skills/review/SKILL.md",
    )

    candidates = build_candidates([agent, extension, skill])
    by_type = {candidate.component_type: candidate for candidate in candidates}

    assert by_type[ComponentType.AGENT].missing_fields == ["model_name", "prompt"]
    assert by_type[ComponentType.AGENT].registration_status is RegistrationStatus.INCOMPLETE
    assert by_type[ComponentType.HOOK].support_status is SupportStatus.UNSUPPORTED
    assert by_type[ComponentType.HOOK].reason_codes == [ReasonCode.UNSUPPORTED_LAUNCH]
    assert by_type[ComponentType.SKILL].registration_status is RegistrationStatus.INCOMPLETE
    assert by_type[ComponentType.SKILL].missing_fields == ["skill_md_content"]
