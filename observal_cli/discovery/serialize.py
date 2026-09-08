# SPDX-FileCopyrightText: 2026 Observal Contributors
# SPDX-License-Identifier: Apache-2.0

"""Deterministic, privacy-safe serialization for component discovery."""

from __future__ import annotations

import os
from collections.abc import Mapping
from enum import Enum
from pathlib import Path, PureWindowsPath
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Sequence

from observal_cli.discovery.models import (
    AdapterDiscoveryResult,
    ComponentType,
    DiscoveryCandidate,
    DiscoveryDiagnostic,
    DiscoveryEvidence,
    ProviderResult,
    RegistryMatch,
    SanitizedLaunch,
)
from observal_cli.harness import DiscoveredAgent, DiscoveredHook, DiscoveredMcp, DiscoveredSkill

DISCOVERY_SCHEMA_VERSION = 1

_COMPONENT_ORDER = {
    ComponentType.MCP: 0,
    ComponentType.SKILL: 1,
    ComponentType.HOOK: 2,
    ComponentType.AGENT: 3,
    None: 4,
}
_SEVERITY_ORDER = {"error": 0, "warning": 1, "info": 2}


def _is_absolute_path(value: str) -> bool:
    return Path(value).is_absolute() or PureWindowsPath(value).is_absolute()


def _relative_to(path: Path, root: Path) -> Path | None:
    try:
        return path.relative_to(root)
    except ValueError:
        return None


def privacy_safe_path(
    path: str | os.PathLike[str] | None,
    *,
    home: Path | None = None,
    project_dir: Path | None = None,
) -> str | None:
    """Return a stable display path without exposing an absolute parent path.

    Project paths take precedence over home paths because projects commonly
    live below the user's home. External paths expose their basename only.
    Existing safe display labels and relative paths are preserved.
    """

    if path is None:
        return None

    raw = os.fspath(path)
    if not _is_absolute_path(raw):
        return raw.replace("\\", "/")

    # A Windows path cannot be meaningfully resolved on POSIX. It is still
    # privacy-safe when reduced to an external basename marker.
    if PureWindowsPath(raw).is_absolute() and not Path(raw).is_absolute():
        return f"<external>/{PureWindowsPath(raw).name}"

    resolved = Path(raw).expanduser().resolve(strict=False)
    resolved_project = (project_dir or Path.cwd()).expanduser().resolve(strict=False)
    resolved_home = (home or Path.home()).expanduser().resolve(strict=False)

    relative = _relative_to(resolved, resolved_project)
    if relative is not None:
        return "<project>" if relative == Path(".") else f"<project>/{relative.as_posix()}"

    relative = _relative_to(resolved, resolved_home)
    if relative is not None:
        return "~" if relative == Path(".") else f"~/{relative.as_posix()}"

    return f"<external>/{resolved.name}"


def _safe_display(value: str | None) -> str | None:
    if value is None or not _is_absolute_path(value):
        return value
    return privacy_safe_path(value)


def component_type_of(component: object | None) -> ComponentType | None:
    if isinstance(component, DiscoveredMcp):
        return ComponentType.MCP
    if isinstance(component, DiscoveredSkill):
        return ComponentType.SKILL
    if isinstance(component, DiscoveredHook):
        return ComponentType.HOOK
    if isinstance(component, DiscoveredAgent):
        return ComponentType.AGENT
    return None


def _json_value(value: Any) -> Any:
    """Copy supported nested values into a deterministic JSON-safe shape."""

    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Path):
        return privacy_safe_path(value)
    if isinstance(value, Mapping):
        return {str(key): _json_value(value[key]) for key in sorted(value, key=str)}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"Unsupported discovery JSON value: {type(value).__name__}")


def component_to_dict(component: object | None) -> dict[str, Any] | None:
    """Serialize a legacy discovered component without using ``vars()``."""

    # Local import avoids coupling the path helper used by redaction back to
    # this module during import initialization.
    from observal_cli.discovery.redact import redact_arguments, redact_text, redact_value, sanitize_url

    if component is None:
        return None
    if isinstance(component, DiscoveredMcp):
        safe_arguments, _ = redact_arguments(component.args)
        return {
            "name": component.name,
            "command": redact_text(component.command) if component.command else None,
            "args": list(safe_arguments),
            "url": sanitize_url(component.url) if component.url else None,
            "description": redact_text(component.description),
            "source": _safe_display(component.source),
        }
    if isinstance(component, DiscoveredSkill):
        return {
            "name": component.name,
            "description": redact_text(component.description),
            "source": _safe_display(component.source),
            "task_type": component.task_type,
        }
    if isinstance(component, DiscoveredHook):
        return {
            "name": component.name,
            "event": component.event,
            "handler_type": component.handler_type,
            "handler_config": _json_value(redact_value(component.handler_config)),
            "description": redact_text(component.description),
            "source": _safe_display(component.source),
        }
    if isinstance(component, DiscoveredAgent):
        return {
            "name": component.name,
            "description": redact_text(component.description),
            "model_name": component.model_name,
            "prompt": redact_text(component.prompt),
            "source_file": _safe_display(component.source_file),
        }
    raise TypeError(f"Unsupported discovered component: {type(component).__name__}")


