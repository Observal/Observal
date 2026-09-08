# SPDX-FileCopyrightText: 2026 Observal Contributors
# SPDX-License-Identifier: Apache-2.0

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from observal_cli.discovery.models import (
    AdapterDiscoveryResult,
    ComponentType,
    Confidence,
    DiagnosticCode,
    DiagnosticSeverity,
    DiscoveryCandidate,
    DiscoveryDiagnostic,
    DiscoveryEvidence,
    DiscoveryScope,
    PackageEcosystem,
    ProviderKind,
    ProviderResult,
    ReasonCode,
    RegistrationStatus,
    RegistryStatus,
    SanitizedLaunch,
    SupportStatus,
    TrackingStatus,
)
from observal_cli.harness import DiscoveredMcp


def test_status_values_are_stable_lowercase_contracts() -> None:
    assert [status.value for status in TrackingStatus] == ["tracked", "not_tracked", "ambiguous"]
    assert [status.value for status in RegistryStatus] == [
        "not_checked",
        "unavailable",
        "no_exact_match",
        "exact_match",
        "owned_existing",
        "ambiguous",
    ]
    assert [status.value for status in SupportStatus] == ["supported", "unsupported"]
    assert [status.value for status in RegistrationStatus] == [
        "eligible",
        "incomplete",
        "requires_auth",
        "already_exists",
        "not_applicable",
    ]


def test_all_required_diagnostic_codes_are_declared() -> None:
    assert {code.value for code in DiagnosticCode} == {
        "executable_missing",
        "subprocess_timeout",
        "subprocess_failed",
        "output_too_large",
        "metadata_too_large",
        "metadata_malformed",
        "unsupported_launch",
        "unsupported_version",
        "permission_denied",
        "path_outside_root",
        "symlink_escape",
        "recursion_limit_reached",
        "item_limit_reached",
        "adapter_deadline_exceeded",
        "approved_root_limit_reached",
        "collection_file_limit_reached",
        "evidence_limit_reached",
        "diagnostic_limit_reached",
        "registry_not_configured",
        "registry_auth_required",
        "registry_unavailable",
        "registry_lookup_incomplete",
    }


def test_evidence_wraps_legacy_component_without_changing_legacy_shape(tmp_path: Path) -> None:
    mcp = DiscoveredMcp("filesystem", "npx", ["-y", "server"], None, "Files", "claude")
    legacy_shape = vars(mcp).copy()

    evidence = DiscoveryEvidence(
        component=mcp,
        provider=ProviderKind.HARNESS,
        scope=DiscoveryScope.PROJECT,
        harness="claude-code",
        source_path=tmp_path / ".mcp.json",
        display_path="<project>/.mcp.json",
        package_ecosystem=PackageEcosystem.NPM,
        package_name="server",
        package_version="1.0.0",
        launch=SanitizedLaunch(kind="npm", package="server", arguments=("--read-only",)),
    )

    assert evidence.component is mcp
    assert vars(mcp) == legacy_shape
    with pytest.raises(FrozenInstanceError):
        evidence.harness = "kiro"  # type: ignore[misc]


def test_candidate_status_dimensions_are_independent() -> None:
    candidate = DiscoveryCandidate(
        component_type=ComponentType.MCP,
        local_name="filesystem",
        correlation_identity="npm:filesystem",
        launch_fingerprint=None,
        tracking_status=TrackingStatus.AMBIGUOUS,
        registry_status=RegistryStatus.UNAVAILABLE,
        support_status=SupportStatus.SUPPORTED,
        registration_status=RegistrationStatus.NOT_APPLICABLE,
        confidence=Confidence.MEDIUM,
        reason_codes=[ReasonCode.TRACKING_AMBIGUOUS, ReasonCode.REGISTRY_UNAVAILABLE],
        missing_fields=["launch_fingerprint"],
    )

    assert candidate.tracking_status is TrackingStatus.AMBIGUOUS
    assert candidate.registry_status is RegistryStatus.UNAVAILABLE
    assert candidate.support_status is SupportStatus.SUPPORTED
    assert candidate.registration_status is RegistrationStatus.NOT_APPLICABLE


def test_result_collections_are_not_shared_between_instances() -> None:
    evidence = DiscoveryEvidence(None, ProviderKind.NPM, DiscoveryScope.GLOBAL)
    diagnostic = DiscoveryDiagnostic(
        DiagnosticCode.EXECUTABLE_MISSING,
        DiagnosticSeverity.WARNING,
        "npm",
        None,
        "npm is unavailable",
    )
    first_provider = ProviderResult()
    second_provider = ProviderResult()
    first_adapter = AdapterDiscoveryResult()
    second_adapter = AdapterDiscoveryResult()

    first_provider.evidence.append(evidence)
    first_adapter.diagnostics.append(diagnostic)

    assert second_provider.evidence == []
    assert second_adapter.diagnostics == []
