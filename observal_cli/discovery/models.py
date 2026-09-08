# SPDX-FileCopyrightText: 2026 Observal Contributors
# SPDX-License-Identifier: Apache-2.0

"""Typed contracts shared by component discovery stages.

The legacy ``Discovered*`` records intentionally remain unchanged. Discovery
wraps those records with provenance and classification instead of extending
their public ``vars()`` shape.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any, TypeAlias

if TYPE_CHECKING:
    from pathlib import Path

from observal_cli.harness import DiscoveredAgent, DiscoveredHook, DiscoveredMcp, DiscoveredSkill

DiscoveredComponent: TypeAlias = DiscoveredMcp | DiscoveredSkill | DiscoveredHook | DiscoveredAgent


class TrackingStatus(StrEnum):
    TRACKED = "tracked"
    NOT_TRACKED = "not_tracked"
    AMBIGUOUS = "ambiguous"


class RegistryStatus(StrEnum):
    NOT_CHECKED = "not_checked"
    UNAVAILABLE = "unavailable"
    NO_EXACT_MATCH = "no_exact_match"
    EXACT_MATCH = "exact_match"
    OWNED_EXISTING = "owned_existing"
    AMBIGUOUS = "ambiguous"


class SupportStatus(StrEnum):
    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"


class RegistrationStatus(StrEnum):
    ELIGIBLE = "eligible"
    INCOMPLETE = "incomplete"
    REQUIRES_AUTH = "requires_auth"
    ALREADY_EXISTS = "already_exists"
    NOT_APPLICABLE = "not_applicable"


class ComponentType(StrEnum):
    MCP = "mcp"
    SKILL = "skill"
    HOOK = "hook"
    AGENT = "agent"


class ProviderKind(StrEnum):
    HARNESS = "harness"
    NPM = "npm"
    PIPX = "pipx"
    UV = "uv"


class DiscoveryScope(StrEnum):
    USER = "user"
    PROJECT = "project"
    GLOBAL = "global"


class PackageEcosystem(StrEnum):
    NPM = "npm"
    PYPI = "pypi"


class LaunchKind(StrEnum):
    NPM = "npm"
    UV = "uv"
    PIPX = "pipx"
    NODE = "node"
    PYTHON_MODULE = "python_module"
    URL = "url"
    EXECUTABLE = "executable"


class Confidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class ReasonCode(StrEnum):
    """Stable machine-readable explanations for candidate classifications."""

    MISSING_REQUIRED_FIELDS = "missing_required_fields"
    UNSAFE_LAUNCH = "unsafe_launch"
    UNSUPPORTED_LAUNCH = "unsupported_launch"
    UNSUPPORTED_COMPONENT_TYPE = "unsupported_component_type"
    PACKAGE_EVIDENCE_ONLY = "package_evidence_only"
    CACHE_EVIDENCE_ONLY = "cache_evidence_only"
    MANAGED_TELEMETRY_COMPONENT = "managed_telemetry_component"
    ALREADY_TRACKED = "already_tracked"
    TRACKING_AMBIGUOUS = "tracking_ambiguous"
    REGISTRY_NOT_CHECKED = "registry_not_checked"
    REGISTRY_NOT_CONFIGURED = "registry_not_configured"
    REGISTRY_AUTH_REQUIRED = "registry_auth_required"
    REGISTRY_UNAVAILABLE = "registry_unavailable"
    REGISTRY_LOOKUP_INCOMPLETE = "registry_lookup_incomplete"
    NO_EXACT_REGISTRY_MATCH = "no_exact_registry_match"
    REGISTRY_EXACT_MATCH = "registry_exact_match"
    REGISTRY_OWNED_EXISTING = "registry_owned_existing"
    REGISTRY_AMBIGUOUS = "registry_ambiguous"


class DiagnosticSeverity(StrEnum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class DiagnosticCode(StrEnum):
    EXECUTABLE_MISSING = "executable_missing"
    SUBPROCESS_TIMEOUT = "subprocess_timeout"
    SUBPROCESS_FAILED = "subprocess_failed"
    OUTPUT_TOO_LARGE = "output_too_large"
    METADATA_TOO_LARGE = "metadata_too_large"
    METADATA_MALFORMED = "metadata_malformed"
    UNSUPPORTED_LAUNCH = "unsupported_launch"
    UNSUPPORTED_VERSION = "unsupported_version"
    PERMISSION_DENIED = "permission_denied"
    PATH_OUTSIDE_ROOT = "path_outside_root"
    SYMLINK_ESCAPE = "symlink_escape"
    RECURSION_LIMIT_REACHED = "recursion_limit_reached"
    ITEM_LIMIT_REACHED = "item_limit_reached"
    ADAPTER_DEADLINE_EXCEEDED = "adapter_deadline_exceeded"
    APPROVED_ROOT_LIMIT_REACHED = "approved_root_limit_reached"
    COLLECTION_FILE_LIMIT_REACHED = "collection_file_limit_reached"
    EVIDENCE_LIMIT_REACHED = "evidence_limit_reached"
    DIAGNOSTIC_LIMIT_REACHED = "diagnostic_limit_reached"
    REGISTRY_NOT_CONFIGURED = "registry_not_configured"
    REGISTRY_AUTH_REQUIRED = "registry_auth_required"
    REGISTRY_UNAVAILABLE = "registry_unavailable"
    REGISTRY_LOOKUP_INCOMPLETE = "registry_lookup_incomplete"


@dataclass(frozen=True)
class SanitizedLaunch:
    """A structured launch with secret values already replaced or removed.

    Normalization and canonical fingerprinting are implemented in the next
    discovery stage. Keeping this model structured prevents callers from
    falling back to shell-string parsing.
    """

    kind: LaunchKind | str
    package: str | None = None
    module: str | None = None
    script: str | None = None
    url: str | None = None
    binary: str | None = None
    requirement: str | None = None
    version: str | None = None
    arguments: tuple[str, ...] = ()
    environment_names: tuple[str, ...] = ()
    header_names: tuple[str, ...] = ()
    transport: str | None = None


@dataclass(frozen=True)
class RegistryMatch:
    id: str
    qualified_name: str
    status: str
    component_type: ComponentType | None = None
    owned: bool = False
    version: str | None = None


@dataclass(frozen=True)
class DiscoveryEvidence:
    component: DiscoveredComponent | None
    provider: ProviderKind
    scope: DiscoveryScope
    harness: str | None = None
    source_path: Path | None = None
    display_path: str | None = None
    package_ecosystem: PackageEcosystem | None = None
    package_name: str | None = None
    package_version: str | None = None
    launch: SanitizedLaunch | None = None


@dataclass
class DiscoveryCandidate:
    component_type: ComponentType | None
    local_name: str
    correlation_identity: str | None
    launch_fingerprint: str | None
    evidence: list[DiscoveryEvidence] = field(default_factory=list)
    tracking_status: TrackingStatus = TrackingStatus.NOT_TRACKED
    registry_status: RegistryStatus = RegistryStatus.NOT_CHECKED
    support_status: SupportStatus = SupportStatus.UNSUPPORTED
    registration_status: RegistrationStatus = RegistrationStatus.INCOMPLETE
    confidence: Confidence = Confidence.LOW
    reason_codes: list[ReasonCode] = field(default_factory=list)
    missing_fields: list[str] = field(default_factory=list)
    registry_match: RegistryMatch | None = None


@dataclass(frozen=True)
class DiscoveryDiagnostic:
    code: DiagnosticCode
    severity: DiagnosticSeverity
    provider: str
    source: str | None
    message: str


@dataclass
class ProviderResult:
    evidence: list[DiscoveryEvidence] = field(default_factory=list)
    diagnostics: list[DiscoveryDiagnostic] = field(default_factory=list)


@dataclass
class AdapterDiscoveryResult:
    evidence: list[DiscoveryEvidence] = field(default_factory=list)
    diagnostics: list[DiscoveryDiagnostic] = field(default_factory=list)


JsonObject: TypeAlias = dict[str, Any]
