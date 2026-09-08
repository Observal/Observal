# SPDX-FileCopyrightText: 2026 Observal Contributors
# SPDX-License-Identifier: Apache-2.0

"""Fail-closed authenticated Registry classification for discovery candidates."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from observal_cli import client, config
from observal_cli.discovery.models import (
    ComponentType,
    DiagnosticCode,
    DiagnosticSeverity,
    DiscoveryCandidate,
    DiscoveryDiagnostic,
    ReasonCode,
    RegistrationStatus,
    RegistryMatch,
    RegistryStatus,
    SupportStatus,
)
from observal_cli.errors import CliError
from observal_shared.namespace_rules import is_valid_namespace
from observal_shared.registry_slug import slugify

_MY_PATHS = {
    ComponentType.AGENT: "/api/v1/agents/my",
    ComponentType.MCP: "/api/v1/mcps/my",
    ComponentType.SKILL: "/api/v1/skills/my",
    ComponentType.HOOK: "/api/v1/hooks/my",
}
_DETAIL_PATHS = {
    ComponentType.AGENT: "/api/v1/agents/{id}",
    ComponentType.MCP: "/api/v1/mcps/{id}",
    ComponentType.SKILL: "/api/v1/skills/{id}",
    ComponentType.HOOK: "/api/v1/hooks/{id}",
}
_ELIGIBILITY_BLOCKERS = {
    ReasonCode.MISSING_REQUIRED_FIELDS,
    ReasonCode.UNSAFE_LAUNCH,
    ReasonCode.UNSUPPORTED_LAUNCH,
    ReasonCode.UNSUPPORTED_COMPONENT_TYPE,
    ReasonCode.PACKAGE_EVIDENCE_ONLY,
    ReasonCode.CACHE_EVIDENCE_ONLY,
    ReasonCode.MANAGED_TELEMETRY_COMPONENT,
}
_REGISTRY_REASONS = {
    ReasonCode.REGISTRY_NOT_CHECKED,
    ReasonCode.REGISTRY_NOT_CONFIGURED,
    ReasonCode.REGISTRY_AUTH_REQUIRED,
    ReasonCode.REGISTRY_UNAVAILABLE,
    ReasonCode.REGISTRY_LOOKUP_INCOMPLETE,
    ReasonCode.NO_EXACT_REGISTRY_MATCH,
    ReasonCode.REGISTRY_EXACT_MATCH,
    ReasonCode.REGISTRY_OWNED_EXISTING,
    ReasonCode.REGISTRY_AMBIGUOUS,
}


def _diagnostic(code: DiagnosticCode, message: str) -> DiscoveryDiagnostic:
    return DiscoveryDiagnostic(code, DiagnosticSeverity.WARNING, "registry", None, message)


def _reset_registry_reasons(candidate: DiscoveryCandidate) -> None:
    candidate.reason_codes = [reason for reason in candidate.reason_codes if reason not in _REGISTRY_REASONS]
    candidate.registry_match = None


def _otherwise_eligible(candidate: DiscoveryCandidate) -> bool:
    return (
        candidate.component_type in _MY_PATHS
        and candidate.support_status == SupportStatus.SUPPORTED
        and not candidate.missing_fields
        and not any(reason in _ELIGIBILITY_BLOCKERS for reason in candidate.reason_codes)
    )


def _mark_auth_required(candidates: list[DiscoveryCandidate], reason: ReasonCode) -> None:
    for candidate in candidates:
        _reset_registry_reasons(candidate)
        candidate.registry_status = RegistryStatus.NOT_CHECKED
        candidate.reason_codes.append(reason)
        if _otherwise_eligible(candidate):
            candidate.registration_status = RegistrationStatus.REQUIRES_AUTH


def _mark_unavailable(candidate: DiscoveryCandidate, *, incomplete: bool = False) -> None:
    _reset_registry_reasons(candidate)
    candidate.registry_status = RegistryStatus.UNAVAILABLE
    candidate.registration_status = RegistrationStatus.NOT_APPLICABLE
    candidate.reason_codes.append(
        ReasonCode.REGISTRY_LOOKUP_INCOMPLETE if incomplete else ReasonCode.REGISTRY_UNAVAILABLE
    )


def _text(item: dict[str, Any], key: str) -> str | None:
    value = item.get(key)
    return value if isinstance(value, str) and value.strip() else None


def _registry_match(
    item: dict[str, Any], component_type: ComponentType, *, owned: bool, qualified_name: str
) -> RegistryMatch | None:
    item_id = _text(item, "id")
    status = _text(item, "status")
    item_qualified_name = _text(item, "qualified_name") or qualified_name
    if not item_id or not status or item_qualified_name != qualified_name:
        return None
    return RegistryMatch(
        id=item_id,
        qualified_name=item_qualified_name,
        status=status,
        component_type=component_type,
        owned=owned,
        version=_text(item, "version") or _text(item, "latest_version"),
    )


def _apply_match(candidate: DiscoveryCandidate, match: RegistryMatch, *, owned: bool) -> None:
    _reset_registry_reasons(candidate)
    candidate.registry_match = match
    candidate.registry_status = RegistryStatus.OWNED_EXISTING if owned else RegistryStatus.EXACT_MATCH
    candidate.registration_status = RegistrationStatus.ALREADY_EXISTS
    candidate.reason_codes.append(ReasonCode.REGISTRY_OWNED_EXISTING if owned else ReasonCode.REGISTRY_EXACT_MATCH)


def _apply_no_match(candidate: DiscoveryCandidate) -> None:
    _reset_registry_reasons(candidate)
    candidate.registry_status = RegistryStatus.NO_EXACT_MATCH
    candidate.reason_codes.append(ReasonCode.NO_EXACT_REGISTRY_MATCH)
    if _otherwise_eligible(candidate):
        candidate.registration_status = RegistrationStatus.ELIGIBLE


def _load_owned(component_type: ComponentType) -> dict[str, list[dict[str, Any]]] | None:
    payload: object = client.get(
        _MY_PATHS[component_type],
        operation=f"List owned {component_type.value} Registry entries",
        resource=f"owned {component_type.value} entries",
    )
    if not isinstance(payload, list):
        return None
    index: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in payload:
        if not isinstance(item, dict):
            return None
        qualified_name = _text(item, "qualified_name")
        if not qualified_name:
            return None
        index[qualified_name].append(item)
    return dict(index)


def classify_registry_candidates(
    candidates: list[DiscoveryCandidate],
    *,
    configuration: dict[str, Any] | None = None,
) -> list[DiscoveryDiagnostic]:
    """Classify proposed personal Registry identities, preserving local results.

    The resolver mutates candidates in place and returns safe, aggregate
    diagnostics. It never treats a failed request or malformed response as
    proof that a canonical Registry identity is absent.
    """

    diagnostics: list[DiscoveryDiagnostic] = []
    registry_candidates = [candidate for candidate in candidates if candidate.component_type in _MY_PATHS]
    for candidate in candidates:
        if candidate not in registry_candidates:
            _reset_registry_reasons(candidate)
            candidate.registry_status = RegistryStatus.NOT_CHECKED
            candidate.registration_status = RegistrationStatus.NOT_APPLICABLE
    if not registry_candidates:
        return diagnostics
    try:
        cfg = config.load() if configuration is None else configuration
    except CliError:
        for candidate in registry_candidates:
            _mark_unavailable(candidate)
        return [_diagnostic(DiagnosticCode.REGISTRY_UNAVAILABLE, "Registry configuration is unavailable")]

    if not cfg.get("server_url"):
        _mark_auth_required(registry_candidates, ReasonCode.REGISTRY_NOT_CONFIGURED)
        return [
            _diagnostic(
                DiagnosticCode.REGISTRY_NOT_CONFIGURED,
                "Configure a Registry server and run observal auth login to enable exact matching",
            )
        ]
    if not cfg.get("access_token"):
        _mark_auth_required(registry_candidates, ReasonCode.REGISTRY_AUTH_REQUIRED)
        return [
            _diagnostic(
                DiagnosticCode.REGISTRY_AUTH_REQUIRED,
                "Run observal auth login to enable exact Registry matching",
            )
        ]

    try:
        identity = client.get(
            "/api/v1/auth/whoami",
            operation="Resolve Registry owner identity",
            resource="authenticated user",
        )
    except CliError:
        for candidate in registry_candidates:
            _mark_unavailable(candidate)
        return [_diagnostic(DiagnosticCode.REGISTRY_UNAVAILABLE, "Registry identity lookup failed")]

    username = _text(identity, "username") if isinstance(identity, dict) else None
    if not username or not is_valid_namespace(username):
        for candidate in registry_candidates:
            _mark_unavailable(candidate, incomplete=True)
        return [_diagnostic(DiagnosticCode.REGISTRY_LOOKUP_INCOMPLETE, "Registry owner namespace is unavailable")]
    namespace = username.strip().lower()

    grouped: dict[ComponentType, list[DiscoveryCandidate]] = defaultdict(list)
    for candidate in registry_candidates:
        _reset_registry_reasons(candidate)
        component_type = candidate.component_type
        if component_type is not None and component_type in _MY_PATHS:
            grouped[component_type].append(candidate)
        else:
            candidate.registry_status = RegistryStatus.NOT_CHECKED
            candidate.registration_status = RegistrationStatus.NOT_APPLICABLE

    for component_type in sorted(grouped, key=lambda item: item.value):
        typed_candidates = grouped[component_type]
        try:
            owned = _load_owned(component_type)
        except CliError:
            for candidate in typed_candidates:
                _mark_unavailable(candidate)
            diagnostics.append(
                _diagnostic(DiagnosticCode.REGISTRY_UNAVAILABLE, f"Owned {component_type.value} lookup failed")
            )
            continue
        if owned is None:
            for candidate in typed_candidates:
                _mark_unavailable(candidate, incomplete=True)
            diagnostics.append(
                _diagnostic(
                    DiagnosticCode.REGISTRY_LOOKUP_INCOMPLETE,
                    f"Owned {component_type.value} response is incomplete",
                )
            )
            continue

        lookup_cache: dict[str, client.OptionalLookupResult | CliError] = {}
        detail_cache: dict[str, dict[str, Any] | CliError | None] = {}
        for candidate in typed_candidates:
            try:
                slug = slugify(candidate.local_name)
            except ValueError:
                _mark_unavailable(candidate, incomplete=True)
                continue
            qualified_name = f"{namespace}/{slug}"
            if qualified_name not in lookup_cache:
                try:
                    lookup_cache[qualified_name] = client.get_optional(
                        "/api/v1/registry/resolve",
                        params={"type": component_type.value, "identifier": qualified_name},
                        operation=f"Resolve exact {component_type.value} Registry identity",
                        resource=qualified_name,
                    )
                except CliError as error:
                    lookup_cache[qualified_name] = error
            lookup = lookup_cache[qualified_name]
            if isinstance(lookup, CliError):
                _mark_unavailable(candidate)
                continue

            resolution: dict[str, Any] | None = None
            resolved_id: str | None = None
            if lookup.status is client.OptionalLookupStatus.FOUND:
                if not isinstance(lookup.data, dict):
                    _mark_unavailable(candidate, incomplete=True)
                    continue
                resolution = lookup.data
                resolved_id = _text(resolution, "id")
                resolved_name = _text(resolution, "qualified_name")
                resolved_type = _text(resolution, "type")
                if not resolved_id or resolved_name != qualified_name or resolved_type != component_type.value:
                    _mark_unavailable(candidate, incomplete=True)
                    continue

            owned_items = owned.get(qualified_name, [])
            if len(owned_items) > 1:
                _reset_registry_reasons(candidate)
                candidate.registry_status = RegistryStatus.AMBIGUOUS
                candidate.registration_status = RegistrationStatus.NOT_APPLICABLE
                candidate.reason_codes.append(ReasonCode.REGISTRY_AMBIGUOUS)
                continue
            if owned_items:
                match = _registry_match(owned_items[0], component_type, owned=True, qualified_name=qualified_name)
                if match is None:
                    _mark_unavailable(candidate, incomplete=True)
                elif resolved_id is not None and match.id != resolved_id:
                    _reset_registry_reasons(candidate)
                    candidate.registry_status = RegistryStatus.AMBIGUOUS
                    candidate.registration_status = RegistrationStatus.NOT_APPLICABLE
                    candidate.reason_codes.append(ReasonCode.REGISTRY_AMBIGUOUS)
                else:
                    _apply_match(candidate, match, owned=True)
                continue

            if lookup.status is client.OptionalLookupStatus.NOT_FOUND:
                _apply_no_match(candidate)
                continue
            assert resolution is not None and resolved_id is not None
            if resolved_id not in detail_cache:
                try:
                    detail = client.get(
                        _DETAIL_PATHS[component_type].format(id=resolved_id),
                        operation=f"Fetch exact {component_type.value} Registry entry",
                        resource=qualified_name,
                    )
                    detail_cache[resolved_id] = detail if isinstance(detail, dict) else None
                except CliError as error:
                    detail_cache[resolved_id] = error
            detail = detail_cache[resolved_id]
            if isinstance(detail, CliError):
                _mark_unavailable(candidate)
                continue
            if detail is None:
                _mark_unavailable(candidate, incomplete=True)
                continue
            match = _registry_match(detail, component_type, owned=False, qualified_name=qualified_name)
            if match is None or match.id != resolved_id:
                _mark_unavailable(candidate, incomplete=True)
                continue
            _apply_match(candidate, match, owned=False)

    if any(ReasonCode.REGISTRY_UNAVAILABLE in candidate.reason_codes for candidate in registry_candidates) and not any(
        item.code == DiagnosticCode.REGISTRY_UNAVAILABLE for item in diagnostics
    ):
        diagnostics.append(_diagnostic(DiagnosticCode.REGISTRY_UNAVAILABLE, "One or more Registry lookups failed"))
    if any(
        ReasonCode.REGISTRY_LOOKUP_INCOMPLETE in candidate.reason_codes for candidate in registry_candidates
    ) and not any(item.code == DiagnosticCode.REGISTRY_LOOKUP_INCOMPLETE for item in diagnostics):
        diagnostics.append(
            _diagnostic(DiagnosticCode.REGISTRY_LOOKUP_INCOMPLETE, "One or more Registry responses were incomplete")
        )
    return diagnostics