def launch_to_dict(launch: SanitizedLaunch) -> dict[str, Any]:
    from observal_cli.discovery.redact import redact_arguments, sanitize_url

    safe_arguments, _ = redact_arguments(launch.arguments)
    return {
        "kind": launch.kind.value if isinstance(launch.kind, Enum) else launch.kind,
        "package": launch.package,
        "module": launch.module,
        "script": _safe_display(launch.script),
        "url": sanitize_url(launch.url) if launch.url else None,
        "binary": launch.binary,
        "requirement": launch.requirement,
        "version": launch.version,
        "arguments": list(safe_arguments),
        "environment_names": sorted(launch.environment_names),
        "header_names": sorted(launch.header_names),
        "transport": launch.transport,
    }


def evidence_sort_key(evidence: DiscoveryEvidence) -> tuple[str, ...]:
    component_type = component_type_of(evidence.component)
    component = evidence.component
    name = getattr(component, "name", "") if component is not None else ""
    return (
        str(_COMPONENT_ORDER[component_type]),
        evidence.provider.value,
        evidence.harness or "",
        evidence.scope.value,
        evidence.display_path or "",
        evidence.package_name or "",
        name,
    )


def evidence_to_dict(evidence: DiscoveryEvidence) -> dict[str, Any]:
    return {
        "component": component_to_dict(evidence.component),
        "provider": evidence.provider.value,
        "scope": evidence.scope.value,
        "harness": evidence.harness,
        "display_path": _safe_display(evidence.display_path),
        "package_ecosystem": evidence.package_ecosystem.value if evidence.package_ecosystem else None,
        "package_name": evidence.package_name,
        "package_version": evidence.package_version,
        "launch": launch_to_dict(evidence.launch) if evidence.launch else None,
    }


def registry_match_to_dict(match: RegistryMatch) -> dict[str, Any]:
    return {
        "id": match.id,
        "qualified_name": match.qualified_name,
        "status": match.status,
        "component_type": match.component_type.value if match.component_type else None,
        "owned": match.owned,
        "version": match.version,
    }


def candidate_sort_key(candidate: DiscoveryCandidate) -> tuple[Any, ...]:
    evidence_key = min((evidence_sort_key(item) for item in candidate.evidence), default=("",) * 7)
    return (
        _COMPONENT_ORDER[candidate.component_type],
        candidate.correlation_identity or "",
        candidate.launch_fingerprint or "",
        candidate.local_name.casefold(),
        evidence_key[2],  # harness
        evidence_key[3],  # scope
        evidence_key[4],  # display path
    )


def candidate_to_dict(candidate: DiscoveryCandidate) -> dict[str, Any]:
    return {
        "component_type": candidate.component_type.value if candidate.component_type else None,
        "local_name": candidate.local_name,
        "correlation_identity": candidate.correlation_identity,
        "launch_fingerprint": candidate.launch_fingerprint,
        "tracking_status": candidate.tracking_status.value,
        "registry_status": candidate.registry_status.value,
        "support_status": candidate.support_status.value,
        "registration_status": candidate.registration_status.value,
        "confidence": candidate.confidence.value,
        "reason_codes": sorted({reason.value for reason in candidate.reason_codes}),
        "missing_fields": sorted(set(candidate.missing_fields)),
        "registry_match": registry_match_to_dict(candidate.registry_match) if candidate.registry_match else None,
        "evidence": [evidence_to_dict(item) for item in sorted(candidate.evidence, key=evidence_sort_key)],
    }


def diagnostic_sort_key(diagnostic: DiscoveryDiagnostic) -> tuple[Any, ...]:
    return (
        _SEVERITY_ORDER[diagnostic.severity.value],
        diagnostic.provider,
        diagnostic.code.value,
        diagnostic.source or "",
    )


def diagnostic_to_dict(diagnostic: DiscoveryDiagnostic) -> dict[str, Any]:
    from observal_cli.discovery.redact import sanitize_diagnostic_message

    return {
        "code": diagnostic.code.value,
        "severity": diagnostic.severity.value,
        "provider": diagnostic.provider,
        "source": _safe_display(diagnostic.source),
        "message": sanitize_diagnostic_message(diagnostic.message),
    }


