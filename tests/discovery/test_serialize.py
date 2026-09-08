# SPDX-FileCopyrightText: 2026 Observal Contributors
# SPDX-License-Identifier: Apache-2.0

from pathlib import Path

from observal_cli.discovery.models import (
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
    ReasonCode,
    RegistrationStatus,
    RegistryMatch,
    RegistryStatus,
    SanitizedLaunch,
    SupportStatus,
    TrackingStatus,
)
from observal_cli.discovery.serialize import (
    DISCOVERY_SCHEMA_VERSION,
    candidate_to_dict,
    diagnostic_to_dict,
    discovery_to_dict,
    evidence_to_dict,
    privacy_safe_path,
)
from observal_cli.harness import DiscoveredAgent, DiscoveredHook, DiscoveredMcp, DiscoveredSkill


def _candidate(
    name: str, component_type: ComponentType | None, evidence: list[DiscoveryEvidence]
) -> DiscoveryCandidate:
    return DiscoveryCandidate(
        component_type=component_type,
        local_name=name,
        correlation_identity=f"npm:{name}" if component_type is ComponentType.MCP else None,
        launch_fingerprint=f"sha256:{name}" if component_type is not None else None,
        evidence=evidence,
        tracking_status=TrackingStatus.NOT_TRACKED,
        registry_status=RegistryStatus.NO_EXACT_MATCH,
        support_status=SupportStatus.SUPPORTED,
        registration_status=RegistrationStatus.ELIGIBLE,
        confidence=Confidence.HIGH,
    )


def test_privacy_safe_path_prefers_project_then_home_and_hides_external_parent(tmp_path: Path) -> None:
    home = tmp_path / "home"
    project = home / "work" / "repo"

    assert privacy_safe_path(project / ".mcp.json", home=home, project_dir=project) == "<project>/.mcp.json"
    assert privacy_safe_path(home / ".claude" / "settings.json", home=home, project_dir=project) == (
        "~/.claude/settings.json"
    )
    assert privacy_safe_path(tmp_path / "private" / "credentials.json", home=home, project_dir=project) == (
        "<external>/credentials.json"
    )
    assert privacy_safe_path("relative/settings.json", home=home, project_dir=project) == "relative/settings.json"
    assert privacy_safe_path(r"C:\\Users\\alice\\secret.json", home=home, project_dir=project) == (
        "<external>/secret.json"
    )


def test_evidence_serialization_omits_internal_source_path_and_emits_nulls() -> None:
    evidence = DiscoveryEvidence(
        component=DiscoveredMcp("server", "npx", ["-y", "server"], None, "Description", "claude"),
        provider=ProviderKind.HARNESS,
        scope=DiscoveryScope.USER,
        harness="claude-code",
        source_path=Path("/Users/alice/.claude/settings.json"),
        display_path="~/.claude/settings.json",
        package_ecosystem=PackageEcosystem.NPM,
        package_name="server",
        launch=SanitizedLaunch(
            kind="npm",
            package="server",
            arguments=("--token", "<secret>"),
            environment_names=("Z_KEY", "API_KEY"),
        ),
    )

    result = evidence_to_dict(evidence)

    assert "source_path" not in result
    assert "/Users/alice" not in str(result)
    assert result["package_version"] is None
    assert result["launch"]["environment_names"] == ["API_KEY", "Z_KEY"]
    assert result["launch"]["header_names"] == []
    assert result["component"] == {
        "name": "server",
        "command": "npx",
        "args": ["-y", "server"],
        "url": None,
        "description": "Description",
        "source": "claude",
    }


