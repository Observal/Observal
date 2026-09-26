# SPDX-FileCopyrightText: 2026 Observal Contributors
# SPDX-License-Identifier: Apache-2.0

"""Component autodiscovery contracts and helpers."""

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
    LaunchKind,
    PackageEcosystem,
    ProviderKind,
    ProviderResult,
    ReasonCode,
    RegistrationStatus,
    RegistryMatch,
    RegistryStatus,
    SanitizedLaunch,
    SupportStatus,
    TrackingStatus,
)

__all__ = [
    "AdapterDiscoveryResult",
    "ComponentType",
    "Confidence",
    "DiagnosticCode",
    "DiagnosticSeverity",
    "DiscoveryCandidate",
    "DiscoveryDiagnostic",
    "DiscoveryEvidence",
    "DiscoveryScope",
    "LaunchKind",
    "PackageEcosystem",
    "ProviderKind",
    "ProviderResult",
    "ReasonCode",
    "RegistrationStatus",
    "RegistryMatch",
    "RegistryStatus",
    "SanitizedLaunch",
    "SupportStatus",
    "TrackingStatus",
]