def provider_result_to_dict(result: ProviderResult) -> dict[str, Any]:
    return {
        "evidence": [evidence_to_dict(item) for item in sorted(result.evidence, key=evidence_sort_key)],
        "diagnostics": [diagnostic_to_dict(item) for item in sorted(result.diagnostics, key=diagnostic_sort_key)],
    }


def adapter_discovery_result_to_dict(result: AdapterDiscoveryResult) -> dict[str, Any]:
    return {
        "evidence": [evidence_to_dict(item) for item in sorted(result.evidence, key=evidence_sort_key)],
        "diagnostics": [diagnostic_to_dict(item) for item in sorted(result.diagnostics, key=diagnostic_sort_key)],
    }


def legacy_scan_to_dict(
    *,
    harnesses: Sequence[Mapping[str, Any]],
    mcps: Sequence[DiscoveredMcp],
    skills: Sequence[DiscoveredSkill],
    hooks: Sequence[DiscoveredHook],
    agents: Sequence[DiscoveredAgent],
) -> dict[str, Any]:
    """Build the stable default-scan JSON shape without adding new keys."""

    return {
        "harnesses": sorted((dict(item) for item in harnesses), key=lambda item: str(item.get("name", ""))),
        "mcps": [component_to_dict(item) for item in sorted(mcps, key=_legacy_component_sort_key)],
        "skills": [component_to_dict(item) for item in sorted(skills, key=_legacy_component_sort_key)],
        "hooks": [component_to_dict(item) for item in sorted(hooks, key=_legacy_component_sort_key)],
        "agents": [component_to_dict(item) for item in sorted(agents, key=_legacy_component_sort_key)],
    }


def discovery_to_dict(
    *,
    harnesses: Sequence[Mapping[str, Any]],
    mcps: Sequence[DiscoveredMcp],
    skills: Sequence[DiscoveredSkill],
    hooks: Sequence[DiscoveredHook],
    agents: Sequence[DiscoveredAgent],
    candidates: Sequence[DiscoveryCandidate],
    diagnostics: Sequence[DiscoveryDiagnostic],
) -> dict[str, Any]:
    """Build the versioned discover JSON document in deterministic order."""

    return {
        "discovery_schema_version": DISCOVERY_SCHEMA_VERSION,
        "harnesses": sorted((dict(item) for item in harnesses), key=lambda item: str(item.get("name", ""))),
        "mcps": [component_to_dict(item) for item in sorted(mcps, key=_legacy_component_sort_key)],
        "skills": [component_to_dict(item) for item in sorted(skills, key=_legacy_component_sort_key)],
        "hooks": [component_to_dict(item) for item in sorted(hooks, key=_legacy_component_sort_key)],
        "agents": [component_to_dict(item) for item in sorted(agents, key=_legacy_component_sort_key)],
        "candidates": [candidate_to_dict(item) for item in sorted(candidates, key=candidate_sort_key)],
        "diagnostics": [diagnostic_to_dict(item) for item in sorted(diagnostics, key=diagnostic_sort_key)],
    }


def to_dict(value: Any) -> dict[str, Any] | None:
    """Serialize one discovery contract object through an explicit dispatcher."""

    if isinstance(value, DiscoveryCandidate):
        return candidate_to_dict(value)
    if isinstance(value, DiscoveryEvidence):
        return evidence_to_dict(value)
    if isinstance(value, DiscoveryDiagnostic):
        return diagnostic_to_dict(value)
    if isinstance(value, RegistryMatch):
        return registry_match_to_dict(value)
    if isinstance(value, SanitizedLaunch):
        return launch_to_dict(value)
    if isinstance(value, ProviderResult):
        return provider_result_to_dict(value)
    if isinstance(value, AdapterDiscoveryResult):
        return adapter_discovery_result_to_dict(value)
    if value is None or isinstance(value, (DiscoveredMcp, DiscoveredSkill, DiscoveredHook, DiscoveredAgent)):
        return component_to_dict(value)
    raise TypeError(f"Unsupported discovery object: {type(value).__name__}")


# Readable alias used by bounded walkers and adapters in later commits.
safe_display_path = privacy_safe_path


def _legacy_component_sort_key(component: object) -> tuple[str, str, str]:
    name = str(getattr(component, "name", "")).casefold()
    source = str(getattr(component, "source", getattr(component, "source_file", "")))
    return name, source, _safe_display(source) or ""
