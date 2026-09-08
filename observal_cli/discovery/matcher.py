# SPDX-FileCopyrightText: 2026 Observal Contributors
# SPDX-License-Identifier: Apache-2.0

"""Ordered local lockfile matching for discovery candidates."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterable

from observal_cli.discovery.models import (
    ComponentType,
    DiscoveryCandidate,
    DiscoveryScope,
    ReasonCode,
    TrackingStatus,
)


def _normalized_directory(value: str | Path | None) -> str | None:
    if value is None:
        return None
    try:
        return os.path.normcase(str(Path(value).expanduser().resolve(strict=False)))
    except (OSError, RuntimeError):
        return os.path.normcase(os.path.abspath(os.path.expanduser(str(value))))


def _candidate_contexts(
    candidate: DiscoveryCandidate, project_directory: str | Path | None
) -> set[tuple[str, str, str | None]]:
    contexts: set[tuple[str, str, str | None]] = set()
    normalized_project = _normalized_directory(project_directory)
    for evidence in candidate.evidence:
        if not evidence.harness or evidence.scope == DiscoveryScope.GLOBAL:
            continue
        directory = normalized_project if evidence.scope == DiscoveryScope.PROJECT else None
        contexts.add((evidence.harness, evidence.scope.value, directory))
    return contexts


def _compatible_entries(candidate: DiscoveryCandidate, registry: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    if candidate.component_type is None:
        return []
    harnesses = {item.harness for item in candidate.evidence if item.harness}
    matches: list[tuple[str, dict[str, Any]]] = []
    for harness in sorted(harnesses):
        section = registry.get("harnesses", {}).get(harness, {})
        if not isinstance(section, dict):
            continue
        if candidate.component_type == ComponentType.AGENT:
            entries = section.get("agents", [])
        else:
            entries = list(section.get("standalone", [])) if isinstance(section.get("standalone", []), list) else []
            agents = section.get("agents", [])
            if isinstance(agents, list):
                for agent in agents:
                    if not isinstance(agent, dict) or not isinstance(agent.get("components"), list):
                        continue
                    for component in agent["components"]:
                        if not isinstance(component, dict):
                            continue
                        inherited = dict(component)
                        inherited.setdefault("scope", agent.get("scope"))
                        inherited.setdefault("directory", agent.get("directory"))
                        entries.append(inherited)
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            entry_type = (
                ComponentType.AGENT.value if candidate.component_type == ComponentType.AGENT else entry.get("type")
            )
            if entry_type == candidate.component_type.value:
                matches.append((harness, entry))
    return matches


def _tier_status(matches: Iterable[tuple[str, dict[str, Any]]]) -> TrackingStatus | None:
    count = sum(1 for _ in matches)
    if count == 1:
        return TrackingStatus.TRACKED
    if count > 1:
        return TrackingStatus.AMBIGUOUS
    return None


def match_local_candidate(
    candidate: DiscoveryCandidate,
    registry: dict[str, Any],
    *,
    component_id: str | None = None,
    qualified_name: str | None = None,
    project_directory: str | Path | None = None,
) -> TrackingStatus:
    """Match one candidate against a current-registry lockfile section.

    Identity metadata is supplied separately because legacy ``Discovered*``
    records intentionally do not expose Registry IDs or qualified names.
    """

    entries = _compatible_entries(candidate, registry)
    if not entries:
        return TrackingStatus.NOT_TRACKED

    if component_id:
        status = _tier_status(item for item in entries if item[1].get("id") == component_id)
        if status is not None:
            return status

    if qualified_name:
        status = _tier_status(item for item in entries if item[1].get("qualified_name") == qualified_name)
        if status is not None:
            return status

    if candidate.launch_fingerprint:
        status = _tier_status(
            item for item in entries if item[1].get("launch_fingerprint") == candidate.launch_fingerprint
        )
        if status is not None:
            return status

    # Fingerprinted entries have asserted an exact launch identity. They must
    # not be matched by weaker legacy name fallbacks when that identity did not
    # match. Entries without the additive field retain version-2 compatibility.
    legacy_entries = [item for item in entries if not item[1].get("launch_fingerprint")]
    contexts = _candidate_contexts(candidate, project_directory)
    scoped_entries = legacy_entries
    if contexts:
        scoped_entries = []
        for harness, entry in legacy_entries:
            entry_scope = str(entry.get("scope") or "user")
            entry_directory = _normalized_directory(entry.get("directory")) if entry_scope == "project" else None
            if (harness, entry_scope, entry_directory) in contexts:
                scoped_entries.append((harness, entry))
        status = _tier_status(item for item in scoped_entries if item[1].get("local_name") == candidate.local_name)
        if status is not None:
            return status

    local_matches = [
        item for item in scoped_entries if candidate.local_name in {item[1].get("local_name"), item[1].get("name")}
    ]
    status = _tier_status(local_matches)
    return status or TrackingStatus.NOT_TRACKED


def apply_local_match(
    candidate: DiscoveryCandidate,
    registry: dict[str, Any],
    *,
    component_id: str | None = None,
    qualified_name: str | None = None,
    project_directory: str | Path | None = None,
) -> DiscoveryCandidate:
    """Apply local tracking state and its stable reason code in place."""

    status = match_local_candidate(
        candidate,
        registry,
        component_id=component_id,
        qualified_name=qualified_name,
        project_directory=project_directory,
    )
    candidate.tracking_status = status
    candidate.reason_codes = [
        reason
        for reason in candidate.reason_codes
        if reason not in {ReasonCode.ALREADY_TRACKED, ReasonCode.TRACKING_AMBIGUOUS}
    ]
    if status == TrackingStatus.TRACKED:
        candidate.reason_codes.append(ReasonCode.ALREADY_TRACKED)
    elif status == TrackingStatus.AMBIGUOUS:
        candidate.reason_codes.append(ReasonCode.TRACKING_AMBIGUOUS)
    return candidate
