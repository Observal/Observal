# SPDX-FileCopyrightText: 2026 Observal Contributors
# SPDX-License-Identifier: Apache-2.0

"""Structured launch parsing, identity normalization, and fingerprinting."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from packaging.requirements import InvalidRequirement, Requirement

from observal_cli.constants import VALID_MCP_TRANSPORTS
from observal_cli.discovery.models import (
    ComponentType,
    Confidence,
    DiscoveryCandidate,
    DiscoveryEvidence,
    LaunchKind,
    PackageEcosystem,
    ProviderKind,
    SanitizedLaunch,
)
from observal_cli.discovery.redact import is_secret_value, redact_arguments, sanitize_url
from observal_cli.harness import DiscoveredAgent, DiscoveredHook, DiscoveredMcp, DiscoveredSkill

_NPM_NAME_RE = re.compile(r"^(?:@[a-z0-9][a-z0-9._-]*/)?[a-z0-9][a-z0-9._-]*$", re.IGNORECASE)
_PYTHON_MODULE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*$")
_PEP503_SEPARATORS_RE = re.compile(r"[-_.]+")
_SHELL_WRAPPERS = {"sh", "bash", "zsh", "cmd", "cmd.exe", "powershell", "pwsh"}
_NPM_SAFE_OPTIONS = {"-y", "--yes", "--silent", "--offline", "--prefer-offline", "--ignore-scripts"}
_MCP_ENVIRONMENT_KEYS = ("env", "environment", "environmentVariables", "environment_variables")
_MCP_HEADER_KEYS = ("headers", "httpHeaders", "http_headers")
_MCP_TRANSPORT_KEYS = ("transport", "type")


@dataclass(frozen=True)
class LaunchNormalizationResult:
    launch: SanitizedLaunch | None
    correlation_identity: str | None
    launch_fingerprint: str | None
    complete: bool
    reason: str | None = None


@dataclass(frozen=True)
class McpLaunchMetadata:
    """Non-secret MCP metadata plus whether every recognized field was valid."""

    environment_names: tuple[str, ...] = ()
    header_names: tuple[str, ...] = ()
    transport: str | None = None
    complete: bool = True
    reason: str | None = None


def canonicalize_python_package_name(name: str) -> str:
    """Return the PEP 503 normalized package name."""

    return _PEP503_SEPARATORS_RE.sub("-", name).lower()


def package_correlation_identity(ecosystem: PackageEcosystem | str, package_name: str) -> str:
    ecosystem_value = ecosystem.value if isinstance(ecosystem, PackageEcosystem) else ecosystem
    normalized = (
        package_name.lower()
        if ecosystem_value == PackageEcosystem.NPM
        else canonicalize_python_package_name(package_name)
    )
    return f"{ecosystem_value}:{normalized}"


def split_npm_package_spec(requirement: str) -> tuple[str, str | None] | None:
    """Split an npm package requirement into package and version/tag."""

    value = requirement.strip()
    if not value or value.startswith(("npm:", "git+", "http://", "https://", "file:")) or "@npm:" in value:
        return None

    version: str | None = None
    if value.startswith("@"):
        slash = value.find("/")
        if slash <= 1:
            return None
        separator = value.rfind("@")
        if separator > slash:
            value, version = value[:separator], value[separator + 1 :]
    elif "@" in value:
        value, version = value.rsplit("@", 1)

    if not _NPM_NAME_RE.fullmatch(value) or version == "" or (version is not None and is_secret_value(version)):
        return None
    return value.lower(), version


def _canonical_python_base(requirement: Requirement) -> str:
    package = canonicalize_python_package_name(requirement.name)
    extras = f"[{','.join(sorted(requirement.extras))}]" if requirement.extras else ""
    return f"{package}{extras}"


def _split_python_requirement(requirement: str) -> tuple[str, str | None, str | None] | None:
    value = requirement.strip()
    if not value:
        return None

    # uv commonly accepts ``name@version`` in addition to PEP 508 syntax.
    if "@" in value and " @ " not in value:
        base, version = value.rsplit("@", 1)
        if base and version and not is_secret_value(version) and not any(marker in base for marker in "/\\:"):
            try:
                parsed_base = Requirement(base)
            except InvalidRequirement:
                return None
            if parsed_base.url:
                return None
            package = canonicalize_python_package_name(parsed_base.name)
            return package, f"{_canonical_python_base(parsed_base)}@{version}", version

    try:
        parsed = Requirement(value)
    except InvalidRequirement:
        return None
    if parsed.url:
        return None
    package = canonicalize_python_package_name(parsed.name)
    metadata = ""
    if parsed.extras:
        metadata += f"[{','.join(sorted(parsed.extras))}]"
    if parsed.specifier:
        metadata += str(parsed.specifier)
    if parsed.marker:
        metadata += f"; {parsed.marker}"
    canonical_requirement = f"{package}{metadata}" if metadata else None
    version_metadata = str(parsed.specifier) or None
    return package, canonical_requirement, version_metadata


def normalize_url_identity(url: str) -> tuple[str, str] | None:
    """Return sanitized launch URL and query-free correlation identity."""

    sanitized = sanitize_url(url)
    identity_url = sanitize_url(url, remove_all_query=True)
    if sanitized is None or identity_url is None:
        return None
    return sanitized, f"url:{identity_url}"


def canonical_launch_document(launch: SanitizedLaunch) -> dict[str, Any]:
    """Build the only document accepted as launch fingerprint input."""

    kind = launch.kind.value if isinstance(launch.kind, LaunchKind) else str(launch.kind)
    document: dict[str, Any] = {"kind": kind}
    for key in ("package", "module", "script", "binary", "requirement", "version", "transport"):
        value = getattr(launch, key)
        if value is not None:
            if is_secret_value(value):
                raise ValueError(f"launch {key} is not safely canonicalizable")
            document[key] = value
    if launch.url is not None:
        safe_url = sanitize_url(launch.url)
        if safe_url is None:
            raise ValueError("launch URL is not safely canonicalizable")
        document["url"] = safe_url
    if launch.arguments:
        safe_arguments, arguments_safe = redact_arguments(launch.arguments)
        if not arguments_safe:
            raise ValueError("launch arguments are not safely canonicalizable")
        document["arguments"] = list(safe_arguments)
    if launch.environment_names:
        document["environment_names"] = sorted(set(launch.environment_names))
    if launch.header_names:
        document["header_names"] = sorted(set(launch.header_names), key=str.casefold)
    return document


def serialize_canonical_launch(launch: SanitizedLaunch) -> str:
    return json.dumps(canonical_launch_document(launch), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def fingerprint_launch(launch: SanitizedLaunch) -> str:
    serialized = serialize_canonical_launch(launch).encode("utf-8")
    return f"sha256:{hashlib.sha256(serialized).hexdigest()}"


def correlation_identity_for_launch(launch: SanitizedLaunch | None) -> str | None:
    """Return the safe package/module/URL identity represented by a launch."""

    if launch is None:
        return None
    kind = launch.kind.value if isinstance(launch.kind, LaunchKind) else str(launch.kind)
    if launch.package:
        if kind == LaunchKind.NPM.value:
            return package_correlation_identity(PackageEcosystem.NPM, launch.package)
        if kind in {LaunchKind.UV.value, LaunchKind.PIPX.value}:
            return package_correlation_identity(PackageEcosystem.PYPI, launch.package)
        return None
    if launch.url:
        normalized = normalize_url_identity(launch.url)
        return normalized[1] if normalized else None
    if launch.module:
        return f"python:{launch.module.casefold()}"
    if launch.script:
        return f"node:{launch.script}"
    return None


def _component_type(component: object | None) -> ComponentType | None:
    if isinstance(component, DiscoveredMcp):
        return ComponentType.MCP
    if isinstance(component, DiscoveredSkill):
        return ComponentType.SKILL
    if isinstance(component, DiscoveredHook):
        return ComponentType.HOOK
    if isinstance(component, DiscoveredAgent):
        return ComponentType.AGENT
    return None


def _component_name(evidence: DiscoveryEvidence) -> str:
    component = evidence.component
    name = getattr(component, "name", None)
    if isinstance(name, str) and name:
        return name
    if evidence.launch and evidence.launch.binary:
        return evidence.launch.binary
    return evidence.package_name or "unknown-package"


def _safe_component_key(evidence: DiscoveryEvidence) -> tuple[object, ...]:
    component = evidence.component
    if isinstance(component, DiscoveredMcp):
        details: tuple[object, ...] = (
            component.name,
            component.command,
            tuple(component.args),
            component.url,
            component.description,
            component.source,
        )
    elif isinstance(component, DiscoveredSkill):
        details = (component.name, component.description, component.source, component.task_type)
    elif isinstance(component, DiscoveredHook):
        details = (
            component.name,
            component.event,
            component.handler_type,
            json.dumps(component.handler_config, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            component.description,
            component.source,
        )
    elif isinstance(component, DiscoveredAgent):
        details = (
            component.name,
            component.description,
            component.model_name,
            component.prompt,
            component.source_file,
        )
    else:
        details = (evidence.package_name, evidence.package_version)
    return (
        *details,
        evidence.harness,
        evidence.scope.value,
        evidence.display_path,
    )


def _evidence_identity(evidence: DiscoveryEvidence) -> tuple[str | None, str | None]:
    correlation = None
    if evidence.package_ecosystem and evidence.package_name:
        correlation = package_correlation_identity(evidence.package_ecosystem, evidence.package_name)
    if correlation is None:
        correlation = correlation_identity_for_launch(evidence.launch)
    fingerprint = None
    if evidence.launch is not None:
        try:
            fingerprint = fingerprint_launch(evidence.launch)
        except ValueError:
            pass
    return correlation, fingerprint


def _classify_candidate(candidate: DiscoveryCandidate) -> None:
    # Import locally so the pure normalization primitives remain independent of
    # draft schemas while candidate readiness uses the exact registration path.
    from observal_cli.discovery.readiness import validate_candidate_readiness

    readiness = validate_candidate_readiness(candidate)
    candidate.support_status = readiness.support_status
    candidate.registration_status = readiness.registration_status
    candidate.confidence = Confidence.LOW if candidate.component_type is None else Confidence.HIGH
    candidate.reason_codes = list(readiness.reason_codes)
    candidate.missing_fields = list(readiness.missing_fields)


def build_candidates(
    evidence: Sequence[DiscoveryEvidence],
    *,
    suppress_package_only: bool = False,
) -> list[DiscoveryCandidate]:
    """Merge exact harness launches and correlate bounded package evidence."""

    ordered = sorted(
        evidence,
        key=lambda item: (
            item.provider.value,
            item.harness or "",
            item.scope.value,
            item.display_path or "",
            _component_name(item).casefold(),
        ),
    )
    harness_candidates: dict[tuple[object, ...], DiscoveryCandidate] = {}
    exact_harness: dict[str, list[DiscoveryCandidate]] = {}
    correlated_harness: dict[str, list[DiscoveryCandidate]] = {}
    provider_evidence: list[DiscoveryEvidence] = []

    for item in ordered:
        if item.provider != ProviderKind.HARNESS:
            provider_evidence.append(item)
            continue
        component_type = _component_type(item.component)
        correlation, fingerprint = _evidence_identity(item)
        key: tuple[object, ...]
        if fingerprint:
            key = (component_type, "fingerprint", fingerprint)
        else:
            key = (component_type, "evidence", *_safe_component_key(item))
        candidate = harness_candidates.get(key)
        if candidate is None:
            candidate = DiscoveryCandidate(
                component_type=component_type,
                local_name=_component_name(item),
                correlation_identity=correlation,
                launch_fingerprint=fingerprint,
            )
            harness_candidates[key] = candidate
        candidate.evidence.append(item)
        if fingerprint:
            exact_harness.setdefault(fingerprint, []).append(candidate)
        if correlation:
            correlated_harness.setdefault(correlation, []).append(candidate)

    # A candidate may have multiple harness evidence records; remove duplicate
    # references before enriching each exact launch once.
    for index in (exact_harness, correlated_harness):
        for identity, values in index.items():
            index[identity] = list({id(candidate): candidate for candidate in values}.values())

    package_candidates: dict[tuple[object, ...], DiscoveryCandidate] = {}
    for item in provider_evidence:
        correlation, fingerprint = _evidence_identity(item)
        matches = exact_harness.get(fingerprint, []) if fingerprint else []
        if not matches and correlation:
            matches = correlated_harness.get(correlation, [])
        if matches:
            for candidate in matches:
                candidate.evidence.append(item)
            continue
        if suppress_package_only or item.launch is None:
            continue
        key = ("fingerprint", fingerprint) if fingerprint else ("evidence", *_safe_component_key(item))
        candidate = package_candidates.get(key)
        if candidate is None:
            candidate = DiscoveryCandidate(
                component_type=None,
                local_name=_component_name(item),
                correlation_identity=correlation,
                launch_fingerprint=fingerprint,
            )
            package_candidates[key] = candidate
        candidate.evidence.append(item)

    candidates = [*harness_candidates.values(), *package_candidates.values()]
    for candidate in candidates:
        candidate.evidence.sort(
            key=lambda item: (
                item.provider.value,
                item.harness or "",
                item.scope.value,
                item.display_path or "",
                _component_name(item).casefold(),
            )
        )
        _classify_candidate(candidate)
    component_order = {
        ComponentType.MCP: 0,
        ComponentType.SKILL: 1,
        ComponentType.HOOK: 2,
        ComponentType.AGENT: 3,
        None: 4,
    }
    return sorted(
        candidates,
        key=lambda candidate: (
            component_order[candidate.component_type],
            candidate.correlation_identity or "",
            candidate.launch_fingerprint or "",
            candidate.local_name.casefold(),
        ),
    )


def _result(
    launch: SanitizedLaunch, correlation_identity: str | None, *, safe: bool = True
) -> LaunchNormalizationResult:
    fingerprint: str | None = None
    if safe:
        try:
            fingerprint = fingerprint_launch(launch)
        except ValueError:
            safe = False
    return LaunchNormalizationResult(
        launch=launch,
        correlation_identity=correlation_identity,
        launch_fingerprint=fingerprint,
        complete=safe,
        reason=None if safe else "unsafe_or_unclassified_arguments",
    )


def _incomplete(
    reason: str, launch: SanitizedLaunch | None = None, identity: str | None = None
) -> LaunchNormalizationResult:
    return LaunchNormalizationResult(launch, identity, None, False, reason)


def _named_metadata(value: object, *, separator: str) -> tuple[tuple[str, ...], bool]:
    raw_names: list[object]
    if isinstance(value, Mapping):
        raw_names = list(value)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        raw_names = []
        for item in value:
            if isinstance(item, Mapping):
                raw_names.append(item.get("name"))
            elif isinstance(item, str):
                raw_names.append(item.split(separator, 1)[0])
            else:
                return (), False
    else:
        return (), False
    if any(not isinstance(name, str) or not name.strip() for name in raw_names):
        return (), False
    return tuple(sorted({name.strip() for name in raw_names}, key=str.casefold)), True


def _metadata_alias(config: Mapping[str, object], keys: tuple[str, ...]) -> tuple[object | None, bool, bool]:
    present = [key for key in keys if key in config]
    if not present:
        return None, False, True
    if len(present) != 1:
        return None, True, False
    return config[present[0]], True, True


def extract_mcp_launch_metadata(config: Mapping[str, object]) -> McpLaunchMetadata:
    """Extract non-secret MCP metadata and fail closed on recognized malformed fields."""

    environment, present, unambiguous = _metadata_alias(config, _MCP_ENVIRONMENT_KEYS)
    if not unambiguous:
        return McpLaunchMetadata(complete=False, reason="ambiguous_environment_metadata")
    environment_names, valid = _named_metadata(environment, separator="=") if present else ((), True)
    if not valid:
        return McpLaunchMetadata(complete=False, reason="malformed_environment")

    headers, present, unambiguous = _metadata_alias(config, _MCP_HEADER_KEYS)
    if not unambiguous:
        return McpLaunchMetadata(environment_names, complete=False, reason="ambiguous_header_metadata")
    header_names, valid = _named_metadata(headers, separator=":") if present else ((), True)
    if not valid:
        return McpLaunchMetadata(environment_names, complete=False, reason="malformed_headers")

    transport_value, present, unambiguous = _metadata_alias(config, _MCP_TRANSPORT_KEYS)
    if not unambiguous:
        return McpLaunchMetadata(environment_names, header_names, complete=False, reason="ambiguous_transport")
    if not present:
        return McpLaunchMetadata(environment_names, header_names)
    if not isinstance(transport_value, str) or not transport_value.strip():
        return McpLaunchMetadata(environment_names, header_names, complete=False, reason="malformed_transport")
    transport = transport_value.strip().casefold().replace("_", "-")
    # Several harnesses use the older `http` spelling for MCP Streamable
    # HTTP. Preserve that input contract while keeping one canonical identity.
    if transport == "http":
        transport = "streamable-http"
    if transport not in VALID_MCP_TRANSPORTS:
        return McpLaunchMetadata(environment_names, header_names, complete=False, reason="unsupported_transport")
    return McpLaunchMetadata(environment_names, header_names, transport)


def _environment_names(environment: Mapping[str, object] | Sequence[str] | None) -> tuple[str, ...]:
    if environment is None:
        return ()
    names = environment.keys() if isinstance(environment, Mapping) else environment
    return tuple(sorted({str(name).split("=", 1)[0] for name in names if str(name).split("=", 1)[0]}))


def _header_names(headers: Mapping[str, object] | Sequence[str] | None) -> tuple[str, ...]:
    if headers is None:
        return ()
    names = headers.keys() if isinstance(headers, Mapping) else headers
    return tuple(sorted({str(name).split(":", 1)[0] for name in names if str(name).split(":", 1)[0]}, key=str.casefold))


def _base_command(command: str) -> str:
    return Path(command).name.casefold()


def _normalize_npm(
    command: str,
    arguments: Sequence[str],
    environment_names: tuple[str, ...],
    header_names: tuple[str, ...],
    transport: str | None,
    selected_binary: str | None,
) -> LaunchNormalizationResult:
    values = list(arguments)
    executable = _base_command(command)
    if executable in {"npx", "npx.cmd"}:
        while values and values[0] in {"-y", "--yes"}:
            values.pop(0)
    else:
        if not values or values.pop(0).casefold() != "exec":
            return _incomplete("unsupported_npm_invocation")
        while values and values[0] != "--":
            option = values.pop(0)
            if not option.startswith("-"):
                return _incomplete("npm_exec_separator_required")
            if option not in _NPM_SAFE_OPTIONS:
                return _incomplete("unsupported_npm_option")
        if not values or values.pop(0) != "--":
            return _incomplete("npm_exec_separator_required")

    if not values:
        return _incomplete("package_required")
    requirement = values.pop(0)
    package_spec = split_npm_package_spec(requirement)
    if package_spec is None:
        return _incomplete("unsupported_npm_requirement")
    package, version = package_spec
    safe_arguments, arguments_safe = redact_arguments(values)
    launch = SanitizedLaunch(
        kind=LaunchKind.NPM,
        package=package,
        binary=selected_binary or package.rsplit("/", 1)[-1],
        requirement=requirement if version is not None else None,
        version=version,
        arguments=safe_arguments,
        environment_names=environment_names,
        header_names=header_names,
        transport=transport,
    )
    return _result(launch, package_correlation_identity(PackageEcosystem.NPM, package), safe=arguments_safe)


def _normalize_uv(
    arguments: Sequence[str],
    environment_names: tuple[str, ...],
    header_names: tuple[str, ...],
    transport: str | None,
    selected_binary: str | None,
) -> LaunchNormalizationResult:
    values = list(arguments)
    if not values:
        return _incomplete("package_required")
    requirement = values.pop(0)
    package_spec = _split_python_requirement(requirement)
    if package_spec is None:
        return _incomplete("unsupported_python_requirement")
    package, canonical_requirement, version_metadata = package_spec
    safe_arguments, arguments_safe = redact_arguments(values)
    launch = SanitizedLaunch(
        kind=LaunchKind.UV,
        package=package,
        binary=selected_binary or package,
        requirement=canonical_requirement,
        version=version_metadata,
        arguments=safe_arguments,
        environment_names=environment_names,
        header_names=header_names,
        transport=transport,
    )
    return _result(launch, package_correlation_identity(PackageEcosystem.PYPI, package), safe=arguments_safe)


def _resolve_script(script: str, source_root: Path | None, working_dir: Path | None) -> str | None:
    if source_root is None:
        return None
    root = source_root.expanduser().resolve(strict=False)
    candidate = Path(script).expanduser()
    if not candidate.is_absolute():
        candidate = (working_dir or root) / candidate
    resolved = candidate.resolve(strict=False)
    try:
        relative = resolved.relative_to(root)
    except ValueError:
        return None
    return relative.as_posix()


def _pipx_package(known: Mapping[str, object], executable: str) -> tuple[str, str | None] | None:
    value = known.get(executable)
    if value is None:
        return None
    if isinstance(value, str):
        return canonicalize_python_package_name(value), None
    if isinstance(value, Mapping):
        name = value.get("package") or value.get("name")
        version = value.get("version")
        if isinstance(name, str):
            return canonicalize_python_package_name(name), str(version) if version is not None else None
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)) and value:
        return canonicalize_python_package_name(str(value[0])), str(value[1]) if len(value) > 1 else None
    return None


def normalize_mcp_definition(
    config: Mapping[str, object],
    *,
    source_root: Path | None = None,
    working_dir: Path | None = None,
) -> LaunchNormalizationResult:
    """Normalize a structured MCP definition shared by discovery and installs."""

    command_value = config.get("command")
    raw_arguments = config.get("args", [])
    if isinstance(command_value, Sequence) and not isinstance(command_value, (str, bytes)):
        command_parts = list(command_value)
        if not command_parts or any(not isinstance(part, str) for part in command_parts):
            return _incomplete("malformed_command")
        command = command_parts[0]
        arguments: Sequence[str] = command_parts[1:]
    else:
        command = command_value if isinstance(command_value, str) else None
        if not isinstance(raw_arguments, Sequence) or isinstance(raw_arguments, (str, bytes)):
            return _incomplete("malformed_arguments")
        if any(not isinstance(argument, str) for argument in raw_arguments):
            return _incomplete("malformed_arguments")
        arguments = raw_arguments

    url_value = config.get("url", config.get("serverUrl"))
    if url_value is not None and not isinstance(url_value, str):
        return _incomplete("malformed_url")
    metadata = extract_mcp_launch_metadata(config)
    normalized = normalize_launch(
        command=command,
        arguments=arguments,
        url=url_value,
        environment=metadata.environment_names,
        headers=metadata.header_names,
        transport=metadata.transport,
        source_root=source_root,
        working_dir=working_dir,
    )
    if not metadata.complete:
        return LaunchNormalizationResult(
            launch=normalized.launch,
            correlation_identity=normalized.correlation_identity,
            launch_fingerprint=None,
            complete=False,
            reason=metadata.reason,
        )
    return normalized


def normalize_launch(
    *,
    command: str | None = None,
    arguments: Sequence[str] = (),
    url: str | None = None,
    environment: Mapping[str, object] | Sequence[str] | None = None,
    headers: Mapping[str, object] | Sequence[str] | None = None,
    transport: str | None = None,
    selected_binary: str | None = None,
    known_pipx_executables: Mapping[str, object] | None = None,
    source_root: Path | None = None,
    working_dir: Path | None = None,
) -> LaunchNormalizationResult:
    """Normalize one structured launch without parsing shell command strings."""

    environment_names = _environment_names(environment)
    header_names = _header_names(headers)

    if url is not None:
        normalized_url = normalize_url_identity(url)
        if normalized_url is None:
            return _incomplete("unsupported_url")
        sanitized_url, identity = normalized_url
        launch = SanitizedLaunch(
            kind=LaunchKind.URL,
            url=sanitized_url,
            environment_names=environment_names,
            header_names=header_names,
            transport=transport,
        )
        return _result(launch, identity)

    if not command:
        return _incomplete("command_or_url_required")
    if any(character.isspace() for character in command.strip()):
        return _incomplete("shell_command_string_unsupported")

    executable = _base_command(command)
    if executable in _SHELL_WRAPPERS:
        return _incomplete("shell_wrapper_unsupported")
    if executable in {"npx", "npx.cmd", "npm", "npm.cmd"}:
        return _normalize_npm(command, arguments, environment_names, header_names, transport, selected_binary)
    if executable == "uvx":
        return _normalize_uv(arguments, environment_names, header_names, transport, selected_binary)
    if executable == "uv":
        values = list(arguments)
        if len(values) < 2 or values[:2] != ["tool", "run"]:
            return _incomplete("unsupported_uv_invocation")
        return _normalize_uv(values[2:], environment_names, header_names, transport, selected_binary)
    if executable in {"python", "python3", "python.exe", "python3.exe"}:
        values = list(arguments)
        if len(values) < 2 or values[0] != "-m" or not _PYTHON_MODULE_RE.fullmatch(values[1]):
            return _incomplete("unsupported_python_invocation")
        module = values[1]
        safe_arguments, arguments_safe = redact_arguments(values[2:])
        launch = SanitizedLaunch(
            kind=LaunchKind.PYTHON_MODULE,
            module=module,
            binary=executable,
            arguments=safe_arguments,
            environment_names=environment_names,
            header_names=header_names,
            transport=transport,
        )
        return _result(launch, f"python:{module.casefold()}", safe=arguments_safe)
    if executable in {"node", "node.exe"}:
        values = list(arguments)
        if not values:
            return _incomplete("script_required")
        script = _resolve_script(values[0], source_root, working_dir)
        if script is None:
            return _incomplete("script_outside_source_root")
        safe_arguments, arguments_safe = redact_arguments(values[1:])
        launch = SanitizedLaunch(
            kind=LaunchKind.NODE,
            script=script,
            binary=executable,
            arguments=safe_arguments,
            environment_names=environment_names,
            header_names=header_names,
            transport=transport,
        )
        return _result(launch, f"node:{script}", safe=arguments_safe)

    pipx = _pipx_package(known_pipx_executables or {}, executable)
    if pipx is not None:
        package, version = pipx
        safe_arguments, arguments_safe = redact_arguments(arguments)
        launch = SanitizedLaunch(
            kind=LaunchKind.PIPX,
            package=package,
            binary=executable,
            version=version,
            arguments=safe_arguments,
            environment_names=environment_names,
            header_names=header_names,
            transport=transport,
        )
        return _result(launch, package_correlation_identity(PackageEcosystem.PYPI, package), safe=arguments_safe)

    return _incomplete("unknown_executable")