def test_candidate_serialization_is_explicit_and_deterministic() -> None:
    package_evidence = DiscoveryEvidence(
        None,
        ProviderKind.NPM,
        DiscoveryScope.GLOBAL,
        package_ecosystem=PackageEcosystem.NPM,
        package_name="server",
    )
    harness_evidence = DiscoveryEvidence(
        DiscoveredMcp("server", "npx", ["server"], None, "", "kiro"),
        ProviderKind.HARNESS,
        DiscoveryScope.PROJECT,
        harness="kiro",
        display_path="<project>/.kiro/settings/mcp.json",
    )
    candidate = _candidate("server", ComponentType.MCP, [package_evidence, harness_evidence])
    candidate.reason_codes = [ReasonCode.REGISTRY_AUTH_REQUIRED, ReasonCode.MISSING_REQUIRED_FIELDS]
    candidate.missing_fields = ["description", "description"]
    candidate.registry_match = RegistryMatch("uuid", "alice/server", "draft", ComponentType.MCP, owned=True)

    result = candidate_to_dict(candidate)

    assert list(result) == [
        "component_type",
        "local_name",
        "correlation_identity",
        "launch_fingerprint",
        "tracking_status",
        "registry_status",
        "support_status",
        "registration_status",
        "confidence",
        "reason_codes",
        "missing_fields",
        "registry_match",
        "evidence",
    ]
    assert result["reason_codes"] == ["missing_required_fields", "registry_auth_required"]
    assert result["missing_fields"] == ["description"]
    assert [item["provider"] for item in result["evidence"]] == ["harness", "npm"]
    assert result["registry_match"]["qualified_name"] == "alice/server"


def test_diagnostic_serialization_never_emits_absolute_source_path(tmp_path: Path) -> None:
    diagnostic = DiscoveryDiagnostic(
        DiagnosticCode.METADATA_MALFORMED,
        DiagnosticSeverity.WARNING,
        "npm",
        str(tmp_path / "private" / "package.json"),
        "Package metadata is malformed",
    )

    result = diagnostic_to_dict(diagnostic)

    assert result["source"] == "<external>/package.json"
    assert str(tmp_path) not in str(result)


def test_discovery_document_preserves_legacy_arrays_and_stable_order() -> None:
    mcp_a = DiscoveredMcp("alpha", "npx", ["alpha"], None, "", "z-source")
    mcp_z = DiscoveredMcp("zeta", "npx", ["zeta"], None, "", "a-source")
    skill = DiscoveredSkill("skill", "", "source")
    hook = DiscoveredHook("hook", "Stop", "command", {"command": "true"}, "", "source")
    agent = DiscoveredAgent("agent", "", "model", "prompt", "AGENTS.md")
    package_evidence = DiscoveryEvidence(None, ProviderKind.NPM, DiscoveryScope.GLOBAL)
    unknown = _candidate("unknown", None, [package_evidence])
    known = _candidate("known", ComponentType.MCP, [package_evidence])
    diagnostics = [
        DiscoveryDiagnostic(
            DiagnosticCode.EXECUTABLE_MISSING,
            DiagnosticSeverity.INFO,
            "npm",
            None,
            "not installed",
        ),
        DiscoveryDiagnostic(
            DiagnosticCode.METADATA_MALFORMED,
            DiagnosticSeverity.ERROR,
            "uv",
            None,
            "bad metadata",
        ),
    ]

    result = discovery_to_dict(
        harnesses=[{"name": "kiro", "hooks": "installed"}, {"name": "claude-code", "hooks": "partial"}],
        mcps=[mcp_z, mcp_a],
        skills=[skill],
        hooks=[hook],
        agents=[agent],
        candidates=[unknown, known],
        diagnostics=diagnostics,
    )

    assert result["discovery_schema_version"] == DISCOVERY_SCHEMA_VERSION == 1
    assert list(result) == [
        "discovery_schema_version",
        "harnesses",
        "mcps",
        "skills",
        "hooks",
        "agents",
        "candidates",
        "diagnostics",
    ]
    assert [item["name"] for item in result["harnesses"]] == ["claude-code", "kiro"]
    assert [item["name"] for item in result["mcps"]] == ["alpha", "zeta"]
    assert [item["local_name"] for item in result["candidates"]] == ["known", "unknown"]
    assert [item["severity"] for item in result["diagnostics"]] == ["error", "info"]
